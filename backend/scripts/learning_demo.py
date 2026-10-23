"""Seed an explicitly synthetic teaching workflow; --run makes two real grading calls.

uv run --project backend python backend/scripts/learning_demo.py --seed --run
Does not confirm grades or create human reference labels. Historical objects stay untouched.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--seed", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--retry-failed", action="store_true", help="保留首轮失败后显式重试一次")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.seed:
        parser.error("请显式指定--seed；增加--run才会调用真实模型")
    client = httpx.Client(base_url=args.base_url, timeout=40, trust_env=False)

    def request(path, method="GET", body=None, key=None):
        response = client.request(method, "/api/" + path, json=body, headers={"Idempotency-Key": key} if key else {})
        response.raise_for_status()
        return response.json()

    def all_rows(path):
        rows = []
        while True:
            page = request(path + ("&" if "?" in path else "?") + f"limit=100&offset={len(rows)}")
            rows.extend(page["items"])
            if len(rows) >= page["total"] or not page["items"]:
                return rows

    health = request("health")
    if args.run and (not health["model_configured"] or "test" in health["model"].lower()):
        raise ValueError("真实运行需配置正式模型，拒绝将测试替身记录为真实模型成果")
    name = "教学增强演示（合成样本）"
    course = next((c for c in all_rows("v2/courses") if c["name"] == name), None) or request("v2/courses", "POST", {"name": name})
    title = "LEFT JOIN报告：资料检索、独立审校与修改对比"
    assignment = next((a for a in all_rows("v2/assignments?course_id=" + course["id"]) if a["title"] == title), None)
    if assignment is None:
        rubric = request("v2/rubrics", "POST", {"title": "数据库报告四维（增强演示，待教师核定）"})["draft"]
        definition = json.loads((ROOT / "samples/v2-benchmark/rubrics/database.json").read_text(encoding="utf-8"))
        rubric = request(f"v2/rubric-versions/{rubric['id']}", "PATCH", {"expected_revision": 1, "definition": definition})
        rubric = request(f"v2/rubric-versions/{rubric['id']}/publish", "POST", {"expected_revision": rubric["revision"]})
        assignment = request("v2/assignments", "POST", {"course_id": course["id"], "title": title, "instructions": "依据量表评价SQL逻辑说明、实验过程、结果分析与表达。目标是展示全部学生及选课数，包含无选课学生，解释AVG与NULL。课程资料为教师示例依据。只评价文本，不执行SQL。", "reference_text": "先核对LEFT JOIN、COUNT(e.id)及AVG对NULL的规则，再根据学生实际文本取证。", "rubric_version_id": rubric["id"]})
        assignment = request(f"v2/assignments/{assignment['id']}/publish", "POST", {"expected_revision": assignment["revision"]})
    data = (ROOT / "samples/learning-demo/course-material.md").read_bytes()
    documents = request(f"v3/courses/{course['id']}/materials")["items"]
    if not any(d["file_hash"] == hashlib.sha256(data).hexdigest() for d in documents):
        request(f"v3/courses/{course['id']}/materials", "POST", {"title": "LEFT JOIN与NULL实验讲义（合成示例）", "filename": "course-material.md", "content_base64": base64.b64encode(data).decode()})
    policy = request(f"v3/assignments/{assignment['id']}/policy")
    if not (policy["retrieval_enabled"] and policy["audit_enabled"]):
        request(f"v3/assignments/{assignment['id']}/policy", "PUT", {"expected_revision": policy["revision"], "retrieval_enabled": True, "audit_enabled": True})
    report = {"synthetic": True, "model": health["model"], "assignment_id": assignment["id"], "course_id": course["id"],
              "human_references_created": 0, "grades_confirmed": 0, "quality_evaluation": False, "tasks": []}

    def wait(identifier):
        for _ in range(330):
            task = request("v2/tasks/" + identifier)
            if task["status"] not in ("queued", "running"):
                return task
            time.sleep(1)
        raise TimeoutError("任务未在预算后结束，请检查服务")

    if args.run:
        initial = (ROOT / "samples/learning-demo/initial.txt").read_bytes().decode("utf-8")
        task = request("v2/tasks", "POST", {"assignment_id": assignment["id"], "submission_label": "增强演示-01（匿名合成）", "text": initial}, "learning-demo-v1-" + hashlib.sha256(initial.encode()).hexdigest())
        task = wait(task["id"])
        tasks = [task]
        # Read the retained retry lineage; --retry-failed creates at most one new attempt.
        for _ in range(16):
            if not task.get("replaced_by"):
                break
            task = wait(task["replaced_by"])
            if any(t["id"] == task["id"] for t in tasks):
                raise ValueError("重试链存在循环")
            tasks.append(task)
        if task["status"] == "failed" and args.retry_failed:
            task = request(f"v2/tasks/{task['id']}/retry", "POST", key="learning-demo-explicit-retry-v1")
            task = wait(task["id"])
            tasks.append(task)
        if task["status"] == "pending_review":
            revised = (ROOT / "samples/learning-demo/revised.txt").read_bytes().decode("utf-8")
            new = request(f"v3/tasks/{task['id']}/revisions", "POST", {"text": revised}, "learning-demo-revision-v1-" + hashlib.sha256(revised.encode()).hexdigest())
            tasks.append(wait(new["id"]))
        for task in tasks:
            learning = request(f"v3/tasks/{task['id']}/learning")
            row = {"id": task["id"], "input_version": task["input_version"], "status": task["status"], "error": task.get("error"),
                   "draft_total": (task.get("draft") or {}).get("total"), "model_calls": task["model_calls"],
                   "retrieval_count": len(learning["retrievals"]), "retrieval_matches": sum(len(r["matches"]) for r in learning["retrievals"]),
                   "audit_status": learning.get("audit", {}).get("status"), "disputed_count": learning.get("audit", {}).get("disputed_count"),
                   "url": "http://127.0.0.1:3000/v2?task=" + task["id"]}
            if learning.get("revision"):
                row["comparison"] = request(f"v3/tasks/{task['id']}/comparison")
            report["tasks"].append(row)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    client.close()


if __name__ == "__main__":
    main()
