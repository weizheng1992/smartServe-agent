"""结算线积分退回契约(2026-10-21 用量配额闸 D2,票 04)。

钉面:
- 降级道歉族(llm_quota_exhausted 等)→ refund_credit 被触发,余额真涨,台账
  落 refund 行;
- interrupted(用户主动停)不退;
- 重复结算同 job 不双退(refund 复合唯一索引兜底,第二笔幂等 False)。

缝测试:协作者全桩件(同 test_settle_turn_interrupted 模式),余额/台账以密封
PG 真表断言。
"""

from __future__ import annotations

import asyncio
import importlib
import uuid

import pytest

FAKE_TOKENS = 100


class _SettleStubs:
    def __init__(self) -> None:
        self.publish_calls: list[tuple] = []

    def patch(self, monkeypatch) -> None:
        module = importlib.import_module("engine_py.run_agent")
        stubs = self

        class ShortMemory:
            def __init__(self, thread_id, limit, business_id):
                pass

            async def add_message(self, role, content, cards=None):
                pass

        class LongMemory:
            def __init__(self, user_id, business_id):
                pass

            async def extract_and_store_fact(self, output, message):
                pass

        class EpisodicMemory:
            def __init__(self, user_id, business_id):
                pass

            async def add_event(self, summary, score):
                pass

        class TaskMemory:
            def __init__(self, thread_id):
                pass

            async def save_task_state(self, state):
                pass

        async def drain(thread_id):
            pass

        def take_total(thread_id):
            return FAKE_TOKENS

        async def badcase(source, **kw):
            pass

        async def claim(thread_id, business_id, output):
            pass

        async def publish(job_id, kind, payload):
            stubs.publish_calls.append((job_id, kind, payload))

        monkeypatch.setattr(module, "ShortMemory", ShortMemory)
        monkeypatch.setattr(module, "LongMemory", LongMemory)
        monkeypatch.setattr(module, "EpisodicMemory", EpisodicMemory)
        monkeypatch.setattr(module, "TaskMemory", TaskMemory)
        monkeypatch.setattr(module, "drain_llm_call_writes", drain)
        monkeypatch.setattr(module, "take_thread_token_total", take_total)
        monkeypatch.setattr(module, "record_badcase_signal", badcase)
        monkeypatch.setattr(module, "record_claim_mismatch_if_any", claim)
        monkeypatch.setattr(module, "publish_agent_event", publish)
        monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)


def _degraded_result(biz_suffix: str) -> dict:
    return {
        "thread_id": f"t-refund-{biz_suffix}",
        "user_id": "CUST-REFUND",
        "job_id": f"job-refund-{biz_suffix}",
        "input": "退货政策是什么",
        "business_config": {"businessId": "aurora"},
        "task_plan": {},
        "loop_count": 2,
        "intents": [],
    }


def _make_job(biz_suffix: str):
    module = importlib.import_module("engine_py.run_agent")
    return module.AgentJobInput(
        job_id=f"job-refund-{biz_suffix}",
        thread_id=f"t-refund-{biz_suffix}",
        user_id="CUST-REFUND",
        business_id="aurora",
        message="退货政策是什么",
    )


def _settle(stubs: _SettleStubs, result: dict, *, llm_quota_fired: bool, interrupted: bool = False):
    module = importlib.import_module("engine_py.run_agent")
    suffix = result["job_id"].removeprefix("job-refund-")
    return asyncio.run(
        module._settle_turn(
            result,
            job=_make_job(suffix),
            # 退回落账的 business_id 就是本参数 —— 测试用专属 biz 隔离,
            # 断言才不会被共享租户的既有账目污染
            business_id=f"refund_{suffix}",
            llm_breaker_fired=False,
            llm_quota_fired=llm_quota_fired,
            graph_error_fired=False,
            interrupted=interrupted,
            elapsed_latency_ms=42.0,
            saved_guide_context=None,
            saved_cart_context=None,
            saved_order_context=None,
        )
    )


def _balance(pg_factory, business_id: str) -> int | None:
    from engine_py.credits import get_balance

    async def _fetch():
        return await get_balance(business_id)

    return asyncio.run(_fetch())


def _seed_thread(suffix: str) -> None:
    """session_metrics.thread_id 有 FK —— 生产时序里 gateway 落用户行时已建线程,
    结算时线程恒存在;测试镜像该时序,否则 metrics 写失败连带跳过退回。"""
    module = importlib.import_module("engine_py.run_agent")
    asyncio.run(module._ensure_thread(f"t-refund-{suffix}", "CUST-REFUND", "aurora"))


@pytest.mark.usefixtures("pg_factory")
def test_quota_exhausted_turn_refunds_credit(monkeypatch, pg_factory):
    """额度快败(降级道歉族)→ 退 1:余额真涨 +1,台账 refund 行带 ref_job_id。"""
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)
    suffix = uuid.uuid4().hex[:8]
    biz = f"refund_{suffix}"
    _seed_thread(suffix)
    from engine_py.credits import consume_credit, recent_transactions

    async def _arrange():
        assert await consume_credit(biz, job_id=f"job-refund-{suffix}") is True

    asyncio.run(_arrange())
    before = _balance(pg_factory, biz)
    assert before == 999  # 初始 1000 - 1

    _settle(stubs, _degraded_result(suffix), llm_quota_fired=True)

    assert _balance(pg_factory, biz) == before + 1
    rows = asyncio.run(recent_transactions(biz))
    refund_rows = [r for r in rows if r["reason"] == "refund"]
    assert len(refund_rows) == 1 and refund_rows[0]["refJobId"] == f"job-refund-{suffix}"


@pytest.mark.usefixtures("pg_factory")
def test_interrupted_turn_does_not_refund(monkeypatch, pg_factory):
    """用户主动中断不退(自己的选择;且退回白名单不含 interrupted)。"""
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)
    suffix = uuid.uuid4().hex[:8]
    biz = f"refund_{suffix}"
    _seed_thread(suffix)
    from engine_py.credits import consume_credit

    asyncio.run(consume_credit(biz, job_id=f"job-refund-{suffix}"))
    before = _balance(pg_factory, biz)

    result = _degraded_result(suffix)
    result["task_plan"] = {
        "goal": "x",
        "subtasks": [{"id": "s1", "status": "pending", "result": {}}],
        "currentStepIndex": 0,
    }
    _settle(stubs, result, llm_quota_fired=False, interrupted=True)

    assert _balance(pg_factory, biz) == before, "中断轮不得触发退回"


@pytest.mark.usefixtures("pg_factory")
def test_double_settle_does_not_double_refund(monkeypatch, pg_factory):
    """同 job 二次结算(防御性重放)不双退:复合唯一索引兜底幂等。"""
    stubs = _SettleStubs()
    stubs.patch(monkeypatch)
    suffix = uuid.uuid4().hex[:8]
    biz = f"refund_{suffix}"
    _seed_thread(suffix)
    from engine_py.credits import consume_credit

    asyncio.run(consume_credit(biz, job_id=f"job-refund-{suffix}"))
    before = _balance(pg_factory, biz)

    _settle(stubs, _degraded_result(suffix), llm_quota_fired=True)
    _settle(stubs, _degraded_result(suffix), llm_quota_fired=True)

    assert _balance(pg_factory, biz) == before + 1, "二次结算不得双退"
