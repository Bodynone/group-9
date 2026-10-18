import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.agent import AgentRunner
from backend.app import create_app
from backend.batch import BatchRunner
from backend.rubric import VERSION

from scripted_provider import ScriptedProvider, reviewed_dimensions


def files(text, count=5):
    return [{"filename": f"学生-{index}.txt", "text": text} for index in range(count)]


class ControlledRunner:
    """Exercise scheduling and real persistence without external model calls."""

    def __init__(self, store, settings, *, failed_filename=None, release=None):
        self.store = store
        self.delegate = AgentRunner(store, object(), settings)
        self.failed_filename = failed_filename
        self.release = release
        self.started = asyncio.Event()
        self.active = 0
        self.peak = 0
        self.calls = Counter()

    def fail(self, *args, **kwargs):
        return self.delegate.fail(*args, **kwargs)

    async def run(self, task_id):
        task = self.store.get_task(task_id)
        if task["status"] != "queued":
            return
        self.calls[task_id] += 1
        self.store.update_task(task_id, status="running")
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 3:
            self.started.set()
        try:
            if self.release:
                await self.release.wait()
            else:
                await asyncio.sleep(0.01)
            if task.get("filename") == self.failed_filename and self.failed_filename:
                raise RuntimeError("模拟单任务调度异常")
            self.store.transition(task_id, "pending_review", status="pending_review")
        finally:
            self.active -= 1


class DispatchProvider:
    def __init__(self, store):
        self.store = store
        self.providers = {}
        self.fail = False

    async def complete(self, messages, tools):
        if self.fail:
            raise RuntimeError("模拟模型故障")
        task_id = json.loads(messages[1]["content"])["task_id"]
        if task_id not in self.providers:
            self.providers[task_id] = ScriptedProvider(self.store.get_task(task_id))
        await asyncio.sleep(0)
        return await self.providers[task_id].complete(messages, tools)


async def test_five_tasks_run_with_peak_three_and_atomic_progress(samples, store, settings):
    batch = store.create_batch("五份作业", files(samples["S1"]))
    runner = ControlledRunner(store, settings)
    scheduler = BatchRunner(store, runner)
    await scheduler.run_batch(batch["batch_id"])
    result = store.get_batch(batch["batch_id"])
    assert runner.peak == 3
    assert len(runner.calls) == 5
    assert set(runner.calls.values()) == {1}
    assert result["total_count"] == result["completed_count"] == 5
    assert result["failed_count"] == 0
    assert result["status"] == "completed"


async def test_limit_is_shared_across_batches_single_tasks_and_retries(samples, store, settings):
    first = store.create_batch("第一批", files(samples["S1"]))
    second = store.create_batch("第二批", files(samples["S1"], 2))
    single = store.create_task(samples["S1"])
    original = store.create_task(samples["S1"])
    store.update_task(original["id"], status="failed")
    retry = store.retry_task(original["id"])
    runner = ControlledRunner(store, settings)
    scheduler = BatchRunner(store, runner)
    await asyncio.gather(
        scheduler.run_batch(first["batch_id"]), scheduler.run_batch(second["batch_id"]),
        scheduler.run_task(single["id"]), scheduler.run_task(retry["id"]),
    )
    assert runner.peak == 3
    assert len(runner.calls) == 9
    assert all(store.get_task(task_id)["status"] == "pending_review" for task_id in runner.calls)
    assert store.get_task(original["id"])["status"] == "failed"


async def test_http_entry_points_share_the_same_concurrency_limit(samples, store, settings):
    app = create_app(settings=settings, store=store, provider=object())
    runner = ControlledRunner(store, settings)
    app.state.runner.run = runner.run
    async with app.router.lifespan_context(app):
        original = store.create_task(samples["S1"])
        store.update_task(original["id"], status="failed")
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            responses = await asyncio.gather(
                client.post("/api/batch/tasks", json={"name": "第一批", "files": files(samples["S1"])}),
                client.post("/api/batch/tasks", json={"name": "第二批", "files": files(samples["S1"], 2)}),
                client.post("/api/tasks", json={"text": samples["S1"]}),
                client.post(f"/api/tasks/{original['id']}/retry"),
            )
    assert all(response.status_code == 202 for response in responses)
    assert runner.peak == 3
    assert len(runner.calls) == 9


