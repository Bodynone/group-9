import pytest

from backend.rubric import VERSION
from backend.storage import Store

from scripted_provider import valid_draft, reviewed_dimensions


def test_task_round_trip_preserves_source_and_trace(samples, settings):
    store = Store(settings.database_path)
    task = store.create_task(samples["S1"], VERSION)
    store.append_event(task["id"], "tool", tool="read_rubric", details={"version": VERSION})
    fresh_store = Store(settings.database_path)
    restored = fresh_store.get_task(task["id"])
    assert restored["text"] == task["text"]
    assert restored["input_version"] == task["input_version"]
    assert restored["rubric_version"] == VERSION
    assert restored["trace"]


def test_restart_marks_only_interrupted_tasks_failed(samples, store):
    queued = store.create_task(samples["S1"], VERSION)
    running = store.create_task(samples["S1"], VERSION)
    review = store.create_task(samples["S1"], VERSION)
    store.update_task(running["id"], status="running")
    store.update_task(review["id"], status="pending_review", draft=valid_draft(review))
    store.recover_interrupted()
    for task in (queued, running):
        result = store.get_task(task["id"])
        assert result["status"] == "failed"
        assert result["error"]
        assert result["text"] == task["text"]
        assert result["input_version"] == task["input_version"]
    assert store.get_task(review["id"])["status"] == "pending_review"


def test_cannot_confirm_an_unreviewed_task(samples, store):
    task = store.create_task(samples["S1"], VERSION)
    with pytest.raises((ValueError, RuntimeError)):
        store.confirm_task(task["id"])
    assert store.get_task(task["id"])["record_id"] is None


def test_second_manual_takeover_cannot_erase_a_saved_teacher_review(samples, store):
    task = store.create_task(samples["S1"], VERSION)
    store.update_task(task["id"], status="failed")
    store.manual_task(task["id"])
    review = {"dimensions": reviewed_dimensions(task), "total": 100}
    saved = store.save_review(task["id"], task["input_version"], review)
    with pytest.raises(ValueError):
        store.manual_task(task["id"])
    assert store.get_task(task["id"]) == saved


def test_confirmation_snapshot_contains_final_teacher_review_event_and_is_immutable(samples, store):
    task = store.create_task(samples["S1"], VERSION)
    store.update_task(task["id"], status="pending_review", draft=valid_draft(task))
    review = {"dimensions": reviewed_dimensions(task), "total": 100}
    store.save_review(task["id"], task["input_version"], review)
    confirmed = store.confirm_task(task["id"])
    snapshot = store.export_task(task["id"])
    assert snapshot["task"]["trace"][-2]["kind"] == "teacher_review"
    assert snapshot["task"]["trace"][-2]["details"] == review
    assert snapshot["task"]["trace"][-1]["kind"] == "confirmed"
    assert snapshot["task"]["review"] == review
    with pytest.raises(ValueError):
        store.append_event(task["id"], "late_event", details={"message": "迟到的事件"})
    assert store.get_task(task["id"]) == confirmed
    assert store.export_task(task["id"]) == snapshot
