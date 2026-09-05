"""AST 只读分析沙箱 — sqlglot 版(镜像 db.executeReadOnlyAnalyticsQuery 行为,AST 级更强)。

规则与 TS 一致:仅 SELECT/WITH、阻断 DDL/DML/系统调用、缺 LIMIT 注入 50、
只读事务 + 3s 语句超时。相比 TS 的正则黑名单,sqlglot 在语法树层校验,
并额外阻断系统表(information_schema / pg_catalog)穿透。
"""

from __future__ import annotations

import sqlglot
from engine_py.db import get_session
from sqlalchemy import text
from sqlglot import exp

_FORBIDDEN_NODE_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
    exp.Command,
    exp.Create,
    exp.Merge,
)
_FORBIDDEN_TABLE_PREFIXES = ("information_schema", "pg_catalog", "pg_")


def validate_readonly_sql(sql_text: str) -> str:
    """校验并规整 SQL;违规抛 ValueError,合法返回注入 LIMIT 后的安全语句。"""
    stripped = (sql_text or "").strip()
    if not stripped:
        raise ValueError("Empty SQL")

    try:
        statements = sqlglot.parse(stripped, read="postgres")
    except sqlglot.errors.ParseError as err:
        raise ValueError(f"SQL parse error: {err}") from err

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise ValueError("Security Violation: exactly one statement is permitted")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.With, exp.Subquery)):
        raise ValueError("Security Violation: Only SELECT or WITH queries are permitted in read-only analytics sandbox.")

    for node in statement.walk():
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            raise ValueError("Security Violation: Data modification or DDL statements are strictly prohibited.")
        if isinstance(node, exp.Table):
            # 限定名逐段检查:information_schema.tables 的 node.name 只有叶名 "tables",
            # catalog/db 限定段必须一并比对,否则限定名可绕写穿透目录拦截
            qualifiers = (node.args.get("catalog"), node.args.get("db"), node.name)
            lowered = [str(q).lower() for q in qualifiers if q]
            if any(q.startswith(prefix) for q in lowered for prefix in _FORBIDDEN_TABLE_PREFIXES):
                raise ValueError("Security Violation: system catalog access is blocked.")

    # 注入 LIMIT 50(TS:无 LIMIT 时追加)
    if not statement.args.get("limit"):
        statement = statement.limit(50)
    return statement.sql(dialect="postgres")


async def execute_readonly_analytics_query(sql_text: str, params: list | None = None) -> list[dict]:
    """只读事务 + 3s 超时执行(镜像 TS 沙箱执行语义)。"""
    safe_sql = validate_readonly_sql(sql_text)
    async with get_session() as session:
        # session.connection() 即自动开启事务,不得再 session.begin()(二次开启必抛
        # InvalidRequestError,原实现从未真正执行过);SET TRANSACTION 须为事务首条语句
        conn = await session.connection()
        await conn.execute(text("SET TRANSACTION READ ONLY"))
        await conn.execute(text("SET LOCAL statement_timeout = '3000ms'"))
        result = await conn.execute(text(safe_sql), params or [])
        return [dict(r) for r in result.mappings()]
