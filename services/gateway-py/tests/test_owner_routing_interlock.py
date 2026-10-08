"""「该找谁」责任人路由 —— 种子互验闸(spec .scratch/owner-routing §1.3)。

纯静态互验(零 DB):商户库 owner_mappings 种子的三份事实源必须互相咬合 ——
1. metrics.yaml 39 键**每一条**都有域映射(dbt 必填 owner 启示:新增指标不配
   责任人即红,防「该找谁」对部分指标哑火);
2. semantic_model 品类枚举全覆盖(种子 6 类 ⊆ 枚举 9 值,CRUD 新品类即有主);
3. 全部 staff_id ∈ STAFF_SEED_ROSTER(跨库无 FK,引用靠同册 + 本闸兜底)。
播种时的行数断言(db:seed 假绿防线)与运行时解析降级在各自册另钉。
"""

from engine_py.analytics.rbac import STAFF_SEED_ROSTER
from engine_py.analytics.tools_registry_bridge import metric_semantic_registry, semantic_model

from gateway_py.merchant_seed import _category_owners, _metric_owners


class TestMetricOwnerCompleteness:
    """互验闸一:39 指标全员有主(Q6 裁决:全灌,不许缺行)。"""

    def test_every_metric_has_owner(self):
        owners = _metric_owners()
        missing = set(metric_semantic_registry()) - set(owners)
        assert not missing, f"指标未配责任人(新增指标须配 _DOMAIN_OWNER 或 sales 轮转):{sorted(missing)}"

    def test_no_orphan_metric_owner(self):
        extra = set(_metric_owners()) - set(metric_semantic_registry())
        assert not extra, f"映射引用了不存在的指标(指标退役后映射须同批清理):{sorted(extra)}"


class TestCategoryOwnerCoverage:
    """互验闸二:品类枚举全覆盖(语义模型单一事实源)。"""

    def test_every_category_has_owner(self):
        owners = _category_owners()
        missing = set(semantic_model()["dimensions"]["category"]["values"]) - set(owners)
        assert not missing, f"品类未配责任人:{sorted(missing)}"


class TestStaffReferenceIntegrity:
    """互验闸三:staff_id 全员 ∈ 员工名册(跨库无 FK 的引用兜底)。"""

    def test_all_owner_staff_in_roster(self):
        roster_ids = {row[0] for row in STAFF_SEED_ROSTER}
        referenced = set(_metric_owners().values()) | set(_category_owners().values())
        orphan = referenced - roster_ids
        assert not orphan, f"映射引用了名册外员工:{sorted(orphan)}"

    def test_seed_promotion_creators_in_roster(self):
        """演示活动创建人也必须在册(Q14 数据原生链路的种子面)。"""
        roster_ids = {row[0] for row in STAFF_SEED_ROSTER}
        assert {"staff_ops_lead", "staff_sales_1"} <= roster_ids
