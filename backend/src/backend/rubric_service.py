"""Transactional v2 configuration, frozen context and teacher-controlled records.

Legacy task and record JSON is never rewritten by migration. New v2 batches use
separate tables because the shipped v1 batch schema has a different contract.
"""

from copy import deepcopy
import csv
from decimal import Decimal
import io
import json
from uuid import uuid4

from .rubric import RUBRIC
from .schemas_v2 import V2Error, canonical, definition_check, digest, money
from .storage import Store, now


def preset(legacy=False):
    body = {"title": "软件工程 A–F（2026-10-09）" if legacy else "软件工程 A–F（2026-v1）",
            "total_score": "100.00",
            "levels": [{"id": f"level_{p}", "label": f"{p}%", "percent": money(p)} for p in (100, 70, 30, 0)],
            "dimensions": [{"id": d["id"], "name": d["name"], "description": d["name"],
                            "max_score": money(w), "criteria": {f"level_{p}": d["criteria"][str(p)] for p in (100, 70, 30, 0)}}
                           for d, w in zip(RUBRIC["dimensions"], (15, 20, 30, 15, 10, 10) if legacy else (15, 25, 25, 15, 10, 10))]}
    if legacy:
        for dimension, name in zip(body["dimensions"], ("用户、依据与范围", "需求表达", "验收可执行性", "行为依据与边界", "AI协作与人工判断", "互评修订与交接")):
            dimension.update(name=name, description=name)
    return definition_check(body)[0]


