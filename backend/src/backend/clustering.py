"""班级共性缺陷聚合与学情诊断引擎。

契约见 master spec 3.4 与 WBS 4.2：纯确定性统计，无模型调用。
输入批次任务字典列表，输出严格对齐 API 12 的结构化字典；
batch_id 从任务元数据推导，路由挂载时以权威参数覆写。
"""

from .rubric import IDS, RUBRIC

# 高频问题短语库：(关键词元组, 问题标题, 教学建议)。
# 关键词仅在失分严重（档位 30 或 0）维度的理由中匹配（spec 3.4 规则）。
_WEAKNESS_LIBRARY = [
    (("缺少测试用例",), "验收测试用例缺失", "在后续课堂中重点强调等价类划分与边界值分析方法。"),
    (("缺少边界", "无边界"), "验收场景缺少边界用例", "在后续课堂中重点强调等价类划分与边界值分析方法。"),
    (("缺少异常", "无异常"), "验收场景缺少异常用例", "在后续课堂中重点强调等价类划分与边界值分析方法。"),
    (("未说明采纳理由", "缺少采纳", "拒绝理由", "采纳与拒绝"), "AI 协作记录缺乏采纳与拒绝理由", "要求学生必须保留至少一条否定 AI 建议并手动重构的真实记录。"),
    (("缺少互评", "无互评", "互评缺失"), "同行互评记录缺失", "强调同行互评需保留带证据的反馈与对应修订。"),
    (("修订对比", "修订记录", "无法追踪反馈"), "互评修订对比不明显", "要求保留版本、成员责任与修订对照记录。"),
    (("主观词", "不可验证", "仅写智能", "方便"), "需求表达含主观词、不可验证", "强调需求须编号、含前提动作与可见结果。"),
    (("缺少状态流转", "状态流转", "恢复逻辑"), "系统行为缺少状态流转或恢复逻辑", "强调系统行为需覆盖完整状态机与异常恢复。"),
    (("该部分未提供", "整体缺失", "未提供"), "维度内容整体缺失", "提示学生补全该维度内容，缺失维度按0分档计。"),
    (("缺少证据", "无证据", "依据不足", "无法追溯"), "系统行为依据不足", "强调输入规则与输出可追溯。"),
    (("决策理由", "改动对应"), "AI 协作决策理由不完整", "要求记录采纳或拒绝理由与具体修改。"),
    (("成员责任", "版本"), "互评缺少版本或成员责任", "要求互评记录版本与成员责任。"),
]


class ClassAnalyticsEngine:
    @staticmethod
    def _grading(task: dict) -> dict | None:
        """教师复核分数优先（与 storage._grading 同规则）；不可分析状态返回 None。"""
        if task.get("status") not in ("pending_review", "confirmed"):
            return None
        grading = task.get("review") or task.get("draft")
        return grading if isinstance(grading, dict) else None

    def analyze_batch(self, tasks: list[dict]) -> dict:
        batch_id = tasks[0].get("batch_id") if tasks else None
        analyzed = [
            item for item in (self._grading(task) for task in tasks)
            if item is not None and item.get("total") is not None and item.get("dimensions")
        ]
        count = len(analyzed)
        totals = [float(item["total"]) for item in analyzed]

        summary = {
            "total_submitted": len(tasks),
            "analyzed_count": count,
            "average_score": round(sum(totals) / count, 1) if count else None,
            "pass_rate": round(sum(1 for total in totals if total >= 60) / count, 2) if count else 0.0,
            "excellent_rate": round(sum(1 for total in totals if total >= 90) / count, 2) if count else 0.0,
            "max_score": round(max(totals), 1) if count else None,
            "min_score": round(min(totals), 1) if count else None,
        }

        radar = []
        for dimension in RUBRIC["dimensions"]:
            dim_id = dimension["id"]
            scores = [float(d["score"]) for item in analyzed for d in item["dimensions"] if d["id"] == dim_id]
            average = round(sum(scores) / len(scores), 1) if scores else 0.0
            radar.append({
                "dimension": dim_id, "name": dimension["name"], "full_score": dimension["max_score"],
                "average_score": average, "scoring_rate": round(average / dimension["max_score"], 2),
            })

        # 共性薄弱项：仅在弱档（30/0）维度理由中统计短语命中，按受影响任务数取 TOP 3
        weak = [
            (position, d["id"], d.get("reason") or "")
            for position, item in enumerate(analyzed)
            for d in item["dimensions"]
            if d.get("level") in (30, 0)
        ]
        candidates = []
        for keywords, title, recommendation in _WEAKNESS_LIBRARY:
            affected = set()
            dimension_hits: dict[str, int] = {}
            for position, dim_id, reason in weak:
                if any(keyword in reason for keyword in keywords):
                    affected.add(position)
                    dimension_hits[dim_id] = dimension_hits.get(dim_id, 0) + 1
            if affected:
                dimension = max(dimension_hits, key=lambda key: (dimension_hits[key], -IDS.index(key)))
                candidates.append((len(affected), dimension, title, recommendation))
        candidates.sort(key=lambda item: (-item[0], IDS.index(item[1])))
        common_weaknesses = [
            {
                "rank": rank, "dimension": dimension, "title": title,
                "affected_count": affected, "percentage": round(affected / count, 2) if count else 0.0,
                "recommendation": recommendation,
            }
            for rank, (affected, dimension, title, recommendation) in enumerate(candidates[:3], start=1)
        ]

        security_alerts = []
        for task in tasks:
            flag = task.get("security_flag") or (task.get("draft") or {}).get("security_flag") or "none"
            if flag == "none":
                continue
            security_alerts.append({
                "task_id": task["id"],
                "filename": task.get("filename") or "单份作业",
                "flag": flag,
                "detail": task.get("security_detail") or "检测到疑似对抗指令，请教师人工核查。",
            })

        return {
            "batch_id": batch_id,
            "summary": summary,
            "radar": radar,
            "common_weaknesses": common_weaknesses,
            "security_alerts": security_alerts,
        }
