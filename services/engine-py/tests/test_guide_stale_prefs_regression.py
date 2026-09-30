"""导购偏好跨题陈旧回归(2026-09-30 实弹「我是新的问题，还带有2500」)。

症状链:同 thread 昨日「金额不超过2500」的预算经 task_memory.guideContext
承接进今日「我喜欢黑色，推荐出去游玩的衣服和背包」的推荐语，「已结合您的
偏好：¥2500以内、黑色」把昨日预算当今日依据宣布。而累积偏好面对检索零参与
(search_products 只吃本轮 max_price 与原始 query)—— 承接的旧偏好出现在
「已结合」句里就是广告出没有发生的结合。

钉死契约:「已结合您的偏好」只列本轮输入实际说出的偏好(相对承接面的新增/
改写);承接面仍照旧累积入库(is_very_vague 连续性依赖),但严禁上展示句,
也严禁折进检索参数。
"""

from __future__ import annotations

import asyncio

import pytest

from engine_py.skills.contract import SkillContext
from engine_py.skills.guide_skills import ShoppingGuideSkill
from engine_py.tools_registry.mall_domain import MallDomainService

_PRODUCTS = [
    {
        "id": "b1", "name": "极光 高山徒步轻量化背包 38L", "price": 829.0,
        "stock": 71, "description": "徒步背包", "specs": {}, "category": "backpack",
    },
    {
        "id": "c1", "name": "极光 速干透气防晒衬衫", "price": 199.0,
        "stock": 30, "description": "户外衬衫", "specs": {}, "category": "apparel",
    },
]

_STALE_GUIDE = {
    "extractedPreferences": {"budget": "¥2500以内", "color": "黑色"},
    "clarificationRound": 3,
    "lastSearchQuery": "我打算出去旅行，给我搭配一套出去旅行的装备和衣服，按照现在的季节，金额不超过2500",
}

_NEW_QUESTION = "我喜欢黑色，推荐出去游玩的衣服和背包"


def _run(user_input: str, guide_context: dict) -> tuple[object, list[dict]]:
    calls: list[dict] = []

    async def fake_search(params: dict) -> dict:
        calls.append(params)
        return {"total": len(_PRODUCTS), "products": _PRODUCTS}

    async def fake_overview() -> list[dict]:
        return []

    original_search = MallDomainService.search_products
    original_overview = MallDomainService.get_shelf_overview
    MallDomainService.search_products = staticmethod(fake_search)
    MallDomainService.get_shelf_overview = staticmethod(fake_overview)
    try:
        res = asyncio.run(
            ShoppingGuideSkill().execute(
                SkillContext(
                    input=user_input,
                    guide_context=guide_context,
                    thread_id="t_stale_prefs",
                    tenant_id="ecommerce",
                )
            )
        )
    finally:
        MallDomainService.search_products = staticmethod(original_search)
        MallDomainService.get_shelf_overview = staticmethod(original_overview)
    return res, calls


class TestGuideStalePrefsRegression:
    def test_new_question_does_not_echo_stale_budget(self) -> None:
        """实弹句:新问题不得把昨日预算宣进「已结合您的偏好」,也不得折进检索。"""
        res, calls = _run(_NEW_QUESTION, dict(_STALE_GUIDE))
        assert "已结合您的偏好：黑色" in res.output, (
            f"本轮实际说出的只有颜色,展示句应只含黑色,实际:{res.output[:120]}"
        )
        assert "2500" not in res.output, f"昨日预算严禁再上展示句,实际:{res.output[:120]}"
        assert calls, "技能路径必须发起检索"
        assert calls[0].get("maxPrice") is None, (
            f"承接预算严禁折进检索参数(本轮未说预算),实际:{calls[0]}"
        )

    def test_carried_sheet_still_accumulates_for_continuity(self) -> None:
        """修复是展示诚实,不是清空记忆:承接面照旧入库(is_very_vague 连续性)。"""
        res, _ = _run(_NEW_QUESTION, dict(_STALE_GUIDE))
        written = (res.guide_context or {}).get("extractedPreferences") or {}
        assert written.get("budget") == "¥2500以内"
        assert written.get("color") == "黑色"

    def test_current_turn_budget_still_displayed_and_filters(self) -> None:
        """多轮正例:本轮说出的预算照常展示并真实折进检索。"""
        res, calls = _run(
            "推荐背包，预算1000",
            {"extractedPreferences": {"color": "黑色"}, "clarificationRound": 2},
        )
        assert "已结合您的偏好：¥1000以内" in res.output, res.output[:120]
        assert calls and calls[0].get("maxPrice") == 1000

    def test_restated_pref_with_same_value_still_displayed(self) -> None:
        """本轮重述承接同值偏好(「我喜欢黑色」而承接面已有黑色)仍须上展示句
        —— 判据是「本轮是否说出」,不是「值是否变化」。"""
        res, _ = _run(_NEW_QUESTION, dict(_STALE_GUIDE))
        assert "已结合您的偏好：黑色" in res.output, res.output[:120]

    def test_no_current_turn_prefs_no_pref_line(self) -> None:
        """本轮零新增偏好 → 干脆不出偏好句,严禁拿承接面充数。"""
        res, _ = _run("推荐一些背包", dict(_STALE_GUIDE))
        assert "已结合您的偏好" not in res.output, res.output[:120]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
