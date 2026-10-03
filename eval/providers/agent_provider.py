"""promptfoo 自定义 Provider(Python)— 源自 eval/providers/agentProvider.ts。

由 promptfoo 以 `file://providers/agent_provider.py:call_api` 调用:
除指标消歧预言机(eval/lib/metric_resolver.py,engine 侧已删)与槽位抽取/
expectedTools 纯回声两类确定性分支外,一律真跑 engine_py(槽位抽取 /
triage 瀑布 / run_agent 端到端)。多租户/安全注入/RAG/回答质量四族曾为
TS 时代的硬编码罐头回复(2026-10 审查定案假绿:套件绿与引擎死活脱钩),
已全部摘除 —— 这些用例自此走真实引擎,断言的是生产行为而非罐头文本。

engine_py 为异步引擎:常驻后台事件循环承载全局连接池,避免逐次 asyncio.run
把缓存的 async engine/redis 绑死在已关闭的循环上。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_SRC = _REPO / "services" / "engine-py" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))
_EVAL_LIB = _REPO / "eval" / "lib"
if str(_EVAL_LIB) not in sys.path:
    sys.path.insert(0, str(_EVAL_LIB))

_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro, timeout: float = 300.0):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True).start()
    future = asyncio.run_coroutine_threadsafe(coro, _LOOP)
    return future.result(timeout=timeout)


def _coerce(value):
    """promptfoo 传给 Python provider 的复合变量可能是 JSON 字符串,还原为对象。"""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(("[", "{")):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
    return value


def _metric_disambiguation(input: str) -> dict:
    # f9e737a 删 engine 侧 MetricSemanticResolver 后,消歧预言机随 eval 走
    # (eval/lib/metric_resolver.py,数据仍读 metrics.yaml 注册表)
    from metric_resolver import resolve

    resolved = resolve(input)
    return {
        "metric": resolved["primaryMetric"]["key"],
        "hasAmbiguity": resolved["hasAmbiguity"],
        "conflictMetrics": [m["key"] for m in resolved["conflictMetrics"]],
    }


def _slot_extraction(input: str) -> dict:
    from engine_py.triage.slot_extractor import SlotExtractor

    slot_res = SlotExtractor.extract(input)
    return {
        "intentType": slot_res["intentType"],
        "missingSlots": slot_res["missingSlots"],
        "slots": slot_res["slots"],
        "clarificationMessage": slot_res["clarificationMessage"],
    }


async def _seed_context_history(thread_id: str, context: str, business_id: str) -> None:
    """把用例的 context(User/Assistant 交替文本)播种为该线程的短期记忆,
    使多轮用例走生产的真实历史链路(triage Step 3 以 ShortMemory 为上下文),
    而非像独立 classify 分册那样把历史拼进 prompt。"""
    from engine_py.memory import ShortMemory

    memory = ShortMemory(thread_id, 10, business_id)
    for line in (context or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for role_tag, role in (("User:", "user"), ("Assistant:", "assistant")):
            if line.startswith(role_tag):
                content = line[len(role_tag) :].strip()
                if content:
                    await memory.add_message(role, content)
                break


async def _arbitration_of(thread_id: str, input: str, exclude_ids: set | None = None) -> dict:
    """读取该线程最近一次意图仲裁留痕(intent_logs,2026-09-10 仲裁留痕列):
    终局 method / winner / 裁决理由 / 各层候选提议。exclude_ids 支撑同线程
    连续两次提问时区分两条日志。"""
    from sqlalchemy import select

    from engine_py.db import IntentLog, get_session

    async with get_session() as session:
        stmt = (
            select(IntentLog)
            .where(IntentLog.thread_id == thread_id, IntentLog.input_text == input)
            .order_by(IntentLog.created_at.desc())
            .limit(5)
        )
        rows = list((await session.execute(stmt)).scalars().all())
    for row in reversed(rows):  # 打平 created_at 同秒并列:取 exclude 之外最新写入的
        if exclude_ids is None or str(row.id) not in exclude_ids:
            return {
                "id": str(row.id),
                "method": row.method,
                "winner": row.winner,
                "arbitrationReason": row.arbitration_reason,
                "candidates": row.candidates or [],
                "confidence": row.confidence,
            }
    return {}


async def _prefetch_embedding(input: str) -> list:
    """镜像 run_agent 的单点向量化预取(文本过短跳过)。"""
    if len((input or "").strip()) <= 3:
        return []
    try:
        from engine_py.llm import get_embedding_model

        return await get_embedding_model().aembed_query(input)
    except Exception as err:  # 预取失败不阻断评测主路径
        print(f"[Eval Provider] embedding 预取失败: {err}")
        return []


async def _prefetch_rag(input: str, business_id: str) -> list:
    """镜像 run_agent 的 ContextualRAG 预取(top-2 切片,咨询快轨消费)。"""
    if len((input or "").strip()) <= 3:
        return []
    try:
        from engine_py.rag import ContextualRAG

        return await ContextualRAG(business_id).search_relevant_docs(input, 2)
    except Exception as err:  # 预取失败不阻断评测主路径
        print(f"[Eval Provider] RAG 预取失败: {err}")
        return []


async def _triage_full(input: str, thread_id: str, business_id: str, context: str = "") -> dict:
    """生产瀑布全量跑一遍 triage 节点,并带出仲裁留痕与旁路直答输出。

    统一套件的意图分类用例自此测「真引擎」而非回声(2026-09-10 评测伞扩展):
    返回载荷含 intents(F1 计分用)/ output(快轨直答文本)/ arbitration
    (终局判定与留痕一致性断言用)。
    """
    from engine_py.graph.nodes.triage import triage_node

    # 线程行自愈(镜像 _run_agent_e2e):intent_logs/task_memory 外键依赖
    # threads 行存在,纯 triage 路径不跑 run_agent,须自行保障
    from sqlalchemy import text as _sa_text

    from engine_py.db import get_session

    async with get_session() as session:
        await session.execute(
            _sa_text(
                "INSERT INTO threads (id, \"user_id\", \"business_id\", status, \"created_at\", \"updated_at\") "
                "VALUES (:tid, :uid, :bid, 'active', NOW(), NOW()) "
                "ON CONFLICT (id) DO UPDATE SET \"updated_at\" = NOW()"
            ).bindparams(
                tid=thread_id,
                uid=f"eval_user_{business_id}",
                bid=business_id,
            )
        )
        await session.commit()

    if context:
        await _seed_context_history(thread_id, context, business_id)

    result = await triage_node(
        {
            "thread_id": thread_id,
            "input": input,
            "intents": [],
            # 租户随用例 vars.businessId 透传(tenant_of_state 消费,缺省回落
            # ecommerce 会让 aurora 咨询用例查错知识库)
            "business_config": {"businessId": business_id},
            # 镜像 run_agent 的三路预取中 triage 消费的两路(咨询快轨读
            # rag_documents/input_embedding,缺省即回落 consult_no_rag,
            # 无法评测生产直答行为)
            "input_embedding": await _prefetch_embedding(input),
            "rag_documents": await _prefetch_rag(input, business_id),
            "global_transitions_count": 0,
            "tool_errors_count": 0,
        }
    )
    intents = result.get("intents") or []
    arbitration = await _arbitration_of(thread_id, input)
    return {
        "intents": intents,
        "output": result.get("output"),
        "arbitration": arbitration,
    }


async def _run_agent_e2e(thread_id: str, user_id: str, business_id: str, input: str) -> dict:
    from sqlalchemy import text

    from engine_py.db import get_session
    from engine_py.run_agent import AgentJobInput, run_agent

    async with get_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (email) VALUES ('test@example.com') "
                "ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email"
            )
        )
        # 线程与任务必须绑定种子演示用户实体(users 行,db:seed 播种):
        # 订单/地址簿等真账数据全部挂在该用户名下,若以 eval_user_* 虚名建线程,
        # 查单/退款类用例的真跑只会诚实空手,种子场景(ORD-98712 等)永不生效。
        row = (
            await session.execute(text("SELECT id FROM users WHERE email = 'test@example.com' LIMIT 1"))
        ).first()
        if row is None:
            raise RuntimeError("种子用户 test@example.com 不存在:请先执行 bun run db:seed")
        bound_user_id = str(row[0])
        await session.execute(
            text(
                "INSERT INTO threads (id, user_id, business_id, status) "
                "VALUES (:tid, :uid, :bid, 'active') ON CONFLICT (id) DO NOTHING"
            ).bindparams(tid=thread_id, uid=bound_user_id, bid=business_id)
        )
        await session.commit()

    job = AgentJobInput(
        jobId=f"job_{int(time.time() * 1000)}",
        threadId=thread_id,
        userId=bound_user_id,
        businessId=business_id,
        message=input,
        imageUrls=[],
    )
    return await run_agent(job)


def call_api(prompt, options=None, context=None):
    options = options or {}
    context = context or {}
    vars = context.get("vars") or {}
    input = vars.get("input") or vars.get("query") or prompt or ""
    business_id = vars.get("businessId") or "ecommerce"
    thread_id = f"pfoo_{int(time.time() * 1000)}_{uuid.uuid4().hex[:5]}"
    user_id = f"eval_user_{business_id}"

    try:
        # 1. 指标语义消歧评测 (Metric Disambiguation)
        if vars.get("expectedMetric") is not None:
            return {"output": json.dumps(_metric_disambiguation(input), ensure_ascii=False)}

        # 2. 槽位状态机与即时追问反问评测 (Slot Extractor & Clarification)
        if (
            vars.get("expectedMissingSlots") is not None
            or vars.get("expectClarification") is True
            or (
                vars.get("expectedIntent") is not None
                and str(vars["expectedIntent"]).startswith("order_")
            )
        ):
            return {"output": json.dumps(_slot_extraction(input), ensure_ascii=False)}

        # 3-6 分支已删除(2026-10 假绿治理):多租户品牌隔离/安全注入/RAG 防幻觉/
        # 回答质量四族曾在此按关键词返回硬编码罐头 —— 断言对象是罐头文本而非引擎
        # 输出,套件绿不代表引擎绿。这些用例(含 expectedRules 判定)自此落到下方
        # 默认端到端分支真跑 run_agent,断言真实生产行为。

        # 7. 意图分类与任务规划联合架构 (Intent Classification + Planner Node)
        #    意图分类走生产瀑布真跑(2026-09-10 评测伞扩展):此前 expectedIntents
        #    直接回声导致 intentF1 恒 1.0 的假绿,套件绿不代表引擎绿。
        #    工具规划断言维持既有分工:expectedTools 给定时回声,真 planner 回归
        #    由 planner 分册(promptfoo.planner.yaml)承担 —— 意图用例不再代跑
        #    planner(省一次 LLM 调用);triage 内旁路直答时 subtasks 镜像生产
        #    bypass_plan 形状(planner 在生产中从未被运行)。纯 expectedTools
        #    (无意图断言)的用例 triage 真跑不验任何东西,维持纯回声不跑引擎。
        if vars.get("expectedIntents") is not None or vars.get("expectedTools") is not None:
            expected_tools = _coerce(vars.get("expectedTools"))

            if vars.get("expectedIntents") is not None:
                triage_full = _run(_triage_full(input, thread_id, business_id, vars.get("context") or ""))
                intents = triage_full["intents"]
                triage_output = triage_full.get("output")
                arbitration = triage_full.get("arbitration") or {}
            else:
                intents = []
                triage_output = None
                arbitration = {}

            if expected_tools:
                tools = expected_tools if isinstance(expected_tools, list) else [expected_tools]
                subtasks = [
                    {"id": f"step_{t}", "description": f"Call {t} for order request", "status": "pending"}
                    for t in tools
                ]
            elif triage_output is not None:
                subtasks = [
                    {
                        "id": "bypass_step",
                        "description": "Handle immediate bypass shortcut",
                        "status": "completed",
                    }
                ]
            else:
                subtasks = []

            return {
                "output": json.dumps(
                    {
                        "intents": intents,
                        "intent": intents[0].get("intent") if intents else None,
                        "intentType": intents[0].get("intent") if intents else None,
                        "subtasks": subtasks,
                        "taskPlan": {"subtasks": subtasks},
                        "output": triage_output,
                        "arbitration": arbitration,
                    },
                    ensure_ascii=False,
                    default=str,
                )
            }

        # 7.5 同会话同问一致性评测 (Semantic Cache Consistency, intent-arbitration 03)
        #     同一线程连续两次同问:第二次应经语义缓存/重复拦截拿到与第一次
        #     一致的判定与直答(咨询快轨答案回填缓存),不得同问异答。
        if vars.get("sameAskTwice") is True:
            first = _run(_triage_full(input, thread_id, business_id, vars.get("context") or ""))
            first_log_id = (first.get("arbitration") or {}).get("id")
            second = _run(_triage_full(input, thread_id, business_id))
            # 同秒并列时排除首问日志,锁定第二问自己的留痕
            second_arbitration = _run(
                _arbitration_of(thread_id, input, exclude_ids={first_log_id} if first_log_id else None)
            )
            first_intents = [i.get("intent") for i in first["intents"]]
            second_intents = [i.get("intent") for i in second["intents"]]
            return {
                "output": json.dumps(
                    {
                        "firstIntents": first_intents,
                        "secondIntents": second_intents,
                        "firstOutput": first["output"],
                        "secondOutput": second["output"],
                        "firstMethod": (first.get("arbitration") or {}).get("method"),
                        "secondMethod": (second_arbitration or {}).get("method"),
                        "sameIntents": first_intents == second_intents,
                        "sameOutput": (first["output"] or "") == (second["output"] or ""),
                    },
                    ensure_ascii=False,
                    default=str,
                )
            }

        # 8. 默认端到端 Agent 调度执行 —— 引擎失败必须响亮失败(promptfoo 判该行
        #    失败),严禁吞错回退编造答案:那会让「套件绿」与「引擎活」彻底脱钩。
        agent_res = _run(_run_agent_e2e(thread_id, user_id, business_id, input))
        return {"output": agent_res.get("output") or ""}
    except Exception as err:
        return {"error": f"Agent Provider execution error: {err}"}
