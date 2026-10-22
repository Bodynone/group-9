"""Atomic SQLite snapshots, batch slots, and immutable confirmed records."""

from contextlib import contextmanager
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import threading
from uuid import uuid4

from .rubric import IDS, VERSION, WEIGHTS


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
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self.transaction():
            self._connection.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            self._connection.execute("CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, task_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL)")
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS batches ("
                "id TEXT PRIMARY KEY, name TEXT NOT NULL, total_count INTEGER NOT NULL, "
                "completed_count INTEGER DEFAULT 0, failed_count INTEGER DEFAULT 0, "
                "status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS batch_items ("
                "batch_id TEXT NOT NULL REFERENCES batches(id), position INTEGER NOT NULL, "
                "filename TEXT NOT NULL, current_task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id), "
                "PRIMARY KEY(batch_id, position))"
            )

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

    @contextmanager
    def _snapshot(self):
        """Keep compound reads on one WAL snapshot, including across Store instances."""
        with self._lock:
            if self._connection.in_transaction:
                yield
                return
            try:
                self._connection.execute("BEGIN DEFERRED")
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
        # Updating in place preserves foreign-key references from current batch slots.
        self._connection.execute(
            "INSERT INTO tasks (id, body) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body",
            (task["id"], json.dumps(task, ensure_ascii=False, allow_nan=False)),
        )

    @staticmethod
    def _new_task(text: str, rubric_version: str, parent_id: str | None = None, **metadata) -> dict:
        timestamp = now()
        return {
            "id": str(uuid4()), "status": "queued", "source": "agent",
            "text": text, "input_version": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "rubric_version": rubric_version, "created_at": timestamp, "updated_at": timestamp,
            "parent_id": parent_id, "draft": None, "review": None, "trace": [], "error": None,
            "repair_rounds": 0, "validation_count": 0, "model_calls": 0, "record_id": None,
            **metadata,
        }

    def _ensure_writable(self, task: dict):
        if task.get("api_version") == 2:
            raise ValueError("该任务须通过 v2 接口及冻结快照复核")
        if task["rubric_version"] != VERSION:
            raise ValueError("历史量表任务仅可查看，请按当前量表重新批改")
        if task["status"] == "confirmed":
            raise ValueError("已确认记录不可修改")
        if task.get("batch_id") is not None:
            row = self._connection.execute(
                "SELECT current_task_id FROM batch_items WHERE batch_id=? AND position=?",
                (task["batch_id"], task.get("batch_position")),
            ).fetchone()
            if row is None or row[0] != task["id"]:
                raise ValueError("该批次任务已被新的重试替换，仅可查看历史结果")

    @staticmethod
    def _append_trace(task: dict, kind: str, tool: str | None = None, details: dict | None = None) -> dict:
        event = {
            "sequence": len(task["trace"]) + 1, "kind": kind, "tool": tool,
            "round": task["repair_rounds"], "validation_count": task["validation_count"],
            "model_calls": task["model_calls"], "details": details or {}, "created_at": task["updated_at"],
            "task_id": task["id"], "input_version": task["input_version"], "rubric_version": task["rubric_version"],
        }
        task["trace"].append(event)
        return event

    def _get_batch_summary(self, batch_id: str) -> dict:
        row = self._connection.execute(
            "SELECT id, name, total_count, completed_count, failed_count, status, created_at, updated_at "
            "FROM batches WHERE id=?", (batch_id,),
        ).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return dict(zip(("batch_id", "name", "total_count", "completed_count", "failed_count", "status", "created_at", "updated_at"), row, strict=True))

    def _get_batch_tasks(self, batch_id: str) -> list[dict]:
        rows = self._connection.execute(
            "SELECT tasks.body FROM batch_items JOIN tasks ON tasks.id=batch_items.current_task_id "
            "WHERE batch_items.batch_id=? ORDER BY batch_items.position", (batch_id,),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def _refresh_batch(self, batch_id: str) -> dict:
        summary = self._get_batch_summary(batch_id)
        tasks = self._get_batch_tasks(batch_id)
        completed = sum(task["status"] in ("pending_review", "confirmed") for task in tasks)
        failed = sum(task["status"] == "failed" for task in tasks)
        active = sum(task["status"] in ("queued", "running") for task in tasks)
        if active:
            status = "queued" if all(task["status"] == "queued" for task in tasks) else "running"
        elif failed == summary["total_count"]:
            status = "failed"
        elif failed:
            status = "partial_failed"
        else:
            status = "completed"
        self._connection.execute(
            "UPDATE batches SET completed_count=?, failed_count=?, status=?, updated_at=? WHERE id=?",
            (completed, failed, status, now(), batch_id),
        )
        return self._get_batch_summary(batch_id)

    def _save_and_refresh(self, task: dict):
        self._save(task)
        row = self._connection.execute("SELECT batch_id FROM batch_items WHERE current_task_id=?", (task["id"],)).fetchone()
        if row is not None:
            self._refresh_batch(row[0])

    def get_task(self, task_id: str) -> dict:
        with self._lock:
            return self._get(task_id)

    def create_task(self, text: str, rubric_version: str = VERSION, parent_id: str | None = None) -> dict:
        task = self._new_task(text, rubric_version, parent_id)
        with self.transaction():
            self._save(task)
        return task

    def create_batch(self, name: str, files: list[dict], rubric_version: str = VERSION) -> dict:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("请填写非空的批次名称")
        if rubric_version != VERSION:
            raise ValueError("量表版本不支持，请重新加载固定量表")
        if not isinstance(files, list) or not files:
            raise ValueError("批次必须包含至少一份作业")
        for file in files:
            if not isinstance(file, dict) or not isinstance(file.get("filename"), str) or not file["filename"].strip():
                raise ValueError("请填写非空的文件名")
            text = file.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 50_000:
                raise ValueError("每份作业正文须为1至50000字符的非空文本")
        batch_id, timestamp = str(uuid4()), now()
        with self.transaction():
            self._connection.execute(
                "INSERT INTO batches VALUES (?,?,?,?,?,?,?,?)",
                (batch_id, name, len(files), 0, 0, "queued", timestamp, timestamp),
            )
            for position, file in enumerate(files):
                task = self._new_task(file["text"], rubric_version, batch_id=batch_id, filename=file["filename"], batch_position=position)
                self._save(task)
                self._connection.execute("INSERT INTO batch_items VALUES (?,?,?,?)", (batch_id, position, file["filename"], task["id"]))
            return self._get_batch_summary(batch_id)

    @staticmethod
    def _grading(task: dict) -> dict:
        if task["status"] not in ("pending_review", "confirmed"):
            return {}
        review = task.get("review")
        if review is not None:
            return review
        return task.get("draft") or {}

    @staticmethod
    def _security_flag(task: dict) -> str:
        return task.get("security_flag") or (task.get("draft") or {}).get("security_flag") or "none"

    def get_batch(self, batch_id: str) -> dict:
        with self._snapshot():
            summary = self._get_batch_summary(batch_id)
            summary["tasks"] = [{
                "task_id": task["id"], "filename": task["filename"], "status": task["status"],
                "total_score": self._grading(task).get("total"),
                "needs_review": any(d.get("needs_review", False) for d in (task.get("draft") or {}).get("dimensions", [])),
                "security_flag": self._security_flag(task), "created_at": task["created_at"],
            } for task in self._get_batch_tasks(batch_id)]
            return summary

    def get_batch_tasks(self, batch_id: str) -> list[dict]:
        with self._snapshot():
            self._get_batch_summary(batch_id)
            return self._get_batch_tasks(batch_id)

    def list_batches(self, limit: int = 20, offset: int = 0) -> dict:
        if type(limit) is not int or limit < 1 or type(offset) is not int or offset < 0:
            raise ValueError("分页参数须为正整数limit和非负整数offset")
        with self._snapshot():
            total = self._connection.execute("SELECT COUNT(*) FROM batches").fetchone()[0]
            rows = self._connection.execute(
                "SELECT id FROM batches ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?", (limit, offset),
            ).fetchall()
            return {"total": total, "items": [self._get_batch_summary(row[0]) for row in rows]}

    def update_batch_progress(self, batch_id: str) -> dict:
        with self.transaction():
            return self._refresh_batch(batch_id)

    def retry_task(self, task_id: str) -> dict:
        with self.transaction():
            original = self._get(task_id)
            legacy = original["rubric_version"] != VERSION
            if original["status"] == "confirmed":
                raise ValueError("已确认任务不可重试")
            if not legacy and original["status"] != "failed":
                raise ValueError("仅失败任务可以重试")
            metadata = {}
            if original.get("batch_id") is not None:
                row = self._connection.execute(
                    "SELECT current_task_id FROM batch_items WHERE batch_id=? AND position=?",
                    (original["batch_id"], original.get("batch_position")),
                ).fetchone()
                if row is None or row[0] != task_id:
                    raise ValueError("该批次任务已被新的重试替换，仅可查看历史结果")
                metadata = {key: original[key] for key in ("batch_id", "filename", "batch_position")}
            task = self._new_task(original["text"], VERSION, parent_id=task_id, **metadata)
            self._append_trace(task, "retry_created", details={"parent_id": task_id})
            self._save(task)
            if metadata:
                result = self._connection.execute(
                    "UPDATE batch_items SET current_task_id=? WHERE batch_id=? AND position=? AND current_task_id=?",
                    (task["id"], metadata["batch_id"], metadata["batch_position"], task_id),
                )
                if result.rowcount != 1:
                    raise ValueError("该批次任务已被新的重试替换，仅可查看历史结果")
                self._refresh_batch(metadata["batch_id"])
            return task

    def update_task(self, task_id: str, **fields) -> dict:
        with self.transaction():
            task = self._get(task_id)
            self._ensure_writable(task)
            task.update(fields)
            task["updated_at"] = now()
            self._save_and_refresh(task)
            return task

    def transition(self, task_id: str, kind: str, details: dict | None = None, tool: str | None = None, **fields) -> dict:
        """Expose a new actionable state and its terminal audit event atomically."""
        with self.transaction():
            task = self._get(task_id)
            self._ensure_writable(task)
            task.update(fields)
            task["updated_at"] = now()
            self._append_trace(task, kind, tool, details)
            self._save_and_refresh(task)
            return task

    def append_event(self, task_id: str, kind: str, tool: str | None = None, details: dict | None = None) -> dict:
        with self.transaction():
            task = self._get(task_id)
            self._ensure_writable(task)
            task["updated_at"] = now()
            event = self._append_trace(task, kind, tool, details)
            self._save_and_refresh(task)
            return event

    def save_review(self, task_id: str, input_version: str, review: dict) -> dict:
        with self.transaction():
            task = self._get(task_id)
            self._ensure_writable(task)
            if task["status"] != "pending_review":
                raise ValueError("当前任务不能编辑复核结果")
            if input_version != task["input_version"]:
                raise ValueError("输入版本已变化，请重新生成草稿")
            task["review"] = review
            task["updated_at"] = now()
            self._append_trace(task, "teacher_review", "calculate_scores", review)
            self._save_and_refresh(task)
            return task

    def manual_task(self, task_id: str) -> dict:
        with self.transaction():
            task = self._get(task_id)
            self._ensure_writable(task)
            if task["status"] != "failed":
                raise ValueError("仅失败任务可以转人工批改")
            task.update(status="pending_review", source="manual", updated_at=now(), review={
                "dimensions": [{"id": dimension, "level": None, "score": None, "reason": "", "reviewed": False} for dimension in IDS], "total": None,
            })
            self._append_trace(task, "manual_takeover", details={"message": "教师已接管评分，Agent失败记录已保留"})
            self._save_and_refresh(task)
            return task

    @staticmethod
    def _review_complete(review: dict) -> bool:
        dimensions = review.get("dimensions", [])
        return (
            len(dimensions) == 6 and {d.get("id") for d in dimensions} == set(IDS)
            and all(d.get("reviewed") is True and type(d.get("level")) is int and d["level"] in (100, 70, 30, 0)
                    and isinstance(d.get("reason"), str) and d["reason"].strip() for d in dimensions)
        )

    def confirm_task(self, task_id: str) -> dict:
        with self.transaction():
            task = self._get(task_id)
            if task["status"] == "confirmed":
                return task
            self._ensure_writable(task)
            review = task.get("review")
            if task["status"] != "pending_review" or not review:
                raise ValueError("仅待复核任务可以确认")
            if not self._review_complete(review):
                raise ValueError("请完成六个维度的档位、理由与复核确认")
            task["status"] = "confirmed"
            task["record_id"] = str(uuid4())
            task["updated_at"] = now()
            self._append_trace(task, "confirmed", details={"record_id": task["record_id"]})
            record = {"record_id": task["record_id"], "confirmed_at": task["updated_at"], "task": task}
            self._connection.execute("INSERT INTO records VALUES (?,?,?)", (task["record_id"], task_id, json.dumps(record, ensure_ascii=False, allow_nan=False)))
            self._save_and_refresh(task)
            return task

    def export_task(self, task_id: str) -> dict:
        with self._lock:
            row = self._connection.execute("SELECT body FROM records WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                raise ValueError("请先完成教师确认，再导出记录")
            return json.loads(row[0])

    @staticmethod
    def _completion_time(task: dict) -> str:
        terminal_kinds = {"pending_review", "completed", "manual_takeover", "confirmed", "failed"}
        for event in reversed(task.get("trace", [])):
            if event.get("kind") in terminal_kinds:
                try:
                    timestamp = datetime.fromisoformat(event["created_at"].replace("Z", "+00:00"))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    return timestamp.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
                except (KeyError, TypeError, ValueError):
                    continue
        return ""

    @staticmethod
    def _csv_text(value: str) -> str:
        # Spreadsheet programs interpret these prefixes as formulas even in quoted CSV cells.
        if value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def export_batch_csv(self, batch_id: str) -> str:
        with self._snapshot():
            self._get_batch_summary(batch_id)
            tasks = self._get_batch_tasks(batch_id)
            output = io.StringIO(newline="")
            output.write("\ufeff")
            writer = csv.writer(output)
            writer.writerow(["文件名/学生标识", "总分", *(f"{dimension}得分({WEIGHTS[dimension]})" for dimension in IDS), "状态", "安全预警", "完成时间"])
            statuses = {"queued": "排队中", "running": "运行中", "pending_review": "待复核", "failed": "失败", "confirmed": "已确认"}
            for task in tasks:
                grading = self._grading(task)
                scores = {dimension["id"]: dimension.get("score") for dimension in grading.get("dimensions", [])}
                status = statuses[task["status"]]
                if task["status"] == "pending_review" and self._review_complete(task.get("review") or {}):
                    status = "已复核"
                flag = self._security_flag(task)
                writer.writerow([
                    self._csv_text(task["filename"]), grading.get("total"), *(scores.get(dimension) for dimension in IDS),
                    status, self._csv_text("正常" if flag == "none" else flag), self._completion_time(task),
                ])
            return output.getvalue()

    def recover_interrupted(self) -> int:
        with self.transaction():
            rows = self._connection.execute("SELECT body FROM tasks").fetchall()
            recovered = 0
            for row in rows:
                task = json.loads(row[0])
                if task["rubric_version"] == VERSION and task["status"] in ("queued", "running"):
                    # An obsolete attempt must never change its replacement's batch state.
                    self._ensure_writable(task)
                    task.update(status="failed", draft=None, review=None, error={"code": "interrupted", "message": "服务已重启，任务中断；原作业与量表已保留，请重试或人工批改。"}, updated_at=now())
                    self._append_trace(task, "failed", details=task["error"])
                    self._save_and_refresh(task)
                    recovered += 1
            return recovered

    def close(self):
        with self._lock:
            self._connection.close()
