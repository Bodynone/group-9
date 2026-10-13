"""Atomic SQLite snapshots of tasks and immutable confirmed records."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from .rubric import VERSION


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False, timeout=20)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.executescript(
            "CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);"
        )
        self._connection.commit()

    @contextmanager
    def transaction(self):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                yield
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def _get(self, task_id: str) -> dict:
        row = self._connection.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return json.loads(row[0])

    def _save(self, task: dict):
        self._connection.execute("INSERT OR REPLACE INTO tasks VALUES (?,?)", (task["id"], json.dumps(task, ensure_ascii=False, allow_nan=False)))

    def get_task(self, task_id: str) -> dict:
        with self._lock:
            return self._get(task_id)

    def create_task(self, text: str, rubric_version: str = VERSION, parent_id: str | None = None) -> dict:
        timestamp = now()
        task = {
            "id": str(uuid4()), "status": "queued", "source": "agent",
            "text": text, "input_version": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "rubric_version": rubric_version, "created_at": timestamp, "updated_at": timestamp,
            "parent_id": parent_id, "draft": None, "review": None, "trace": [], "error": None,
            "repair_rounds": 0, "validation_count": 0, "model_calls": 0, "record_id": None,
        }
        with self.transaction():
            self._save(task)
        return task

    def update_task(self, task_id: str, **fields) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] == "confirmed":
                raise ValueError("已确认记录不可修改")
            task.update(fields)
            task["updated_at"] = now()
            self._save(task)
            return task

    def transition(self, task_id: str, kind: str, details: dict | None = None, tool: str | None = None, **fields) -> dict:
        """Expose a new actionable state and its terminal audit event atomically."""
        with self.transaction():
            task = self._get(task_id)
            if task["status"] == "confirmed":
                raise ValueError("已确认记录不可修改")
            task.update(fields)
            task["updated_at"] = now()
            task["trace"].append({
                "sequence": len(task["trace"]) + 1, "kind": kind, "tool": tool,
                "round": task["repair_rounds"], "validation_count": task["validation_count"], "model_calls": task["model_calls"],
                "details": details or {}, "created_at": task["updated_at"], "task_id": task_id,
                "input_version": task["input_version"], "rubric_version": task["rubric_version"],
            })
            self._save(task)
            return task

    def append_event(self, task_id: str, kind: str, tool: str | None = None, details: dict | None = None) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] == "confirmed":
                raise ValueError("已确认记录不可追加执行事件")
            event = {
                "sequence": len(task["trace"]) + 1, "kind": kind, "tool": tool,
                "round": task["repair_rounds"], "validation_count": task["validation_count"],
                "model_calls": task["model_calls"], "details": details or {}, "created_at": now(),
                "task_id": task_id, "input_version": task["input_version"], "rubric_version": task["rubric_version"],
            }
            task["trace"].append(event)
            task["updated_at"] = now()
            self._save(task)
            return event

    def save_review(self, task_id: str, input_version: str, review: dict) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] != "pending_review":
                raise ValueError("当前任务不能编辑复核结果")
            if input_version != task["input_version"]:
                raise ValueError("输入版本已变化，请重新生成草稿")
            task["review"] = review
            task["updated_at"] = now()
            task["trace"].append({
                "sequence": len(task["trace"]) + 1, "kind": "teacher_review", "tool": "calculate_scores",
                "round": task["repair_rounds"], "validation_count": task["validation_count"],
                "model_calls": task["model_calls"], "details": review, "created_at": task["updated_at"],
                "task_id": task_id, "input_version": task["input_version"], "rubric_version": task["rubric_version"],
            })
            self._save(task)
            return task

    def manual_task(self, task_id: str) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] != "failed":
                raise ValueError("仅失败任务可以转人工批改")
            task.update(status="pending_review", source="manual", updated_at=now(), review={
                "dimensions": [{"id": dimension, "level": None, "score": None, "reason": "", "reviewed": False} for dimension in "ABCDEF"], "total": None,
            })
            task["trace"].append({
                "sequence": len(task["trace"]) + 1, "kind": "manual_takeover", "tool": None,
                "round": task["repair_rounds"], "validation_count": task["validation_count"], "model_calls": task["model_calls"],
                "details": {"message": "教师已接管评分，Agent失败记录已保留"}, "created_at": task["updated_at"],
                "task_id": task_id, "input_version": task["input_version"], "rubric_version": task["rubric_version"],
            })
            self._save(task)
            return task

    def confirm_task(self, task_id: str) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] == "confirmed":
                return task
            review = task.get("review")
            if task["status"] != "pending_review" or not review:
                raise ValueError("仅待复核任务可以确认")
            dimensions = review.get("dimensions", [])
            if len(dimensions) != 6 or not all(d.get("reviewed") and d.get("level") in (100, 70, 30, 0) and str(d.get("reason", "")).strip() for d in dimensions):
                raise ValueError("请完成六个维度的档位、理由与复核确认")
            task["status"] = "confirmed"
            task["record_id"] = str(uuid4())
            task["updated_at"] = now()
            task["trace"].append({
                "sequence": len(task["trace"]) + 1, "kind": "confirmed", "tool": None,
                "round": task["repair_rounds"], "validation_count": task["validation_count"],
                "model_calls": task["model_calls"], "details": {"record_id": task["record_id"]},
                "created_at": task["updated_at"], "task_id": task_id,
                "input_version": task["input_version"], "rubric_version": task["rubric_version"],
            })
            record = {"record_id": task["record_id"], "confirmed_at": task["updated_at"], "task": task}
            self._connection.execute("INSERT INTO records VALUES (?,?,?)", (task["record_id"], task_id, json.dumps(record, ensure_ascii=False, allow_nan=False)))
            self._save(task)
            return task

    def export_task(self, task_id: str) -> dict:
        with self._lock:
            row = self._connection.execute("SELECT body FROM records WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("请先完成教师确认，再导出记录")
            return json.loads(row[0])

    def recover_interrupted(self) -> int:
        with self.transaction():
            rows = self._connection.execute("SELECT body FROM tasks").fetchall()
            recovered = 0
            for row in rows:
                task = json.loads(row[0])
                if task["status"] in ("queued", "running"):
                    task.update(status="failed", draft=None, review=None, error={"code": "interrupted", "message": "服务已重启，任务中断；原作业与量表已保留，请重试或人工批改。"}, updated_at=now())
                    task["trace"].append({"sequence": len(task["trace"]) + 1, "kind": "failed", "tool": None, "round": task["repair_rounds"], "validation_count": task["validation_count"], "model_calls": task["model_calls"], "details": task["error"], "created_at": now(), "task_id": task["id"], "input_version": task["input_version"], "rubric_version": task["rubric_version"]})
                    self._save(task)
                    recovered += 1
            return recovered

    def close(self):
        with self._lock:
            self._connection.close()
