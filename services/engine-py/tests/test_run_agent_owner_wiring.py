"""run_agent → 中断登记表的 owner 接线钉面(S2b,stream-reliability-push 03)。

背景:owner 接线曾在实验性 checkout 中丢失(gateway WIP 隔离的副作用,工作区
未提交改动被 checkout HEAD 覆写),生产面 _job_owners 恒空 → 真实在途作业取消
一律 404「不存在或已结束」(谎报明明在跑),403 属主闸成死码 —— 网关闸单测全靠
手工 register_run 造数,恰好绕开真派发路径,「全量绿」对本缺陷盲。本钉面把
「run_agent 派发必须以权威租户:用户身份记 owner」变成显式契约,接线再断即红。

桩:build_graph 换 astream 协议假图;publish_agent_event 桩(免 Redis);
消息「查订单」恰 3 字 → 预取 embedding 与三路检索整段跳过,零外联。
"""

from __future__ import annotations

import asyncio
import importlib

import pytest


@pytest.mark.usefixtures("pg_factory")
def test_run_agent_registers_dispatch_owner(monkeypatch, pg_factory):
    from engine_py import interruption

    module = importlib.import_module("engine_py.run_agent")
    captured: dict = {}
    real_register = interruption.register_run

    def spy_register(job_id, owner=None):
        captured["job_id"] = job_id
        captured["owner"] = owner
        return real_register(job_id, owner)

    monkeypatch.setattr(module, "register_run", spy_register)

    async def _noop_publish(job_id, kind, payload):
        return None

    monkeypatch.setattr(module, "publish_agent_event", _noop_publish)

    class _OwnerGraph:
        """astream 协议假图:健康终态,驱动 run_agent 走完整收口。"""

        async def astream(self, state, stream_mode=None):
            yield state
            yield {
                **state,
                "output": "好的,已为您处理。",
                "task_plan": {"goal": "订单查询", "subtasks": [], "currentStepIndex": 0},
                "intents": [],
            }

    monkeypatch.setattr(module, "build_graph", lambda: _OwnerGraph())

    job = module.AgentJobInput(
        jobId="job_owner_wiring",
        threadId="thr_owner_wiring",
        userId="CUST-OWN",
        businessId="Aurora",  # 刻意带大写:记账侧必须归一(比对侧网关归一入参)
        message="查订单",
    )
    final = asyncio.run(module.run_agent(job))

    assert captured["job_id"] == "job_owner_wiring"
    # 记账侧归一:权威租户小写 strip + 用户精确 —— 与网关比对口径对称
    assert captured["owner"] == "aurora:CUST-OWN"
    assert final["output"] == "好的,已为您处理。"
    # 收口后作业注销(peek 打不中,防泄漏)
    assert interruption.peek_job_owner("job_owner_wiring") is None
