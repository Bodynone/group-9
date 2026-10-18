import csv
from concurrent.futures import ThreadPoolExecutor
import io
import json
import sqlite3

import pytest

from backend.rubric import IDS, VERSION, WEIGHTS
from backend.storage import Store

from scripted_provider import valid_draft


LEGACY_VERSION = "af-2026-10-09-v1"


def files(count=3):
    return [{"filename": f"202300{i}_学生.txt", "text": f"匿名作业正文 {i}"} for i in range(count)]


def review_for(task, level=100):
    dimensions = [{"id": dimension, "level": level, "score": WEIGHTS[dimension] * level / 100,
                   "reason": "教师已核查原文与评分依据", "reviewed": True} for dimension in IDS]
    return {"dimensions": dimensions, "total": sum(dimension["score"] for dimension in dimensions)}


def seed_legacy(store, status):
    task = store.create_task("历史匿名作业", LEGACY_VERSION)
    task["status"] = status
    task["review"] = review_for(task)
    with store.transaction():
        store._save(task)
    return task


def csv_rows(store, batch_id):
    result = store.export_batch_csv(batch_id)
    assert result.encode("utf-8").startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(result.removeprefix("\ufeff"))))


def test_batch_creation_is_ordered_persistent_and_preserves_text(tmp_path):
    database = tmp_path / "grades.sqlite3"
    store = Store(database)
    submitted = files(3)
    submitted[1]["text"] = " \n保留原始文本和空白\n "
    batch = store.create_batch("软件工程-第二次作业", submitted)
    tasks = store.get_batch_tasks(batch["batch_id"])
    assert batch["status"] == "queued"
    assert (batch["total_count"], batch["completed_count"], batch["failed_count"]) == (3, 0, 0)
    assert [task["filename"] for task in tasks] == [file["filename"] for file in submitted]
    assert [task["batch_position"] for task in tasks] == [0, 1, 2]
    assert [task["text"] for task in tasks] == [file["text"] for file in submitted]
    assert all(task["batch_id"] == batch["batch_id"] and task["rubric_version"] == VERSION for task in tasks)
    assert [item["task_id"] for item in store.get_batch(batch["batch_id"])["tasks"]] == [task["id"] for task in tasks]
    store.close()
    restored = Store(database)
    assert restored.get_batch_tasks(batch["batch_id"]) == tasks
    assert restored.get_batch(batch["batch_id"])["name"] == batch["name"]
    restored.close()


def test_failed_batch_creation_rolls_back_batch_tasks_and_slots(store, monkeypatch):
    original_save = store._save
    calls = 0

    def fail_second_task(task):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("模拟第二份作业写入失败")
        original_save(task)

    monkeypatch.setattr(store, "_save", fail_second_task)
    with pytest.raises(RuntimeError, match="第二份"):
        store.create_batch("原子写入", files())
    assert store.list_batches() == {"total": 0, "items": []}
    assert store._connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
    assert store._connection.execute("SELECT COUNT(*) FROM batch_items").fetchone()[0] == 0


@pytest.mark.parametrize("name,submitted,version", [
    (" ", files(), VERSION), ("班级", [], VERSION),
    ("班级", [{"filename": " ", "text": "内容"}], VERSION),
    ("班级", [{"filename": "x.txt", "text": "\n\t"}], VERSION),
    ("班级", [{"filename": "x.txt", "text": "文" * 50_001}], VERSION),
    ("班级", files(), LEGACY_VERSION),
])
def test_invalid_batch_never_creates_partial_records(store, name, submitted, version):
    with pytest.raises(ValueError):
        store.create_batch(name, submitted, version)
    assert store.list_batches()["total"] == 0
    assert store._connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


