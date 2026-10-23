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
from typing import TypedDict

from engine_py.approvals import takeover
from engine_py.interruption import peek_job_owner, request_cancel
from engine_py.run_agent import AgentJobInput, run_agent

from . import conversation_repo, quota

# 后台受理任务持有表(async-1 作业蒸发收口,2026-10-18):asyncio 对 task 是
# 弱引用 —— 即弃 create_task 可被 GC 中途打断,异常无人 retrieve 只在 GC 时
# 打一条「Task exception was never retrieved」。强引用 + done 回调:自清、
# 异常带 jobId 留痕、并注入合成 result 帧让 SSE 流诚实收口(tail 只认 result
# 终局,不注入则流侧心跳挂死到客户端断连)。analytics ask 面 _ASK_PRODUCERS
# 同款机制(其对照在对抗核验 stream-5 中成立)。
_ASYNC_TURNS: set[asyncio.Task] = set()
_TURN_DEGRADED_OUTPUT = "抱歉,本次回答中断了,请稍后重试。"


async def _emit_terminal_frame(job_id: str) -> None:
    """终局帧兜底:仅图前段异常逃逸时注入(引擎图内异常自带降级 result 帧)。"""
    try:
        from engine_py.event_bus import publish_agent_event

        await publish_agent_event(
            job_id,
            "result",
            {"output": _TURN_DEGRADED_OUTPUT, "cards": [], "degraded": True},
        )
    except Exception as err:
        print(f"[ChatTurn] 后台受理作业 {job_id} 终局帧注入失败: {err}")


def _on_background_turn_done(job_id: str):
    def _cb(task: asyncio.Task) -> None:
        _ASYNC_TURNS.discard(task)
        if task.cancelled():
            print(f"[ChatTurn] 后台受理作业 {job_id} 已取消(S2c)")
            return
        err = task.exception()
        if err is None:
            return
        print(f"[ChatTurn] 后台受理作业 {job_id} 异常逃逸: {err!r}")
        asyncio.get_running_loop().create_task(_emit_terminal_frame(job_id))

    return _cb


class ChatTurnResult(TypedDict):
    """受理脊返回契约(夜评 2026-10-07 smell 清尾):两路由(chat/merchant)与
    测试桩共以此为准 —— 旧五键裸 dict 无形状,键名拼错无检查。
    quotaCode:配额拒时携机读码(QUOTA_*),放行/暂停/正常轮为空串(2026-10-21 配额闸)。"""

    paused: bool
    jobId: str
    output: str
    cards: list
    state: dict | None
    quotaCode: str


def generate_job_id(hex_len: int = 9) -> str:
    return f"job_{int(time.time() * 1000)}_{uuid.uuid4().hex[:hex_len]}"


async def _emit_quota_rejection(job_id: str, verdict) -> None:
    """配额拒终局帧:result 是尾认终局帧(stop_on),quotaCode 增量键承载机器
    语义 —— web 异步臂在流上收;store/chat 同步臂走 POST 信封同码。写入失败
    只留痕不阻断(同步臂信封仍会送达)。"""
    try:
        from engine_py.event_bus import publish_agent_event

        await publish_agent_event(
            job_id,
            "result",
            {"output": verdict.message, "cards": [], "quotaCode": verdict.code},
        )
    except Exception as err:
        print(f"[ChatTurn] 配额拒终局帧写入失败 {job_id}: {err}")


