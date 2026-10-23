"""Check a teacher-labeled suite or explicitly run its real 2x2 experiment."""
import argparse
import json
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="只检查人工参考门禁，不调用模型")
    group.add_argument("--run", action="store_true", help="实际调用已配置模型进行四条件对照")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=40, trust_env=False) as client:
        response = client.get("/api/v3/evaluation-suites/" + args.suite); response.raise_for_status(); suite = response.json()
        eligible = sum(s["reference"] is not None for s in suite["samples"])
        report = {"suite_id": suite["id"], "samples": len(suite["samples"]), "adjudicated": eligible,
                  "excluded": len(suite["samples"]) - eligible, "frozen_documents": len(suite["library"]["documents"]),
                  "model_called": False, "ready": eligible > 0 and bool(suite["library"]["documents"])}
        if args.run:
            if not report["ready"]:
                raise ValueError("请先完成课程资料准备及至少一份样本的双人独立评分、人工裁定")
            response = client.post(f"/api/v3/evaluation-suites/{args.suite}/runs"); response.raise_for_status(); run = response.json()
            while run["status"] in ("queued", "running"):
                time.sleep(2)
                response = client.get("/api/v3/evaluation-runs/" + run["id"]); response.raise_for_status(); run = response.json()
            report = {**run, "model_called": True}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
