"""本体知识层编译产物 —— GENERATED,手改无效(漂移门 test_codegen_sync 钉死)。

源头:ontology/{core,domain,application}/*.yaml,经 ontology/registry.py 编译;
再生成:仓库根执行 `services/.venv/bin/python ontology/registry.py --write`。
消费方(ADR-0015 批一):engine approvals/gatekeeper(受理集+早退 400+阈值缺省)、
graph/nodes/step_execution_engine(免签限额)、gateway approval_actions(四词表派生再出口)。
"""

from __future__ import annotations

from typing import Final

# --- 动作面(application/actions.yaml)--------------------------------------
APPROVAL_ACTIONS: Final[dict[str, dict[str, object]]] = {
    "approve": {
        'label': "审批通过",
        'faces': ('customer', 'staff_review', 'spi'),
        'permission': 'live_desk:approve',
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "human_escalation 工单 → resolved_by_human;其余 → approved",
    },
    "reject": {
        'label': "审批驳回",
        'faces': ('customer', 'staff_review', 'spi'),
        'permission': 'live_desk:approve',
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "2026-10-19 前无显式分支、靠 next_status 初值兜底——未知动作静默驳回与之 同路(gatekeeper else 兜底);现显式分支 + 引擎早退 400 双闸收口(ADR-0015 批一)",
    },
    "cancel": {
        'label': "取消工单",
        'faces': ('customer', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': True,
        'notes': "→ cancelled",
    },
    "start_human_takeover": {
        'label': "呼叫人工接管",
        'faces': ('customer', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator', 'system', 'customer'),
        'requires_approval_id': False,
        'notes': "无 operator 即呼叫排队形态;带 operator 即认领(P1 坐席身份)",
    },
    "human_message": {
        'label': "坐席发言(不结束)",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "带 operator 落 role=operator 列;无身份旧通道前缀写(P5 退役)",
    },
    "human_finish": {
        'label': "坐席结案",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "→ resolved_by_human + 释放接管(幂等)",
    },
    "release_takeover": {
        'label': "释放人工接管",
        'faces': ('operator', 'spi'),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': False,
        'notes': "线程级动作(P1),条件 UPDATE 幂等;网关按线程归属校验租户",
    },
    "human_reply": {
        'label': "人工回复(SPI 旧通道)",
        'faces': ('spi',),
        'permission': None,
        'roles': ('platform_admin', 'merchant_operator'),
        'requires_approval_id': True,
        'notes': "SPI 面仍合法(P4 只收管理台面);引擎分支保留至 P5",
    },
}

CUSTOMER_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'cancel', 'reject', 'start_human_takeover'])
OPERATOR_ACTIONS: Final[frozenset[str]] = frozenset(['human_finish', 'human_message', 'release_takeover'])
STAFF_REVIEW_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'reject'])
SPI_ACTIONS: Final[frozenset[str]] = frozenset(['approve', 'cancel', 'human_finish', 'human_message', 'human_reply', 'reject', 'release_takeover', 'start_human_takeover'])
ENGINE_HANDLED_ACTIONS: Final[frozenset[str]] = frozenset(APPROVAL_ACTIONS)
TS_GHOST_ACTIONS: Final[frozenset[str]] = frozenset(['reply'])

# --- 资金闸缺省(application/actions.yaml defaults)-------------------------
# 考古注记:历史六处分叉 50/100 —— 统一 50(收紧方向,ADR-0015 决策 4);
# 租户级显式覆写(nike=150/adidas=120)通道语义不变,本常量只钉缺省。
DEFAULT_REFUND_AUTO_APPROVAL_LIMIT: Final[float] = 50.0

__all__ = [
    "APPROVAL_ACTIONS",
    "CUSTOMER_ACTIONS",
    "DEFAULT_REFUND_AUTO_APPROVAL_LIMIT",
    "ENGINE_HANDLED_ACTIONS",
    "OPERATOR_ACTIONS",
    "SPI_ACTIONS",
    "STAFF_REVIEW_ACTIONS",
    "TS_GHOST_ACTIONS",
]
