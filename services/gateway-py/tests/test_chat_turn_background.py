"""后台受理任务持有表回归(async-1 作业蒸发收口,2026-10-18):
sync=False 的受理此前即弃 create_task —— 引擎图前段(DB/检索)异常逃逸成
GC 时的「Task exception was never retrieved」,SSE 流侧只见心跳挂死到客户端
断连,且 jobId 无法对账。本册钉三件事:

1. 强引用持有:任务在 _ASYNC_TURNS 里,GC 不可中断;
2. done 回调自清:任务结束即出表;
3. 终局帧兜底:异常逃逸时注入合成 result 帧(degraded 诚实降级文案)——
   tail 只认 result 终局,据此诚实收口而非心跳挂死。
"""

from __future__ import annotations

import asyncio
import uuid as _uuid

from engine_py.event_bus import read_agent_events

from gateway_py.chat_turn import _ASYNC_TURNS, accept_chat_turn


async def test_background_turn_failure_publishes_terminal_frame(client, contract_fixtures, monkeypatch):
    async def _boom(job):
        raise RuntimeError("图前段爆炸(测试注入)")

    monkeypatch.setattr("gateway_py.chat_turn.run_agent", _boom)
    job_id = f"job_evaporate_{_uuid.uuid4().hex[:8]}"
    out = await accept_chat_turn(
        thread_id=f"evaporate_{job_id}",
        user_id="CUST-CT-EVAP",
        business_id="aurora",
        message="触发图前段异常",
        sync=False,
        job_id=job_id,
    )
    assert out["jobId"] == job_id
    assert out["paused"] is False

    # 任务抛错 → done 回调 → 再 create_task 注入终局帧:让循环跑几拍
    for _ in range(5):
        await asyncio.sleep(0.02)

    events = await read_agent_events(job_id)
    terminal = [e for e in events if e["type"] == "result"]
    assert terminal, f"终局帧必须注入(SSE 流据此收口): {events}"
    assert terminal[-1]["data"].get("degraded") is True
    assert "中断" in (terminal[-1]["data"].get("output") or "")
    # 自清:表内不得残留未完成任务
    assert all(t.done() for t in _ASYNC_TURNS)
