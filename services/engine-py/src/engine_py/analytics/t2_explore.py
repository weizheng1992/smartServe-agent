"""T2 探索通道(ADR-0010 分层信任架构):LLM 接地生成 SQL,守卫栈强制审计,
输出强制「探索性(非核验口径)」章 + 生成 SQL 折叠展示 —— 0005 二期缝的正式启用形态。

与课件的差别:语义层不是 Text-to-SQL 的「接地装置」而是「守卫对象」—— 生成 SQL
必须单语句、过 assert_safe_select(表白名单/危险函数黑名单)、AST 强制 LIMIT ≤ 50、
表 ∈ 语义模型 merchant_db 实体闭集(engine 库不可达,租户谓词面简化)、只读 reader
执行(3s 超时)。失败一律回落 unsupported 响亮语义,绝不降级编造。

双闸:`AI_T2_EXPLORE=on`(默认 off)∧ 角色 ∈ {admin, finance_owner};
eval 门(spec §7)未绿前 env 保持 off。
"""

from __future__ import annotations

import os
import re
from typing import Any

from sqlglot import exp

EXPLORED_TRUST = "explored"
EXPLORED_CALIBER = "探索性结果(非核验口径):AI 生成 SQL 的查询结果,未经口径审核,数字仅供参考"
_EXPLORE_ROLES = frozenset({"admin", "finance_owner"})
_MAX_LIMIT = 50

_FENCE_RE = re.compile(r"^```(?:sql)?\s*|\s*```$", re.MULTILINE)
# 引号外 CJK(中文字符):schema 全 ASCII,生成 SQL 引号字面量外出现中文 =
# 散文泄漏(live eval 实弹:「SELECT 查询, 且无法满足该更新需求…」被当合法
# 列名解析通过),响亮拒绝;WHERE category = '衬衫' 这类字面量不受累
_CJK_RE = re.compile(r"[一-鿿]")


def _reject_cjk_outside_literals(sql: str) -> None:
    unquoted = re.sub(r"'(?:[^']|'')*'", "''", sql)
    unquoted = re.sub(r'"(?:[^"]|"")*"', '""', unquoted)
    if _CJK_RE.search(unquoted):
        raise ExploreRejected("生成 SQL 含非 SQL 文本(引号外中文散文,疑似模型跑题)")


def _quote_cjk_aliases(stmt: exp.Expression) -> None:
    """中文列别名自动加引号(AST 自修复):模型常写 `AS 品类` 不带引号 —— SQL
    本身合法,PG 接受未加引号的 CJK 标识符,但白名单渲染/下游展示都要求规范
    形态;修完再过 CJK 审计(live eval 实弹:双品类退货对比整条 SQL 死于风格)。"""
    for alias_node in stmt.find_all(exp.Alias):
        alias_exp = alias_node.args.get("alias")
        if isinstance(alias_exp, exp.Identifier) and _CJK_RE.search(str(alias_exp.this or "")):
            alias_exp.set("quoted", True)


def t2_enabled() -> bool:
    return os.environ.get("AI_T2_EXPLORE", "off") == "on"


def enabled_for(role: str | None) -> bool:
    """双闸:env 开关 ∧ 角色白名单(admin/finance_owner 先行灰度,ADR-0010 决议 5)。"""
    return t2_enabled() and (role or "") in _EXPLORE_ROLES


class ExploreRejected(Exception):
    """探索查询生成/守卫不通过(响亮回落 unsupported;呈现层给拒绝原因)。"""


def grounding_context() -> str:
    """接地上下文:schema 卡(compact 文本)+ 指标目录(口径来源)。"""
    from .schema_cards import schema_card_text
    from .tools_registry_bridge import metric_semantic_registry

    metric_lines = [
        f"- {key}: {entry['label']} — {entry.get('description', '')[:80]}"
        for key, entry in metric_semantic_registry().items()
    ]
    return "商户库 schema(仅可查询这些表与列):\n" + schema_card_text() + "\n\n指标口径字典:\n" + "\n".join(metric_lines)


async def generate_sql(question: str) -> str:
    """LLM 单次生成(只产 SQL 文本,交给守卫;绝不直接执行)。"""
    from langchain_core.messages import HumanMessage, SystemMessage

    from .llm_intent import _content_text, get_chat_model

    system = (
        "你是商户数据分析的探索查询生成器。根据问题生成一条 PostgreSQL SELECT 查询。\n"
        "硬规则:\n"
        "- 只输出一条 SELECT 语句原文,不要解释、不要 markdown 代码块\n"
        "- 只能使用下方 schema 中列出的表与列\n"
        "- 结果集必须加 LIMIT 且不超过 50\n"
        "- 时间过滤用 created_at(下单/发生时间);金额与件数口径遵循指标字典 businessRules\n"
        "- 常用口径常量:有效成交 = status NOT IN ('REFUNDED', 'CANCELLED');差评 = rating <= 2;\n"
        "  在售 = status = 'ON_SALE';GMV = SUM(oi.quantity * oi.price)\n"
        "- 问题与 schema/指标字典无法对应时,输出空字符串,绝不编造表名\n"
        + grounding_context()
    )
    resp = await get_chat_model().ainvoke([SystemMessage(content=system), HumanMessage(content=question)])
    return _content_text(resp).strip()