async def test_duplicate_dispatch_does_not_execute_a_task_twice(samples, store, settings):
    batch = store.create_batch("去重", files(samples["S1"], 2))
    task = store.get_batch_tasks(batch["batch_id"])[0]
    runner = ControlledRunner(store, settings)
    scheduler = BatchRunner(store, runner)
    await asyncio.gather(
        scheduler.run_batch(batch["batch_id"]), scheduler.run_batch(batch["batch_id"]),
        scheduler.run_task(task["id"]), scheduler.run_task(task["id"]),
    )
    assert len(runner.calls) == 2
    assert set(runner.calls.values()) == {1}


async def test_one_worker_exception_isolated_and_remaining_tasks_complete(samples, store, settings):
    batch = store.create_batch("错误隔离", files(samples["S1"]))
    scheduler = BatchRunner(store, ControlledRunner(store, settings, failed_filename="学生-2.txt"))
    await scheduler.run_batch(batch["batch_id"])
    result = store.get_batch(batch["batch_id"])
    assert result["status"] == "partial_failed"
    assert result["completed_count"] == 4
    assert result["failed_count"] == 1
    failed = next(task for task in store.get_batch_tasks(batch["batch_id"]) if task["status"] == "failed")
    assert failed["error"]["code"] == "execution_error"
    assert failed["text"] == samples["S1"]


async def test_shutdown_cancels_running_and_waiting_tasks_before_store_closes(samples, store, settings):
    batch = store.create_batch("关闭中断", files(samples["S1"]))
    runner = ControlledRunner(store, settings, release=asyncio.Event())
    scheduler = BatchRunner(store, runner)
    pending = asyncio.create_task(scheduler.run_batch(batch["batch_id"]))
    await asyncio.wait_for(runner.started.wait(), timeout=1)
    await scheduler.aclose()
    await asyncio.gather(pending, return_exceptions=True)
    assert runner.active == 0
    assert not scheduler._active
    assert not scheduler._task_ids
    assert not scheduler._batch_ids
    tasks = store.get_batch_tasks(batch["batch_id"])
    assert all(task["status"] == "failed" and task["error"]["code"] == "interrupted" for task in tasks)
    assert store.get_batch(batch["batch_id"])["status"] == "failed"
    await scheduler.aclose()


async def test_lifespan_awaits_cancellation_before_closing_owned_store(samples, settings):
    app = create_app(settings=settings, provider=object())
    storage = app.state.store
    runner = ControlledRunner(storage, settings, release=asyncio.Event())
    app.state.runner.run = runner.run
    original_close = storage.close
    closed = False

    def checked_close():
        nonlocal closed
        assert not app.state.batch_runner._active
        assert runner.active == 0
        assert all(task["status"] == "failed" for task in storage.get_batch_tasks(batch["batch_id"]))
        closed = True
        original_close()

    storage.close = checked_close
    async with app.router.lifespan_context(app):
        batch = storage.create_batch("生命周期", files(samples["S1"]))
        pending = asyncio.create_task(app.state.batch_runner.run_batch(batch["batch_id"]))
        await asyncio.wait_for(runner.started.wait(), timeout=1)
    assert closed
    assert pending.cancelled()


def test_batch_routes_run_real_agent_export_csv_and_paginate(samples, store, settings):
    provider = DispatchProvider(store)
    with TestClient(create_app(settings=settings, store=store, provider=provider)) as client:
        response = client.post("/api/batch/tasks", json={
            "name": "软件工程班", "files": files(samples["S1"]), "rubric_version": VERSION,
        })
        assert response.status_code == 202
        created = response.json()
        assert created["status"] == "queued"
        assert created["total_count"] == 5
        batch_id = created["batch_id"]
        result = client.get(f"/api/batch/{batch_id}").json()
        assert result["status"] == "completed"
        assert result["completed_count"] == 5
        assert len(result["tasks"]) == 5
        assert all(task["total_score"] == 100 for task in result["tasks"])
        listed = client.get("/api/batches?limit=1&offset=0").json()
        assert listed["total"] == 1
        assert listed["items"][0]["batch_id"] == batch_id
        assert client.get("/api/batches?limit=1&offset=1").json()["items"] == []
        exported = client.get(f"/api/batch/{batch_id}/export-csv")
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert exported.headers["content-type"] == "text/csv; charset=utf-8"
        assert exported.headers["content-disposition"] == f'attachment; filename="gradebook-{batch_id}.csv"'
        assert "学生-0.txt" in exported.text