@pytest.mark.parametrize("states,expected,completed,failed", [
    (["queued", "queued", "queued"], "queued", 0, 0),
    (["running", "queued", "queued"], "running", 0, 0),
    (["pending_review", "queued", "failed"], "running", 1, 1),
    (["pending_review", "pending_review", "confirmed"], "completed", 3, 0),
    (["failed", "pending_review", "confirmed"], "partial_failed", 2, 1),
    (["failed", "failed", "failed"], "failed", 0, 3),
])
def test_batch_counts_and_states_follow_current_slots(store, states, expected, completed, failed):
    batch_id = store.create_batch("状态机", files())["batch_id"]
    for task, status in zip(store.get_batch_tasks(batch_id), states, strict=True):
        store.update_task(task["id"], status=status)
    batch = store.get_batch(batch_id)
    assert (batch["status"], batch["completed_count"], batch["failed_count"]) == (expected, completed, failed)
    assert store.list_batches()["items"][0] == {key: value for key, value in batch.items() if key != "tasks"}


def test_manual_review_confirmation_and_recovery_refresh_batch(store):
    batch_id = store.create_batch("人工接管和恢复", files(2))["batch_id"]
    first, second = store.get_batch_tasks(batch_id)
    store.transition(first["id"], "failed", status="failed")
    assert store.get_batch(batch_id)["failed_count"] == 1
    store.manual_task(first["id"])
    assert store.get_batch(batch_id)["completed_count"] == 1
    assert store.get_batch(batch_id)["failed_count"] == 0
    store.save_review(first["id"], first["input_version"], review_for(first))
    store.confirm_task(first["id"])
    store.append_event(second["id"], "model_request")
    assert store.recover_interrupted() == 1
    batch = store.get_batch(batch_id)
    assert (batch["status"], batch["completed_count"], batch["failed_count"]) == ("partial_failed", 1, 1)
    assert store.get_task(second["id"])["error"]["code"] == "interrupted"


def test_concurrent_retry_replaces_one_slot_once_and_retains_original(tmp_path):
    path = tmp_path / "retry.sqlite3"
    first_store, second_store = Store(path), Store(path)
    batch_id = first_store.create_batch("并发重试", files(1))["batch_id"]
    original = first_store.get_batch_tasks(batch_id)[0]
    failed = first_store.transition(original["id"], "failed", status="failed", error={"code": "model_error"})

    def attempt(store):
        try:
            return store.retry_task(original["id"])
        except ValueError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [first_store, second_store]))
    retried = [result for result in results if isinstance(result, dict)]
    assert len(retried) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    replacement = retried[0]
    assert replacement["parent_id"] == original["id"]
    assert replacement["rubric_version"] == VERSION
    assert replacement["batch_position"] == original["batch_position"]
    assert first_store.get_batch_tasks(batch_id) == [replacement]
    assert first_store.get_task(original["id"]) == failed
    assert first_store.get_batch(batch_id)["total_count"] == 1
    assert first_store.get_batch(batch_id)["failed_count"] == 0
    assert first_store._connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 2
    with pytest.raises(ValueError):
        first_store.manual_task(original["id"])
    first_store.update_task(replacement["id"], status="pending_review")
    assert first_store.get_batch(batch_id)["status"] == "completed"
    first_store.close()
    second_store.close()


@pytest.mark.parametrize("status", ["queued", "running", "pending_review", "failed"])
def test_legacy_tasks_are_readonly_and_retry_uses_current_rubric(store, status):
    original = seed_legacy(store, status)
    operations = [
        lambda: store.update_task(original["id"], status="failed"),
        lambda: store.transition(original["id"], "failed", status="failed"),
        lambda: store.append_event(original["id"], "late_event"),
        lambda: store.save_review(original["id"], original["input_version"], review_for(original)),
        lambda: store.manual_task(original["id"]),
        lambda: store.confirm_task(original["id"]),
    ]
    for operation in operations:
        with pytest.raises(ValueError, match="历史量表"):
            operation()
    assert store.recover_interrupted() == 0
    assert store.get_task(original["id"]) == original
    retried = store.retry_task(original["id"])
    assert retried["rubric_version"] == VERSION
    assert retried["parent_id"] == original["id"]
    assert retried["text"] == original["text"]
    assert retried["input_version"] == original["input_version"]
    assert store.get_task(original["id"]) == original


