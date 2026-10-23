"""Additive v3 endpoints; shipped /api and /api/v2 contracts remain unchanged."""

from fastapi import APIRouter, Header, Query
from fastapi.responses import Response
import base64
from pathlib import PurePath
from pydantic import Field, StrictBool, StrictInt

from .evaluation import Evaluations
from .schemas_v2 import StrictModel, Versions, V2Error, canonical


class DocumentUpload(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=2666668)
    replaces_id: str | None = None


class DocumentState(StrictModel):
    expected_revision: StrictInt = Field(ge=1)
    archived: StrictBool


class Policy(StrictModel):
    expected_revision: StrictInt = Field(ge=0)
    retrieval_enabled: StrictBool
    audit_enabled: StrictBool


class RevisionText(StrictModel):
    text: str = Field(min_length=1, max_length=50000)


class Acknowledgment(Versions):
    note: str = Field(min_length=1, max_length=10000)


class SuiteCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    assignment_id: str


class SampleAdd(StrictModel):
    task_id: str
    expected_revision: StrictInt = Field(ge=1)


class ReferenceChoice(StrictModel):
    dimension_id: str
    level_id: str


class HumanLabel(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=100)
    human_attested: StrictBool
    note: str = Field(min_length=1, max_length=10000)
    dimensions: list[ReferenceChoice] = Field(min_length=1, max_length=12)
    evidence_supported: StrictBool | None = None
    review_seconds: StrictInt | None = Field(default=None, ge=0, le=86400)


class EvidenceReview(StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=100)
    human_attested: StrictBool
    supported: StrictBool
    note: str = Field(min_length=1, max_length=10000)


def install(app, learning, runner, provider):
    router = APIRouter(prefix="/api/v3")
    evaluations = Evaluations(learning)
    app.state.evaluations = evaluations

    def ensure_model():
        if not app.state.settings.api_key:
            raise V2Error("MODEL_NOT_CONFIGURED", "模型尚未配置", 503)

    @router.get("/courses/{identifier}/materials")
    def documents(identifier: str, include_archived: bool = False):
        return learning.documents(identifier, include_archived)

    @router.post("/courses/{identifier}/materials", status_code=201)
    def add_document(identifier: str, body: DocumentUpload):
        return learning.add_document(identifier, body.model_dump())

    @router.get("/materials/{identifier}")
    def document(identifier: str):
        return learning.document(identifier)

    @router.patch("/materials/{identifier}")
    def archive(identifier: str, body: DocumentState):
        return learning.archive_document(identifier, body.expected_revision, body.archived)

    @router.get("/materials/{identifier}/file")
    def original_document(identifier: str):
        with learning.store._snapshot():
            doc = learning.service.get("learning_documents", identifier)
            return Response(base64.b64decode(doc["content_base64"]), media_type="application/octet-stream", headers={
                "Content-Disposition": f'attachment; filename="material-{identifier}{PurePath(doc["filename"]).suffix.lower()}"', "Cache-Control": "no-store"})

    @router.get("/assignments/{identifier}/policy")
    def policy(identifier: str):
        return learning.policy(identifier)

    @router.put("/assignments/{identifier}/policy")
    def save_policy(identifier: str, body: Policy):
        return learning.save_policy(identifier, body.model_dump())

    @router.get("/assignments/{identifier}/review-queue")
    def queue(identifier: str):
        return learning.queue(identifier)

    @router.get("/assignments/{identifier}/metrics")
    def metrics(identifier: str):
        return learning.metrics(identifier)

    @router.get("/tasks/{identifier}/learning")
    def detail(identifier: str):
        return learning.detail(identifier)

    @router.post("/tasks/{identifier}/audit-acknowledgment")
    def acknowledge(identifier: str, body: Acknowledgment):
        return learning.acknowledge(identifier, body.model_dump())

    @router.post("/tasks/{identifier}/revisions", status_code=202)
    async def revise(identifier: str, body: RevisionText, idempotency_key: str | None = Header(default=None)):
        ensure_model()
        task = learning.revise(identifier, body.text, idempotency_key)
        runner.schedule(task["id"])
        return task

    @router.get("/tasks/{identifier}/comparison")
    def comparison(identifier: str):
        return learning.comparison(identifier)

    @router.post("/evaluation-suites", status_code=201)
    def suite(body: SuiteCreate):
        return evaluations.create(body.model_dump())

    @router.get("/evaluation-suites")
    def suites(assignment_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return learning.service.list("evaluation_suites", limit, offset, assignment_id=assignment_id)

    @router.get("/evaluation-suites/{identifier}")
    def get_suite(identifier: str):
        return evaluations.suite(identifier)

    @router.post("/evaluation-suites/{identifier}/samples")
    def sample(identifier: str, body: SampleAdd):
        return evaluations.add_sample(identifier, body.task_id, body.expected_revision)

    @router.get("/evaluation-suites/{identifier}/samples/{task_id}/context")
    def reference_context(identifier: str, task_id: str):
        with learning.store._snapshot():
            task = evaluations._sample(identifier, task_id)
            return {k: task[k] for k in ("text", "input_version", "rubric_snapshot", "assignment_snapshot")}

    @router.post("/evaluation-suites/{identifier}/samples/{task_id}/ballots", status_code=201)
    def ballot(identifier: str, task_id: str, body: HumanLabel):
        return evaluations.label(identifier, task_id, body.model_dump())

    @router.post("/evaluation-suites/{identifier}/samples/{task_id}/adjudication", status_code=201)
    def adjudication(identifier: str, task_id: str, body: HumanLabel):
        return evaluations.label(identifier, task_id, body.model_dump(), True)

    @router.post("/evaluation-suites/{identifier}/runs", status_code=202)
    async def run(identifier: str):
        ensure_model()
        created = evaluations.prepare_run(identifier)
        evaluations.schedule(created, provider, app.state.settings, runner.semaphore)
        return created

    @router.get("/evaluation-runs/{identifier}")
    def get_run(identifier: str):
        with learning.store._snapshot():
            return learning.service.get("evaluation_runs", identifier)

    @router.get("/evaluation-runs")
    def runs(suite_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        return learning.service.list("evaluation_runs", limit, offset, suite_id=suite_id)

    @router.get("/evaluation-runs/{identifier}/export")
    def export(identifier: str):
        with learning.store._snapshot():
            run = learning.service.get("evaluation_runs", identifier)
            return Response(canonical(run), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="evaluation-{identifier}.json"', "Cache-Control": "no-store"})

    @router.post("/evaluation-runs/{identifier}/rows/{index}/evidence-review")
    def evidence(identifier: str, index: int, body: EvidenceReview):
        return evaluations.evidence_review(identifier, index, body.model_dump())

    app.include_router(router)