class RubricService:
    def __init__(self, store: Store):
        self.store = store
        self.db = store._connection
        with store.transaction():
            for table in ("courses", "rubrics", "rubric_versions", "assignments", "v2_batches"):
                self.db.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS task_contexts (task_id TEXT PRIMARY KEY REFERENCES tasks(id), body TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS v2_batch_items (batch_id TEXT REFERENCES v2_batches(id), position INTEGER, current_task_id TEXT UNIQUE REFERENCES tasks(id), PRIMARY KEY(batch_id,position))")
            self.db.execute("CREATE TABLE IF NOT EXISTS request_keys (scope TEXT, key TEXT, request_hash TEXT, resource_id TEXT, PRIMARY KEY(scope,key))")
            for legacy, identifier in ((True, "af-2026-10-09-v1"), (False, "2026-v1")):
                if self.db.execute("SELECT 1 FROM rubric_versions WHERE id=?", (identifier,)).fetchone():
                    continue
                definition = preset(legacy)
                rubric_id = "preset-" + identifier
                self.put("rubrics", {"id": rubric_id, "title": definition["title"], "created_at": now()})
                self.put("rubric_versions", {"id": identifier, "rubric_id": rubric_id, "version_no": 1,
                         "state": "published", "revision": 1, "definition": definition, "content_hash": digest(definition), "created_at": now()})
            # A sidecar adds context without touching historical JSON or records.
            for task_id, raw in self.db.execute("SELECT id,body FROM tasks").fetchall():
                task = json.loads(raw)
                version_id = task["rubric_version"]
                if version_id in ("2026-v1", "af-2026-10-09-v1"):
                    version = self.get("rubric_versions", version_id)
                    context = self.context(None, version)
                    self.db.execute("INSERT OR IGNORE INTO task_contexts VALUES (?,?)", (task_id, canonical(context)))

    def get(self, table, identifier):
        # table values are application constants, never request data.
        row = self.db.execute(f"SELECT body FROM {table} WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise V2Error("NOT_FOUND", "对象不存在", 404)
        obj = json.loads(row[0])
        if table == "rubric_versions" and obj.get("deleted_at"):
            raise V2Error("NOT_FOUND", "量表草稿已删除", 404)
        return obj

    def put(self, table, obj):
        self.db.execute(f"INSERT INTO {table} VALUES (?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body", (obj["id"], canonical(obj)))
        return obj

    def list(self, table, limit=20, offset=0, include_archived=False, **filters):
        with self.store._snapshot():
            items = [json.loads(row[0]) for row in self.db.execute(f"SELECT body FROM {table} ORDER BY rowid DESC")]
            items = [item for item in items if all(value is None or item.get(key) == value for key, value in filters.items())]
            if table == "rubrics":
                versions = [json.loads(row[0]) for row in self.db.execute("SELECT body FROM rubric_versions")]
                for item in items:
                    item["revision"] = item.get("revision", 1)
                    item["archived"] = bool(item.get("archived"))
                    item["versions"] = [self.describe(version) for version in versions
                                        if version["rubric_id"] == item["id"] and not version.get("deleted_at")
                                        and (include_archived or not (item["archived"] or version.get("archived")))]
                items = [item for item in items if item["versions"] and (include_archived or not item["archived"])]
            return {"total": len(items), "items": items[offset:offset + limit]}

    def require_active(self, version):
        if version.get("archived") or self.get("rubrics", version["rubric_id"]).get("archived"):
            raise V2Error("RUBRIC_ARCHIVED", "量表已归档，请恢复后用于新任务配置")

    def lifecycle(self, identifier, expected, archived, series=False):
        table = "rubrics" if series else "rubric_versions"
        with self.store.transaction():
            obj = self.get(table, identifier)
            obj.setdefault("revision", 1)
            self.revision(obj, expected, draft=False)
            obj.update(archived=archived, revision=expected + 1)
            self.put(table, obj)
            return obj if series else self.describe(obj)

    def delete_draft(self, identifier, expected):
        with self.store.transaction():
            obj = self.get("rubric_versions", identifier)
            self.revision(obj, expected)
            # Keep a tombstone so deleting a draft never reuses its version number.
            for table, field in (("assignments", "rubric_version_id"), ("task_contexts", "rubric_version_id"),
                                 ("tasks", "rubric_version"), ("records", "rubric_version")):
                for (raw,) in self.db.execute(f"SELECT body FROM {table}"):
                    body = json.loads(raw)
                    if body.get(field) == identifier or body.get("task", {}).get(field) == identifier:
                        raise V2Error("RUBRIC_IN_USE", "草稿已被作业或评分记录引用，请先调整绑定；已有评分记录不能删除")
            obj.update(deleted_at=now(), revision=expected + 1)
            self.put("rubric_versions", obj)
            return {"id": identifier, "deleted": True}

    @staticmethod
    def nonblank(*texts):
        if any(not isinstance(text, str) or not text.strip() for text in texts):
            raise V2Error("INVALID_INPUT", "名称、任务要求和正文不能全为空白", 422)

    def course(self, name):
        self.nonblank(name)
        with self.store.transaction():
            return self.put("courses", {"id": str(uuid4()), "name": name, "created_at": now()})

    def new_rubric(self, title, source_version_id=None):
        self.nonblank(title)
        with self.store.transaction():
            if source_version_id is None:
                candidates = [json.loads(row[0]) for row in self.db.execute("SELECT body FROM rubric_versions ORDER BY rowid")]
                source_version_id = next((v["id"] for v in candidates if v["state"] == "published"
                                          and not v.get("deleted_at") and not v.get("archived")
                                          and not self.get("rubrics", v["rubric_id"]).get("archived")), None)
                if source_version_id is None:
                    raise V2Error("RUBRIC_ARCHIVED", "暂无可用的已发布标准，请先恢复一份归档量表")
            source = self.get("rubric_versions", source_version_id)
            self.require_active(source)
            if source["state"] != "published":
                raise V2Error("RUBRIC_NOT_PUBLISHED", "只能复制已发布量表")
            rubric = self.put("rubrics", {"id": str(uuid4()), "title": title, "created_at": now()})
            definition = deepcopy(source["definition"])
            definition["title"] = title
            version = self.put("rubric_versions", {"id": str(uuid4()), "rubric_id": rubric["id"], "version_no": 1,
                               "state": "draft", "revision": 1, "definition": definition, "content_hash": None, "created_at": now()})
            return {**rubric, "draft": self.describe(version)}

    def copy_version(self, rubric_id, source_version_id):
        with self.store.transaction():
            source = self.get("rubric_versions", source_version_id)
            self.require_active(source)
            versions = [json.loads(row[0]) for row in self.db.execute("SELECT body FROM rubric_versions")]
            own = [version for version in versions if version["rubric_id"] == rubric_id]
            if source["state"] != "published" or source["rubric_id"] != rubric_id:
                raise V2Error("VERSION_MISMATCH", "只能从本系列发布版本复制")
            if any(version["state"] == "draft" and not version.get("deleted_at") for version in own):
                raise V2Error("STATE_CONFLICT", "本量表已有草稿")
            return self.describe(self.put("rubric_versions", {**source, "id": str(uuid4()), "state": "draft", "revision": 1, "archived": False,
                                 "version_no": max(version["version_no"] for version in own) + 1, "content_hash": None, "created_at": now()}))

    def describe(self, version):
        rubric = self.get("rubrics", version["rubric_id"])
        return {**version, "archived": bool(version.get("archived")), "rubric_archived": bool(rubric.get("archived")),
                "rubric_revision": rubric.get("revision", 1), **definition_check(version["definition"])[1]}

    @staticmethod
    def revision(obj, expected, draft=True):
        if obj["revision"] != expected:
            raise V2Error("REVISION_CONFLICT", "页面已过期，请重新加载，当前输入尚未保存")
        if draft and obj["state"] != "draft":
            raise V2Error("STATE_CONFLICT", "已发布内容只读，请复制新版本")

    def update_version(self, identifier, expected, definition):
        definition, _ = definition_check(definition)
        with self.store.transaction():
            obj = self.get("rubric_versions", identifier)
            self.require_active(obj)
            self.revision(obj, expected)
            obj.update(definition=definition, revision=expected + 1)
            return self.describe(self.put("rubric_versions", obj))

    def publish_version(self, identifier, expected):
        with self.store.transaction():
            obj = self.get("rubric_versions", identifier)
            self.require_active(obj)
            self.revision(obj, expected, draft=False)
            definition, check = definition_check(obj["definition"])
            if not check["publishable"]:
                raise V2Error("RUBRIC_INVALID", "请补齐判据并使总分等于100", 422, check["field_errors"])
            obj.update(state="published", definition=definition, content_hash=digest(definition))
            return self.describe(self.put("rubric_versions", obj))

    def assignment(self, body, identifier=None):
        self.nonblank(body["title"], body["instructions"])
        with self.store.transaction():
            version = self.get("rubric_versions", body["rubric_version_id"])
            existing = self.get("assignments", identifier) if identifier else None
            if not existing or existing["rubric_version_id"] != version["id"]:
                self.require_active(version)
            if identifier:
                obj = self.get("assignments", identifier)
                self.revision(obj, body["expected_revision"])
                obj.update({key: value for key, value in body.items() if key != "expected_revision"})
                obj["revision"] += 1
            else:
                self.get("courses", body["course_id"])
                obj = {**body, "id": str(uuid4()), "state": "draft", "revision": 1, "context_hash": None, "created_at": now()}
            return self.put("assignments", obj)

    def publish_assignment(self, identifier, expected):
        with self.store.transaction():
            obj = self.get("assignments", identifier)
            self.revision(obj, expected, draft=False)
            version = self.get("rubric_versions", obj["rubric_version_id"])
            if version["state"] != "published":
                raise V2Error("RUBRIC_NOT_PUBLISHED", "请先发布量表")
            if obj["state"] != "published":
                self.require_active(version)
            obj["state"] = "published"
            obj["context_hash"] = self.context(obj, version)["context_hash"]
            return self.put("assignments", obj)

    @staticmethod
    def context(assignment, version):
        snapshot = ({key: assignment[key] for key in ("id", "course_id", "title", "instructions", "reference_text", "rubric_version_id")}
                    if assignment else {"title": "历史固定量表作业", "instructions": "按该版本固定规则评价", "reference_text": ""})
        return {"assignment_id": assignment["id"] if assignment else None, "rubric_version_id": version["id"],
                "rubric_hash": version["content_hash"], "context_hash": digest(snapshot),
                "rubric_snapshot": version["definition"], "assignment_snapshot": snapshot}

    def task(self, identifier):
        with self.store._snapshot():
            try:
                task = self.store._get(identifier)
            except KeyError:
                raise V2Error("NOT_FOUND", "任务不存在", 404) from None
            row = self.db.execute("SELECT body FROM task_contexts WHERE task_id=?", (identifier,)).fetchone()
            if not row:
                raise V2Error("VERSION_MISMATCH", "该任务尚无 v2 上下文，请使用原工作台")
            context = json.loads(row[0])
            if task.get("api_version") != 2:
                # Read adapter only: preserve historical task/record bytes until
                # a teacher explicitly saves a new versioned review.
                for field in ("draft", "review"):
                    grade = task.get(field)
                    if not grade:
                        continue
                    grade["dimensions"] = [{**{key: value for key, value in d.items() if key not in ("id", "level")},
                                             "dimension_id": d["id"], "level_id": f"level_{d['level']}" if d.get("level") is not None else None,
                                             "score": money(d["score"]) if d.get("score") is not None else None} for d in grade["dimensions"]]
                    grade["total"] = money(grade["total"]) if grade.get("total") is not None else None
            return {**task, **context, "submission_label": task.get("submission_label", "历史-" + identifier[:8]),
                    "review_revision": task.get("review_revision", 0)}

    def submissions(self, assignment_id=None, limit=20, offset=0):
        """Read-only task index; grading JSON and historical exports stay untouched."""
        with self.store._snapshot():
            if assignment_id is not None:
                self.get("assignments", assignment_id)
            items = []
            for task_raw, context_raw in self.db.execute(
                    "SELECT tasks.body,task_contexts.body FROM tasks JOIN task_contexts ON tasks.id=task_contexts.task_id ORDER BY tasks.rowid DESC"):
                task, context = json.loads(task_raw), json.loads(context_raw)
                owner = context.get("assignment_id")
                if owner is None or (assignment_id is not None and owner != assignment_id):
                    continue
                grade = task.get("review") or task.get("draft") or {}
                items.append({"id": task["id"], "assignment_id": owner, "submission_label": task.get("submission_label", task["id"][:8]),
                              "status": task["status"], "total": grade.get("total"), "created_at": task["created_at"],
                              "rubric_version_id": context["rubric_version_id"], "replaced_by": task.get("replaced_by"),
                              "parent_task_id": task.get("parent_id"), "record_id": task.get("record_id")})
            return {"total": len(items), "items": items[offset:offset + limit]}

    def _create_task(self, file, context, parent_id=None):
        self.nonblank(file["submission_label"], file["text"])
        if len(file["text"].encode("utf-8")) > 200000:
            raise V2Error("INPUT_LIMIT_EXCEEDED", "每份文本最多200000字节", 413)
        task = Store._new_task(file["text"], context["rubric_version_id"], parent_id,
                               api_version=2, submission_label=file["submission_label"], review_revision=0)
        self.store._save(task)
        self.db.execute("INSERT INTO task_contexts VALUES (?,?)", (task["id"], canonical(context)))
        return task

    def _request(self, scope, key, body, create):
        if not key or len(key) > 200:
            raise V2Error("IDEMPOTENCY_KEY_REQUIRED", "请提供1至200字符的 Idempotency-Key", 422)
        with self.store.transaction():
            row = self.db.execute("SELECT request_hash,resource_id FROM request_keys WHERE scope=? AND key=?", (scope, key)).fetchone()
            request_hash = digest(body)
            if row:
                if row[0] != request_hash:
                    raise V2Error("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求")
                return row[1]
            identifier = create()
            self.db.execute("INSERT INTO request_keys VALUES (?,?,?,?)", (scope, key, request_hash, identifier))
            return identifier

    def submit(self, body, key, batch=False):
        def create():
            assignment = self.get("assignments", body["assignment_id"])
            if assignment["state"] != "published":
                raise V2Error("ASSIGNMENT_NOT_PUBLISHED", "请先发布作业")
            context = self.context(assignment, self.get("rubric_versions", assignment["rubric_version_id"]))
            if not batch:
                return self._create_task(body, context)["id"]
            self.nonblank(body["name"])
            if sum(len(file["text"].encode("utf-8")) for file in body["files"]) > 2000000:
                raise V2Error("INPUT_LIMIT_EXCEEDED", "每批正文最多2000000字节", 413)
            obj = self.put("v2_batches", {"id": str(uuid4()), "assignment_id": assignment["id"], "name": body["name"],
                                       "rubric_version_id": context["rubric_version_id"], "context_hash": context["context_hash"], "created_at": now()})
            for position, file in enumerate(body["files"]):
                self.nonblank(file["filename"])
                task = self._create_task(file, context)
                task["filename"] = file["filename"]
                self.store._save(task)
                self.db.execute("INSERT INTO v2_batch_items VALUES (?,?,?)", (obj["id"], position, task["id"]))
            return obj["id"]
        identifier = self._request("batch" if batch else "task", key, body, create)
        return self.batch(identifier) if batch else self.task(identifier)

    def _writable(self, task):
        if task["status"] == "confirmed":
            raise V2Error("STATE_CONFLICT", "已确认任务不可修改")
        if self.db.execute("SELECT 1 FROM v2_batch_items WHERE current_task_id=?", (task["id"],)).fetchone():
            return
        # A retried batch task is retained for reading but cannot be changed.
        if task.get("replaced_by"):
            raise V2Error("STATE_CONFLICT", "任务已由重试替换，仅可查看")

    def change(self, identifier, fields, event, tool=None, details=None):
        with self.store.transaction():
            task = self.task(identifier)
            self._writable(task)
            original = self.store._get(identifier)
            original.update(fields, updated_at=now())
            self.store._append_trace(original, event, tool, details)
            self.store._save(original)
        return self.task(identifier)

    @staticmethod
    def versions(task, body):
        for field in ("input_version", "rubric_hash", "context_hash"):
            if body[field] != task[field]:
                raise V2Error("VERSION_MISMATCH", "输入、量表或作业快照不匹配")
        if body["expected_review_revision"] != task.get("review_revision", 0):
            raise V2Error("REVISION_CONFLICT", "复核已被其他页面更新，请重新加载")

    def review(self, identifier, body):
        from .tools_v2 import DynamicToolbox
        with self.store.transaction():
            task = self.task(identifier)
            self._writable(task)
            self.versions(task, body)
            if task["status"] != "pending_review":
                raise V2Error("STATE_CONFLICT", "仅待复核任务可以修改")
            calculated = DynamicToolbox(task).calculate_scores(body["dimensions"])
            if not calculated["ok"]:
                raise V2Error("RUBRIC_INVALID", calculated["errors"][0], 422)
            entries = {d["dimension_id"]: d for d in body["dimensions"]}
            dimensions = []
            for score in calculated["dimensions"]:
                entry = entries[score["dimension_id"]]
                self.nonblank(entry["reason"])
                dimensions.append({**entry, "score": score["score"]})
            original = self.store._get(identifier)
            original.update(api_version=2, draft=task.get("draft"), review={"dimensions": dimensions, "total": calculated["total"]}, review_revision=task["review_revision"] + 1, updated_at=now())
            self.store._append_trace(original, "teacher_review", "calculate_scores")
            self.store._save(original)
        return self.task(identifier)

    def confirm(self, identifier, body):
        with self.store.transaction():
            task = self.task(identifier)
            self.versions(task, body)
            if task["status"] == "confirmed":
                return task
            self._writable(task)
            review = task.get("review")
            if task["status"] != "pending_review" or not review or not all(d.get("reviewed") is True for d in review["dimensions"]):
                raise V2Error("STATE_CONFLICT", "须先保存所有维度的完整复核再确认")
            from .tools_v2 import DynamicToolbox
            calculated = DynamicToolbox(task).calculate_scores(review["dimensions"])
            if not calculated["ok"] or calculated["total"] != review["total"] or any(not d["reason"].strip() for d in review["dimensions"]):
                raise V2Error("STATE_CONFLICT", "复核不完整，请重新保存")
            original = self.store._get(identifier)
            original.update(status="confirmed", record_id=str(uuid4()), updated_at=now())
            self.store._append_trace(original, "confirmed", details={"record_id": original["record_id"]})
            self.store._save(original)
            record = {"record_id": original["record_id"], "confirmed_at": original["updated_at"], "task": self.task(identifier)}
            self.db.execute("INSERT INTO records VALUES (?,?,?)", (record["record_id"], identifier, canonical(record)))
        return self.task(identifier)

    def manual(self, identifier):
        with self.store.transaction():
            task = self.task(identifier)
            self._writable(task)
            if task["status"] != "failed":
                raise V2Error("STATE_CONFLICT", "仅失败任务可以转人工")
            original = self.store._get(identifier)
            original.update(api_version=2, status="pending_review", source="manual", updated_at=now(), review={"total": None, "dimensions": [
                {"dimension_id": d["id"], "level_id": None, "score": None, "reason": "", "reviewed": False}
                for d in task["rubric_snapshot"]["dimensions"]]})
            self.store._append_trace(original, "manual_takeover")
            self.store._save(original)
        return self.task(identifier)

    def retry(self, identifier, key):
        def create():
            task = self.task(identifier)
            self._writable(task)
            if task["status"] != "failed":
                raise V2Error("STATE_CONFLICT", "仅失败任务可以重试")
            context = {k: task[k] for k in ("assignment_id", "rubric_version_id", "rubric_hash", "context_hash", "rubric_snapshot", "assignment_snapshot")}
            new = self._create_task(task, context, identifier)
            if "filename" in task:
                new["filename"] = task["filename"]
                self.store._save(new)
            self.db.execute("UPDATE v2_batch_items SET current_task_id=? WHERE current_task_id=?", (new["id"], identifier))
            original = self.store._get(identifier)
            original["replaced_by"] = new["id"]
            self.store._save(original)
            return new["id"]
        return self.task(self._request("retry:" + identifier, key, {"task_id": identifier}, create))

    def batch(self, identifier):
        with self.store._snapshot():
            obj = self.get("v2_batches", identifier)
            ids = [row[0] for row in self.db.execute("SELECT current_task_id FROM v2_batch_items WHERE batch_id=? ORDER BY position", (identifier,))]
            tasks = [self.task(task_id) for task_id in ids]
            counts = {state + "_count": sum(task["status"] == state for task in tasks)
                      for state in ("queued", "running", "pending_review", "confirmed", "failed")}
            active = counts["queued_count"] + counts["running_count"]
            status = ("queued" if counts["queued_count"] == len(tasks) else "running") if active else (
                "failed" if counts["failed_count"] == len(tasks) else "partial_failed" if counts["failed_count"] else "completed")
            return {**obj, "status": status, "total_count": len(tasks), "finished_count": len(tasks) - active, **counts,
                    "items": [{"task_id": t["id"], "submission_label": t["submission_label"], "filename": t.get("filename", ""),
                               "status": t["status"], "total": (t.get("review") or t.get("draft") or {}).get("total")} for t in tasks]}

    def analytics(self, identifier, basis="confirmed"):
        with self.store._snapshot():
            batch = self.batch(identifier)
            version = self.get("rubric_versions", batch["rubric_version_id"])
            rows = []
            for item in batch["items"]:
                task = self.task(item["task_id"])
                if task["rubric_version_id"] != batch["rubric_version_id"] or task["context_hash"] != batch["context_hash"]:
                    raise V2Error("MIXED_RUBRIC_VERSIONS", "批次快照不一致，禁止混合统计")
                if task["status"] == "confirmed":
                    grade, source = self.store.export_task(task["id"])["task"]["review"], "record"
                elif basis == "working" and task["status"] == "pending_review":
                    grade, source = task.get("review") or task.get("draft"), "review" if task.get("review") else "draft"
                else:
                    continue
                if grade is not None and grade["total"] is not None:
                    rows.append({"task_id": task["id"], "submission_label": task["submission_label"], "source": source, **grade})
            scores = [Decimal(row["total"]) for row in rows]
            dimensions = []
            for dimension in version["definition"]["dimensions"]:
                values = [Decimal(next(d["score"] for d in row["dimensions"] if d["dimension_id"] == dimension["id"])) for row in rows]
                mean = sum(values, Decimal(0)) / len(values) if values else None
                dimensions.append({"id": dimension["id"], "name": dimension["name"], "max_score": dimension["max_score"],
                                   "average_score": money(mean) if mean is not None else None,
                                   "scoring_rate": money(mean / Decimal(dimension["max_score"]) * 100) if mean is not None else None})
            weaknesses = []
            for dimension in dimensions:
                reasons = [{"submission_label": row["submission_label"], "task_id": row["task_id"], "reason": d["reason"]}
                           for row in rows for d in row["dimensions"] if d["dimension_id"] == dimension["id"] and Decimal(d["score"]) < Decimal(dimension["max_score"])]
                if reasons:
                    weaknesses.append({"dimension_id": dimension["id"], "name": dimension["name"], "affected_count": len(reasons), "reasons": reasons})
            weaknesses.sort(key=lambda row: -row["affected_count"])
            return {"batch_id": identifier, "basis": basis, "provisional": basis == "working", "submitted": batch["total_count"],
                    "analyzed": len(rows), "confirmed": batch["confirmed_count"], "pending": batch["pending_review_count"],
                    "failed": batch["failed_count"], "excluded": batch["total_count"] - len(rows),
                    "average_score": money(sum(scores, Decimal(0)) / len(scores)) if scores else None,
                    "dimensions": dimensions, "rows": rows, "common_weaknesses": weaknesses[:3]}

    def csv(self, identifier):
        with self.store._snapshot():
            result = self.analytics(identifier)
            if not result["rows"]:
                raise V2Error("NO_CONFIRMED_RECORDS", "暂无已确认成绩，不能导出")
            batch = self.batch(identifier)
            out = io.StringIO(newline="")
            out.write("\ufeff")
            writer = csv.writer(out)
            writer.writerow(["匿名提交号", "状态", "量表版本", *[Store._csv_text(d["name"]) for d in result["dimensions"]], "总分", "确认时间"])
            for row in result["rows"]:
                record = self.store.export_task(row["task_id"])
                writer.writerow([Store._csv_text(row["submission_label"]), "已确认", batch["rubric_version_id"],
                                 *[d["score"] for d in row["dimensions"]], row["total"], record["confirmed_at"]])
            return out.getvalue(), len(result["rows"]), result["excluded"]

    def recover(self):
        with self.store.transaction():
            for identifier, raw in self.db.execute("SELECT id,body FROM tasks").fetchall():
                task = json.loads(raw)
                if task.get("api_version") == 2 and task["status"] in ("queued", "running"):
                    task.update(status="failed", updated_at=now(), error={"code": "interrupted_by_restart", "message": "进程中断，输入与快照已保留，请显式重试"})
                    self.store._append_trace(task, "failed", details=task["error"])
                    self.store._save(task)
