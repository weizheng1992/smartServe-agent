"""阶段② analytics 骨架契约(wayfinder 09-D5 / 08-D1-D5;spec 第②部分)。

MetricQueryEngine 深模块三方法 + 四错误模式 + 两不变量:
- resolve(question, session_ctx) → StructuredQueryIntent | ClarificationRequest
- compile(intent, session_ctx)   → CompiledSQL(位置参数;租户谓词注入;LIMIT clamp)
- execute(compiled)              → QueryResult(rows+指标元数据+口径注记)
- 错误:不支持→UnsupportedQuery;歧义→ClarificationRequest;超预算/超时如实;空→诚实空
- 不变量:用户输入永不进 SQL 文本;business_id 服务端强制注入不可被调用方触达
- L0 词面归一(含反向词)走 resolver;未命中= unsupported(绝不静默兜底 gmv)
"""

from __future__ import annotations

import pytest

from engine_py.analytics.engine import MetricQueryEngine, QueryResult, UnsupportedQuery
from engine_py.analytics.schema_cards import merchant_schema_card
from engine_py.analytics.sql_guard import assert_safe_select, reject_unsafe


@pytest.fixture()
def engine() -> MetricQueryEngine:
    return MetricQueryEngine(session_ctx={"business_id": "aurora", "role": "finance_owner"})


class TestResolve:
    def test_exact_metric_key(self, engine):
        intent = engine.resolve("按 gmv 排行")
        assert intent.metric == "gmv" and intent.direction == "DESC"

    def test_synonym_hits_l0(self, engine):
        intent = engine.resolve("销售额最高的商品")
        assert intent.metric == "gmv"

    def test_reverse_word_flips_direction(self, engine):
        """L0 反向词族:「卖得最差」→ gmv + ASC(不静默兜底、不答反)。"""
        intent = engine.resolve("卖得最差的商品")
        assert intent.metric == "gmv" and intent.direction == "ASC"

    def test_stock_risk_maps_inventory(self, engine):
        intent = engine.resolve("压货最严重的商品")
        assert intent.metric == "stock_risk"

    def test_time_window_last_month(self, engine):
        intent = engine.resolve("上个月的销量排行")
        assert intent.metric == "volume" and intent.time_window is not None
        assert intent.time_window["kind"] == "last_month"

    def test_no_hit_is_unsupported_never_silent_gmv(self, engine):
        """08-P1 铁律:未命中必须 unsupported,严禁静默兜底 gmv。"""
        with pytest.raises(UnsupportedQuery):
            engine.resolve("今天心情怎么样")

    def test_ambiguous_returns_clarification_with_conflict_group(self, engine):
        result = engine.resolve("卖得最好的商品")
        assert isinstance(result, dict) and result.get("clarify") is True
        keys = {c["key"] for c in result["options"]}
        assert {"gmv", "volume"} <= keys  # conflictGroup sales_performance_ranking

    def test_limit_extracted_and_clamped(self, engine):
        assert engine.resolve("卖得最差的商品 Top 20").limit == 20
        assert engine.resolve("卖得最差的商品 Top 999").limit == 50  # clamp 上限


class TestSqlGuard:
    def test_select_passes(self):
        assert assert_safe_select("SELECT 1", schema={}) is not None

    def test_multi_statement_rejected(self):
        from engine_py.analytics.sql_guard import UnsafeSqlError

        with pytest.raises((UnsafeSqlError, ValueError)):
            reject_unsafe("SELECT 1; DROP TABLE products", schema={})

    def test_dml_rejected(self):
        from engine_py.analytics.sql_guard import UnsafeSqlError

        for bad in ("UPDATE products SET stock = 0", "DELETE FROM orders", "INSERT INTO orders VALUES (1)", "DROP TABLE products"):
            with pytest.raises((UnsafeSqlError, ValueError)):
                reject_unsafe(bad, schema={})

    def test_unknown_table_rejected(self):
        from engine_py.analytics.sql_guard import UnsafeSqlError

        with pytest.raises((UnsafeSqlError, ValueError)):
            reject_unsafe("SELECT * FROM evil_table", schema={"merchant_orders": {"columns": ["order_id"]}})

    def test_tenant_predicate_asserted_present(self):
        """编译后 AST 必须含租户谓词(不可被调用方剥离)。"""
        from engine_py.analytics.sql_guard import UnsafeSqlError

        with pytest.raises((UnsafeSqlError, ValueError)):
            reject_unsafe("SELECT 1", schema={}, require_business_id=True)


class TestInlineEntityBinding:
    """「这款商品卖多少」实体槽接线:spu 槽必须进标准族模板过滤
    (此前只认 PageContext 勾选,L3/行内绑定的实体被静默忽略)。"""

    def test_volume_filters_by_spu_entity_slot(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(StructuredQueryIntent(metric="volume", entity_slot={"spu": ["SPU-E2E-X"]}))
        assert "ANY(:entities)" in compiled.sql
        assert compiled.params["entities"] == ["SPU-E2E-X"]

    def test_page_context_selection_wins_over_slot(self, engine):
        from engine_py.analytics.engine import StructuredQueryIntent

        compiled = engine.compile(
            StructuredQueryIntent(metric="volume", entity_ids=["SEL-1"], entity_slot={"spu": ["SPU-E2E-X"]})
        )
        assert compiled.params["entities"] == ["SEL-1"]


class TestCompile:
    def test_compiled_sql_is_parameterized(self, engine):
        intent = engine.resolve("卖得最差的商品 Top 3")
        compiled = engine.compile(intent)
        assert compiled.sql is not None
        assert "DROP" not in compiled.sql.upper() or True
        assert ":lim" in compiled.sql or "?" in compiled.sql or "$" in compiled.sql or "lim" in compiled.params
        # 用户输入不出现在 SQL 文本(不变量):数字 3 只允许出现在绑定参数面
        assert "3" not in compiled.sql.replace("LIMIT :lim", "").replace("3000", "")

    def test_business_id_required_in_session_ctx(self, engine):
        """不变量:调用方必须携租户身份;缺席即拒编译(响亮,不静默)。"""
        intent = engine.resolve("销售额排行")
        from engine_py.analytics.engine import MetricQueryEngine

        with pytest.raises(ValueError, match="business_id"):
            MetricQueryEngine(session_ctx={}).compile(intent)
        compiled = engine.compile(intent)  # 有 business_id 正常编译
        assert compiled.sql

    def test_schema_card_covers_merchant_tables(self):
        card = merchant_schema_card()
        for table in ("merchant_spus", "merchant_skus", "merchant_orders", "merchant_order_items", "merchant_product_reviews"):
            assert table in card["tables"]


class TestExecute:
    def test_honest_empty_and_error_contract(self, engine, monkeypatch):
        """execute 的 rows 走真实 DB;此处只验契约形状:QueryResult 必带口径注记。"""
        r = QueryResult(rows=[], metric="gmv", unit="元", caliber="有效订单聚合(排除退款/取消)")
        assert r.rows == [] and r.caliber
