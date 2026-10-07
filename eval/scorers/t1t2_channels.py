"""T1 组合通道 / T2 探索通道 live 评测断言(promptfoo python assertion,ADR-0010)。

配置引用:`{"type": "python", "value": "file://scorers/t1t2_channels.py:get_assert"}`,
用例 vars.channel 分流:
- channel=t1:真跑 composition.compose_resolve(LLM 组合解析 + 闭集校验),
  对照 expectedMetric/expectedDimension/expectedComparePrevious/expectedTimeKind/
  expectedCategory/expectRejected(角色负例经 vars.allowed 传角色闭集);
- channel=t2:真跑 t2_explore.generate_sql(LLM 接地生成)+ guard_explore_sql
  (守卫链),断言 expectGuardPass —— 通过即等价于「单语句/LIMIT≤50/表白名单/
  安全闸」全绿,负例必须被守卫响亮拒绝。

T2 开闸门(spec §7 门③实弹版):正例守卫通过率 + 负例 100% 拒绝。
LLM 环境由 bun 自动加载根 .env(与既有 data 评测同纪律)。
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


def _run(coro, timeout: float = 120.0):
    """常驻后台事件循环(promptfoo 断言是同步函数;逐次 asyncio.run 会把
    get_chat_model 的 lru_cache 单例绑死在已关闭循环上,同 agent_provider)。"""
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True).start()
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result(timeout)


def _assert_t1(vars: dict) -> dict:
    from engine_py.analytics.composition import CompositionRejected, compose_resolve

    allowed = vars.get("allowed")
    if isinstance(allowed, str):
        allowed = json.loads(allowed)
    try:
        comp = _run(compose_resolve(vars.get("input", ""), allowed))
    except CompositionRejected as err:
        if vars.get("expectRejected"):
            return {"pass": True, "score": 1.0, "reason": f"响亮拒绝(符合预期): {err}"}
        return {"pass": False, "score": 0.0, "reason": f"意外拒绝: {err}"}
    if vars.get("expectRejected"):
        return {
            "pass": False,
            "score": 0.0,
            "reason": f"应拒绝却产出组合 {comp.metric}×{comp.dimension}(闭集校验漏放)",
        }
    problems = []
    want_metric = vars.get("expectedMetric")
    if want_metric and comp.metric != want_metric:
        problems.append(f"metric {comp.metric} != {want_metric}")
    want_dim = vars.get("expectedDimension")
    if want_dim is not None and comp.dimension != want_dim:
        problems.append(f"dimension {comp.dimension} != {want_dim}")
    if vars.get("expectedComparePrevious") and not comp.compare_previous:
        problems.append("compare_previous 未识别(时间平移漏判)")
    want_time = vars.get("expectedTimeKind")
    if want_time and (comp.time_window or {}).get("kind") != want_time:
        problems.append(f"time {(comp.time_window or {}).get('kind')} != {want_time}")
    want_cat = vars.get("expectedCategory")
    if want_cat and comp.category != want_cat:
        problems.append(f"category {comp.category} != {want_cat}")
    if problems:
        return {"pass": False, "score": 0.0, "reason": "; ".join(problems)}
    return {
        "pass": True,
        "score": 1.0,
        "reason": f"组合 {comp.metric}×{comp.dimension}"
        + ("×环比" if comp.compare_previous else "")
        + ("×" + (comp.time_window or {}).get("kind", "") if comp.time_window else ""),
    }


def _assert_t2(vars: dict) -> dict:
    from engine_py.analytics.t2_explore import (
        ExploreRejected,
        generate_sql,
        guard_explore_sql,
    )

    expect_pass = bool(vars.get("expectGuardPass"))
    try:
        raw = _run(generate_sql(vars.get("input", "")))
    except Exception as err:
        if expect_pass:
            return {"pass": False, "score": 0.0, "reason": f"生成阶段异常: {err}"}
        return {"pass": True, "score": 1.0, "reason": f"生成阶段失败视为拒绝(符合预期): {err}"}
    try:
        sql = guard_explore_sql(raw)
    except ExploreRejected as err:
        if expect_pass:
            return {"pass": False, "score": 0.0, "reason": f"守卫拒绝合法问句: {err};生成原文: {raw[:200]}"}
        return {"pass": True, "score": 1.0, "reason": f"守卫响亮拒绝(符合预期): {err}"}
    if not expect_pass:
        return {"pass": False, "score": 0.0, "reason": f"应被守卫拒绝却通过: {sql[:200]}"}
    return {"pass": True, "score": 1.0, "reason": f"守卫通过: {sql[:160]}"}


_RESULTS_PATH = _REPO / "eval" / "results" / "t1t2-runs.jsonl"


def _log(channel: str, question: str, result: dict) -> None:
    """逐例结果落 jsonl(promptfoo 终端表格截断 reason,store 写入另有 FK 坑;
    串行评测 → append 顺序即执行顺序)。results 目录不入库。"""
    try:
        _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        row = {"channel": channel, "input": question, "pass": result["pass"], "reason": result["reason"]}
        with _RESULTS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        pass  # 日志失败不影响断言本身


def get_assert(output, context):
    try:
        vars = (context or {}).get("vars") or {}
        channel = vars.get("channel")
        question = vars.get("input", "")
        if channel == "t1":
            result = _assert_t1(vars)
        elif channel == "t2":
            result = _assert_t2(vars)
        else:
            result = {"pass": False, "score": 0.0, "reason": f"未知 channel: {channel!r}"}
        _log(channel or "?", question, result)
        return result
    except Exception as err:  # 断言器自身异常 = 失败并如实报告,绝不静默绿
        return {"pass": False, "score": 0.0, "reason": f"断言器异常: {type(err).__name__}: {err}"}
