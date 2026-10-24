"""坏例候选池 triage CLI — 周度人工评审入口(第五阶段 v1,半自动闭环的人工侧)。

用法(在 ``services/engine-py`` 下执行)::

    uv run python -m engine_py.badcase.cli list [--status candidate] [--source X] [--limit 50]
    uv run python -m engine_py.badcase.cli show <候选ID>          # 原文 vs 脱敏对照
    uv run python -m engine_py.badcase.cli triage <候选ID> --status confirmed|dismissed|converted [--note ...]
    uv run python -m engine_py.badcase.cli draft <候选ID> --input "脱敏后的问题" \
        [--expected-tools listUserOrders,getOrderStatus] [--not-contains 退款已到账] \
        [--intents order_status] [--out /path/to/case.json]
    uv run python -m engine_py.badcase.cli expire                 # 立即执行保留期(90d/30d)
    uv run python -m engine_py.badcase.cli shadow                # shadow 集自动起草(P0-2,高置信信号→pending.json)
    uv run python -m engine_py.badcase.cli promote <候选ID> --suite testCases/ecommerce/order-query.json \
        [--expected-tools ...] [--not-contains ...] [--input 手改输入]   # 人审转正进硬闸套件

设计原则(2026-09-03 评审锁定):
- 信号只入池,永不直接成为回归断言;``draft`` 产出的用例由人确认后手工并入
  ``eval/testCases/``,跑通 promptfoo 再 ``triage --status converted`` 留痕;
- 断言最小化:只写 ``expectedTools`` / ``not-contains``,禁止整句黄金答案;
- 仓库零原始数据:draft 的 ``--input`` 必须基于脱敏侧撰写(``show`` 已给对照)。

shadow 通道(docs/multi-turn-task-state.md P0-2/D7,2026-10-24):高置信信号
自动起草进 ``eval/testCases/shadow/pending.json``(不被任何硬闸 yaml 引用,
夜评只跑只报告);promote 是人审闸 —— 选套件、补断言都在这一步发生。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import desc, select

from ..db import BadcaseCandidate, Message, PendingApproval, get_session
from ..intent_flywheel.common import load_env_file
from .digest import run_badcase_digest
from .pool import SOURCE_PRIORS
from .redaction import redact_text

# draft 允许的状态:confirmed(评审确认)后才能起草;converted 后禁止重复起草
_DRAFT_ALLOWED_STATUS = ("candidate", "confirmed")

# promote 额外允许 shadow_draft(自动起草产物;docs/multi-turn-task-state.md P0-2)
_PROMOTE_ALLOWED_STATUS = ("candidate", "confirmed", "shadow_draft")


def apply_case_assertions(
    case: dict, expected_tools: str, expected_intents: str, not_contains: str
) -> dict:
    """断言旗标 → case(与 cmd_draft 同一口径;promote 复用,断言最小化纪律)。"""
    expected_tools_list = [t.strip() for t in (expected_tools or "").split(",") if t.strip()]
    expected_intents_list = [t.strip() for t in (expected_intents or "").split(",") if t.strip()]
    if expected_tools_list:
        case["vars"]["expectedTools"] = expected_tools_list
    if expected_intents_list:
        case["vars"]["expectedIntents"] = expected_intents_list
    if expected_tools_list or expected_intents_list:
        case["assert"].append({"type": "javascript", "value": "file://scorers/intentF1.scorer.ts"})
    for phrase in [p.strip() for p in (not_contains or "").split(",") if p.strip()]:
        case["assert"].append({"type": "not-contains", "value": phrase})
    return case


def _short_id(c: BadcaseCandidate) -> str:
    return str(c.id)[:8]


async def _get_candidate(candidate_id: str) -> BadcaseCandidate:
    exact = None
    async with get_session() as session:
        stmt = select(BadcaseCandidate).order_by(desc(BadcaseCandidate.created_at)).limit(200)
        for row in (await session.execute(stmt)).scalars():
            if str(row.id) == candidate_id or str(row.id).startswith(candidate_id):
                exact = row
                break
    if exact is None:
        raise SystemExit(f"[BadcaseCLI] 候选不存在: {candidate_id}(可先 `list` 查看短 ID)")
    return exact


async def cmd_list(args: argparse.Namespace) -> None:
    async with get_session() as session:
        stmt = select(BadcaseCandidate).order_by(desc(BadcaseCandidate.created_at)).limit(args.limit)
        if args.status:
            stmt = stmt.where(BadcaseCandidate.status == args.status)
        if args.source:
            stmt = stmt.where(BadcaseCandidate.signal_source == args.source)
        rows = (await session.execute(stmt)).scalars().all()
    if not rows:
        print("[BadcaseCLI] 无匹配候选")
        return
    print(f"{'ID':<9} {'信号源':<28} {'状态':<11} {'先验类别':<17} {'租户':<11} 引用")
    for c in rows:
        print(
            f"{_short_id(c):<9} {c.signal_source:<28} {c.status:<11} "
            f"{(c.suggested_class or '-'):<17} {(c.business_id or '-'):<11} {c.conversation_ref}"
        )
    print(f"\n共 {len(rows)} 条 · 信号先验表: {json.dumps(SOURCE_PRIORS, ensure_ascii=False)}")


async def cmd_show(args: argparse.Namespace) -> None:
    c = await _get_candidate(args.id)
    print(f"候选 {_short_id(c)}(完整 ID: {c.id})")
    print(f"  信号源: {c.signal_source}  状态: {c.status}  先验类别: {c.suggested_class or '-'}")
    print(f"  租户: {c.business_id}  引用: {c.conversation_ref}")
    print(f"  入池: {c.created_at}  备注: {c.note or '-'}")

    ref = c.conversation_ref
    if ref.startswith("thread:"):
        await _show_thread_conversation(ref.removeprefix("thread:"), c.business_id)
    elif ref.startswith("approval:"):
        await _show_approval(ref.removeprefix("approval:"), c.business_id)
    else:
        print("\n(该信号类型无对话原文可展示 — 引用仅指向事件本身,评审基于备注与后台上下文)")


async def _show_thread_conversation(thread_id: str, business_id: str | None) -> None:
    async with get_session() as session:
        msgs = (
            await session.execute(
                select(Message)
                .where(Message.thread_id == thread_id)
                .order_by(Message.created_at)
                .limit(50)
            )
        ).scalars().all()
    if not msgs:
        print(f"\n(线程 {thread_id} 无消息记录)")
        return
    print(f"\n── 对话原文 vs 脱敏对照(线程 {thread_id},共 {len(msgs)} 条)──")
    for m in msgs:
        redacted = await redact_text(m.content or "", business_id)
        print(f"\n[{m.role}] {m.timestamp}")
        print(f"  原文  : {m.content}")
        print(f"  脱敏后: {redacted}")
    print("\n⚠️ 回归用例的 --input 必须取自『脱敏后』一侧")


async def _show_approval(approval_id: str, business_id: str | None) -> None:
    async with get_session() as session:
        row = (
            await session.execute(select(PendingApproval).where(PendingApproval.id == approval_id))
        ).scalar_one_or_none()
    if row is None:
        print(f"\n(审批单 {approval_id} 已不存在)")
        return
    payload = json.dumps(row.action_payload or {}, ensure_ascii=False)
    print("\n── 审批单原文 vs 脱敏对照 ──")
    print(f"  动作类型: {row.action_type}  状态: {row.status}  驳回/审批原因: {row.reason or '-'}")
    print(f"  原文  : {payload}")
    print(f"  脱敏后: {await redact_text(payload, business_id)}")


async def _mark_candidate(candidate_id, status: str, note: str | None) -> None:
    """候选状态留痕单点(triage/promote 共用;note 追加式留痕)。"""
    async with get_session() as session:
        row = (
            await session.execute(select(BadcaseCandidate).where(BadcaseCandidate.id == candidate_id))
        ).scalar_one()
        row.status = status
        if note:
            row.note = f"{row.note or ''}; {note}".lstrip("; ")
        await session.commit()


async def cmd_triage(args: argparse.Namespace) -> None:
    c = await _get_candidate(args.id)
    await _mark_candidate(c.id, args.status, args.note)
    print(f"[BadcaseCLI] 候选 {_short_id(c)} → {args.status}" + (f"(备注: {args.note})" if args.note else ""))


async def cmd_draft(args: argparse.Namespace) -> None:
    c = await _get_candidate(args.id)
    if c.status not in _DRAFT_ALLOWED_STATUS:
        raise SystemExit(f"[BadcaseCLI] 状态 {c.status} 不可起草(需 candidate/confirmed;入集后标 converted)")
    if not args.input:
        raise SystemExit("[BadcaseCLI] --input 必填:请基于 `show` 的脱敏侧撰写回归输入(仓库零原始数据)")

    # 起草前对输入再过一次脱敏管道兜底(防人工誊抄带入 PII)
    redacted_input = await redact_text(args.input, c.business_id)
    if redacted_input != args.input:
        print(f"[BadcaseCLI] ⚠️ --input 含已知 PII,已自动脱敏: {redacted_input}")

    case = {
        "description": f"[badcase:{_short_id(c)}] {args.description or c.signal_source}",
        "vars": {
            "input": redacted_input,
            "origin": f"badcase:{c.id}",  # 溯源标记:该用例由哪条候选转化(不携带任何原始数据)
            **({"context": args.context} if args.context else {}),
        },
        "assert": [],
    }
    case = apply_case_assertions(case, args.expected_tools, args.intents, args.not_contains)

    payload = json.dumps([case], ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"[BadcaseCLI] 用例草稿已写入 {args.out}(人工确认后并入 eval/testCases/,跑通后 triage --status converted)")
    else:
        print(payload)


async def cmd_shadow(_: argparse.Namespace) -> None:
    """立即执行 shadow 集自动起草(digest 6h 节奏同函数;P0-2 手动触发口)。"""
    from .shadow import auto_draft_shadow_cases, default_pending_path

    summary = await auto_draft_shadow_cases()
    print(
        f"[BadcaseCLI] shadow 起草完成: drafted={summary['drafted']} skipped={summary['skipped']} "
        f"→ {default_pending_path()}"
    )


async def cmd_promote(args: argparse.Namespace, *, pending_path=None, eval_dir=None) -> None:
    """人审转正:shadow 草稿(或 --input 现写)补断言 → 并入硬闸套件 → 留痕 converted。

    D7 纪律的人工侧:套件文件由人显式指定(--suite),选哪个硬闸集、加什么
    断言都是评审决定 —— 自动只到 shadow 为止。``pending_path``/``eval_dir``
    为注入缝(测试);缺省分别取仓库 shadow 集与 ``<repo>/eval/``。
    """
    from .shadow import (
        STATUS_SHADOW_DRAFT,
        build_shadow_case,
        default_pending_path,
        load_pending,
        remove_shadow_case,
        save_pending,
    )

    c = await _get_candidate(args.id)
    if c.status not in _PROMOTE_ALLOWED_STATUS:
        raise SystemExit(f"[BadcaseCLI] 状态 {c.status} 不可转正(需 candidate/confirmed/{STATUS_SHADOW_DRAFT})")

    _default = default_pending_path()
    pending_path = pending_path or _default
    origin = f"badcase:{c.id}"
    pending = load_pending(pending_path)
    case, pending = remove_shadow_case(pending, origin)
    if case is not None:
        if args.input:
            case["vars"]["input"] = await redact_text(args.input, c.business_id)
        print(f"[BadcaseCLI] 取 shadow 草稿(origin={origin[:20]}…),输入: {case['vars']['input']}")
    elif args.input:
        redacted_input = await redact_text(args.input, c.business_id)
        case = build_shadow_case(str(c.id), c.signal_source, redacted_input)
        print(f"[BadcaseCLI] shadow 无草稿,按 --input 现建(origin={origin[:20]}…)")
    else:
        raise SystemExit(
            "[BadcaseCLI] shadow 集无该候选草稿且未给 --input(可先 `shadow` 自动起草或 --input 现写)"
        )

    if args.description:
        case["description"] = f"[badcase:{_short_id(c)}] {args.description}"
    case = apply_case_assertions(case, args.expected_tools, args.intents, args.not_contains)

    eval_dir = eval_dir or _default.parents[2]  # 默认几何:pending.json → shadow/ → testCases/ → eval/
    suite_path = Path(args.suite)
    if not suite_path.is_absolute():
        suite_path = eval_dir / suite_path
    suite = []
    if suite_path.exists():
        try:
            loaded = json.loads(suite_path.read_text(encoding="utf-8"))
            suite = loaded if isinstance(loaded, list) else []
        except ValueError as err:
            raise SystemExit(f"[BadcaseCLI] 套件文件不是合法 JSON 数组: {suite_path} ({err})") from err
    suite.append(case)
    suite_path.parent.mkdir(parents=True, exist_ok=True)
    suite_path.write_text(json.dumps(suite, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_pending(pending_path, pending)  # 已转正,从 shadow 集摘除

    async with get_session() as session:
        row = (
            await session.execute(select(BadcaseCandidate).where(BadcaseCandidate.id == c.id))
        ).scalar_one()
        row.status = "converted"
        if args.note:
            row.note = f"{row.note or ''}; {args.note}".lstrip("; ")
        await session.commit()
    print(f"[BadcaseCLI] 已转正 → {suite_path}(共 {len(suite)} 例);候选 {_short_id(c)} → converted")


async def cmd_expire(_: argparse.Namespace) -> None:
    summary = await run_badcase_digest()
    print(f"[BadcaseCLI] 保留期执行完成: {json.dumps(summary, ensure_ascii=False)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="engine_py.badcase.cli", description="坏例候选池 triage CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="列出候选(默认最近 50 条)")
    p_list.add_argument("--status", choices=["candidate", "confirmed", "dismissed", "converted"])
    p_list.add_argument("--source", help="按信号源过滤(见 pool.SOURCE_* 常量)")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="候选详情 + 原文/脱敏对照")
    p_show.add_argument("id", help="候选 ID(支持 8 位短 ID 前缀)")
    p_show.set_defaults(func=cmd_show)

    p_triage = sub.add_parser("triage", help="人工定夺候选状态")
    p_triage.add_argument("id")
    p_triage.add_argument("--status", required=True, choices=["confirmed", "dismissed", "converted"])
    p_triage.add_argument("--note", help="定夺理由(追加入 note 留痕)")
    p_triage.set_defaults(func=cmd_triage)

    p_draft = sub.add_parser("draft", help="从候选起草 promptfoo 回归用例(断言最小化)")
    p_draft.add_argument("id")
    p_draft.add_argument("--input", help="脱敏后的回归输入(必填,基于 show 的脱敏侧撰写)")
    p_draft.add_argument("--description", help="用例描述(默认用信号源)")
    p_draft.add_argument("--expected-tools", default="", help="逗号分隔,如 listUserOrders,getOrderStatus")
    p_draft.add_argument("--intents", default="", help="逗号分隔,如 order_status")
    p_draft.add_argument("--not-contains", default="", help="逗号分隔的禁止出现短语")
    p_draft.add_argument("--context", help="附加上下文(须自行脱敏)")
    p_draft.add_argument("--out", help="输出文件路径(缺省打印到 stdout)")
    p_draft.set_defaults(func=cmd_draft)

    p_shadow = sub.add_parser(
        "shadow", help="立即执行 shadow 集自动起草(高置信信号 → eval/testCases/shadow/,digest 6h 节奏同函数)"
    )
    p_shadow.set_defaults(func=cmd_shadow)

    p_promote = sub.add_parser(
        "promote", help="人审转正:shadow 草稿补断言并入硬闸套件,候选留痕 converted(P0-2 最后一公里)"
    )
    p_promote.add_argument("id", help="候选 ID(支持 8 位短 ID 前缀)")
    p_promote.add_argument(
        "--suite", required=True, help="目标硬闸套件(eval 相对路径,如 testCases/ecommerce/order-query.json)"
    )
    p_promote.add_argument("--input", help="覆盖/现写回归输入(缺省用 shadow 草稿的脱敏输入)")
    p_promote.add_argument("--description", help="覆盖用例描述")
    p_promote.add_argument("--expected-tools", default="", help="逗号分隔,如 listUserOrders,getOrderStatus")
    p_promote.add_argument("--intents", default="", help="逗号分隔,如 order_status")
    p_promote.add_argument("--not-contains", default="", help="逗号分隔的禁止出现短语")
    p_promote.add_argument("--note", help="转正理由(追加入 note 留痕)")
    p_promote.set_defaults(func=cmd_promote)

    p_expire = sub.add_parser("expire", help="立即执行保留期(candidate 90d / dismissed 30d)")
    p_expire.set_defaults(func=cmd_expire)

    return parser


def main(argv: list[str] | None = None) -> None:
    load_env_file()
    args = _build_parser().parse_args(argv)
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
