"""作业文本安全护栏：纯正则/启发式 Prompt 注入检测，无模型调用。

契约见 master spec 3.3 与 WBS 4.1：scan_text 为纯函数式检测，
50k 字符文本耗时须低于 5ms（WBS 放宽上限 10ms）。
实现采用"关键词预筛 + 逐模式编译正则"：每个模式携带其任意匹配
必含的强制字面量，预筛不通过则完全跳过正则执行，干净文本近零开销。
"""

from dataclasses import dataclass
import re
from typing import Literal


@dataclass
class GuardrailResult:
    safe: bool
    risk_level: Literal["none", "low", "high"]
    detected_patterns: list[str]
    warning_message: str | None


_CANONICAL_NAMES = (
    "ignore_previous_instructions",
    "system_you_must",
    "give_full_marks",
    "ignore_previous_chinese",
)

# 与 INJECTION_PATTERNS 一一对应：每条正则任意匹配必含的关键字（小写，中文原样）
_CANONICAL_KEYWORDS = (
    ("ignore",),
    ("system",),
    ("满分", "越狱", "jailbreak", "disregard"),
    ("忽略",),
)


class SecurityGuardrails:
    # master spec 3.3 契约固定的四类高危注入模式（逐字保留）
    INJECTION_PATTERNS = [
        r"(?i)ignore\s+(all\s+)?(previous|above)\s+instructions",
        r"(?i)system\s*:\s*you\s+must",
        r"(?i)(给(我|本作业)?满分|越狱|jailbreak|disregard)",
        r"(?i)忽略(上面|之前|前文)的(所有)?(指令|规则)",
    ]

    # 扩展特征库：(模式名, 正则, 风险档位, 匹配必含关键字)。
    # high=确认注入（safe=False），low=可疑表述（仅告警）。
    _EXTRA_PATTERNS = [
        ("jailbreak_mode", r"(?i)\b(jailbreak|dan\s+mode|developer\s+mode)\b", "high", ("jailbreak", "dan mode", "developer mode")),
        ("reset_system_prompt", r"(?i)(系统提示(词)?(已被|已|被)?(重置|清空)|重置(你|系统)的?(提示词|指令|设定))", "high", ("重置", "清空")),
        ("role_override", r"(?i)(你现在是|现在开始扮演|假装你是).{0,16}(打分|评分|批改|满分)", "high", ("打分", "评分", "批改", "满分")),
        ("must_give_full_marks", r"(?i)(必须|一定|务必|无论如何都要).{0,10}(给|打|评).{0,6}(满分|100\s*分|高分)", "high", ("满分", "100", "高分")),
        ("unconditional_score", r"(?i)(无条件|直接)(给|打).{0,8}(满分|100\s*分|高分)", "high", ("满分", "100", "高分")),
        ("ignore_above_give", r"(?i)ignore\s+(above|previous).{0,20}(give|给).{0,10}(full\s+marks|100|满分|高分)", "high", ("ignore",)),
        ("give_me_marks", r"(?i)give\s+(me|this\s+assignment|it).{0,10}(full\s+marks|100|perfect\s+score|a\s+high\s+score)", "high", ("give",)),
        ("hidden_instruction", r"(?i)(隐藏|秘密|特殊|后台)\s*(指令|提示词|规则)", "high", ("隐藏", "秘密", "特殊", "后台")),
        ("stop_assistant", r"(?i)(忘记(你的|你|所有).{0,10}(设定|指令|规则)|不要遵守.{0,10}(指令|规则|设定))", "high", ("忘记", "遵守")),
        ("bypass_policy", r"(?i)(绕过|无视|忽略).{0,10}(评分|打分|量表|校验|规则)", "high", ("评分", "打分", "量表", "校验", "规则")),
        ("output_score_only", r"(?i)(只|直接)(输出|给出).{0,10}(满分|分数|成绩)", "high", ("满分", "分数", "成绩")),
        ("prompt_leak", r"(?i)(泄露|泄漏|输出|展示).{0,10}(系统提示词|你的提示词|system\s*prompt)", "high", ("提示词", "system")),
        ("admin_mode", r"(?i)\b(admin|administrator|root)\s+mode\b|管理员模式", "high", ("admin", "管理员")),
        ("do_not_grade", r"(?i)(不要|别)(再)?(批改|评分|打分|评估)(我(的)?)?(作业|内容|文本)", "high", ("批改", "评分", "打分", "评估")),
        ("claim_developer", r"(?i)(我是(你|该系统|系统)的?(开发者|管理员|设计者)|这是.{0,8}(开发者|管理员)的?(指令|命令))", "high", ("开发者", "管理员", "设计者")),
        ("new_rules_apply", r"(?i)(从现在开始|从现在起).{0,12}(遵守|执行|按).{0,10}(新)?(指令|规则)", "high", ("从现在",)),
        ("score_begging", r"(给我|帮我).{0,10}(高分|加分|多给.{0,4}分|提高.{0,4}分)", "low", ("给我", "帮我")),
        ("flattery_attack", r"(?i)(你是(最|非常|特别|无比|真的)(棒|厉害|聪明|强大|优秀|专业))", "low", ("你是",)),
        ("fake_history", r"(?i)(我们(之前|先前|刚才)(说好|约定|已经|早就))", "low", ("我们",)),
        ("coercion_threat", r"(?i)(不然|否则|如果不).{0,10}(差评|举报|投诉|不及格|挂科)", "low", ("不然", "否则", "如果不")),
        ("shortcut_request", r"(?i)(帮我(简化|跳过|省去).{0,10}(步骤|流程|校验|检查))", "low", ("简化", "跳过", "省去")),
    ]


