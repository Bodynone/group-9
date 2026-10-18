"""Pre-upgrade snapshots stay immutable while teachers can regrade their input."""

import asyncio
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.agent import AgentRunner
from backend.app import create_app
from backend.rubric import VERSION

from scripted_provider import reviewed_dimensions, valid_draft
from ui_server import UiTestProvider


LEGACY_VERSION = "af-2026-10-09-v1"


def legacy_snapshot(store, text, status):
    task = store.create_task(text)
    task.update(status=status, rubric_version=LEGACY_VERSION)
    if status in {"pending_review", "confirmed"}:
        task["draft"] = valid_draft(task)
        for dimension in task["draft"]["dimensions"]:
            dimension["score"] = dict(zip("ABCDEF", (15, 20, 30, 15, 10, 10)))[dimension["id"]]
        task["review"] = {
            "dimensions": [
                {**dimension, "score": task["draft"]["dimensions"][index]["score"]}
                for index, dimension in enumerate(reviewed_dimensions(task))
            ],
            "total": 100,
        }
    if status == "confirmed":
        task["record_id"] = str(uuid4())
    # Simulate opening a database produced before the upgrade, rather than
    # weakening production write guards to make legacy fixtures.
    with store.transaction():
        store._save(task)
        if status == "confirmed":
            record = {"record_id": task["record_id"], "confirmed_at": task["updated_at"], "task": task}
            store._connection.execute(
                "INSERT INTO records VALUES (?,?,?)",
                (task["record_id"], task["id"], json.dumps(record, ensure_ascii=False)),
            )
    return task


@pytest.mark.parametrize("status", ["queued", "running", "pending_review", "failed"])
def test_legacy_unconfirmed_input_is_frozen_and_can_be_regraded(status, samples, store, settings):
    old = legacy_snapshot(store, samples["S1"], status)
    app = create_app(settings=settings, store=store, provider=UiTestProvider())
    with TestClient(app) as client:
        assert client.get(f"/api/tasks/{old['id']}").json() == old
        body = {"input_version": old["input_version"], "dimensions": reviewed_dimensions(old)}
        assert client.patch(f"/api/tasks/{old['id']}/review", json=body).status_code == 409
        assert client.post(f"/api/tasks/{old['id']}/manual").status_code == 409
        assert client.post(f"/api/tasks/{old['id']}/confirm").status_code == 409
        asyncio.run(AgentRunner(store, object(), settings).run(old["id"]))
        assert store.get_task(old["id"]) == old

        response = client.post(f"/api/tasks/{old['id']}/retry")
        assert response.status_code == 202
        current = client.get(f"/api/tasks/{response.json()['id']}").json()
        assert current["parent_id"] == old["id"]
        assert current["rubric_version"] == VERSION
        assert current["input_version"] == old["input_version"]
        assert current["status"] == "pending_review"
        assert [dimension["score"] for dimension in current["draft"]["dimensions"]] == [15, 25, 25, 15, 10, 10]
    assert store.get_task(old["id"]) == old


def test_legacy_confirmed_record_keeps_original_scores_and_export(samples, store, settings):
    old = legacy_snapshot(store, samples["S1"], "confirmed")
    archived = store.export_task(old["id"])
    with TestClient(create_app(settings=settings, store=store, provider=object())) as client:
        assert client.get(f"/api/tasks/{old['id']}").json() == old
        assert client.post(f"/api/tasks/{old['id']}/confirm").json() == old
        assert client.get(f"/api/tasks/{old['id']}/export").json() == archived
        assert client.post(f"/api/tasks/{old['id']}/retry").status_code == 409
        assert client.post(f"/api/tasks/{old['id']}/manual").status_code == 409
    assert store.export_task(old["id"]) == archived
    assert store.get_task(old["id"]) == old


def test_old_rubric_is_rejected_for_new_single_tasks(samples, store, settings):
    client = TestClient(create_app(settings=settings, store=store, provider=object()))
    response = client.post("/api/tasks", json={"text": samples["S1"], "rubric_version": LEGACY_VERSION})
    assert response.status_code == 422
