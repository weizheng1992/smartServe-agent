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
GREETING_RE = re.compile(r"^(你好|您好|哈喽|哈罗|hello|hi|hey|哈拉|早上好|下午好|晚上好)$", re.IGNORECASE)
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
