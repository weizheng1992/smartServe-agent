"""影子回放 — 从 threads/messages 物理表重放真实会话,经 Python 引擎输出结果 JSONL。

用法::

    python -m engine_py.shadow.replay --limit 50 --out py_results.jsonl

⚠️ run_agent 会写库(messages/记忆/遥测)。影子回放请将 ``DATABASE_URL`` 指向
影子数据库(生产库副本或容器),避免污染生产表;事件仅发布到
``job_shadow_*`` 流,无 SSE 消费方,零干扰。

TS 侧等价回放器(产出同格式 ts_results.jsonl)落在 eval/ 批次;
``diff.py`` 对两份 JSONL 逐会话对比。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from sqlalchemy import desc, select

from ..db import Message, Thread, get_session
from ..run_agent import AgentJobInput, run_agent


async def fetch_replay_inputs(limit: int) -> list[dict]:
    """按最近活跃线程取样:每个线程取首条 user 消息作为重放输入。"""
    async with get_session() as session:
        threads = (
            (
                await session.execute(
                    select(Thread).order_by(desc(Thread.updated_at)).limit(limit)
                )
            )
            .scalars()
            .all()
        )

        replay_inputs: list[dict] = []
        for thread in threads:
            first_user_msg = (
                await session.execute(
                    select(Message)
                    .where(Message.thread_id == thread.id, Message.role == "user")
                    .order_by(Message.timestamp)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if first_user_msg:
                replay_inputs.append(
                    {
                        "threadId": thread.id,
                        "userId": thread.user_id or "CUST-8801",
                        "businessId": thread.business_id or "ecommerce",
                        "message": first_user_msg.content,
                    }
                )
        return replay_inputs


def extract_signature(result: dict) -> dict:
    """抽取影子对比特征:意图序列、工具执行序列、规划步数、输出摘要。"""
    intents = [i.get("intent") for i in (result.get("intents") or [])]
    task_plan = result.get("taskPlan") or {}
    subtasks = task_plan.get("subtasks") or []
    tools = [
        (st.get("result") or {}).get("toolExecuted")
        for st in subtasks
        if (st.get("result") or {}).get("toolExecuted")
    ]
    output = result.get("output") or ""
    return {
        "intents": intents,
        "tools": tools,
        "subtaskCount": len(subtasks),
        "outputLength": len(output),
        "outputPreview": output[:120],
    }


async def replay_threads(limit: int = 50, out_path: str = "py_results.jsonl") -> dict:
    inputs = await fetch_replay_inputs(limit)
    print(f"[Shadow Replay] 取样 {len(inputs)} 个会话,开始回放 → {out_path}")

    ok_count = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for idx, item in enumerate(inputs):
            job_id = f"job_shadow_{int(time.time() * 1000)}_{idx}"
            try:
                result = await run_agent(
                    AgentJobInput(
                        jobId=job_id,
                        threadId=item["threadId"],
                        userId=item["userId"],
                        businessId=item["businessId"],
                        message=item["message"],
                    )
                )
                record = {
                    "threadId": item["threadId"],
                    "input": item["message"],
                    "engine": "python",
                    "signature": extract_signature(result),
                }
                ok_count += 1
            except Exception as err:
                record = {"threadId": item["threadId"], "input": item["message"], "engine": "python", "error": str(err)}
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    summary = {"total": len(inputs), "ok": ok_count, "failed": len(inputs) - ok_count, "out": out_path}
    print(f"[Shadow Replay] 完成: {summary}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="engine-py 影子回放")
    parser.add_argument("--limit", type=int, default=50, help="取样线程数")
    parser.add_argument("--out", type=str, default="py_results.jsonl", help="输出 JSONL 路径")
    args = parser.parse_args()
    asyncio.run(replay_threads(args.limit, args.out))


if __name__ == "__main__":
    main()
