"""步级执行日志与崩溃恢复(docs/multi-turn-task-state.md P2-1,2026-10-24 裁决 D5/D10)。

治「执行中崩溃 → 降级臂用空桩覆写在途计划 → 下一轮从零重规划」的病象
(课程⑧ checkpoint 的轻量自研落位;不引入 Temporal/Restate —— 部署矩阵
A 档单机不匹配其运维面):

- **写入**:executor_node 对进出 task_plan 做 diff,每个子任务状态变化追加
  一行(append-only,ok/failed + result_digest 审计留痕);任何异常自吞
  print,绝不阻断执行(观测性规范;context_builder「回退不阻断」同款纪律)。
- **检测**:`detect_crash_tail` —— 同会话最新一轮 session_metrics 落在崩溃态
  (graph_error_degraded / llm_circuit_breaker)∧ 该 job 有 journal 行 → 崩溃
  尾巴在场。「超 1 轮未续」由构造自然成立:任何更新一轮(成功与否)都会让
  latest 不再是那个崩溃 job。
- **恢复**:run_agent 轮入口检测到尾巴 → 非 System 轮也载回 task_memory 在途
  计划并按 journal 真值修补步状态(`rebuild_plan_from_journal`:completed 步
  保留、failed 步挂回重试),planner Journal-Resume 保留计划继续执行。HITL
  审批挂起不产生 journal 行(步未完成),两套恢复正交。
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import select

from ..db import SessionMetric, TaskStepJournalRow, get_session

# 崩溃态闭集(session_metrics.resolution_status):图异常与上游熔断两臂。
# interrupted 是用户主动停止(ADR-0013 语义:结果诚实标注、可「继续」接力),
# llm_quota_exhausted 同属降级但通常需要人工干预,均不入恢复面 —— 保守起步。
CRASH_RESOLUTION_STATUSES = ("graph_error_degraded", "llm_circuit_breaker")


def _digest_of(subtask: dict | None) -> str | None:
    """步结果摘要指纹(审计留痕;幂等重放判断的原料,v1 仅记录不消费)。"""
    if not subtask:
        return None
    try:
        payload = json.dumps(
            {"description": subtask.get("description"), "result": subtask.get("result")},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    except (TypeError, ValueError):
        return None


async def write_step_transitions(
    thread_id: str, job_id: str, prev_subtasks: list[dict], next_subtasks: list[dict]
) -> int:
    """进出 plan diff → journal 追加行。返回写入行数;失败静默 print 绝不上抛
    (执行主链路的旁路,炸了只丢观测不丢功能)。"""
    if not thread_id or not job_id:
        return 0
    rows: list[TaskStepJournalRow] = []
    for idx, nxt in enumerate(next_subtasks or []):
        prev_status = (prev_subtasks or [])[idx].get("status") if idx < len(prev_subtasks or []) else None
        next_status = (nxt or {}).get("status")
        if next_status in ("completed", "failed") and next_status != prev_status:
            rows.append(
                TaskStepJournalRow(
                    thread_id=thread_id,
                    job_id=job_id,
                    step_index=idx,
                    status=next_status,
                    result_digest=_digest_of(nxt),
                )
            )
    if not rows:
        return 0
    try:
        async with get_session() as session:
            session.add_all(rows)
            await session.commit()
        return len(rows)
    except Exception as err:
        print(f"[StepJournal] 步状态落库失败(不阻断): {err!r}")
        return 0


async def detect_crash_tail(thread_id: str) -> dict | None:
    """轮入口崩溃尾巴检测。返回 ``{"job_id", "rows": [{step_index,status}...]}``
    或 None(无尾巴/无 journal 行/任何异常 —— 检测是旁路,炸了当没有)。

    排序契约(code-review 裁定):journal 行按 (step_index, created_at) 次序
    返回 —— 同步多行(failed→completed 补写同 idx)时后写真值靠后,消费侧
    rebuild 逐行覆盖即天然 last-wins;latest 轮以 id 作同秒 tiebreak。"""
    if not thread_id:
        return None
    try:
        async with get_session() as session:
            latest = (
                await session.execute(
                    select(SessionMetric.job_id, SessionMetric.resolution_status)
                    .where(SessionMetric.thread_id == thread_id)
                    .order_by(SessionMetric.created_at.desc(), SessionMetric.id.desc())
                    .limit(1)
                )
            ).first()
            if latest is None or (latest.resolution_status or "") not in CRASH_RESOLUTION_STATUSES:
                return None
            job_id = latest.job_id
            if not job_id:
                return None
            rows = (
                await session.execute(
                    select(
                        TaskStepJournalRow.step_index,
                        TaskStepJournalRow.status,
                        TaskStepJournalRow.created_at,
                    )
                    .where(TaskStepJournalRow.job_id == job_id)
                )
            ).all()
        if not rows:
            return None
        return {
            "job_id": job_id,
            "rows": [
                {"step_index": int(r.step_index), "status": r.status}
                for r in sorted(rows, key=lambda r: (r.step_index, r.created_at or 0))
            ],
        }
    except Exception as err:
        print(f"[StepJournal] 崩溃尾巴检测失败(按无尾巴处理): {err!r}")
        return None


def rebuild_plan_from_journal(plan: dict, rows: list[dict] | None) -> dict:
    """按 journal 真值修补在途计划(纯函数):completed/failed 状态逐行覆盖
    (detect 返回序 = (step_index, created_at),后写真值 last-wins);
    currentStepIndex 落在**第一个未完成步** —— 并行分支下 failed 步可能先于
    completed 步共存,取 max(completed)+1 会把失败步跳过(code-review 裁定),
    「首个未完成」语义下失败步被重试、已 completed 步被执行器自然跳过。
    计划形状异常原样返回(恢复面严禁炸)。"""
    subtasks = (plan or {}).get("subtasks") or []
    if not subtasks or not rows:
        return plan
    patched = [dict(s) for s in subtasks]
    for row in rows or []:
        idx = row.get("step_index")
        if not isinstance(idx, int) or not (0 <= idx < len(patched)):
            continue
        if row.get("status") in ("completed", "failed"):
            # journal 是执行真值;执行器只跳 completed 步,failed 步重试
            patched[idx]["status"] = row["status"]
    first_unfinished = next(
        (i for i, s in enumerate(patched) if s.get("status") != "completed"), len(patched)
    )
    return {**plan, "subtasks": patched, "currentStepIndex": first_unfinished}


def plan_to_persist_on_crash(result_plan: dict | None, saved_state: dict | None, crash: bool) -> dict:
    """崩溃臂落库策略(纯函数):降级桩的空 task_plan 严禁覆写在途计划 ——
    journal 恢复面依赖 task_memory 里的计划存续。非崩溃臂(含 HITL 挂起、
    正常完成)原样返回 result_plan。"""
    if not crash:
        return result_plan or {}
    if (result_plan or {}).get("subtasks"):
        return result_plan
    prev = saved_state if isinstance(saved_state, dict) else None
    if prev and prev.get("subtasks"):
        return {k: prev[k] for k in ("goal", "subtasks", "currentStepIndex") if k in prev}
    return result_plan or {}
