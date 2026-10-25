"""RAG 检索层直评 Provider(S3,stream-reliability-push 05)— 检索质量独立度量。

与 agent_provider 的区别:agent_provider 走端到端管线(检索质量被 finish 措辞
掩盖);本 provider 直呼 ``ContextualRAG.search_relevant_docs``,量的是检索本体
—— 混合检索(向量 0.8 + BM25 0.2)对预期语料段的命中能力。断言维度:
hit@k(预期段是否进前 k)/ 段位(MRR 风格 rank 上限)/ 租户隔离(跨租户语料
零混入)/ 响应形状契约。全链无 LLM 调用:embedding 走本地 bge(免费)、语料
来自 docs/knowledge 自愈种子 —— 钉定零 token 成本,可高频重钉。

由 promptfoo 以 `file://providers/rag_provider.py:call_api` 调用;engine_py 引导
与常驻事件循环同 agent_provider(异步引擎/全局连接池不绑死已关闭循环)。
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_ENGINE_SRC = _REPO / "services" / "engine-py" / "src"
if str(_ENGINE_SRC) not in sys.path:
    sys.path.insert(0, str(_ENGINE_SRC))

_LOOP: asyncio.AbstractEventLoop | None = None


def _run(coro, timeout: float = 120.0):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True).start()
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result(timeout=timeout)


async def _retrieve(business_id: str, query: str, k: int) -> dict:
    from engine_py.rag import ContextualRAG

    started = time.time()
    docs = await ContextualRAG(business_id).search_relevant_docs(query, limit=k)
    hits = []
    for i, doc in enumerate(docs):
        chunk = str(doc.get("chunkText") or "")
        hits.append(
            {
                "rank": i + 1,
                "sourceUrl": doc.get("sourceUrl") or "",
                "headerPath": doc.get("headerPath") or "",
                "similarity": round(float(doc.get("similarity") or 0.0), 4),
                "snippet": chunk[:80],
                # 300 字全文面(10 号票 recall/MRR 锚点断言;80 字 snippet 盖不住锚点)
                "text": chunk[:300],
            }
        )
    return {
        "query": query,
        "businessId": business_id,
        "k": k,
        "hits": hits,
        "latencyMs": round((time.time() - started) * 1000, 1),
    }


def call_api(prompt, options=None, context=None):
    context = context or {}
    vars = context.get("vars") or {}
    query = vars.get("input") or prompt or ""
    business_id = vars.get("businessId") or "ecommerce"
    try:
        k = int(vars.get("k") or 5)
    except (TypeError, ValueError):
        k = 5

    try:
        payload = _run(_retrieve(business_id, query, k))
        return {"output": json.dumps(payload, ensure_ascii=False)}
    except Exception as err:
        return {"output": json.dumps({"error": f"{type(err).__name__}: {err}"}, ensure_ascii=False)}
