"""咨询直答 prompt 的信任边界回归(2026-09-26 帐篷表格历史投毒实弹)。

症状:thread 历史里躺着一轮旧幻觉答案(「帐篷A款 ¥399/B款 ¥699/C款 ¥899」,
货架切片挂错租户时代的产物)。次日用户问「几个帐篷的特点和价格对比,给一个
表格」,consult 直答(rag_direct)把该行原样缝进新表 —— RAG 已给真货
(极光帐篷 ¥1299/¥1499),答案却混合 399/699/899 幻觉行。

差分重放实锤(/tmp 环,limit=2 对齐产线):事故 prompt(毒行在场)5/10
逐字复刻 A/B/C 款,毒行换诚实答案后 0/10 —— 缝合点 =
answer_consult_from_rag 的 [RECENT CONVERSATION] 装配无信任边界。

本套钉死 prompt 契约:历史块必须显式标注「未验证记忆」,商品名/型号/
价格只准从 RAG 摘录逐字引用;「要对比多款而摘录不足」时只出摘录内条目,
严禁拿记忆或编造填表。
"""

from __future__ import annotations

import asyncio


class _CapturingChatModel:
    """捕获 prompt 的假聊天模型:answer_consult_from_rag 只消费 .ainvoke().content。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def ainvoke(self, prompt: str):
        self.prompts.append(prompt)

        class _Resp:
            content = "（捕获响应）知识库未见相关内容，需转人工核实。"

        return _Resp()


def _build_prompt(monkeypatch) -> tuple[str, _CapturingChatModel]:
    import engine_py.triage.consult_fast_path as cfp

    fake = _CapturingChatModel()
    monkeypatch.setattr(cfp, "get_chat_model", lambda: fake)

    history = [
        {"role": "user", "content": "几个帐篷的特点和价格对比"},
        # 真实 10:37 幻觉行(节选, 与库中逐字一致的核心段)
        {
            "role": "assistant",
            "content": (
                "1. 极光帐篷A款：\n   - 特点：轻便便携，适合短期户外露营。\n   - 价格：¥399元。\n"
                "2. 极光帐篷B款：\n   - 特点：防水防风，空间较大，适合家庭使用。\n   - 价格：¥699元。"
            ),
        },
        {"role": "user", "content": "给一个表格显示"},
    ]
    rag_docs = [
        {
            "chunkText": "商品名：极光 轻量化双人双层露营帐篷 20D硅涂尼龙外帐防水3000mm，双人 ¥1299.00，三人 ¥1499.00",
            "contextualSummary": "商品知识：极光 轻量化双人双层露营帐篷",
        }
    ]
    answer = asyncio.run(cfp.answer_consult_from_rag("几个帐篷的特点和价格对比，给一个表格", rag_docs, history, "极光潮品官方旗舰店"))
    assert answer, "直答须返回捕获响应"
    assert len(fake.prompts) == 1
    return fake.prompts[0], fake


class TestConsultPromptTrustBoundary:
    def test_history_block_is_labeled_unverified(self, monkeypatch):
        """历史块必须显式标注未验证 —— 裸 [RECENT CONVERSATION] 被模型当事实源。"""
        prompt, _ = _build_prompt(monkeypatch)
        assert "RECENT CONVERSATION" in prompt, "历史块标签不得更名(定位依据)"
        assert "UNVERIFIED" in prompt.upper(), "历史块必须显式标注未验证记忆"

    def test_catalog_facts_must_come_verbatim_from_excerpts(self, monkeypatch):
        """商品名/型号/价格只准摘录逐字引用 —— 幻觉行经历史搬运的通道封死。"""
        prompt, _ = _build_prompt(monkeypatch)
        assert "NEVER copy" in prompt, "必须明令禁止从历史复制商品事实"
        assert "verbatim" in prompt.lower(), "必须要求商品与价格逐字出自摘录"

    def test_presupposition_gap_fills_no_rows(self, monkeypatch):
        """要对比多款而摘录不足:只出摘录内条目,严禁填表式编造。"""
        prompt, _ = _build_prompt(monkeypatch)
        assert "NOT fill" in prompt or "do not fill" in prompt.lower(), "必须明令禁止拿记忆/编造补齐表格行"

    def test_history_and_excerpts_still_reach_the_prompt(self, monkeypatch):
        """信任边界不得矫枉过正:历史上下文与 RAG 摘录仍须在场(连续性/接地素材)。"""
        prompt, _ = _build_prompt(monkeypatch)
        assert "极光帐篷A款" in prompt, "历史上下文仍须进入 prompt(连续性依赖)"
        assert "轻量化双人双层露营帐篷" in prompt, "RAG 摘录仍须进入 prompt(接地素材)"
        assert "¥1299.00" in prompt and "¥399元" in prompt


if __name__ == "__main__":
    import pytest

    pytest.main([__file__])
