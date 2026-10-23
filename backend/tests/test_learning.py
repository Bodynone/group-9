import asyncio
import base64
from copy import deepcopy
from dataclasses import replace
import hashlib
import io
import json
import zipfile
import httpx

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from backend.agent_v2 import DynamicRunner
from backend.app import create_app
from backend.evaluation import Evaluations
from backend.knowledge import chunks, extract, retrieve
from backend.learning import LearningService
from backend.provider import ChatProvider
from backend.rubric_service import RubricService
from backend.schemas_v2 import V2Error, digest
from learning_provider import LearningTestProvider
from test_v2 import configured, review_body, versions


def upload(text="\ufeff🧪 SQL LEFT JOIN查询保留左侧全部记录。\r\nNULL不参与AVG聚合。", **kwargs):
    return {"title": "数据库资料", "filename": "lesson.txt", "content_base64": base64.b64encode(text.encode()).decode(), **kwargs}


def setup(store, retrieval=True, audit=True):
    service = RubricService(store)
    learning = LearningService(service)
    _, assignment = configured(service)
    doc = learning.add_document(assignment["course_id"], upload())
    learning.save_policy(assignment["id"], {"expected_revision": 0, "retrieval_enabled": retrieval, "audit_enabled": audit})
    task = service.submit({"assignment_id": assignment["id"], "submission_label": "anonymous-01", "text": "\ufeff🧪 SQL LEFT JOIN实验报告\r\n查询、步骤与结果，组合e\u0301"}, "first")
    return service, learning, assignment, doc, task


def run(service, task, settings, mode="disagree"):
    provider = LearningTestProvider(mode)
    asyncio.run(DynamicRunner(service, provider, settings, asyncio.Semaphore(3)).run(task["id"]))
    return service.task(task["id"]), provider


def test_chunk_and_bm25_offsets_scope_and_no_match():
    text = "\ufeff🧪\r\n" + "关联查询SQL LEFT JOIN，保留左侧记录。\n" * 100
    parts = chunks(text)
    assert len(parts) > 1 and all(text[p["start"]:p["end"]] == p["quote"] for p in parts)
    docs = [{"id": "d", "title": "课件", "text": text, "content_hash": hashlib.sha256(text.encode()).hexdigest()}]
    hits = retrieve(docs, "关联查询 LEFT JOIN", 3)
    assert hits and all(text[h["start"]:h["end"]] == h["quote"] for h in hits)
    assert retrieve(docs, "完全无关的超级火山", 3) == []


def test_docx_extraction_and_pdf_scan_rejection():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>SQL</w:t><w:tab/><w:t>实验</w:t></w:r></w:p><w:p><w:r><w:t>过程</w:t></w:r></w:p></w:body></w:document>')
    text, _ = extract("notes.docx", base64.b64encode(buffer.getvalue()).decode())
    assert text == "SQL\t实验\n过程"
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100); pdf = io.BytesIO(); writer.write(pdf)
    with pytest.raises(V2Error): extract("scan.pdf", base64.b64encode(pdf.getvalue()).decode())


@pytest.mark.parametrize("name,data", [("bad.txt", b"\xff"), ("script.html", b"<script>"), ("bad.pdf", b"not pdf"), ("bad.docx", b"not zip"), ("empty.md", b" ")])
def test_invalid_documents_do_not_enter_library(store, name, data):
    service = RubricService(store); learning = LearningService(service); course = service.course("c")
    with pytest.raises(V2Error): learning.add_document(course["id"], {"title": "d", "filename": name, "content_base64": base64.b64encode(data).decode()})
    assert learning.documents(course["id"])["total"] == 0


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_docx_entities_rejected_in_supported_xml_encodings(encoding):
    xml = '<?xml version="1.0" encoding="'+encoding+'"?><!DOCTYPE document [<!ENTITY injected "not a real lesson">]><document>&injected;</document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("word/document.xml", xml.encode(encoding))
    with pytest.raises(V2Error): extract("lesson.docx", base64.b64encode(buffer.getvalue()).decode())