# 类体推导式无法访问类作用域，统一在类定义后装配预编译表。
# 每条正则单独编译（Python 3.13 禁止 (?i) 全局标志出现在联合表达式中部），
# 预筛命中才执行，规避联合大正则的灾难性回溯。
SecurityGuardrails._COMPILED = [
    (name, re.compile(pattern), risk, tuple(keywords))
    for name, pattern, risk, keywords in (
        [(name, pattern, "high", keywords)
         for name, pattern, keywords in zip(_CANONICAL_NAMES, SecurityGuardrails.INJECTION_PATTERNS, _CANONICAL_KEYWORDS)]
        + list(SecurityGuardrails._EXTRA_PATTERNS)
    )
]


def scan_text(self, text: str) -> GuardrailResult:
    """纯正则单遍扫描。空文本或非字符串视为安全，直接放行。"""
    if not isinstance(text, str) or not text:
        return GuardrailResult(True, "none", [], None)
    detected: list[str] = []
    first_high = None
    first_match = None
    text_lower = text.lower()
    for name, regex, risk, keywords in self._COMPILED:
        if not any(keyword in text_lower for keyword in keywords):
            continue
        match = regex.search(text)
        if match is None:
            continue
        if first_match is None:
            first_match = match
        detected.append(name)
        if risk == "high" and first_high is None:
            first_high = match
    if not detected:
        return GuardrailResult(True, "none", [], None)
    risk = "high" if first_high is not None else "low"
    snippet = (first_high or first_match).group(0)
    if len(snippet) > 80:
        snippet = snippet[:80] + "…"
    hits = "、".join(detected)
    if risk == "high":
        return GuardrailResult(
            False, "high", detected,
            f"检测到疑似对抗性注入指令：“{snippet}”（命中模式：{hits}）。已强制标记全部维度待教师复核，请人工核查该作业来源。",
        )
    return GuardrailResult(
        True, "low", detected,
        f"检测到可疑表述：“{snippet}”（命中模式：{hits}），建议教师复核时留意。",
    )


# 绑定到类上，保持 master spec 3.3 的实例方法签名契约
SecurityGuardrails.scan_text = scan_text
