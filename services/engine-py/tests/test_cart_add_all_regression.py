"""回归:全量加购 —— "3个全部加入购物车"必须把全部候选商品入车。

背景 bug(2026-09-06 用户报告):
导购推荐 3 款商品后,用户说"3个全部加入购物车",实际只加入了 1 款。
CartManageSkill 加购分支仅解析单一目标 SKU(序数词或 candidate[0]),
无"全部/都"批量语义,导致 _cart_storage 只落地第一款。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.cart import CartManageSkill
from engine_py.skills.contract import SkillContext
from engine_py.tools_registry.mall_domain import MallDomainService

_CANDIDATES = [
    {"id": "prod_a", "name": "测试商品A", "price": 100.0},
    {"id": "prod_b", "name": "测试商品B", "price": 200.0},
    {"id": "prod_c", "name": "测试商品C", "price": 300.0},
]
_CANDIDATE_IDS = {c["id"] for c in _CANDIDATES}


def _run_skill(user_input: str, user_id: str = "u_addall") -> None:
    # 镜像 _try_skill_fast_track 的真实调用形状
    context = SkillContext(
        thread_id="t_addall",
        tenant_id="ecommerce",
        user_id=user_id,
        input=user_input,
        slots={"activeIntent": "cart_manage"},
        guide_context={
                "candidateProducts": _CANDIDATES,
                "candidateProductIds": sorted(_CANDIDATE_IDS),
            },
        cart_context={},
    )
    MallDomainService._cart_storage.pop(user_id, None)
    asyncio.run(CartManageSkill().execute(context)).to_dict()


@pytest.mark.parametrize(
    "user_input",
    [
        "3个全部加入购物车",
        "全部加入购物车",
        "三件都加入购物车",
        "把这3个都加入购物车",
        "都买了,全部加入购物车",
    ],
)
def test_add_all_phrasings_put_every_candidate_in_cart(user_input: str) -> None:
    _run_skill(user_input)
    items = MallDomainService._cart_storage.get("u_addall", [])
    landed = {i["skuId"] for i in items}
    assert landed == _CANDIDATE_IDS, f"input={user_input!r} 实际入车仅: {landed}"


def test_add_all_card_reflects_full_cart() -> None:
    _run_skill("3个全部加入购物车")
    items = MallDomainService._cart_storage.get("u_addall", [])
    assert sum(i["quantity"] for i in items) == 3, "全量加购后购物车总件数应为 3"
