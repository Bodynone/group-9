"""Run one public fixture against the configured real model and retain evidence.

Reference scores are compared only after AgentRunner finishes; they are never
added to the model's messages. Mechanical checks do not imply teacher approval.
"""

import argparse
import asyncio
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from backend.agent import AgentRunner
from backend.config import Settings
from backend.provider import ChatProvider
from backend.rubric import VERSION
from backend.storage import Store
from backend.tools import Toolbox


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_TOOLS = {"read_rubric", "locate_evidence", "calculate_scores", "validate_draft"}
DISPLAY_TIMEZONE = ZoneInfo("Asia/Shanghai")


def safe_service(base_url: str) -> str:
    """Keep the service location while removing credentials and query values."""
    try:
        parsed = urlsplit(base_url)
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if parsed.port is not None:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "[服务地址无法解析]"


def redact(value, api_key: str):
    if isinstance(value, str):
        return value.replace(api_key, "[已隐藏]") if api_key else value
    if isinstance(value, list):
        return [redact(item, api_key) for item in value]
    if isinstance(value, dict):
        return {key: redact(item, api_key) for key, item in value.items()}
    return value


def assess(task: dict, expected: dict, sample_text: str) -> dict:
    draft = task.get("draft")
    dimensions = draft.get("dimensions", []) if isinstance(draft, dict) else []
    scores = {item["id"]: item["score"] for item in dimensions}
    levels = {item["id"]: item["level"] for item in dimensions}
    events = [event for event in task.get("trace", []) if event.get("kind") == "tool_result"]
    actual_tools = {event.get("tool") for event in events}
    validations = [event for event in events if event.get("tool") == "validate_draft"]
    located = [event.get("details", {}).get("result", {}).get("evidence") for event in events
               if event.get("tool") == "locate_evidence" and event.get("details", {}).get("result", {}).get("found")]
    checks = {
        "pending_teacher_review": task.get("status") == "pending_review",
        "source_preserved": task.get("text") == sample_text,
        "input_version_matches_fixture": task.get("input_version") == expected["input_version"],
        "rubric_version_matches": task.get("rubric_version") == VERSION,
        "reference_levels_match": levels == expected["levels"],
        "reference_scores_match": scores == expected["scores"],
        "reference_total_matches": isinstance(draft, dict) and draft.get("total") == expected["total"],
        "four_tools_actually_executed": REQUIRED_TOOLS.issubset(actual_tools),
        "last_validation_passed": bool(validations) and validations[-1]["details"]["result"].get("valid") is True,
        "current_exact_evidence_and_scores_valid": Toolbox(task).validate_draft(draft)["valid"],
        "evidence_came_from_locator": bool(dimensions) and all(reference in located for dimension in dimensions for reference in dimension["evidence"]),
    }
    return {"passed": all(checks.values()), "checks": checks, "actual_tools": sorted(actual_tools),
            "note": "参考档位仍待教师核定；机械检查通过不代表教师已确认评分。"}


async def run_sample(sample: str) -> int:
    started = datetime.now(DISPLAY_TIMEZONE)
    sample_path = ROOT / "samples" / f"{sample}.txt"
    text = sample_path.read_text(encoding="utf-8")
    settings = Settings.from_env()
    # Keep CLI experiments apart from the application database, regardless of
    # any DATABASE_PATH supplied for the normal backend service.
    settings.database_path = ROOT / "backend/data/live-acceptance.sqlite3"
    store = Store(settings.database_path)
    try:
        task = store.create_task(text, VERSION)
        await AgentRunner(store, ChatProvider(settings), settings).run(task["id"])
        final = store.get_task(task["id"])
    finally:
        store.close()
    # Load the proposed references only after all real model calls finish.
    references = json.loads((ROOT / "samples/expected.json").read_text(encoding="utf-8"))
    result = assess(final, references[sample], text)
    completed = datetime.now(DISPLAY_TIMEZONE)
    record = redact({
        "started_at": started.isoformat(), "completed_at": completed.isoformat(),
        "mode": "real_model", "sample": sample, "source": str(sample_path.relative_to(ROOT)),
        "service": safe_service(settings.base_url), "model": settings.model,
        "request_timeout_seconds": settings.request_timeout, "task_timeout_seconds": settings.task_timeout,
        "max_model_calls": settings.max_model_calls, "rubric_version": VERSION,
        "human_approval": "pending", "assessment": result, "task": final,
    }, settings.api_key)
    output_dir = ROOT / "docs/live-runs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{started.strftime('%Y%m%dT%H%M%S%z')}-{final['id']}.json"
    output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    draft = final.get("draft") or {}
    print(json.dumps(redact({
        "sample": sample, "passed": result["passed"], "status": final["status"],
        "scores": {dimension["id"]: dimension["score"] for dimension in draft.get("dimensions", [])},
        "total": draft.get("total"), "model_calls": final["model_calls"],
        "validation_count": final["validation_count"], "repair_rounds": final["repair_rounds"],
        "error": final.get("error"), "human_approval": "pending", "output": str(output),
    }, settings.api_key), ensure_ascii=False))
    return 0 if result["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="使用真实模型执行 S1/S2，保存工具与评分证据；人工核定保持待完成。")
    parser.add_argument("--sample", choices=("S1", "S2"), default="S1", help="匿名合成验收样本，默认 S1")
    arguments = parser.parse_args()
    return asyncio.run(run_sample(arguments.sample))


if __name__ == "__main__":
    raise SystemExit(main())
