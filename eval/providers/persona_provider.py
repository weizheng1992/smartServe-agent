"""promptfoo 自定义 Provider(Python)— 画像审计 Agent 抽取质量评测(persona-hardening 07)。

prompt 装配与 JSON 围栏解析 import 自 engine_py.memory.long_memory(与生产
_run_profile_audit 同一实现,单一事实源),LLM 调用走统一入口 get_chat_model
(生产参数同链:thinking 关闭、glm 参数兼容、熔断遥测);仅省去订单流水 SQL
与落库 —— 订单上下文由用例 vars.pastOrders 注入,评测只看「抽得准不准」,
不入库不污染画像表。

复用 agent_provider 的常驻后台事件循环模式(engine_py 为异步引擎,逐次
asyncio.run 会把缓存的 async 连池绑死在已关闭的循环上)。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_SRC = _REPO / "services" / "engine-py" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro, timeout: float = 300.0):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True).start()
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result(timeout=timeout)


def _coerce_orders(value):
    """promptfoo 传给 Python provider 的复合变量可能是 JSON 字符串,还原为对象。"""
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def call_api(prompt, options=None, context=None):  # promptfoo provider 接口约定
    from engine_py.llm.chat import get_chat_model
    from engine_py.memory.long_memory import build_profile_audit_prompt, parse_profile_audit_response

    vars_ = (context or {}).get("vars") or {}
    user_query = str(vars_.get("userQuery") or "").strip()
    assistant_response = str(vars_.get("conversation") or "").strip()
    past_orders = _coerce_orders(vars_.get("pastOrders"))
    if not user_query:
        return {"error": "vars.userQuery is required for persona audit eval"}

    audit_prompt = build_profile_audit_prompt(past_orders, user_query, assistant_response)

    async def _invoke():
        response = await get_chat_model().ainvoke(audit_prompt)
        return response.content if hasattr(response, "content") else str(response)

    try:
        content = _run(_invoke())
    except Exception as err:  # noqa: BLE001 — provider 边界,错误透传给 promptfoo 展示
        return {"error": f"persona audit LLM call failed: {type(err).__name__}: {err}"}

    try:
        audit = parse_profile_audit_response(content)
    except Exception:
        return {"error": f"persona audit returned non-JSON (围栏破产): {content[:300]}"}
    if not isinstance(audit, dict):
        return {"error": f"persona audit JSON is not an object: {content[:300]}"}
    return {"output": json.dumps(audit, ensure_ascii=False)}
