"""Human-reference capture and reproducible 2x2 retrieval/reviewer ablation.

References are explicit local teacher attestations, never model-generated labels.
All experimental grading runs use ephemeral databases, not the teacher's tasks.
"""

import asyncio
import hashlib
from copy import deepcopy
from decimal import Decimal
from time import perf_counter
from pathlib import Path
from uuid import uuid4

from .agent_v2 import DynamicRunner
from .learning import LearningService
from .rubric_service import RubricService
from .schemas_v2 import V2Error, digest, money
from .storage import Store, now
from .tools_v2 import DynamicToolbox


class Evaluations:
    def __init__(self, learning):
        self.learning, self.service, self.store = learning, learning.service, learning.store
        self.active = {}

    def suite(self, identifier):
        with self.store._snapshot():
            suite = self.service.get("evaluation_suites", identifier)
            ballots = self.learning.rows("evaluation_ballots")
            refs = self.learning.rows("evaluation_references")
            return {**suite, "samples": [{**sample, "ballots": [b for b in ballots if b["suite_id"] == identifier and b["task_id"] == sample["task_id"]],
                      "reference": next((r for r in refs if r["suite_id"] == identifier and r["task_id"] == sample["task_id"]), None)} for sample in suite["samples"]]}

    def create(self, body):
        self.service.nonblank(body["name"])
        with self.store.transaction():
            assignment = self.service.get("assignments", body["assignment_id"])
            if assignment["state"] != "published":
                raise V2Error("ASSIGNMENT_NOT_PUBLISHED", "请先发布任务")
            snapshot = self.learning.freeze(assignment)
            # Always freeze the available library, even when this assignment has retrieval disabled.
            docs = self.learning.documents(assignment["course_id"])["items"]
            library = {"course_id": assignment["course_id"], "policy_revision": (snapshot or {}).get("policy_revision", 0),
                       "retrieval_enabled": True, "audit_enabled": True, "documents": [{"id": d["id"], "content_hash": d["content_hash"]} for d in docs],
                       "retrieval_method": "bm25-cjk-bigram-v1"}
            library["snapshot_hash"] = digest(library)
            return self.service.put("evaluation_suites", {"id": str(uuid4()), "name": body["name"], "assignment_id": assignment["id"],
                           "library": library, "samples": [], "created_at": now(), "revision": 1})

    def add_sample(self, identifier, task_id, expected):
        with self.store.transaction():
            suite = self.service.get("evaluation_suites", identifier)
            if suite["revision"] != expected:
                raise V2Error("REVISION_CONFLICT", "评测集已更新，请刷新")
            task = self.service.task(task_id)
            if task["assignment_id"] != suite["assignment_id"]:
                raise V2Error("ASSIGNMENT_MISMATCH", "只可加入同次作业的匿名提交")
            if any(s["task_id"] == task_id for s in suite["samples"]):
                return self.suite(identifier)
            if len(suite["samples"]) >= 40:
                raise V2Error("SAMPLE_LIMIT", "每评测集最多40份样本", 422)
            suite["samples"].append({"task_id": task_id, "submission_label": task["submission_label"], "input_version": task["input_version"],
                                     "rubric_hash": task["rubric_hash"], "context_hash": task["context_hash"]})
            suite["revision"] += 1
            self.service.put("evaluation_suites", suite)
            return self.suite(identifier)

    def _sample(self, suite_id, task_id):
        suite = self.suite(suite_id)
        if not any(s["task_id"] == task_id for s in suite["samples"]):
            raise V2Error("SAMPLE_NOT_FOUND", "样本不在本评测集", 404)
        task = self.service.task(task_id)
        sample = next(s for s in suite["samples"] if s["task_id"] == task_id)
        if any(task[k] != sample[k] for k in ("input_version", "rubric_hash", "context_hash")):
            raise V2Error("VERSION_MISMATCH", "样本快照不匹配")
        return task

    def label(self, suite_id, task_id, body, adjudicate=False):
        with self.store.transaction():
            task = self._sample(suite_id, task_id)
            self.service.nonblank(body["reviewer_id"], body["note"])
            body = {**body, "reviewer_id": body["reviewer_id"].strip()}
            if body.get("human_attested") is not True:
                raise V2Error("HUMAN_REFERENCE_REQUIRED", "须由实际人工评阅者填写并声明独立评阅", 422)
            calculation = DynamicToolbox(task).calculate_scores(body["dimensions"])
            if not calculation["ok"]:
                raise V2Error("INVALID_REFERENCE", "参考档位必须完整对应冻结量表", 422)
            ballots = [b for b in self.learning.rows("evaluation_ballots") if b["suite_id"] == suite_id and b["task_id"] == task_id]
            reference_id = digest([suite_id, task_id])
            if self.learning.optional("evaluation_references", reference_id):
                raise V2Error("REFERENCE_FROZEN", "该样本参考已裁定并冻结")
            if adjudicate and len({b["reviewer_id"] for b in ballots}) < 2:
                raise V2Error("SECOND_REVIEW_REQUIRED", "至少两位不同人工评阅者独立评分后才能裁定")
            if not adjudicate and any(b["reviewer_id"] == body["reviewer_id"] for b in ballots):
                raise V2Error("DUPLICATE_REVIEWER", "该评阅者已提交独立评分")
            row = {"id": reference_id if adjudicate else str(uuid4()), "suite_id": suite_id, "task_id": task_id,
                   "reviewer_id": body["reviewer_id"].strip(), "human_attested": True, "note": body["note"],
                   "dimensions": body["dimensions"], "total": calculation["total"], "evidence_supported": body.get("evidence_supported"),
                   "review_seconds": body.get("review_seconds"), "created_at": now(), "source": "human_attested", "input_version": task["input_version"]}
            self.service.put("evaluation_references" if adjudicate else "evaluation_ballots", row)
            return self.suite(suite_id)

    def prepare_run(self, identifier):
        with self.store.transaction():
            suite = self.suite(identifier)
            if not suite["library"]["documents"]:
                raise V2Error("DOCUMENT_REQUIRED", "四条件对比需要课程资料，请添加资料后新建评测集", 422)
            eligible = [s for s in suite["samples"] if s["reference"]]
            if not eligible:
                raise V2Error("REFERENCE_REQUIRED", "没有完成双人评分及裁定的样本，不运行准确性实验", 422)
            for row in self.learning.rows("evaluation_runs"):
                if row["suite_id"] == identifier and row["status"] in ("queued", "running"):
                    raise V2Error("RUN_IN_PROGRESS", "该评测集已有正在运行的实验")
            run = {"id": str(uuid4()), "suite_id": identifier, "suite_revision": suite["revision"], "status": "queued", "created_at": now(),
                   "eligible": len(eligible), "excluded": len(suite["samples"]) - len(eligible), "planned_trials": len(eligible) * 4,
                   "samples": eligible, "library": suite["library"], "rows": [], "summary": {}, "reference_basis": "human_attested_local"}
            return self.service.put("evaluation_runs", run)

    def evidence_review(self, identifier, index, body):
        with self.store.transaction():
            run = self.service.get("evaluation_runs", identifier)
            if run["status"] in ("queued", "running"):
                raise V2Error("RUN_IN_PROGRESS", "请等待实验结束后核查输出")
            if index < 0 or index >= len(run["rows"]) or not run["rows"][index]["success"]:
                raise V2Error("OUTPUT_NOT_FOUND", "没有可核查的输出", 404)
            self.service.nonblank(body["reviewer_id"], body["note"])
            if body["human_attested"] is not True:
                raise V2Error("HUMAN_REFERENCE_REQUIRED", "请由实际人工核查者填写", 422)
            if run["rows"][index]["output_evidence_support"] is not None:
                raise V2Error("REFERENCE_FROZEN", "该次输出的核查记录已保存")
            run["rows"][index]["output_evidence_support"] = {**body, "created_at": now()}
            run["summary"] = summarize(run["rows"])
            self.service.put("evaluation_runs", run)
            return run

    def schedule(self, run, provider, settings, semaphore):
        task = asyncio.create_task(self.execute(run["id"], provider, settings, semaphore))
        self.active[run["id"]] = task
        task.add_done_callback(lambda _: self.active.pop(run["id"], None))

    async def execute(self, identifier, provider, settings, semaphore):
        with self.store.transaction():
            run = self.service.get("evaluation_runs", identifier)
            run.update(status="running")
            source = Path(__file__).parent
            run["configuration"] = {"model": settings.model, "max_model_calls": settings.max_model_calls, "task_timeout": settings.task_timeout,
                                    "max_output_tokens": settings.max_output_tokens, "min_request_interval": settings.min_request_interval,
                                    "design": "2x2-retrieval-audit-v1", "source_hashes": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                    for name in ("agent_v2.py", "tools_v2.py", "learning.py", "knowledge.py", "provider.py", "schemas_v2.py")}}
            self.service.put("evaluation_runs", run)
        try:
            for sample in run["samples"]:
                original = self.service.task(sample["task_id"])
                for retrieval, audit in ((False, False), (True, False), (False, True), (True, True)):
                    condition = ("retrieval" if retrieval else "core") + ("_audit" if audit else "")
                    temporary = Store(":memory:")
                    try:
                        service = RubricService(temporary)
                        learning = LearningService(service)
                        context = {k: deepcopy(original[k]) for k in ("assignment_id", "rubric_version_id", "rubric_hash", "context_hash", "rubric_snapshot", "assignment_snapshot")}
                        if retrieval or audit:
                            snapshot = {**run["library"], "retrieval_enabled": retrieval, "audit_enabled": audit}
                            snapshot.pop("snapshot_hash", None)
                            snapshot["snapshot_hash"] = digest(snapshot)
                            context["learning_snapshot"] = snapshot
                        with self.store._snapshot():
                            documents = self.learning.frozen_documents(run["library"])
                        with temporary.transaction():
                            for doc in documents:
                                service.put("learning_documents", doc)
                            task = service._create_task({"text": original["text"], "submission_label": original["submission_label"]}, context)
                        start = perf_counter()
                        await DynamicRunner(service, provider, settings, semaphore).run(task["id"])
                        task = service.task(task["id"])
                        elapsed = perf_counter() - start
                        draft = task.get("draft")
                        reference = {d["dimension_id"]: d["level_id"] for d in sample["reference"]["dimensions"]}
                        actual = {d["dimension_id"]: d["level_id"] for d in draft["dimensions"]} if draft else {}
                        successful = task["status"] == "pending_review"
                        usages = [e["details"] for e in task["trace"] if e["kind"] == "model_usage"]
                        costs = [Decimal(str(u["cost_cny"])) for u in usages if u.get("cost_cny") is not None]
                        row = {"task_id": original["id"], "condition": condition, "input_version": task["input_version"],
                               "rubric_hash": task["rubric_hash"], "context_hash": task["context_hash"], "library_hash": run["library"]["snapshot_hash"],
                               "success": successful, "error": task.get("error"), "seconds": round(elapsed, 3), "model_calls": task["model_calls"],
                               "reference_dimensions": len(reference), "correct_dimensions": sum(actual.get(k) == v for k, v in reference.items()) if successful else 0,
                               "absolute_score_error": money(abs(Decimal(draft["total"]) - Decimal(sample["reference"]["total"]))) if successful else None,
                               "prompt_tokens": sum(u.get("prompt_tokens", 0) for u in usages), "completion_tokens": sum(u.get("completion_tokens", 0) for u in usages),
                               "cost_cny": str(sum(costs, Decimal(0))) if usages and len(costs) == len(usages) else None,
                               "draft": draft, "learning": learning.detail(task["id"]), "teacher_evidence_support": sample["reference"].get("evidence_supported"),
                               "output_evidence_support": None}
                    finally:
                        temporary.close()
                    with self.store.transaction():
                        run["rows"].append(row)
                        run["summary"] = summarize(run["rows"])
                        self.service.put("evaluation_runs", run)
            with self.store.transaction():
                run.update(status="completed", finished_at=now())
                self.service.put("evaluation_runs", run)
        except asyncio.CancelledError:
            with self.store.transaction():
                run.update(status="interrupted", finished_at=now(), error="实验中断，已完成的行保留。新实验重新运行，不自动续调模型。")
                self.service.put("evaluation_runs", run)
            raise
        except Exception:
            with self.store.transaction():
                run.update(status="failed", finished_at=now(), error="实验执行失败，已完成的行保留，请检查环境后重建实验。")
                self.service.put("evaluation_runs", run)

    def recover(self):
        with self.store.transaction():
            for run in self.learning.rows("evaluation_runs"):
                if run["status"] in ("queued", "running"):
                    run.update(status="interrupted", error="进程中断，不自动重发模型请求")
                    self.service.put("evaluation_runs", run)

    async def close(self):
        pending = list(self.active.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


def summarize(rows):
    result = {}
    for condition in sorted({r["condition"] for r in rows}):
        group = [r for r in rows if r["condition"] == condition]
        completed = [r for r in group if r["success"]]
        errors = [Decimal(r["absolute_score_error"]) for r in completed]
        denominator = sum(r["reference_dimensions"] for r in group)
        result[condition] = {"attempted": len(group), "completed": len(completed), "failed": len(group) - len(completed),
                             "correct_dimensions": sum(r["correct_dimensions"] for r in group), "reference_dimensions_all_attempts": denominator,
                             "agreement_all_attempts_percent": money(Decimal(sum(r["correct_dimensions"] for r in group)) * 100 / denominator) if denominator else None,
                             "mean_absolute_error_successes": money(sum(errors, Decimal(0)) / len(errors)) if errors else None,
                             "mae_denominator": len(errors), "mean_seconds": round(sum(r["seconds"] for r in group) / len(group), 3),
                             "audit_disputed_trials": sum(bool(r.get("learning", {}).get("audit", {}).get("disputed_count")) for r in group),
                             "audit_failures": sum(r.get("learning", {}).get("audit", {}).get("status") == "failed" for r in group),
                             "human_evidence_reviewed": sum(r.get("output_evidence_support") is not None for r in group),
                             "human_evidence_supported": sum(r.get("output_evidence_support", {}).get("supported") is True for r in group if r.get("output_evidence_support") is not None)}
    return result
