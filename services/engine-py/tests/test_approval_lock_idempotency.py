"""审批决议幂等锁契约(gatekeeper.process_approval_action 入口闸)。

夜审 2026-10-02 测试缺口②:Redis SETNX + 内存后备锁的双层防重此前零覆盖。
钉四性质:
- SETNX 明确答复「锁被持」(返回非 OK)→ 直接 409,严禁落内存兜底继续执行
  —— 兜底只服务 Redis 不可用;2026-10-02 修复:旧代码把「锁被持」误当
  「Redis 不可用」走本地兜底放行,并发双批可双双过闸(双开 resume 事件);
- Redis 不可用 → 内存兜底放行,finally 必释放(不泄漏,后续请求不永锁);
- 内存兜底被占 → 409,且响应方不得抢释放他人持有的锁;
- 非 UUID 工单号 → 404,锁之前就拒绝(不打 Redis)。
"""

from __future__ import annotations

import asyncio
import uuid

from engine_py.approvals import gatekeeper as gk


class _FakeRedis:
    """SETNX 语义桩:hold=True 模拟锁已被并发请求持有。"""

    def __init__(self, *, hold: bool = False, fail: bool = False):
        self.hold = hold
        self.fail = fail
        self.set_calls: list[str] = []
        self.deleted: list[str] = []

    async def set(self, key, value, px=None, nx=None):
        if self.fail:
            raise RuntimeError("redis down")
        self.set_calls.append(key)
        return None if self.hold else "OK"

    async def delete(self, key):
        self.deleted.append(key)


def _approval_request(approval_id: str) -> dict:
    return {"approvalId": approval_id, "action": "approve", "resolvedBy": "tester", "resolvedByRole": "system"}


def _patch_client(monkeypatch, client):
    async def _get_client():
        if client is None:
            raise RuntimeError("redis unavailable")
        return client

    monkeypatch.setattr(gk, "get_client", _get_client)


def test_setnx_lock_held_returns_409_without_local_fallback(monkeypatch):
    """锁被持 → 409;不落内存兜底(不执行业务)、不误删他人锁。"""
    fake = _FakeRedis(hold=True)
    _patch_client(monkeypatch, fake)
    out = asyncio.run(gk.ApprovalGatekeeper.process_approval_action(_approval_request(str(uuid.uuid4()))))
    assert out["statusCode"] == 409 and "请勿重复提交" in out["error"]
    assert gk._local_locks == set(), "「锁被持」不得落内存兜底"
    assert fake.deleted == []


def test_redis_unavailable_falls_back_and_releases(pg_factory, monkeypatch):
    """Redis 不可用 → 内存兜底放行(过闸后业务照走,此处无工单 → 404),
    finally 必释放兜底锁。"""
    _patch_client(monkeypatch, None)
    approval_id = str(uuid.uuid4())
    out = asyncio.run(gk.ApprovalGatekeeper.process_approval_action(_approval_request(approval_id)))
    assert out["statusCode"] == 404, f"应穿过锁闸到工单查询: {out}"
    assert gk._local_locks == set(), "兜底锁必须 finally 释放"


def test_local_lock_held_returns_409_and_does_not_steal_lock(monkeypatch):
    """内存兜底被占 → 409;响应方不得释放他人持有的锁(由持锁方 finally 释放,
    抢删会打开并发窗口)。"""
    _patch_client(monkeypatch, None)
    approval_id = str(uuid.uuid4())
    lock_key = f"lock:approval:{approval_id}"
    gk._local_locks.add(lock_key)
    try:
        out = asyncio.run(gk.ApprovalGatekeeper.process_approval_action(_approval_request(approval_id)))
        assert out["statusCode"] == 409 and "请勿重复提交" in out["error"]
        assert lock_key in gk._local_locks, "409 响应方不得释放他人持有的锁"
    finally:
        gk._local_locks.discard(lock_key)


def test_malformed_approval_id_rejected_before_lock(monkeypatch):
    """非 UUID 工单号 → 404;SETNX 不该被打(形状闸在锁之前)。"""
    fake = _FakeRedis()
    _patch_client(monkeypatch, fake)
    out = asyncio.run(gk.ApprovalGatekeeper.process_approval_action(_approval_request("not-a-uuid")))
    assert out["statusCode"] == 404
    assert fake.set_calls == [] and gk._local_locks == set()
