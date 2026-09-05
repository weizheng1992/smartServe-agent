"""AST 只读分析沙箱契约(gateway_py/sandbox.py,镜像 TS executeReadOnlyAnalyticsQuery)。

两层语义分别钉死:
- 校验层 ``validate_readonly_sql``(纯函数):仅 SELECT/WITH/UNION、单语句、
  阻断 DML/DDL/系统调用、系统目录表穿透拦截、缺 LIMIT 强制注入 50;
- 执行层 ``execute_readonly_analytics_query``(密封 PG):LIMIT 50 真实封顶、
  3s 语句超时熔断、只读事务。

已知边界(文档化,非背书):``pg_`` 前缀拦截仅作用于 Table 节点,
``pg_sleep()`` 等函数调用不在拦截范围——执行层超时是其后防线。
"""

from __future__ import annotations

import pytest

from gateway_py.sandbox import execute_readonly_analytics_query, validate_readonly_sql

# ---------- 校验层:合法查询 ----------


def test_纯空白输入拒绝() -> None:
    with pytest.raises(ValueError, match="Empty SQL"):
        validate_readonly_sql("   ")


def test_解析失败拒绝() -> None:
    with pytest.raises(ValueError, match="SQL parse error"):
        validate_readonly_sql("SELEC * FROM orders")


def test_多语句拒绝() -> None:
    with pytest.raises(ValueError, match="exactly one statement"):
        validate_readonly_sql("SELECT 1; SELECT 2")


def test_单条语句带尾分号合法() -> None:
    sql = validate_readonly_sql("SELECT 1;")
    assert sql.upper().startswith("SELECT")


def test_select_缺limit_强制注入50() -> None:
    sql = validate_readonly_sql("SELECT * FROM orders")
    assert "LIMIT 50" in sql.upper()


def test_select_显式limit_保留原值不覆写() -> None:
    sql = validate_readonly_sql("SELECT * FROM orders LIMIT 5")
    assert "LIMIT 5" in sql.upper()


def test_with_cte合法() -> None:
    sql = validate_readonly_sql("WITH t AS (SELECT 1 AS n) SELECT * FROM t")
    assert "LIMIT 50" in sql.upper()


def test_union合法() -> None:
    sql = validate_readonly_sql("SELECT 1 AS n UNION SELECT 2")
    assert "UNION" in sql.upper()


# ---------- 校验层:写操作与DDL全谱拦截 ----------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO orders (order_id) VALUES ('ORD-1')",
        "UPDATE orders SET status = 'PAID'",
        "DELETE FROM orders",
        "DROP TABLE orders",
        "ALTER TABLE orders ADD COLUMN note text",
        "TRUNCATE TABLE orders",
        "GRANT SELECT ON orders TO public",
        "REVOKE SELECT ON orders FROM public",
        # CTE 内嵌写操作:AST walk 穿透 Subquery 捕获 Delete 节点
        "WITH t AS (DELETE FROM orders RETURNING *) SELECT * FROM t",
    ],
)
def test_写操作与DDL拦截(sql: str) -> None:
    with pytest.raises(ValueError, match="Security Violation"):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "VACUUM ANALYZE orders",
        "EXPLAIN SELECT * FROM orders",
        "SET statement_timeout = 0",
        "COPY orders TO '/tmp/dump.csv'",
    ],
)
def test_非查询语句拦截(sql: str) -> None:
    with pytest.raises(ValueError, match="Only SELECT or WITH"):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM information_schema.tables",
        "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public'",
        "SELECT * FROM pg_catalog.pg_tables",
        "SELECT * FROM pg_tables",
        # Table 节点 name 做小写归一后比对,大写绕写无效
        "SELECT * FROM PG_TABLES",
    ],
)
def test_系统目录表穿透拦截(sql: str) -> None:
    with pytest.raises(ValueError, match="system catalog"):
        validate_readonly_sql(sql)


# ---------- 执行层:密封 PG 上钉死真实行为 ----------


async def test_执行层_正常查询返回行() -> None:
    rows = await execute_readonly_analytics_query("SELECT 1 AS one")
    assert rows == [{"one": 1}]


async def test_执行层_超过50行强制封顶() -> None:
    rows = await execute_readonly_analytics_query("SELECT n FROM generate_series(1, 100) AS g(n)")
    assert len(rows) == 50
    assert {r["n"] for r in rows} <= set(range(1, 101))


async def test_执行层_语句超时3s熔断() -> None:
    """pg_sleep 走校验层盲区(函数非 Table),由执行层 statement_timeout 兜底熔断。"""
    with pytest.raises(Exception, match="(?i)cancel|timeout"):
        await execute_readonly_analytics_query("SELECT pg_sleep(8) AS zzz")