def test_retry_replaces_current_batch_item_without_increasing_total(samples, store, settings):
    provider = DispatchProvider(store)
    provider.fail = True
    with TestClient(create_app(settings=settings, store=store, provider=provider)) as client:
        batch = client.post("/api/batch/tasks", json={"name": "重试", "files": files(samples["S1"], 1)}).json()
        batch_id = batch["batch_id"]
        failed = store.get_batch_tasks(batch_id)[0]
        assert failed["status"] == "failed"
        provider.fail = False
        retried = client.post(f"/api/tasks/{failed['id']}/retry")
        assert retried.status_code == 202
        task = store.get_batch_tasks(batch_id)[0]
        assert task["id"] == retried.json()["id"]
        assert task["parent_id"] == failed["id"]
        assert task["status"] == "pending_review"
        assert store.get_task(failed["id"])["status"] == "failed"
        assert client.post(f"/api/tasks/{failed['id']}/retry").status_code == 409
        result = client.get(f"/api/batch/{batch_id}").json()
        assert result["total_count"] == result["completed_count"] == 1
        assert result["failed_count"] == 0


def test_concurrent_retry_has_one_winner_and_no_orphan_task(samples, store):
    batch = store.create_batch("重试竞争", files(samples["S1"], 1))
    original = store.get_batch_tasks(batch["batch_id"])[0]
    store.update_task(original["id"], status="failed")

    def retry():
        try:
            return store.retry_task(original["id"])
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: retry(), range(2)))
    assert sum(outcome is not None for outcome in outcomes) == 1
    current = store.get_batch_tasks(batch["batch_id"])[0]
    assert current["id"] == next(outcome["id"] for outcome in outcomes if outcome)
    with store._lock:
        assert store._connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    assert store.get_batch(batch["batch_id"])["total_count"] == 1


def test_legacy_task_is_frozen_but_can_be_regenerated_under_current_rubric(samples, store, settings):
    legacy = store.create_task(samples["S1"], "af-2026-10-09-v1")
    provider = DispatchProvider(store)
    with TestClient(create_app(settings=settings, store=store, provider=provider)) as client:
        assert store.get_task(legacy["id"]) == legacy
        body = {"input_version": legacy["input_version"], "dimensions": reviewed_dimensions(legacy)}
        assert client.patch(f"/api/tasks/{legacy['id']}/review", json=body).status_code == 409
        assert client.post(f"/api/tasks/{legacy['id']}/manual").status_code == 409
        assert client.post(f"/api/tasks/{legacy['id']}/confirm").status_code == 409
        response = client.post(f"/api/tasks/{legacy['id']}/retry")
        assert response.status_code == 202
        regenerated = store.get_task(response.json()["id"])
        assert regenerated["parent_id"] == legacy["id"]
        assert regenerated["rubric_version"] == VERSION
        assert regenerated["status"] == "pending_review"
    assert store.get_task(legacy["id"]) == legacy


@pytest.mark.parametrize("mutation", ["empty", "name", "filename", "text", "oversized", "rubric", "extra"])
def test_invalid_batches_are_rejected_without_partial_creation(mutation, samples, store, settings):
    payload = {"name": "测试班", "files": files(samples["S1"], 1), "rubric_version": VERSION}
    if mutation == "empty":
        payload["files"] = []
    elif mutation == "name":
        payload["name"] = " \t"
    elif mutation in ("filename", "text"):
        payload["files"][0][mutation] = " \n"
    elif mutation == "oversized":
        payload["files"][0]["text"] = "字" * 50_001
    elif mutation == "rubric":
        payload["rubric_version"] = "unknown"
    else:
        payload["unexpected"] = True
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    assert client.post("/api/batch/tasks", json=payload).status_code == 422
    assert store.list_batches()["total"] == 0


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "limit=no"])
def test_invalid_pagination_and_unknown_batch(query, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    assert client.get(f"/api/batches?{query}").status_code == 422
    assert client.get("/api/batch/missing").status_code == 404
    assert client.get("/api/batch/missing/export-csv").status_code == 404


@pytest.mark.parametrize("concurrency", [0, -1, True, 1.5])
def test_invalid_concurrency_fails_immediately(concurrency, store, settings):
    with pytest.raises(ValueError):
        BatchRunner(store, AgentRunner(store, object(), settings), concurrency=concurrency)
