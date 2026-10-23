"""Lifecycle changes must never alter grading history or bypass reference checks."""
import json

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.rubric_service import RubricService
from backend.schemas_v2 import V2Error, canonical
from dynamic_provider import DynamicTestProvider
from test_v2 import configured, definition, review_body, versions


def test_delete_draft_hides_empty_series_and_preserves_version_numbers(store):
    service = RubricService(store)
    published, _ = configured(service)
    draft = service.copy_version(published["rubric_id"], published["id"])
    assert draft["version_no"] == 2
    with pytest.raises(V2Error, match="页面已过期"):
        service.delete_draft(draft["id"], 999)
    service.delete_draft(draft["id"], draft["revision"])
    with pytest.raises(V2Error) as exc:
        service.get("rubric_versions", draft["id"])
    assert exc.value.status == 404
    replacement = service.copy_version(published["rubric_id"], published["id"])
    assert replacement["version_no"] == 3
    assert draft["id"] not in canonical(service.list("rubrics", include_archived=True))
    empty = service.new_rubric("误建标准")
    service.delete_draft(empty["draft"]["id"], 1)
    assert empty["id"] not in [r["id"] for r in service.list("rubrics", include_archived=True)["items"]]


def test_published_version_cannot_be_deleted(store):
    service = RubricService(store)
    version, _ = configured(service)
    with pytest.raises(V2Error) as exc:
        service.delete_draft(version["id"], version["revision"])
    assert exc.value.code == "STATE_CONFLICT"


def test_referenced_draft_cannot_be_deleted(store):
    service = RubricService(store)
    course = service.course("课程")
    draft = service.new_rubric("草稿")["draft"]
    service.assignment({"course_id": course["id"], "title": "未发布任务", "instructions": "说明过程",
                        "reference_text": "", "rubric_version_id": draft["id"]})
    with pytest.raises(V2Error) as exc:
        service.delete_draft(draft["id"], 1)
    assert exc.value.code == "RUBRIC_IN_USE"
    assert service.get("rubric_versions", draft["id"])["state"] == "draft"


@pytest.mark.parametrize("series", [False, True])
def test_archive_blocks_new_bindings_but_preserves_existing_grading(store, series):
    service = RubricService(store)
    version, assignment = configured(service)
    task = service.submit({"assignment_id": assignment["id"], "submission_label": "原任务", "text": "🧪 原文"}, "before")
    snapshot = canonical(task)
    target = version["rubric_id"] if series else version["id"]
    revision = version["rubric_revision"] if series else version["revision"]
    archived = service.lifecycle(target, revision, True, series)
    assert version["id"] not in canonical(service.list("rubrics"))
    assert version["id"] in canonical(service.list("rubrics", include_archived=True))
    assert canonical(service.task(task["id"])) == snapshot
    assert service.submit({"assignment_id": assignment["id"], "submission_label": "后续提交", "text": "同一作业"}, "after")["rubric_hash"] == task["rubric_hash"]
    assert service.publish_assignment(assignment["id"], assignment["revision"])["state"] == "published"
    with pytest.raises(V2Error) as exc:
        service.assignment({"course_id": assignment["course_id"], "title": "新任务", "instructions": "说明", "reference_text": "", "rubric_version_id": version["id"]})
    assert exc.value.code == "RUBRIC_ARCHIVED"
    with pytest.raises(V2Error): service.new_rubric("新标准", version["id"])
    with pytest.raises(V2Error): service.copy_version(version["rubric_id"], version["id"])
    with pytest.raises(V2Error): service.lifecycle(target, revision, False, series)
    service.lifecycle(target, archived["revision"], False, series)
    assert version["id"] in canonical(service.list("rubrics"))
    assert service.get("rubric_versions", version["id"])["content_hash"] == version["content_hash"]


def test_series_restore_does_not_restore_individually_archived_version(store):
    service = RubricService(store)
    version, _ = configured(service)
    service.lifecycle(version["id"], version["revision"], True)
    parent = service.lifecycle(version["rubric_id"], 1, True, True)
    service.lifecycle(version["rubric_id"], parent["revision"], False, True)
    assert version["id"] not in canonical(service.list("rubrics"))
    assert service.describe(service.get("rubric_versions", version["id"]))["archived"]


def test_archived_draft_cannot_save_or_publish_and_pending_assignment_cannot_publish(store):
    service = RubricService(store)
    version, assignment = configured(service)
    pending = service.assignment({"course_id": assignment["course_id"], "title": "待发布", "instructions": "说明", "reference_text": "", "rubric_version_id": version["id"]})
    service.lifecycle(version["id"], version["revision"], True)
    with pytest.raises(V2Error): service.publish_assignment(pending["id"], 1)
    draft = service.new_rubric("编辑草稿")["draft"]
    archived = service.lifecycle(draft["id"], 1, True)
    with pytest.raises(V2Error): service.update_version(draft["id"], archived["revision"], definition())
    with pytest.raises(V2Error): service.publish_version(draft["id"], archived["revision"])


def test_default_template_uses_active_preset_and_handles_all_archived(store):
    service = RubricService(store)
    service.lifecycle("af-2026-10-09-v1", 1, True)
    assert service.new_rubric("仍可新建")["draft"]["definition"]["dimensions"][1]["max_score"] == "25.00"
    service.lifecycle("2026-v1", 1, True)
    with pytest.raises(V2Error) as exc: service.new_rubric("没有可用模板")
    assert exc.value.code == "RUBRIC_ARCHIVED"


def test_lifecycle_api_revision_filters_delete_and_restore(settings, store):
    app = create_app(settings=settings, store=store, provider=DynamicTestProvider())
    with TestClient(app) as client:
        draft = client.post("/api/v2/rubrics", json={"title": "API草稿"}).json()["draft"]
        path = f"/api/v2/rubric-versions/{draft['id']}"
        assert client.post(path + "/archive", json={"expected_revision": 99}).status_code == 409
        archived = client.post(path + "/archive", json={"expected_revision": 1}).json()
        assert draft["id"] not in json.dumps(client.get("/api/v2/rubrics").json())
        assert draft["id"] in json.dumps(client.get("/api/v2/rubrics?include_archived=true").json())
        restored = client.post(path + "/restore", json={"expected_revision": archived["revision"]}).json()
        assert client.request("DELETE", path, json={"expected_revision": restored["revision"]}).status_code == 200
        assert client.get(path).status_code == 404
        assert client.request("DELETE", path, json={"expected_revision": restored["revision"]}).status_code == 404


@pytest.mark.parametrize("series", [False, True])
def test_archive_does_not_change_confirmed_export(store, series):
    service = RubricService(store)
    version, assignment = configured(service)
    task = service.submit({"assignment_id": assignment["id"], "submission_label": "匿名", "text": "原文"}, "confirm")
    task = service.change(task["id"], {"status": "failed"}, "test_failure")
    task = service.manual(task["id"])
    task = service.review(task["id"], review_body(task))
    task = service.confirm(task["id"], versions(task))
    original = canonical(store.export_task(task["id"]))
    service.lifecycle(version["rubric_id"] if series else version["id"], version["rubric_revision"] if series else version["revision"], True, series)
    assert canonical(store.export_task(task["id"])) == original
