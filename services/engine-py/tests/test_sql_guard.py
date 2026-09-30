"""SQL 安全闸专册(2026-10-01 夜审补缺,此前零直接测试)。

钉死四层:
1. 白名单放行:SELECT/UNION/CTE 正常过闸(assert_safe_select 回传 AST);
2. 非查询与多语句拒:INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/GRANT、
   分号串联一律 UnsafeSqlError;
3. 危险函数黑名单真实生效 —— 夜审实证 sqlglot 把未知名函数解析为
   exp.Anonymous 且 sql_name() 恒 'ANONYMOUS',旧实现按 sql_name() 比对
   即对 pg_sleep/dblink 全部漏放(黑名单形同虚设);现按 Anonymous.this
   取真名,睡眠/跨库/文件/大对象/后端控制各族抽验;
4. require_business_id 编译层断言:只认 AST 真实列引用 —— 注释、字符串
   字面量、绑定参数(:business_id)、同名表均不算谓词(旧裸子串检查
   `business_id in sql` 被注释即可绕过)。
"""

from __future__ import annotations

import pytest
from sqlglot import exp

from engine_py.analytics.sql_guard import UnsafeSqlError, assert_safe_select, reject_unsafe

SCHEMA = {"tables": {"merchant_orders": {}, "merchant_spus": {}}}


# ---- 1. 白名单放行 ----


def test_合法select过闸并回传AST():
    ast = assert_safe_select(
        "SELECT spu_code, MIN(price) FROM merchant_spus WHERE status = 'ON_SALE' GROUP BY spu_code LIMIT 10",
        SCHEMA,
    )
    assert isinstance(ast, exp.Select)


def test_union与CTE过闸_CTE别名豁免表白名单():
    sql = (
        "WITH hot AS (SELECT spu_code FROM merchant_orders) "
        "SELECT a.spu_code FROM merchant_spus a UNION ALL SELECT spu_code FROM hot"
    )
    assert reject_unsafe(sql, SCHEMA) is None


# ---- 2. 非查询与多语句拒 ----


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO merchant_orders VALUES (1)",
        "UPDATE merchant_orders SET status = 'X'",
        "DELETE FROM merchant_orders",
        "DROP TABLE merchant_orders",
        "ALTER TABLE merchant_orders ADD COLUMN x int",
        "TRUNCATE merchant_orders",
        "GRANT ALL ON merchant_orders TO PUBLIC",
    ],
)
def test_非查询语句一律拒(sql: str):
    with pytest.raises(UnsafeSqlError):
        reject_unsafe(sql, SCHEMA)


def test_多语句串联拒():
    with pytest.raises(UnsafeSqlError, match="多语句"):
        reject_unsafe("SELECT 1; SELECT 2", SCHEMA)


def test_表白名单外幻觉表拒():
    with pytest.raises(UnsafeSqlError, match="表白名单外"):
        reject_unsafe("SELECT * FROM pg_catalog.pg_tables", SCHEMA)


# ---- 3. 危险函数黑名单(Anonymous 真名比对) ----


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_sleep(10)",  # 睡眠拖库
        "SELECT pg_sleep_for('1 min')",
        "SELECT * FROM dblink('dbname=x', 'SELECT 1') AS t(a int)",  # 跨库穿透
        "SELECT pg_read_file('/etc/passwd')",  # 文件读取
        "SELECT lo_import('/etc/passwd')",  # 大对象导入
        "SELECT lo_export(oid, '/tmp/x')",
        "SELECT pg_terminate_backend(123)",  # 后端进程控制
        "SELECT pg_cancel_backend(123)",
        "SELECT set_config('search_path', 'evil', false)",  # 会话设置篡改
    ],
)
def test_危险函数黑名单拒(sql: str):
    with pytest.raises(UnsafeSqlError, match="危险函数"):
        reject_unsafe(sql, SCHEMA)


def test_普通函数不误伤():
    assert reject_unsafe("SELECT COALESCE(MAX(total_amount), 0) FROM merchant_orders", SCHEMA) is None


# ---- 4. require_business_id:只认 AST 列引用 ----


def test_有租户谓词列引用过闸():
    assert (
        reject_unsafe("SELECT * FROM merchant_orders WHERE business_id = :business_id", SCHEMA, require_business_id=True)
        is None
    )


def test_无谓词拒():
    with pytest.raises(UnsafeSqlError, match="缺租户谓词"):
        reject_unsafe("SELECT * FROM merchant_orders WHERE status = 'PAID'", SCHEMA, require_business_id=True)


def test_注释伪装谓词拒():
    """旧实现裸子串检查被一句注释绕过 —— AST 断言后不再成立。"""
    with pytest.raises(UnsafeSqlError, match="缺租户谓词"):
        reject_unsafe("SELECT /* business_id */ * FROM merchant_orders", SCHEMA, require_business_id=True)


def test_字符串字面量伪装谓词拒():
    with pytest.raises(UnsafeSqlError, match="缺租户谓词"):
        reject_unsafe(
            "SELECT 'business_id' AS claim FROM merchant_orders", SCHEMA, require_business_id=True
        )


def test_绑定参数不算谓词_同名表不算谓词():
    """表名恰为 business_id(白名单内)也救不了:谓词断言只认列引用节点。"""
    with pytest.raises(UnsafeSqlError, match="缺租户谓词"):
        reject_unsafe(
            "SELECT * FROM business_id WHERE x = :business_id",
            {"tables": {"business_id": {}, "merchant_orders": {}}},
            require_business_id=True,
        )


def test_CTE内列引用算谓词():
    sql = "WITH scoped AS (SELECT * FROM merchant_orders WHERE business_id = :business_id) SELECT * FROM scoped"
    assert reject_unsafe(sql, SCHEMA, require_business_id=True) is None
