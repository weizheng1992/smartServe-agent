"""回归:CartManageSkill.execute 各分支不得经 self. 访问模块级正则常量。

背景 bug(2026-09-04 生产日志):
[Triage Slot-Clarification Exception]: 'CartManageSkill' object has no attribute '_VIEW_ONLY_RE'
_VIEW_ONLY_RE 等五个正则为模块级常量,execute() 内误用 self. 前缀访问,
导致任何购物车输入都在 Step 1.5 快车道抛 AttributeError,整段分流被吞。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart_manage_skill import CartManageSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_FAKE_CART = {
    "cart": {
        "items": [{"skuId": "sku_a", "title": "测试商品A", "price": 100, "quantity": 1}],
        "totalQuantity": 1,
        "totalAmount": 100,
        "payableAmount": 100,
    }
}


def _stub_mall(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_summary(payload: dict) -> dict:
        return _FAKE_CART

    async def fake_update(payload: dict) -> dict:
        return _FAKE_CART

    monkeypatch.setattr(MallDomainService, "get_cart_summary", staticmethod(fake_summary))
    monkeypatch.setattr(MallDomainService, "update_cart_item", staticmethod(fake_update))


@pytest.mark.parametrize(
    ("user_input", "branch"),
    [
        ("查看购物车", "view"),  # 命中 self._VIEW_ONLY_RE(bug 首爆点)
        ("删除第1件", "delete"),  # 命中 self._DELETE_RE / self._CLEAR_RE 判定链
        ("清空购物车", "clear"),  # 命中 self._CLEAR_RE
        ("把第1件数量改成2", "qty"),  # 数量修改分支(模块级 _QTY_UPDATE_RE,回归护栏)
    ],
)
def test_execute_branches_succeed(user_input: str, branch: str, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_mall(monkeypatch)
    skill = CartManageSkill()

    async def run() -> dict:
        # bug 时此处抛 AttributeError: 'CartManageSkill' object has no attribute '_VIEW_ONLY_RE'
        return await skill.execute({"input": user_input, "userId": "u1", "threadId": "t1"})

    res = asyncio.run(run())
    assert res["success"] is True, f"branch={branch}"