def test_old_schema_upgrade_preserves_confirmed_archive_exactly(tmp_path):
    temporary_store = Store(":memory:")
    task = temporary_store.create_task("历史已确认匿名作业", LEGACY_VERSION)
    task.update(status="confirmed", record_id="legacy-record", review=review_for(task))
    temporary_store.close()
    record = {"record_id": task["record_id"], "confirmed_at": task["updated_at"], "task": task}
    task_json = json.dumps(task, ensure_ascii=False)
    record_json = json.dumps(record, ensure_ascii=False)
    path = tmp_path / "old-schema.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript("CREATE TABLE tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL); CREATE TABLE records (id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);")
    connection.execute("INSERT INTO tasks VALUES (?,?)", (task["id"], task_json))
    connection.execute("INSERT INTO records VALUES (?,?,?)", (task["record_id"], task["id"], record_json))
    connection.commit()
    connection.close()
    store = Store(path)
    assert store.get_task(task["id"]) == task
    assert store.confirm_task(task["id"]) == task
    assert store.export_task(task["id"]) == record
    assert store._connection.execute("SELECT body FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == task_json
    assert store._connection.execute("SELECT body FROM records WHERE id=?", (task["record_id"],)).fetchone()[0] == record_json
    with pytest.raises(ValueError):
        store.retry_task(task["id"])
    assert store.list_batches()["total"] == 0
    store.close()


def test_csv_uses_teacher_scores_zero_and_blank_and_safe_escaped_filenames(store, samples):
    submitted = [
        {"filename": '张三,"同学"\n作业.txt', "text": samples["S1"]},
        {"filename": '=HYPERLINK("https://example.invalid")', "text": "排队中的作业"},
        {"filename": "人工接管.txt", "text": "待人工填写"},
    ]
    batch_id = store.create_batch("中文成绩单", submitted)["batch_id"]
    first, second, third = store.get_batch_tasks(batch_id)
    draft = valid_draft(first)
    draft["dimensions"][0]["needs_review"] = True
    store.transition(first["id"], "pending_review", status="pending_review", draft=draft, review=review_for(first, 0), security_flag="prompt_injection_detected")
    store.transition(third["id"], "failed", status="failed", draft=valid_draft({**third, "text": samples["S1"]}))
    store.manual_task(third["id"])
    rows = csv_rows(store, batch_id)
    assert rows[0] == ["文件名/学生标识", "总分", "A得分(15)", "B得分(25)", "C得分(25)", "D得分(15)", "E得分(10)", "F得分(10)", "状态", "安全预警", "完成时间"]
    assert rows[1][0] == submitted[0]["filename"]
    assert float(rows[1][1]) == 0
    assert all(float(score) == 0 for score in rows[1][2:8])
    assert rows[1][8:10] == ["已复核", "prompt_injection_detected"]
    assert rows[2][0] == "'" + submitted[1]["filename"]
    assert rows[2][1:8] == [""] * 7
    assert rows[2][8:] == ["排队中", "正常", ""]
    assert rows[3][1:8] == [""] * 7
    assert rows[3][8] == "待复核"
    summary = store.get_batch(batch_id)["tasks"]
    assert summary[0]["total_score"] == 0
    assert summary[0]["needs_review"] is True
    assert summary[1]["total_score"] is None
    assert summary[2]["total_score"] is None


def test_csv_completion_time_uses_terminal_event_in_china_timezone(store):
    batch_id = store.create_batch("完成时间", files(1))["batch_id"]
    task = store.get_batch_tasks(batch_id)[0]
    store.update_task(task["id"], status="pending_review", trace=[
        {"kind": "pending_review", "created_at": "2026-10-17T01:02:03Z"},
        {"kind": "teacher_review", "created_at": "2026-10-18T01:02:03Z"},
    ])
    assert csv_rows(store, batch_id)[1][-1] == "2026-10-17 09:02:03"


def test_batch_pagination_and_unknown_ids(store):
    first = store.create_batch("第一批", files(1))
    second = store.create_batch("第二批", files(1))
    assert store.list_batches(limit=1)["items"][0]["batch_id"] == second["batch_id"]
    assert store.list_batches(limit=1, offset=1)["items"][0]["batch_id"] == first["batch_id"]
    assert store.list_batches(offset=2) == {"total": 2, "items": []}
    for method in (store.get_batch, store.get_batch_tasks, store.update_batch_progress, store.export_batch_csv):
        with pytest.raises(KeyError):
            method("unknown-batch")
    with pytest.raises(KeyError):
        store.retry_task("unknown-task")


@pytest.mark.parametrize("method", ["get_batch", "get_batch_tasks", "export_batch_csv"])
def test_compound_batch_reads_keep_one_snapshot_across_connections(tmp_path, monkeypatch, method):
    path = tmp_path / "snapshot.sqlite3"
    reader, writer = Store(path), Store(path)
    try:
        batch_id = reader.create_batch("快照一致性", files(1))["batch_id"]
        task_id = reader.get_batch_tasks(batch_id)[0]["id"]
        original_summary = reader._get_batch_summary
        interleaved = False

        def summary_then_commit(batch_id):
            nonlocal interleaved
            summary = original_summary(batch_id)
            if not interleaved:
                interleaved = True
                writer.update_task(task_id, status="pending_review")
            return summary

        monkeypatch.setattr(reader, "_get_batch_summary", summary_then_commit)
        result = getattr(reader, method)(batch_id)
        assert interleaved
        if method == "get_batch":
            assert result["status"] == "queued"
            assert result["completed_count"] == 0
            assert result["tasks"][0]["status"] == "queued"
        elif method == "get_batch_tasks":
            assert result[0]["status"] == "queued"
        else:
            rows = list(csv.reader(io.StringIO(result.removeprefix("\ufeff"))))
            assert rows[1][8] == "排队中"
        refreshed = reader.get_batch(batch_id)
        assert refreshed["status"] == "completed"
        assert refreshed["completed_count"] == 1
        assert refreshed["tasks"][0]["status"] == "pending_review"
    finally:
        reader.close()
        writer.close()


def test_batch_list_total_and_items_share_snapshot_when_another_connection_inserts(tmp_path, monkeypatch):
    path = tmp_path / "pagination-snapshot.sqlite3"
    reader, writer = Store(path), Store(path)
    try:
        first = reader.create_batch("原有批次", files(1))
        connection = reader._connection
        added = None

        class InterleavingConnection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *parameters):
                nonlocal added
                cursor = connection.execute(sql, *parameters)
                if sql == "SELECT COUNT(*) FROM batches" and added is None:
                    added = writer.create_batch("并发新增批次", files(1))
                return cursor

        monkeypatch.setattr(reader, "_connection", InterleavingConnection())
        original_snapshot = reader.list_batches()
        assert added is not None
        assert original_snapshot["total"] == 1
        assert [item["batch_id"] for item in original_snapshot["items"]] == [first["batch_id"]]
        refreshed = reader.list_batches()
        assert refreshed["total"] == 2
        assert [item["batch_id"] for item in refreshed["items"]] == [added["batch_id"], first["batch_id"]]
    finally:
        reader.close()
        writer.close()


def test_compound_read_reuses_write_transaction_without_committing_it(store):
    batch_id = store.create_batch("复用事务", files(1))["batch_id"]
    task = store.get_batch_tasks(batch_id)[0]
    with pytest.raises(RuntimeError, match="回滚外部事务"):
        with store.transaction():
            task["status"] = "pending_review"
            store._save_and_refresh(task)
            assert store.get_batch(batch_id)["completed_count"] == 1
            assert store.get_batch_tasks(batch_id)[0]["status"] == "pending_review"
            assert store.list_batches()["items"][0]["status"] == "completed"
            assert "待复核" in store.export_batch_csv(batch_id)
            assert store._connection.in_transaction
            raise RuntimeError("回滚外部事务")
    assert store.get_batch(batch_id)["status"] == "queued"
    assert store.get_task(task["id"])["status"] == "queued"
