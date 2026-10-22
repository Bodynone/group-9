from contextlib import asynccontextmanager
import json

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import Response

from .agent import AgentRunner
from .batch import BatchRunner
from .clustering import ClassAnalyticsEngine
from .config import Settings
from .models import CreateBatch, CreateTask, UpdateReview
from .provider import ChatProvider
from .rubric import IDS, RUBRIC, VERSION
from .storage import Store
from .tools import Toolbox


def create_app(settings: Settings | None = None, provider=None, store: Store | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    owns_store = store is None
    store = store if store is not None else Store(settings.database_path)
    provider = provider if provider is not None else ChatProvider(settings)
    runner = AgentRunner(store, provider, settings)
    batch_runner = BatchRunner(store, runner)

    @asynccontextmanager
    async def lifespan(app):
        store.recover_interrupted()
        try:
            yield
        finally:
            await batch_runner.aclose()
            store.recover_interrupted()
            if owns_store:
                store.close()

    app = FastAPI(title="阅见作业辅助批改", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.runner = runner
    app.state.batch_runner = batch_runner
    app.state.settings = settings

    def get(task_id):
        try:
            return store.get_task(task_id)
        except KeyError:
            raise HTTPException(404, "任务不存在") from None

    @app.get("/api/health")
    def health():
        return {"status": "ok", "model": settings.model, "model_configured": bool(settings.api_key)}

    @app.get("/api/rubric")
    def rubric():
        return RUBRIC

    @app.post("/api/tasks", status_code=202)
    def create(body: CreateTask, background: BackgroundTasks):
        if body.rubric_version != VERSION:
            raise HTTPException(422, "量表版本不支持，请重新加载固定量表")
        task = store.create_task(body.text, body.rubric_version)
        background.add_task(batch_runner.run_task, task["id"])
        return task

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str):
        return get(task_id)

    @app.post("/api/tasks/{task_id}/retry", status_code=202)
    def retry(task_id: str, background: BackgroundTasks):
        get(task_id)
        try:
            task = store.retry_task(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        background.add_task(batch_runner.run_task, task["id"])
        return task

    @app.post("/api/batch/tasks", status_code=202)
    def create_batch(body: CreateBatch, background: BackgroundTasks):
        if body.rubric_version != VERSION:
            raise HTTPException(422, "量表版本不支持，请重新加载固定量表")
        batch = store.create_batch(body.name, [file.model_dump() for file in body.files], body.rubric_version)
        background.add_task(batch_runner.run_batch, batch["batch_id"])
        return batch

    @app.get("/api/batches")
    def batches(limit: int = Query(default=10, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        return store.list_batches(limit=limit, offset=offset)

    @app.get("/api/batch/{batch_id}")
    def batch(batch_id: str):
        try:
            return store.get_batch(batch_id)
        except KeyError:
            raise HTTPException(404, "批次不存在") from None

    @app.get("/api/batch/{batch_id}/export-csv")
    def export_batch(batch_id: str):
        try:
            csv = store.export_batch_csv(batch_id)
        except KeyError:
            raise HTTPException(404, "批次不存在") from None
        return Response(csv, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="gradebook-{batch_id}.csv"',
            "Cache-Control": "no-store",
        })

    @app.get("/api/batch/{batch_id}/analytics")
    def analytics(batch_id: str):
        try:
            tasks = store.get_batch_tasks(batch_id)
        except KeyError:
            raise HTTPException(404, "批次不存在") from None
        result = ClassAnalyticsEngine().analyze_batch(tasks)
        result["batch_id"] = batch_id
        return result

    @app.post("/api/tasks/{task_id}/manual")
    def manual(task_id: str):
        get(task_id)
        try:
            return store.manual_task(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.patch("/api/tasks/{task_id}/review")
    def review(task_id: str, body: UpdateReview):
        task = get(task_id)
        if task["rubric_version"] != VERSION:
            raise HTTPException(409, "历史量表任务仅可查看，请按当前量表重新批改")
        dimensions = [d.model_dump() for d in body.dimensions]
        calculated = Toolbox(task).calculate_scores(dimensions)
        if not calculated["ok"]:
            raise HTTPException(422, calculated["errors"])
        scores = {d["id"]: d["score"] for d in calculated["dimensions"]}
        dimensions.sort(key=lambda d: IDS.index(d["id"]))
        for d in dimensions:
            d["score"] = scores[d["id"]]
        try:
            store.save_review(task_id, body.input_version, {"dimensions": dimensions, "total": calculated["total"]})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return get(task_id)

    @app.post("/api/tasks/{task_id}/confirm")
    def confirm(task_id: str):
        get(task_id)
        try:
            return store.confirm_task(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/tasks/{task_id}/export")
    def export(task_id: str):
        get(task_id)
        try:
            record = store.export_task(task_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        return Response(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="grading-{record["record_id"]}.json"', "Cache-Control": "no-store"})

    return app