def test_material_freeze_archive_replacement_and_cross_course(store):
    service, learning, assignment, doc, task = setup(store)
    original = learning.search(task, "LEFT JOIN", "dim_0")["matches"]
    replaced = learning.add_document(assignment["course_id"], upload("新资料：GROUP BY分组查询。", replaces_id=doc["id"]))
    assert replaced["version_no"] == 2 and learning.document(doc["id"])["archived"]
    assert learning.search(service.task(task["id"]), "LEFT JOIN", "dim_0")["matches"] == original
    next_task = service.submit({"assignment_id": assignment["id"], "submission_label": "new", "text": "新提交"}, "next")
    assert next_task["learning_snapshot"]["documents"][0]["id"] == replaced["id"]
    another = service.course("other")
    foreign = learning.add_document(another["id"], upload("秘密跨课程资料 LEFT JOIN"))
    forged = deepcopy(task["learning_snapshot"]); forged["documents"] = [{"id": foreign["id"], "content_hash": foreign["content_hash"]}]
    forged["snapshot_hash"] = digest({k: v for k, v in forged.items() if k != "snapshot_hash"})
    with pytest.raises(V2Error): learning.frozen_documents(forged)
    with pytest.raises(V2Error): learning.archive_document(doc["id"], 1, False)


def test_policy_guard_and_stale_revision(store):
    service = RubricService(store); learning = LearningService(service); _, assignment = configured(service)
    body = {"expected_revision": 0, "retrieval_enabled": True, "audit_enabled": False}
    with pytest.raises(V2Error): learning.save_policy(assignment["id"], body)
    learning.add_document(assignment["course_id"], upload())
    learning.save_policy(assignment["id"], body)
    with pytest.raises(V2Error): learning.save_policy(assignment["id"], body)


def test_retrieval_audit_blinding_and_teacher_gate(store, settings):
    service, learning, assignment, doc, task = setup(store)
    final, provider = run(service, task, settings)
    assert final["status"] == "pending_review" and final["draft"]["total"] == "100.00"
    assert final["model_calls"] == 5  # Four core rounds plus audit; bootstrap retrieval adds no model round.
    rubric_result = next(e["details"]["result"] for e in final["trace"] if e["tool"] == "read_rubric")
    assert len(rubric_result["course_materials"]) == 4 and len(rubric_result["material_passages"]) == 1
    data = learning.detail(final["id"])
    assert len(data["retrievals"]) == 4 and data["audit"]["total"] == "88.00" and data["audit"]["disputed_count"] == 1
    assert all("draft" not in m and "review" not in m for m in provider.audit_inputs)
    assert data["audit"]["blind"] and final["draft"]["dimensions"][0]["needs_review"]
    assert learning.queue(assignment["id"])["items"][0]["priority"] == "high"
    reviewed = service.review(final["id"], review_body(final))
    with pytest.raises(V2Error) as e: service.confirm(final["id"], versions(reviewed))
    assert e.value.code == "AUDIT_REVIEW_REQUIRED"
    learning.acknowledge(final["id"], {**versions(reviewed), "note": "人工核对后按70%档处理"})
    confirmed = service.confirm(final["id"], versions(reviewed))
    assert confirmed["review"]["total"] == "70.00"
    raw = service.store.export_task(final["id"])
    assert raw["learning"]["audit"]["acknowledgment"]["note"] == "人工核对后按70%档处理"
    with pytest.raises(V2Error): learning.acknowledge(final["id"], {**versions(confirmed), "note": "changed"})
    assert service.store.export_task(final["id"]) == raw


@pytest.mark.parametrize("mode", ["bad", "fabricated"])
def test_failed_audit_preserves_primary_and_requires_teacher(store, settings, mode):
    service, learning, _, _, task = setup(store)
    final, _ = run(service, task, settings, mode)
    assert final["status"] == "pending_review" and final["draft"]["total"] == "100.00"
    assert learning.detail(task["id"])["audit"]["status"] == "failed"
    final = service.review(task["id"], review_body(final))
    with pytest.raises(V2Error): service.confirm(task["id"], versions(final))
    learning.acknowledge(task["id"], {**versions(final), "note": "独立核查全部维度"})
    assert service.confirm(task["id"], versions(final))["status"] == "confirmed"


def test_audit_timeout_and_manual_takeover_can_finish(store, settings):
    service, learning, _, _, task = setup(store, retrieval=False)
    final, _ = run(service, task, replace(settings, task_timeout=.05), "timeout")
    assert final["status"] == "failed" and final["text"] == task["text"]
    assert learning.detail(task["id"])["audit"]["status"] == "failed"
    manual = service.manual(task["id"]); reviewed = service.review(task["id"], review_body(manual))
    learning.acknowledge(task["id"], {**versions(reviewed), "note": "超时后人工完成"})
    assert service.confirm(task["id"], versions(reviewed))["status"] == "confirmed"


