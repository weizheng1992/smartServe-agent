"""已知值脱敏 — 坏例候选池配套工具(第五阶段 v1)。

两层防线,顺序执行:
1. **已知值精确替换**:从 ``user_addresses``(收件人/手机号/地址)与 ``users.email``
   收集业务库中真实存在的 PII 值,对文本做精确子串替换为 ``[REDACTED]``
   —— 覆盖正则无法命中的姓名、详细地址等自由文本;
2. **模式脱敏**:复用 ``tools_registry/scrubber.py`` 的正则(手机号/身份证/邮箱/银行卡),
   兜底捕获库外数据(用户在对话中直接输入的 PII)。

设计原则:坏例入黄金集前必须过 ``redact_text``;候选池评审(``cli.py show``)输出
"原文 vs 脱敏对照",评审人基于脱敏侧撰写回归用例。
"""

from __future__ import annotations

from sqlalchemy import select

from ..db import User, UserAddress, get_session
from ..tools_registry.scrubber import scrub_pii_string

# 已知值收集上限:防大库全表扫拖垮 CLI/调度(超限值交由正则层兜底)
_MAX_KNOWN_VALUES_PER_SOURCE = 2000
# 过短的已知值跳过精确替换(单字符误伤率过高,如姓氏、地级市单字简称)
_MIN_VALUE_LENGTH = 2


async def collect_known_pii_values(business_id: str | None = None) -> list[str]:
    """收集库内已知 PII 值:收件人姓名/手机号/地址 + 用户邮箱。

    ``business_id`` 提供时仅收集该租户(多租户隔离);为空收集全库(评审跨租户候选时使用)。
    """
    values: list[str] = []

    async with get_session() as session:
        addr_stmt = select(
            UserAddress.receiver_name,
            UserAddress.receiver_phone,
            UserAddress.full_address,
            UserAddress.detail_address,
        ).limit(_MAX_KNOWN_VALUES_PER_SOURCE)
        if business_id:
            addr_stmt = addr_stmt.where(UserAddress.business_id == business_id)
        for name, phone, full_addr, detail_addr in (await session.execute(addr_stmt)).all():
            values.extend(v for v in (name, phone, full_addr, detail_addr) if v)

        email_stmt = select(User.email).where(User.email.is_not(None)).limit(_MAX_KNOWN_VALUES_PER_SOURCE)
        values.extend(e for (e,) in (await session.execute(email_stmt)).all() if e)

    # 去重;按长度降序替换,避免短值先替换破坏长值命中(如地址包含姓名)
    return sorted({v.strip() for v in values if v and len(v.strip()) >= _MIN_VALUE_LENGTH}, key=len, reverse=True)


def redact_known_values(text: str, known_values: list[str]) -> str:
    """精确子串替换为 ``[REDACTED]``(known_values 需已按长度降序)。"""
    for value in known_values:
        if value in text:
            text = text.replace(value, "[REDACTED]")
    return text


async def redact_text(text: str, business_id: str | None = None) -> str:
    """完整脱敏管道:已知值精确替换 ➔ 正则模式兜底。"""
    if not text:
        return text
    known = await collect_known_pii_values(business_id)
    return scrub_pii_string(redact_known_values(text, known))
