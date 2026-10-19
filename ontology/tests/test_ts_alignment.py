"""TS 冻结面双向对齐(ADR-0015 批一;第四实弹收口)。

已知差异(声明层 ts_ghost_actions 登记,差异清单不得静默增长):
- packages/types/src/approval.ts:36 union = {approve, reject, cancel, reply},
  其中 cancel/reply 后端不受理、前端零发送方(reply=幽灵,cancel=死成员);
- 反向:前端实发 start_human_takeover(web useApprovals.ts:228)/
  release_takeover(merchant-admin api.ts:765)/human_message·human_finish
  (ui useApprovalMachine.ts:119)不在 approval.ts union 内 —— 漏登事实靠本册
  反向断言钉住,清理差异走独立契约修订批。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ontology import ACTION_SPECS, ENGINE_HANDLED_ACTIONS, TS_GHOST_ACTIONS

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVAL_TS = REPO_ROOT / "packages" / "types" / "src" / "approval.ts"
UI_MACHINE_TS = REPO_ROOT / "packages" / "ui" / "src" / "hooks" / "useApprovalMachine.ts"

# 前端实际发送面(2026-10-19 grep 实证;新增发送词须同批登记此处并过反向断言)
FRONTEND_SENDS = {
    "approve",              # web/admin/merchant-admin 多处
    "reject",               # 同上
    "start_human_takeover", # apps/web/src/hooks/useApprovals.ts:228
    "release_takeover",     # apps/merchant-admin/src/lib/api.ts:765
    "human_message",        # packages/ui useApprovalMachine.ts:119
    "human_finish",         # 同上(isFinish=true)
}


def _union_members(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if "action:" in line and "'approve'" in line and "|" in line:
            return re.findall(r"'([a-z_]+)'", line)
    raise AssertionError(f"{path.name} 未找到 action union 行(契约面被改?)")


@pytest.mark.skipif(not APPROVAL_TS.exists(), reason="approval.ts 不在本仓布局内")
def test_types_union_forward_alignment() -> None:
    union = set(_union_members(APPROVAL_TS))
    allowed = set(ENGINE_HANDLED_ACTIONS) | set(TS_GHOST_ACTIONS)
    extra = union - allowed
    assert not extra, f"approval.ts union 出现未登记成员 {sorted(extra)} —— 幽灵清单不得静默增长"


@pytest.mark.skipif(not UI_MACHINE_TS.exists(), reason="useApprovalMachine.ts 不在本仓布局内")
def test_ui_machine_union_forward_alignment() -> None:
    union = set(_union_members(UI_MACHINE_TS))
    allowed = set(ENGINE_HANDLED_ACTIONS) | set(TS_GHOST_ACTIONS) | {"cancel"}  # cancel=死成员已盘
    extra = union - allowed
    assert not extra, f"useApprovalMachine union 出现未登记成员 {sorted(extra)}"


def test_frontend_send_words_backward_alignment() -> None:
    missing = FRONTEND_SENDS - set(ACTION_SPECS)
    assert not missing, f"前端实发动作未被本体受理 {sorted(missing)} —— 漏登即契约面错位"
