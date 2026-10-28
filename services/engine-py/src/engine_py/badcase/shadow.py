"""badcase 回灌 shadow 集(docs/multi-turn-task-state.md P0-2,2026-10-24 裁决 D7)。

eval 飞轮的最后一公里:高置信信号(suspected_defect 先验族)此前止步于
「人工 CLI draft → 人工并入 testCases」,信号在池里积灰。本模块把
「起草」自动化到 shadow 集为止 —— ``eval/testCases/shadow/pending.json``
不被任何 promptfoo 硬闸 yaml 引用(主配置 suites 显式列举,新目录天然
不入闸),夜评/手动对 shadow **只跑只报告**;人审 ``cli promote`` 一键
把草稿(补断言、选套件)转正进硬闸集并留痕 converted。

纪律(2026-09-03 评审锁定 + D7):
- 自动只到 shadow 为止,人审才拦发版 —— 误信号自动入硬闸等于让噪声锁死发布;
- ``vars.input`` 必须取自脱敏管道产物(仓库零原始数据,与 ``cli draft``
  的兜底再脱敏同律);取不到脱敏安全输入就跳过,绝不落原文;
- 断言最小化:自动起草零断言,人审 promote 时按需补 expectedTools /
  not-contains;
- 一切失败静默降级(print 上下文),绝不阻断主链路/摘要任务(观测性规范)。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from ..db import BadcaseCandidate, Message, get_session
from .pool import SOURCE_CIRCUIT_BREAKER, SOURCE_PRIORS
from .redaction import redact_text

# 自动起草开闸面 = suspected_defect 先验族,**派生自 pool.SOURCE_PRIORS 单点**
# (code-review 裁定:手抄双源,新增先验要改两处)。circuit_breaker 刻意排除
# —— pool 注释明文「单独立案聚合,不直接转 case」;其定性必须过人。
AUTO_DRAFT_SOURCES = frozenset(
    source for source, prior in SOURCE_PRIORS.items() if prior == "suspected_defect"
) - {SOURCE_CIRCUIT_BREAKER}

STATUS_SHADOW_DRAFT = "shadow_draft"

_THREAD_PREFIX = "thread:"

# 测试线程前缀闭集(2026-10-28 人审实证):e2e(merchant_thread_e2e_*)与夜评
# (nightly_*)线程是测试流量 —— 行为面已由 e2e 册与夜评自身门禁钉死,起草进
# shadow 只产噪声(pending.json 四连 persona_fact_deleted 全来自 e2e 购物车
# 批次,对话本身零缺陷)。测试候选保持 candidate 留周度人审面,只是不自动起草。
_TEST_THREAD_PREFIXES = ("merchant_thread_e2e_", "nightly_")


def default_pending_path() -> Path:
    """仓库 shadow 集:``<repo>/eval/testCases/shadow/pending.json``。

    本文件位于 ``<repo>/services/engine-py/src/engine_py/badcase/``,向上五级
    到仓根;editable 安装(uv sync)下该相对关系恒成立。
    """
    return Path(__file__).resolve().parents[5] / "eval" / "testCases" / "shadow" / "pending.json"


def build_shadow_case(candidate_id: str, signal_source: str, redacted_input: str) -> dict:
    """候选 → promptfoo 用例草稿(形状与 ``cli draft`` 产物一致,零断言)。"""
    return {
        "description": f"[badcase:{candidate_id[:8]}] {signal_source}",
        "vars": {
            "input": redacted_input,
            "origin": f"badcase:{candidate_id}",  # 溯源标记(不携带任何原始数据)
        },
        "assert": [],
    }


def merge_shadow_case(cases: list[dict], case: dict) -> list[dict]:
    """按 origin 去重合并:同源重起草替换旧稿并沉底,其余保序。"""
    origin = (case.get("vars") or {}).get("origin")
    kept = [c for c in cases if (c.get("vars") or {}).get("origin") != origin]
    kept.append(case)
    return kept


def remove_shadow_case(cases: list[dict], origin: str) -> tuple[dict | None, list[dict]]:
    """按 origin 摘出草稿(promote 用);未命中返回 (None, 原表)。"""
    for i, c in enumerate(cases):
        if (c.get("vars") or {}).get("origin") == origin:
            return c, cases[:i] + cases[i + 1 :]
    return None, list(cases)


def load_pending(path: Path) -> list[dict]:
    """读 shadow 集:缺失/坏 JSON → 空表兜底(首跑即用,坏文件不炸节奏任务)。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else []
    except (OSError, ValueError):
        return []


