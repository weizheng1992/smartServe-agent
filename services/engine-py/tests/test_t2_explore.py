"""T2 探索通道契约(ADR-0010;spec §6)。

双闸(env ∧ 角色)/ 守卫链(单语句/LIMIT 强制/模型表白名单/统一安全闸)/
失败响亮回落。生成面(generate_sql)需真模型,由 T2 评测门覆盖(spec §7)。
"""

from __future__ import annotations

import pytest

from engine_py.analytics.t2_explore import ExploreRejected, enabled_for, guard_explore_sql


class TestT2Gate:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("AI_T2_EXPLORE", raising=False)
        assert enabled_for("admin") is False

    def test_env_on_admin_allowed(self, monkeypatch):
        monkeypatch.setenv("AI_T2_EXPLORE", "on")
        assert enabled_for("admin") is True
        assert enabled_for("finance_owner") is True

    def test_env_on_viewer_rejected(self, monkeypatch):
        """角色白名单:admin/finance_owner 先行灰度(ADR-0010 决议 5)。"""
        monkeypatch.setenv("AI_T2_EXPLORE", "on")
        assert enabled_for("sales_viewer") is False
        assert enabled_for("warehouse_operator") is False
        assert enabled_for(None) is False

    def test_env_off_blocks_even_admin(self, monkeypatch):
        monkeypatch.setenv("AI_T2_EXPLORE", "off")
        assert enabled_for("admin") is False


class TestExploreGuard:
    def test_strips_markdown_fence(self):
        sql = guard_explore_sql("```sql\nSELECT title FROM merchant_spus LIMIT 10\n```")
        assert sql.startswith("SELECT") and "LIMIT" in sql

    def test_missing_limit_is_injected(self):
        sql = guard_explore_sql("SELECT title FROM merchant_spus")
        assert "LIMIT" in sql and "50" in sql

    def test_limit_clamped_to_fifty(self):
        sql = guard_explore_sql("SELECT title FROM merchant_spus LIMIT 500")
        assert "500" not in sql

    def test_multi_statement_rejected(self):
        """首分号截断(16 号票)后语义:仅首语句进守卫,尾随语句视同尾注丢弃;
        常量多语句由常量查询闸拒绝(执行面永不触达第二条)。"""
        with pytest.raises(ExploreRejected, match="事实表"):
            guard_explore_sql("SELECT 1; SELECT 2")
        sql = guard_explore_sql("SELECT title FROM merchant_spus LIMIT 3; SELECT 1")
        assert sql.startswith("SELECT") and "; SELECT 1" not in sql

    def test_non_select_rejected(self):
        """非查询语句(无 SELECT/WITH 可提取)响亮拒绝;文案区分「空生成」与
        「生成了非查询语句」。"""
        with pytest.raises(ExploreRejected, match="未包含 SELECT"):
            guard_explore_sql("DELETE FROM merchant_spus")

    def test_engine_db_table_rejected(self):
        """engine 库实体不可达(租户谓词面简化,ADR-0010 新增不变量 3)。"""
        with pytest.raises(ExploreRejected, match="表白名单外"):
            guard_explore_sql("SELECT COUNT(*) FROM session_metrics LIMIT 10")

    def test_hallucinated_table_rejected(self):
        with pytest.raises(ExploreRejected, match="表白名单外"):
            guard_explore_sql("SELECT * FROM orders_archive LIMIT 10")

    def test_dangerous_function_rejected(self):
        with pytest.raises(ExploreRejected, match="安全闸"):
            guard_explore_sql("SELECT pg_sleep(10) FROM merchant_spus LIMIT 1")

    def test_cte_query_passes(self):
        sql = guard_explore_sql(
            "WITH t AS (SELECT category, SUM(stock) AS s FROM merchant_skus k "
            "JOIN merchant_spus s2 ON s2.id = k.spu_id GROUP BY category) "
            "SELECT * FROM t ORDER BY s DESC LIMIT 5"
        )
        assert sql.upper().startswith("WITH")

    def test_empty_generation_rejected(self):
        with pytest.raises(ExploreRejected, match="为空"):
            guard_explore_sql("```sql\n```")

    def test_non_literal_limit_rejected(self):
        with pytest.raises(ExploreRejected, match="字面整数"):
            guard_explore_sql("SELECT title FROM merchant_spus LIMIT :n")

    def test_constant_query_rejected(self):
        """常量查询盲区(eval-gap-2026-10 16):写请求/闲聊在 generate 域外拒答
        纪律缺位时,LLM 偶发产出无事实表的合法废话查询 —— 结构闸须拒,不能只
        赌生成层拒答。"""
        with pytest.raises(ExploreRejected, match="事实表"):
            guard_explore_sql("SELECT '' LIMIT 1")
        with pytest.raises(ExploreRejected, match="事实表"):
            guard_explore_sql("SELECT ' weather' AS message LIMIT 1")

    def test_cte_over_real_table_passes(self):
        """CTE 锚定真实表白名单时不受常量查询闸影响(只拦零事实表查询)。"""
        sql = guard_explore_sql(
            "WITH top AS (SELECT title FROM merchant_spus LIMIT 5) SELECT * FROM top"
        )
        assert "merchant_spus" in sql

    def test_trailing_prose_after_semicolon_cut(self):
        """首分号截断(16 号票):模型尾注接在分号后,旧序整条进解析器被
        「引号外中文散文」误杀 —— 截断后合法 SQL 存活。"""
        sql = guard_explore_sql(
            "SELECT title FROM merchant_spus LIMIT 5; 以上查询对比了两个品类的退货情况"
        )
        assert "merchant_spus" in sql and "以上" not in sql

    def test_cjk_alias_bare_reference_in_order_by(self):
        """中文别名裸引用(16 号票 live 实弹:ORDER BY 退款单数)非 Alias 节点,
        只扫 Alias 漏引号化 → 引号外中文误杀 —— 通用 Identifier 遍历覆盖。"""
        sql = guard_explore_sql(
            "SELECT s.category AS 品类, COUNT(o.order_id) AS 退款单数 "
            "FROM merchant_orders o GROUP BY s.category ORDER BY 退款单数 DESC LIMIT 10"
        )
        assert '"品类"' in sql and '"退款单数"' in sql