def cancel_chat_job_gate(
    job_id: str,
    *,
    user_id: str | None,
    business_id: str | None,
) -> tuple[dict, int]:
    """取消闸(S2b):消费引擎中断原语(interruption),返回 (响应体, 状态码)。

    - 400 身份参数缺失:取消是写动作,严禁落到 dispatch 的缺省身份
      (CUST-8801/ecommerce)上 —— 否则缺省身份即可停任何人的作业;
    - 404 作业未知/已结束:审批挂起作业 run_agent 早已返回、不在活跃表,
      「审批挂起不可被停止误杀」构造性成立(HITL 边界,引擎侧同源钉面);
    - 403 属主不符:owner = 派发身份(引擎侧 register_run 记录的权威租户:
      用户),business 段归一大小写与空白(store 面 tenant 同口径),user 段
      精确 —— 多租户不变量 #1;
    - 409 peek 与 cancel 之间刚好结束(窗口竞态):防御性分支 —— 当前闸体无
      await、引擎派发同循环,构造性不可达;登记表 Redis 化(多实例化)后成真
      语义,保留以免那时谎报已受理;
    - 200 受理:引擎在下一个图检查点协作停止,终态 interrupted 走 result 帧
      (interrupted:true)照常收口 SSE 流(S2c 契约)。
    """
    if not user_id or not business_id:
        return {"success": False, "error": "userId 与 businessId 必填"}, 400
    owner = peek_job_owner(job_id)
    if owner is None:
        return {"success": False, "error": f"作业 {job_id} 不存在或已结束"}, 404
    owner_biz, _, owner_user = owner.partition(":")
    if owner_user != user_id.strip() or owner_biz != business_id.strip().lower():
        return {"success": False, "error": "作业不属于该用户,拒绝取消"}, 403
    if not request_cancel(job_id):
        return {"success": False, "error": f"作业 {job_id} 刚已结束,无需取消"}, 409
    return {"success": True, "jobId": job_id, "status": "cancelling"}, 200


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
    client_ip: str | None = None,
) -> ChatTurnResult:
    """受理一回合:暂停闸 → 配额闸 → 落用户行 → 跑引擎。

    返回 {"paused", "jobId", "output", "cards", "state", "quotaCode"}:
    - paused=True 时 jobId 为空串、state 为 None(output = 暂停闸文案);
    - 配额拒时 quotaCode 携机读码,用户行不落、作业不建(D9);
    - sync=False 时仅受理(后台任务),output/cards 为空、state 为 None;
    - sync=True 且非 paused 时 state 为 run_agent 终态(调用方可取 cards 等)。
    异常自然上抛,通道错误语义留路由。
    """
    job_id = job_id or generate_job_id()

    # 闸序(2026-10-21 配额闸):暂停闸先行 —— 接管期零 LLM 成本,不占问询
    # 额度,用户消息照常落库(接管语义不变);配额闸次之,拒的轮次不落用户行
    # (拒绝的问询不在历史里凭空出现)。
    paused, paused_output = await takeover.paused_gate(thread_id)
    if not paused:
        verdict = await quota.check_and_consume(
            user_id=user_id,
            business_id=business_id,
            client_ip=client_ip or "",
            job_id=job_id,
        )
        if not verdict.allowed:
            await _emit_quota_rejection(job_id, verdict)
            return {
                "paused": False,
                "jobId": job_id,
                "output": verdict.message,
                "cards": [],
                "state": None,
                "quotaCode": verdict.code,
            }

    saved_user_row = await conversation_repo.append_message(
        {
            "threadId": thread_id,
            "businessId": business_id,
            "userId": user_id,
            "role": "user",
            "content": message,
            "imageUrls": image_urls,
        }
    )
    # 坐席侧桥(2026-10-23):顾客 HTTP 消息落库即向坐席 socket 房间补发
    # new_message —— 坐席台开着的线程面板只靠该事件刷新,此前桥缺失致接管
    # 会话中顾客后续消息坐席全部「不显示了」。paused/常规两臂同覆盖;顾客
    # SSE 频道不补发(防顾客端双气泡),详见 realtime.broadcast_customer_message。
    from .realtime import broadcast_customer_message

    await broadcast_customer_message(thread_id, business_id, saved_user_row, message)

    if paused:
        return {"paused": True, "jobId": "", "output": paused_output or "", "cards": [], "state": None, "quotaCode": ""}

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
        task = asyncio.create_task(run_agent(job))
        _ASYNC_TURNS.add(task)
        task.add_done_callback(_on_background_turn_done(job_id))
        return {"paused": False, "jobId": job_id, "output": "", "cards": [], "state": None, "quotaCode": ""}

    state = await run_agent(job)
    return {
        "paused": False,
        "jobId": job_id,
        "output": state.get("output") or "",
        "cards": state.get("cards") or [],
        "state": state,
        "quotaCode": "",
    }
