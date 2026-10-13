import asyncio
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.agent import AgentRunner
from backend.app import create_app
from backend.rubric import VERSION

from scripted_provider import ScriptedProvider, DIMENSIONS, reviewed_dimensions


@pytest.fixture
def reviewed_task(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    provider = ScriptedProvider(task)
    asyncio.run(AgentRunner(store, provider, settings).run(task["id"]))
    return store.get_task(task["id"])


def test_teacher_review_recomputes_score_confirmation_is_idempotent_and_export_is_immutable(reviewed_task, store, settings):
    task = reviewed_task
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    assert client.get(f"/api/tasks/{task['id']}/export").status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/confirm").status_code == 409
    levels = {dimension: 70 if dimension == "A" else 100 for dimension in DIMENSIONS}
    response = client.patch(f"/api/tasks/{task['id']}/review", json={
        "input_version": task["input_version"], "dimensions": reviewed_dimensions(task, levels),
    })
    assert response.status_code == 200
    assert response.json()["review"]["total"] == 95.5
    assert response.json()["review"]["dimensions"][0]["score"] == 10.5
    assert response.json()["draft"]["total"] == 100
    first = client.post(f"/api/tasks/{task['id']}/confirm")
    second = client.post(f"/api/tasks/{task['id']}/confirm")
    assert first.status_code == second.status_code == 200
    assert first.json()["record_id"] == second.json()["record_id"]
    assert first.json()["status"] == "confirmed"
    exported = client.get(f"/api/tasks/{task['id']}/export")
    assert exported.status_code == 200
    assert exported.json()["task"]["review"]["total"] == 95.5
    assert exported.json()["task"]["draft"]["total"] == 100
    assert exported.json()["task"]["text"] == task["text"]
    assert exported.json()["record_id"] == first.json()["record_id"]
    assert client.patch(f"/api/tasks/{task['id']}/review", json={
        "input_version": task["input_version"], "dimensions": reviewed_dimensions(task),
    }).status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/manual").status_code == 409
    assert client.post(f"/api/tasks/{task['id']}/retry").status_code == 409
    assert client.get(f"/api/tasks/{task['id']}/export").json() == exported.json()


def test_unreviewed_dimension_blocks_confirmation(reviewed_task, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    dimensions = reviewed_dimensions(reviewed_task)
    dimensions[2]["reviewed"] = False
    response = client.patch(f"/api/tasks/{reviewed_task['id']}/review", json={
        "input_version": reviewed_task["input_version"], "dimensions": dimensions,
    })
    assert response.status_code == 200
    assert client.post(f"/api/tasks/{reviewed_task['id']}/confirm").status_code == 409
    assert store.get_task(reviewed_task["id"])["record_id"] is None


@pytest.mark.parametrize("mutation", ["stale", "missing", "duplicate", "level", "blank_reason", "coerced_level"])
def test_invalid_teacher_review_cannot_be_saved(mutation, reviewed_task, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    payload = {"input_version": reviewed_task["input_version"], "dimensions": reviewed_dimensions(reviewed_task)}
    expected_status = 422
    if mutation == "stale":
        payload["input_version"] = "old-input"
        expected_status = 409
    elif mutation == "missing":
        payload["dimensions"].pop()
    elif mutation == "duplicate":
        payload["dimensions"][-1]["id"] = "A"
    elif mutation == "level":
        payload["dimensions"][0]["level"] = 50
    elif mutation == "blank_reason":
        payload["dimensions"][0]["reason"] = "  "
    elif mutation == "coerced_level":
        payload["dimensions"][0]["level"] = "100"
    previous = deepcopy(store.get_task(reviewed_task["id"])["review"])
    assert client.patch(f"/api/tasks/{reviewed_task['id']}/review", json=payload).status_code == expected_status
    assert store.get_task(reviewed_task["id"])["review"] == previous


def test_failed_task_allows_manual_grading_with_all_six_dimensions(samples, store, settings):
    task = store.create_task(samples["S1"], VERSION)
    store.update_task(task["id"], status="failed", error={"code": "tool_failure", "message": "503"})
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    response = client.post(f"/api/tasks/{task['id']}/manual")
    assert response.status_code == 200
    manual = response.json()
    assert manual["status"] == "pending_review"
    assert manual["source"] == "manual"
    assert manual["text"] == task["text"]
    assert manual["draft"] is None
    assert len(manual["review"]["dimensions"]) == 6
    assert all(item["level"] is None and item["reviewed"] is False for item in manual["review"]["dimensions"])
    assert client.post(f"/api/tasks/{task['id']}/confirm").status_code == 409
    payload = {"input_version": task["input_version"], "dimensions": reviewed_dimensions(task)}
    assert client.patch(f"/api/tasks/{task['id']}/review", json=payload).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/confirm").status_code == 200
    assert client.get(f"/api/tasks/{task['id']}/export").json()["task"]["review"]["total"] == 100


def test_create_task_executes_background_agent_and_retry_preserves_versions(samples, store, settings):
    reference = store.create_task(samples["S1"], VERSION)
    provider = ScriptedProvider(reference)
    client = TestClient(create_app(settings=settings, store=store, provider=provider))
    created = client.post("/api/tasks", json={"text": samples["S1"], "rubric_version": VERSION})
    assert created.status_code == 202
    task_id = created.json()["id"]
    assert task_id != reference["id"]
    completed = client.get(f"/api/tasks/{task_id}").json()
    assert completed["status"] == "pending_review"
    assert completed["draft"]["total"] == 100
    assert client.post(f"/api/tasks/{task_id}/manual").status_code == 409
    assert client.post(f"/api/tasks/{task_id}/retry").status_code == 409

    failed = store.create_task(samples["S1"], VERSION)
    store.update_task(failed["id"], status="failed", error={"message": "503"})
    provider.pending = list(provider.initial)
    retried = client.post(f"/api/tasks/{failed['id']}/retry")
    assert retried.status_code == 202
    retry_task = client.get(f"/api/tasks/{retried.json()['id']}").json()
    assert retry_task["id"] != failed["id"]
    assert retry_task["parent_id"] == failed["id"]
    assert retry_task["text"] == failed["text"]
    assert retry_task["input_version"] == failed["input_version"]
    assert retry_task["rubric_version"] == failed["rubric_version"]
    assert retry_task["status"] == "pending_review"
    assert store.get_task(failed["id"])["status"] == "failed"


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_blank_input_is_rejected(text, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    assert client.post("/api/tasks", json={"text": text}).status_code == 422


def test_unknown_task_and_unsupported_rubric_are_explicit(samples, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    assert client.get("/api/tasks/not-found").status_code == 404
    assert client.post("/api/tasks", json={"text": samples["S1"], "rubric_version": "unknown"}).status_code == 422
    rubric = client.get("/api/rubric")
    assert rubric.status_code == 200
    assert rubric.json()["version"] == VERSION
    assert [dimension["max_score"] for dimension in rubric.json()["dimensions"]] == [15, 20, 30, 15, 10, 10]
