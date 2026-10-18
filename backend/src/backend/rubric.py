from decimal import Decimal

VERSION = "2026-v1"
DIMENSIONS = (
    ("A", "需求背景与用户范围", 15, "用户困难与功能对应；来源、现状与排除项清楚", "用户功能明确，来源或边界有一项缺失", "仅列功能或愿望，混淆现状与建议"),
    ("B", "需求表达可验证性", 25, "编号、前提、动作、可见结果齐全且一致", "主体结果明确，前提或动作有歧义", "仅写智能、方便、快或技术方案"),
    ("C", "验收场景与测试用例", 25, "至少三场景覆盖正常、差异或边界、异常；输入、预期、判据、判定人、样本、数字来源齐全", "三场景多数可判定，但关键字段或数字来源缺失", "只有正常流程或无法复核的效果承诺"),
    ("D", "系统行为依据", 15, "输入或规则与输出可追溯，变化有理由；功能边界或AI失败与人工核查明确", "解释部分依据边界，但关键变化或失败结果未说明", "输出变化无依据或异常与需求无关"),
    ("E", "AI 协作过程记录与反思", 10, "有问题、建议、采纳或拒绝理由与具体修改；AI不可用时有人工审查替代记录", "有记录，决策理由或改动对应不完整", "仅写AI生成或未用，没有审查"),
    ("F", "同行互评与修订记录", 10, "有版本、成员责任、带证据的反馈与对应修订或合理拒绝", "有反馈修订，缺版本、责任或处理理由", "无法追踪反馈和改动"),
)
WEIGHTS = {row[0]: row[2] for row in DIMENSIONS}
IDS = tuple(WEIGHTS)
LEVELS = (100, 70, 30, 0)
RUBRIC = {
    "version": VERSION,
    "levels": list(LEVELS),
    "dimensions": [
        {"id": row[0], "name": row[1], "max_score": row[2],
         "criteria": {"100": row[3], "70": row[4], "30": row[5], "0": "相关内容整体缺失；零散缺项不能直接判0"}}
        for row in DIMENSIONS
    ],
}


def score(dimension: str, level: int) -> Decimal:
    if dimension not in WEIGHTS or type(level) is not int or level not in LEVELS:
        raise ValueError("维度或档位不合法")
    return Decimal(WEIGHTS[dimension]) * Decimal(level) / Decimal(100)