def test_audit_ack_invalidated_by_new_review_revision(store, settings):
    service, learning, _, _, task = setup(store)
    task, _ = run(service, task, settings)
    task = service.review(task["id"], review_body(task))
    learning.acknowledge(task["id"], {**versions(task), "note": "已核查"})
    task = service.review(task["id"], review_body(task))
    with pytest.raises(V2Error): service.confirm(task["id"], versions(task))


def test_primary_failure_before_audit_allows_documented_manual_confirmation(store):
    service, learning, _, _, task = setup(store)
    service.change(task["id"], {"status": "failed"}, "test_failure")
    manual = service.manual(task["id"])
    assert learning.detail(task["id"])["audit"]["status"] == "failed"
    reviewed = service.review(task["id"], review_body(manual))
    learning.acknowledge(task["id"], {**versions(reviewed), "note": "首轮失败，由教师独立核查全部维度"})
    assert service.confirm(task["id"], versions(reviewed))["status"] == "confirmed"


def test_audit_never_exceeds_task_model_call_budget(store, settings):
    service, learning, _, _, task = setup(store, retrieval=False)
    task, provider = run(service, task, replace(settings, max_model_calls=4))
    assert task["status"] == "pending_review" and task["model_calls"] == 4 and not provider.audit_inputs
    assert learning.detail(task["id"])["audit"]["error_code"] == "model_call_limit"


def test_retry_of_revision_retains_revision_lineage(store, settings):
    service, learning, _, _, task = setup(store, retrieval=False, audit=False)
    task, _ = run(service, task, settings)
    revision = learning.revise(task["id"], task["text"] + "修改", "revision")
    service.change(revision["id"], {"status": "failed"}, "test")
    retried = service.retry(revision["id"], "retry")
    assert learning.detail(retried["id"])["revision"]["previous_task_id"] == task["id"]
    assert learning.comparison(retried["id"])["version_no"] == 2


def test_revision_keeps_snapshot_idempotency_and_original_record(store, settings):
    service, learning, assignment, doc, task = setup(store, retrieval=False, audit=False)
    task, _ = run(service, task, settings)
    task = service.review(task["id"], review_body(task)); task = service.confirm(task["id"], versions(task))
    frozen = service.store.export_task(task["id"])
    new_text = task["text"] + "\n补充修改：SQL限制条件与结果。"
    revision = learning.revise(task["id"], new_text, "revision-key")
    assert learning.revise(task["id"], new_text, "revision-key")["id"] == revision["id"]
    with pytest.raises(V2Error): learning.revise(task["id"], new_text + "other", "revision-key")
    with pytest.raises(V2Error): learning.revise(task["id"], task["text"], "unchanged")
    revision, _ = run(service, revision, settings)
    compared = learning.comparison(revision["id"])
    assert compared["total_delta"] == "30.00" and compared["provisional"] and compared["comparable"]
    assert compared["changes"] and service.store.export_task(task["id"]) == frozen
    assert learning.feedback(task)[0]["target_criterion"]
    assert all(revision[k] == task[k] for k in ("context_hash", "rubric_hash")) and revision["input_version"] != task["input_version"]


def test_retry_keeps_frozen_material_snapshot(store, settings):
    service, learning, assignment, doc, task = setup(store)
    service.change(task["id"], {"status": "failed"}, "test")
    learning.add_document(assignment["course_id"], upload("SQL替换资料", replaces_id=doc["id"]))
    retried = service.retry(task["id"], "retry")
    assert retried["learning_snapshot"] == task["learning_snapshot"]


def human(task, reviewer, **kw):
    return {"reviewer_id": reviewer, "human_attested": True, "note": "隔离测试中的人工输入替身，不是真实评阅记录", "dimensions": review_body(task)["dimensions"] and [{"dimension_id": d["id"], "level_id": "basic"} for d in task["rubric_snapshot"]["dimensions"]], **kw}


