"""PII 脱敏器 — 镜像 tools/src/scrubber.ts(手机号/身份证/邮箱/银行卡递归遮蔽)。"""

from __future__ import annotations

import re
from typing import Any

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)")
_ID_CARD_RE = re.compile(r"(?<!\d)([1-9]\d{5})\d{8}(\d{3}[\dX])(?!\d)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b([a-zA-Z0-9._%+-]{1,2})[a-zA-Z0-9._%+-]*@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")
_BANK_CARD_RE = re.compile(r"(?<!\d)(\d{4})\d{8,11}(\d{4})(?!\d)")
_SENSITIVE_KEY_RE = re.compile(r"password|secret|token|auth", re.IGNORECASE)


def scrub_pii_string(text: str) -> str:
    if not text:
        return text
    text = _PHONE_RE.sub(r"\1****\2", text)
    text = _ID_CARD_RE.sub(r"\1********\2", text)
    text = _EMAIL_RE.sub(r"\1***@\2", text)
    text = _BANK_CARD_RE.sub(r"\1********\2", text)
    return text


def scrub_pii(value: Any) -> Any:
    if value is None:
        return value
    if isinstance(value, str):
        return scrub_pii_string(value)
    if isinstance(value, list):
        return [scrub_pii(item) for item in value]
    if isinstance(value, dict):
        return {
            key: "******" if isinstance(val, str) and _SENSITIVE_KEY_RE.search(key) else scrub_pii(val)
            for key, val in value.items()
        }
    return value