def save_pending(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _latest_user_message(thread_id: str) -> str | None:
    """线程最新一条用户行(timestamp ISO 文本序即时间序;网关零写用户行治理
    后用户行只来自 dispatch/SPI,内容即触发信号的那轮输入)。"""
    async with get_session() as session:
        row = (
            await session.execute(
                select(Message.content)
                .where(Message.thread_id == thread_id, Message.role == "user")
                .order_by(Message.timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row


async def auto_draft_shadow_cases(pending_path: Path | None = None) -> dict:
    """扫描候选池 → 高置信信号自动起草进 shadow 集(挂 digest 6h 节奏)。

    流程:candidate ∧ 高置信源 → 取线程最新用户行 → 脱敏管道 → 零断言草稿
    merge 进 pending.json → 候选标 ``shadow_draft``。任何一步失败只计 skipped
    (候选保持 candidate 等人工 draft 流程),绝不抛。
    """
    path = pending_path or default_pending_path()
    summary = {"drafted": 0, "skipped": 0}
    try:
        async with get_session() as session:
            rows = (
                await session.execute(
                    select(BadcaseCandidate)
                    .where(
                        BadcaseCandidate.status == "candidate",
                        BadcaseCandidate.signal_source.in_(AUTO_DRAFT_SOURCES),
                    )
                    .order_by(BadcaseCandidate.created_at)
                    .limit(200)
                )
            ).scalars().all()

        drafted_ids: list[str] = []
        for row in rows:
            try:
                if not row.conversation_ref.startswith(_THREAD_PREFIX):
                    summary["skipped"] += 1
                    continue
                thread_id = row.conversation_ref.removeprefix(_THREAD_PREFIX)
                if thread_id.startswith(_TEST_THREAD_PREFIXES):
                    print(f"[BadcaseShadow] 测试线程不入 shadow(行为面归 e2e/夜评自有门禁): {thread_id[:48]}")
                    summary["skipped"] += 1
                    continue
                raw_text = await _latest_user_message(thread_id)
                if not raw_text or not raw_text.strip():
                    summary["skipped"] += 1
                    continue
                redacted = await redact_text(raw_text, row.business_id)
                if not redacted or not redacted.strip():
                    summary["skipped"] += 1
                    continue
                cases = merge_shadow_case(
                    load_pending(path),
                    build_shadow_case(str(row.id), row.signal_source, redacted),
                )
                save_pending(path, cases)
                drafted_ids.append(str(row.id))
                summary["drafted"] += 1
            except Exception as row_err:
                print(f"[BadcaseShadow] 单候选起草失败(跳过) id={row.id}: {row_err!r}")
                summary["skipped"] += 1

        if drafted_ids:
            async with get_session() as session:
                for cid in drafted_ids:
                    row = (
                        await session.execute(
                            select(BadcaseCandidate).where(BadcaseCandidate.id == cid).limit(1)
                        )
                    ).scalar_one_or_none()
                    if row is not None and row.status == "candidate":
                        row.status = STATUS_SHADOW_DRAFT
                await session.commit()
            print(
                f"[BadcaseShadow] 自动起草 {summary['drafted']} 条 → {path}"
                f"(夜评只跑不出闸;人工 promote 转正)"
            )
    except Exception as err:
        print(f"[BadcaseShadow] 扫描/起草异常(静默降级): {err!r}")
    return summary
