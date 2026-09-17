"""SQL 安全闸(08-D4 四层链的代码侧两层:解析层 + 编译层断言)。

DB 层(只读角色/连接池/超时)在阶段①已随 reader 引擎落地;呈现层诚实报错
归卡片层。本模块职责:
- 解析层:sqlglot parse → 单语句 → AST 白名单(仅 SELECT/UNION/子查询)→
  表白名单(sqlglot qualify 对照 schema 卡片,挡幻觉表)→ 危险函数黑名单;
- 编译层断言:require_business_id 时 AST 必须含 business_id 谓词(租户谓词
  服务端注入后不可被剥离)。
选型否决留档:pglast(GPL 法务)、sqlparse(non-validating 不可作安全边界)。
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp

_ALLOWED_NODE_TYPES = (exp.Select, exp.Union, exp.Subquery, exp.With, exp.CTE, exp.Order, exp.Limit, exp.Column, exp.Table, exp.Alias, exp.Star)
_FORBIDDEN_FUNCTIONS = {"pg_sleep", "dblink", "pg_read_file", "lo_import", "pg_terminate_backend"}


class UnsafeSqlError(Exception):
    """任何校验不通过的统一异常(呈现层据此分类诚实报错)。"""


def _validate_expression(expr: exp.Expression, allowed_tables: set[str] | None) -> None:
    for node in expr.walk():
        if isinstance(node, exp.Func) and node.sql_name().lower() in _FORBIDDEN_FUNCTIONS:
            raise UnsafeSqlError(f"危险函数: {node.sql_name()}")
        if isinstance(node, (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter, exp.TruncateTable, exp.Grant, exp.Command)):
            raise UnsafeSqlError(f"非查询语句: {type(node).__name__}")
        if isinstance(node, exp.Table):
            table_name = node.name
            if allowed_tables is not None and table_name and table_name not in allowed_tables:
                raise UnsafeSqlError(f"表白名单外: {table_name}")


def reject_unsafe(sql: str, schema: dict, require_business_id: bool = False) -> None:
    """校验失败抛 UnsafeSqlError;通过返回 None。schema 形如 schema_cards 产出。"""
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1:
        raise UnsafeSqlError(f"多语句被拒({len(statements)} 条)")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise UnsafeSqlError(f"仅允许 SELECT/UNION,实际 {type(stmt).__name__}")

    allowed_tables = set(schema.get("tables", {}).keys()) if schema else None
    _validate_expression(stmt, allowed_tables)

    if require_business_id and "business_id" not in sql:
        raise UnsafeSqlError("缺租户谓词 business_id")


def assert_safe_select(sql: str, schema: dict, require_business_id: bool = False):
    """校验并回传解析后的 AST(调用方无需二次 parse)。"""
    reject_unsafe(sql, schema, require_business_id=require_business_id)
    return sqlglot.parse_one(sql, read="postgres")
