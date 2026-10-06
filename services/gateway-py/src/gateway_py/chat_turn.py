"""一回合顾客消息受理(chat.py 与 merchant.py 两入口的共享编排,A3 收口 2026-10-06)。

受理脊:用户行落库(005 治理:用户行唯一归网关)→ P1 AI 暂停闸(接管期不建
作业不调 LLM,用户消息照常落库;文案分形见 takeover.paused_gate)→ 构建
AgentJobInput → run_agent(sync 直跑 / 后台任务两形态)。

刻意不收口(通道语义,留路由):消息校验(chat 要求文本;store 允许仅图)、
注册闸(ensure_tenant_registered 仅商户面)、响应信封形状(chat 的
isHumanActive/sync 降级文案;store 的 messageId + 顾客 SSE 发布)、用户行
归网关之上的租户细节。异常自然上抛,各路由按通道语义映射
(chat sync 兜降级道歉;store 外层 500 信封)。
"""

from __future__ import annotations

import asyncio
import time
import uuid

from engine_py.approvals import takeover
from engine_py.run_agent import AgentJobInput, run_agent

from . import conversation_repo


def generate_job_id(hex_len: int = 9) -> str:
    return f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:hex_len]}"


async def accept_chat_turn(
    *,
    thread_id: str,
    user_id: str,
    business_id: str,
    message: str,
    image_urls: list[str] | None = None,
    store_cart: list[dict] | None = None,
    sync: bool = True,
    job_id: str | None = None,
) -> dict:
    """受理一回合:落用户行 → 暂停闸 → 跑引擎。

    返回 {"paused", "jobId", "output", "cards", "state"}:
    - paused=True 时 jobId 为空串、state 为 None(output = 暂停闸文案);
    - sync=False 时仅受理(后台任务),output/cards 为空、state 为 None;
    - sync=True 且非 paused 时 state 为 run_agent 终态(调用方可取 cards 等)。
    异常自然上抛,通道错误语义留路由。
    """
    job_id = job_id or generate_job_id()

    await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": business_id,
            "userId": user_id,
            "role": "user",
            "content": message,
            "imageUrls": image_urls,
        }
    )

    paused, paused_output = await takeover.paused_gate(thread_id)
    if paused:
        return {"paused": True, "jobId": "", "output": paused_output or "", "cards": [], "state": None}

    job = AgentJobInput(
        jobId=job_id,
        threadId=thread_id,
        userId=user_id,
        businessId=business_id,
        message=message,
        imageUrls=image_urls or [],
        storeCart=store_cart or [],
    )
    if not sync:
        asyncio.create_task(run_agent(job))
        return {"paused": False, "jobId": job_id, "output": "", "cards": [], "state": None}

    state = await run_agent(job)
    return {
        "paused": False,
        "jobId": job_id,
        "output": state.get("output") or "",
        "cards": state.get("cards") or [],
        "state": state,
    }
