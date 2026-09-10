"""规则前置匹配 — 镜像 triage/ruleMatchers.ts(正则逐条移植)。"""

from __future__ import annotations

import re

FAILURE_RESPONSE_RE = re.compile(
    r"熔断|网络.*波动|资金.*保障|接口.*延迟|拒绝|驳回|取消|超时|rejected|cancelled|expired|failed|error",
    re.IGNORECASE,
)
SYMBOL_ONLY_RE = re.compile(r"^[\s\d`~!@#$%^&*()_\-+=+\[\]{}|;:',.<>?/\\??,。！；：‘“”、]+$")
HUMAN_ESCALATION_RE = re.compile(
    r"转人工|找客服|联系人工|人工客服|找人工|转接人工|转人工客服|human agent|talk to human|speak to agent|customer service representative",
    re.IGNORECASE,
)
# 问候/身份词表(new-user-onboarding D 统一):run_agent 快道与 triage 规则层
# 此前各持一份且口径不一致(run_agent 含身份问句,triage 含时段问候),
# 并集收口为本单一来源 —— GREETING_RE 由词表派生,两层永不漂移。
# 词形一律为规整后形态(空白已在匹配前剥除);原表里的 "who are you" 等带空格
# 词条在两层规整逻辑下从来匹配不到(死词条),统一为无空格形态。
QUICK_GREETING_WORDS = frozenset(
    {
        # 通用与时段问候(原 triage GREETING_RE)
        "你好", "您好", "哈喽", "哈罗", "哈拉", "早上好", "下午好", "晚上好",
        "hello", "hi", "hey",
        # 身份问句(原 run_agent _QUICK_GREETINGS)
        "你是谁", "你是哪个", "你是ai吗", "你是机器人吗", "whoareyou", "howareyou",
    }
)

GREETING_RE = re.compile(
    "^(" + "|".join(sorted(QUICK_GREETING_WORDS, key=lambda w: (-len(w), w))) + ")$",
    re.IGNORECASE,
)


GREETING_STRIP_RE = re.compile(r"[，。！？,.!?\s]")


def normalize_greeting_input(user_input: str) -> str:
    """问候/身份词判定的统一规整(去标点空白 + 小写)——单一来源。

    ``is_quick_greeting`` 与 triage 的 ``strip_punctuation_for_greeting``
    共用本函数,两层永不漂移。
    """
    return GREETING_STRIP_RE.sub("", user_input.lower())


def is_quick_greeting(user_input: str) -> bool:
    """规整(去标点空白 + 小写)后精确命中问候/身份词表。

    run_agent 极速旁路直接传原始输入即可。
    """
    clean = normalize_greeting_input(user_input)
    return clean in QUICK_GREETING_WORDS
EXIT_RE = re.compile(
    r"^(再见|退出|bye|exit|quit|再见啦|拜拜|不聊了|好的，我的问题已经解决了，谢谢|我的问题解决了|问题解决了|解决了|谢谢|谢谢你|多谢)$",
    re.IGNORECASE,
)


def is_failed_response(content: str) -> bool:
    if not content:
        return False
    return bool(FAILURE_RESPONSE_RE.search(content))


def is_symbol_only(user_input: str) -> bool:
    return bool(SYMBOL_ONLY_RE.match(user_input))


def is_human_escalation_requested(user_input: str) -> bool:
    return bool(HUMAN_ESCALATION_RE.search(user_input))


def is_greeting(clean_input: str) -> bool:
    return bool(GREETING_RE.match(clean_input))


def is_exit_command(clean_input: str) -> bool:
    return bool(EXIT_RE.match(clean_input))