def test_reference_gate_blind_context_and_2x2_experiment(store, settings):
    service, learning, assignment, _, task = setup(store)
    evaluations = Evaluations(learning)
    suite = evaluations.create({"name": "隔离流程测试", "assignment_id": assignment["id"]})
    suite = evaluations.add_sample(suite["id"], task["id"], 1)
    with pytest.raises(V2Error): evaluations.prepare_run(suite["id"])
    with pytest.raises(V2Error): evaluations.label(suite["id"], task["id"], human(task, "a", human_attested=False))
    with pytest.raises(V2Error): evaluations.label(suite["id"], task["id"], human(task, "a"), True)
    evaluations.label(suite["id"], task["id"], human(task, "a"))
    with pytest.raises(V2Error): evaluations.label(suite["id"], task["id"], human(task, " a "))
    evaluations.label(suite["id"], task["id"], human(task, "b"))
    evaluations.label(suite["id"], task["id"], human(task, "judge"), True)
    with pytest.raises(V2Error): evaluations.label(suite["id"], task["id"], human(task, "judge"), True)
    before = deepcopy(service.task(task["id"]))
    run = evaluations.prepare_run(suite["id"])
    asyncio.run(evaluations.execute(run["id"], LearningTestProvider(), settings, asyncio.Semaphore(3)))
    result = service.get("evaluation_runs", run["id"])
    assert result["status"] == "completed" and len(result["rows"]) == 4
    assert set(result["summary"]) == {"core", "retrieval", "core_audit", "retrieval_audit"}
    assert all(r["success"] and r["absolute_score_error"] == "30.00" and r["output_evidence_support"] is None for r in result["rows"])
    assert service.task(task["id"]) == before
    reviewed = evaluations.evidence_review(run["id"], 0, {"reviewer_id": "test", "human_attested": True, "supported": False, "note": "测试核查"})
    assert not reviewed["rows"][0]["output_evidence_support"]["supported"]


def test_additive_migration_keeps_raw_json_and_metrics_unknown_cost(store, settings):
    service, learning, assignment, _, task = setup(store)
    task, _ = run(service, task, settings)
    before = store._connection.execute("SELECT body FROM tasks WHERE id=?", (task["id"],)).fetchone()[0]
    LearningService(RubricService(store))
    assert store._connection.execute("SELECT body FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == before
    row = learning.metrics(assignment["id"])["rows"][0]
    assert row["cost_cny"] is None and row["prompt_tokens"] > 0 and row["runtime_seconds"] >= 0


def test_v3_http_limits_and_full_workflow(settings, store):
    app = create_app(settings=settings, store=store, provider=LearningTestProvider())
    service, learning = app.state.v2_service, app.state.learning
    _, assignment = configured(service)
    with TestClient(app) as client:
        path = f"/api/v3/courses/{assignment['course_id']}/materials"
        assert client.post(path, json=upload()).status_code == 201
        assert client.get(path).json()["total"] == 1
        assert "text" not in client.get(path).json()["items"][0]
        assert client.put(f"/api/v3/assignments/{assignment['id']}/policy", json={"expected_revision": 0, "retrieval_enabled": True, "audit_enabled": True}).status_code == 200
        assert client.post("/api/v3/tasks/missing/revisions", json={"text": "x" * 50001}, headers={"Idempotency-Key": "x"}).status_code == 422
        assert client.post(path, json={**upload(), "extra": True}).status_code == 422
        assert client.get(f"/api/v3/assignments/{assignment['id']}/review-queue").json()["total"] == 0
        assert sum(len(v) for p, v in app.openapi()["paths"].items() if p.startswith("/api/v2/")) == 31


def test_optional_pacing_and_output_budget_share_provider(settings, monkeypatch):
    original = httpx.AsyncClient
    starts, budgets = [], []
    async def handler(request):
        starts.append(asyncio.get_running_loop().time())
        budgets.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    monkeypatch.setattr("backend.provider.httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    provider = ChatProvider(replace(settings, min_request_interval=.01, max_output_tokens=4096))
    async def together(): return await asyncio.gather(*(provider.complete([], []) for _ in range(5)))
    assert len(asyncio.run(together())) == 5
    assert all(b-a >= .009 for a,b in zip(starts,starts[1:])) and budgets == [4096]*5


@pytest.mark.parametrize("changes", [{"max_output_tokens": 0}, {"max_output_tokens": 32769}, {"min_request_interval": -1}, {"min_request_interval": float("nan")}])
def test_invalid_provider_budgets_are_rejected(settings, changes):
    with pytest.raises(ValueError): ChatProvider(replace(settings, **changes))
