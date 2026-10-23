"""Versioned teacher workflows; legacy contracts remain available unchanged."""

from fastapi import APIRouter, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.exception_handlers import request_validation_exception_handler

from .schemas_v2 import (AssignmentCreate, AssignmentUpdate, BatchCreate, CourseCreate,
                         DefinitionUpdate, Revision, ReviewUpdate, RubricCreate, TaskCreate,
                         V2Error, VersionCopy, Versions, canonical)


def install(app, service, runner):
    router = APIRouter(prefix="/api/v2")

    def ensure_model():
        if not app.state.settings.api_key:
            raise V2Error("MODEL_NOT_CONFIGURED", "模型尚未配置，请先设置后端模型参数", 503)

    @app.exception_handler(V2Error)
    async def v2_error(request, exc):
        error = {"code": exc.code, "message": exc.message}
        if exc.fields is not None:
            error["field_errors"] = exc.fields
        return JSONResponse({"error": error}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc):
        if request.url.path.startswith(("/api/v2/", "/api/v3/")):
            fields = [{"field": ".".join(str(part) for part in err["loc"]), "message": err["msg"]} for err in exc.errors()]
            return JSONResponse({"error": {"code": "INVALID_INPUT", "message": "请求字段不合法", "field_errors": fields}}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @router.post("/courses", status_code=201)
    def course(body: CourseCreate):
        return service.course(body.name)

    @router.get("/courses")
    def courses(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return service.list("courses", limit, offset)

    @router.post("/rubrics", status_code=201)
    def rubric(body: RubricCreate):
        return service.new_rubric(body.title, body.source_version_id)

    @router.get("/rubrics")
    def rubrics(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), include_archived: bool = False):
        return service.list("rubrics", limit, offset, include_archived=include_archived)

    @router.post("/rubrics/{identifier}/archive")
    def archive_rubric(identifier: str, body: Revision):
        return service.lifecycle(identifier, body.expected_revision, True, series=True)

    @router.post("/rubrics/{identifier}/restore")
    def restore_rubric(identifier: str, body: Revision):
        return service.lifecycle(identifier, body.expected_revision, False, series=True)

    @router.post("/rubric-versions/{identifier}/archive")
    def archive_version(identifier: str, body: Revision):
        return service.lifecycle(identifier, body.expected_revision, True)

    @router.post("/rubric-versions/{identifier}/restore")
    def restore_version(identifier: str, body: Revision):
        return service.lifecycle(identifier, body.expected_revision, False)

    @router.delete("/rubric-versions/{identifier}")
    def delete_draft(identifier: str, body: Revision):
        return service.delete_draft(identifier, body.expected_revision)

    @router.post("/rubrics/{identifier}/versions", status_code=201)
    def copy(identifier: str, body: VersionCopy):
        return service.copy_version(identifier, body.source_version_id)

    @router.get("/rubric-versions/{identifier}")
    def version(identifier: str):
        with service.store._snapshot():
            return service.describe(service.get("rubric_versions", identifier))

    @router.patch("/rubric-versions/{identifier}")
    def save_version(identifier: str, body: DefinitionUpdate):
        return service.update_version(identifier, body.expected_revision, body.definition)

    @router.post("/rubric-versions/{identifier}/publish")
    def publish_version(identifier: str, body: Revision):
        return service.publish_version(identifier, body.expected_revision)

    @router.post("/assignments", status_code=201)
    def assignment(body: AssignmentCreate):
        return service.assignment(body.model_dump())

    @router.get("/assignments")
    def assignments(course_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return service.list("assignments", limit, offset, course_id=course_id)

    @router.get("/assignments/{identifier}")
    def get_assignment(identifier: str):
        with service.store._snapshot():
            return service.get("assignments", identifier)

    @router.patch("/assignments/{identifier}")
    def save_assignment(identifier: str, body: AssignmentUpdate):
        return service.assignment(body.model_dump(), identifier)

    @router.post("/assignments/{identifier}/publish")
    def publish_assignment(identifier: str, body: Revision):
        return service.publish_assignment(identifier, body.expected_revision)

    @router.post("/tasks", status_code=202)
    async def create_task(body: TaskCreate, idempotency_key: str | None = Header(default=None)):
        ensure_model()
        task = service.submit(body.model_dump(), idempotency_key)
        runner.schedule(task["id"])
        return task

    @router.get("/tasks/{identifier}")
    def get_task(identifier: str):
        return service.task(identifier)

    @router.get("/tasks")
    def submissions(assignment_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return service.submissions(assignment_id, limit, offset)

    @router.patch("/tasks/{identifier}/review")
    def review(identifier: str, body: ReviewUpdate):
        return service.review(identifier, body.model_dump())

    @router.post("/tasks/{identifier}/confirm")
    def confirm(identifier: str, body: Versions):
        return service.confirm(identifier, body.model_dump())

    @router.get("/tasks/{identifier}/export")
    def export(identifier: str):
        task = service.task(identifier)
        if task["status"] != "confirmed":
            raise V2Error("STATE_CONFLICT", "请先完成教师确认")
        return Response(canonical(service.store.export_task(identifier)), media_type="application/json", headers={
            "Content-Disposition": f'attachment; filename="grading-{task["record_id"]}.json"', "Cache-Control": "no-store"})

    @router.post("/tasks/{identifier}/retry", status_code=202)
    async def retry(identifier: str, idempotency_key: str | None = Header(default=None)):
        ensure_model()
        task = service.retry(identifier, idempotency_key)
        runner.schedule(task["id"])
        return task

    @router.post("/tasks/{identifier}/manual")
    def manual(identifier: str):
        return service.manual(identifier)

    @router.post("/batches", status_code=202)
    async def create_batch(body: BatchCreate, idempotency_key: str | None = Header(default=None)):
        ensure_model()
        batch = service.submit(body.model_dump(), idempotency_key, batch=True)
        for item in batch["items"]:
            runner.schedule(item["task_id"])
        return batch

    @router.get("/batches/{identifier}")
    def batch(identifier: str):
        return service.batch(identifier)

    @router.get("/batches/{identifier}/analytics")
    def analytics(identifier: str, basis: str = Query("confirmed", pattern="^(confirmed|working)$")):
        return service.analytics(identifier, basis)

    @router.get("/batches/{identifier}/export-csv")
    def csv(identifier: str):
        data, exported, excluded = service.csv(identifier)
        return Response(data, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="gradebook-{identifier}.csv"', "Cache-Control": "no-store",
            "X-Exported-Count": str(exported), "X-Excluded-Count": str(excluded)})

    @router.get("/batches")
    def batches(assignment_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return service.list("v2_batches", limit, offset, assignment_id=assignment_id)

    app.include_router(router)