def _extract_sql(raw_sql: str) -> str:
    """从生成文本提取 SQL:剥围栏后取首个 SELECT/WITH 起始处 —— 模型常无视
    「只输出语句原文」纪律带中文铺垫/尾注(live eval 实弹),散文不进解析器。"""
    text = _FENCE_RE.sub("", (raw_sql or "").strip()).strip()
    match = re.search(r"\b(SELECT|WITH)\b", text, re.IGNORECASE)
    return text[match.start() :].strip().rstrip(";").strip() if match else ""


def guard_explore_sql(raw_sql: str) -> str:
    """探索 SQL 强制守卫链:围栏/散文剥离 → 单语句 → LIMIT 注入/钳制 → 模型
    表白名单(engine 库不可达)→ 统一安全闸。任何一环不过 = ExploreRejected(响亮)。"""
    import sqlglot

    from .schema_cards import compile_safe_schema_card
    from .semantic_compiler import _assert_model_matches_card
    from .sql_guard import UnsafeSqlError, _cte_aliases, assert_safe_select
    from .tools_registry_bridge import semantic_model

    sql = _extract_sql(raw_sql)
    if not sql:
        stripped = _FENCE_RE.sub("", (raw_sql or "").strip()).strip()
        if stripped:
            raise ExploreRejected("生成内容未包含 SELECT 查询(仅允许只读查询)")
        raise ExploreRejected("生成内容为空,拒绝执行")

    _assert_model_matches_card()
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except sqlglot.errors.ParseError as err:
        # 散文混入并非都能被 sqlglot 当合法标识符消化(实弹两种结局:解析通过
        # 靠 CJK 审计拦 / 解析炸 → 此处响亮归类),绝不裸异常穿透
        raise ExploreRejected(f"生成内容不是合法 SQL(解析失败): {err}") from err
    if len(statements) != 1:
        raise ExploreRejected(f"多语句被拒({len(statements)} 条;探索通道只允许单条 SELECT)")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise ExploreRejected(f"仅允许 SELECT,实际 {type(stmt).__name__}")

    _quote_cjk_aliases(stmt)

    # LIMIT 强制:缺失注入 50,超限钳回 50(行数上限双保险之一,DB 侧另有超时)
    limit = stmt.args.get("limit")
    if limit is None:
        stmt.set("limit", exp.Limit(expression=exp.Literal.number(_MAX_LIMIT)))
    else:
        try:
            n = int(limit.expression.this)
        except Exception as err:
            raise ExploreRejected("LIMIT 必须是字面整数") from err
        if n > _MAX_LIMIT:
            limit.set("expression", exp.Literal.number(_MAX_LIMIT))

    # 模型表白名单(engine_db 实体不可达;租户面简化,ADR-0010 新增不变量 3)
    allowed_tables = {
        key for key, entity in semantic_model()["entities"].items()
        if entity["database"] == "merchant_db"
    }
    cte_names = _cte_aliases(stmt)
    for node in stmt.walk():
        if isinstance(node, exp.Table):
            name = node.name
            if not name or name in cte_names:
                continue
            if name not in allowed_tables:
                raise ExploreRejected(f"探索通道表白名单外(engine 库不可达): {name}")

    sql = stmt.sql(dialect="postgres")
    _reject_cjk_outside_literals(sql)
    try:
        assert_safe_select(sql, compile_safe_schema_card(), require_business_id=False)
    except UnsafeSqlError as err:
        raise ExploreRejected(f"未过统一安全闸: {err}") from err
    return sql


async def explore(question: str) -> tuple[Any, str]:
    """探索查询端到端:生成 → 守卫 → 只读 reader 执行 → (QueryResult, sql)。

    返回的 QueryResult.metric 固定 "__explore__"(非注册表闭集;呈现层据此
    不做指标口径注记,信任级走帧字段 trust=explored)。
    """
    from .engine import QueryResult
    from .tools_registry import order_domain

    raw = await generate_sql(question)
    sql = guard_explore_sql(raw)
    async with order_domain.merchant_reader_engine().connect() as conn:
        from sqlalchemy import text

        rows = (await conn.execute(text(sql))).mappings().all()
    capped = [dict(r) for r in rows[:_MAX_LIMIT]]
    result = QueryResult(rows=capped, metric="__explore__", unit="", caliber=EXPLORED_CALIBER)
    return result, sql
