"""动作注册表契约册(ADR-0015 批一)。

① 商户台白名单收口(实弹①):未知/空动作 400 诚实报错 —— 此前本面无白名单,
  未知动作直透引擎落 next_status="rejected" 初值兜底 = 真实退款工单被静默
  驳回;现与 admin/SPI 两面同律(本册负例;正控 = 既有册合法裁决照常 200)。
② 三面词表与本体生成物逐成员相等(受理集单一事实源 = ontology actions.yaml;
  引擎受理集 = SPI 面现行口径)。
③ permission 锚真实性:动作声明的 perm 码必须存在于 rbac 种子面(防拼写漂移;
  DB 级闭包断言随批三 CI 门升级)。
"""

from __future__ import annotations

import inspect
import uuid

import pytest


class TestMerchantFaceWhitelist:
    pytestmark = pytest.mark.usefixtures("staff_auth")

    async def test_unknown_action_is_400(self, client, staff_auth):
        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": str(uuid.uuid4()), "action": "definitely_not_an_action"},
            headers=staff_auth,
        )
        assert res.status_code == 400, res.text
        body = res.json()
        assert body["success"] is False
        assert "未知审批动作" in body["error"]

    async def test_blank_action_is_400(self, client, staff_auth):
        res = await client.post(
            "/api/admin/approvals",
            json={"approvalId": str(uuid.uuid4()), "action": "   "},
            headers=staff_auth,
        )
        assert res.status_code == 400, res.text
        assert res.json()["success"] is False


class TestRegistryParity:
    def test_gateway_vocab_derived_from_ontology(self):
        from engine_py.ontology_generated import (
            CUSTOMER_ACTIONS,
            ENGINE_HANDLED_ACTIONS,
            OPERATOR_ACTIONS,
            SPI_ACTIONS,
            STAFF_REVIEW_ACTIONS,
        )

        from gateway_py.approval_actions import (
            CUSTOMER_ACTIONS as gw_customer,
        )
        from gateway_py.approval_actions import (
            OPERATOR_ACTIONS as gw_operator,
        )
        from gateway_py.approval_actions import (
            SPI_ACTIONS as gw_spi,
        )
        from gateway_py.approval_actions import (
            STAFF_REVIEW_ACTIONS as gw_staff,
        )

        assert gw_customer == CUSTOMER_ACTIONS
        assert gw_operator == OPERATOR_ACTIONS
        assert gw_staff == STAFF_REVIEW_ACTIONS
        assert gw_spi == SPI_ACTIONS
        # 现行口径:三面曝光并集 = 引擎受理集(声明派生,非抄写)
        assert gw_spi == ENGINE_HANDLED_ACTIONS

    def test_action_permissions_exist_in_rbac_seed(self):
        from engine_py.analytics import rbac
        from engine_py.ontology_generated import APPROVAL_ACTIONS

        seed_source = inspect.getsource(rbac)
        for name, spec in APPROVAL_ACTIONS.items():
            if spec.get("permission") is not None:
                quoted = f'"{spec["permission"]}"'
                assert quoted in seed_source, (
                    f"动作 {name} 声明的 permission {spec['permission']} 不在 rbac 种子面 —— 声明层拼写漂移"
                )
