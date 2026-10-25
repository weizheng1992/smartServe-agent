"""RAG 检索层 recall/MRR 断言(eval-gap-2026-10 10 号票)。

配置引用:`{"type": "python", "value": "file://scorers/rag_recall.py:get_assert"}`。
vars:input(问句)/ businessId / expectedDoc(sourceUrl 子串,定位语料文件)/
expectedAnchor(期望段内独特短语,验「检对了段」而非只对文档)/ k(缺省 5)。

产出:**score = 1/rank**(未检回 0)—— 册级 baseline 的 rag_recall.py
meanScore 即 MRR;pass 语义 = recall@k(该检到的必须检回)。与 hit@1 册
互补:hit@1 钉「首位即对」,本册钉「k 内召回 + 排序质量」。零 LLM(本地 bge)。
"""

from __future__ import annotations

import json


def get_assert(output, context) -> dict:
    vars = (context or {}).get("vars") or {}
    expected_doc = str(vars.get("expectedDoc") or "")
    anchor = str(vars.get("expectedAnchor") or "")
    try:
        k = int(vars.get("k") or 5)
    except (TypeError, ValueError):
        k = 5
    try:
        payload = json.loads(output)
    except Exception:
        return {"pass": False, "score": 0.0, "reason": "provider 输出非 JSON"}
    if payload.get("error"):
        return {"pass": False, "score": 0.0, "reason": f"检索层错误: {payload['error']}"}

    rank = 0
    for h in payload.get("hits") or []:
        source = str(h.get("sourceUrl") or "")
        if expected_doc and expected_doc not in source:
            continue
        blob = f"{source}{h.get('headerPath', '')}{h.get('snippet', '')}{h.get('text', '')}"
        if anchor and anchor not in blob:
            continue
        rank = int(h.get("rank") or 0)
        break
    if rank == 0:
        return {"pass": False, "score": 0.0,
                "reason": f"recall@{k}=0:期望段({expected_doc or '任意'} / 锚点 {anchor[:18]})未检回 —— 检索层召回缺口"}
    rr = 1.0 / rank
    return {"pass": True, "score": rr,
            "reason": f"recall@{k}=1,rank={rank},RR={rr:.2f}(册级 meanScore 即 MRR)"}
