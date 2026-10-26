"""发货链路收口契约(客服优化批,2026-10-25)。

坐席台右栏「一键发货」复用 ``POST /api/admin/orders/ship``,本册钉死发货写路径
三个既有坑的收口语义:
1. **状态谓词**:仅 PAID 可发货 —— REFUNDED/SHIPPED 单直打 API 必 409 且零副作用
   (此前无谓词,已退款单可被直接打成 SHIPPED,前端按钮显隐曾是唯一状态闸);
2. **审计落账**:发货写 ``merchant_audit_logs``(action_type=SHIP,operator=员工
   email),订单详情审计时间线可见(此前发货零审计 —— MODIFY_ADDRESS/
   REQUEST_REFUND 有审计而 SHIP 没有,详情抽屉看不到发货动作);
3. **诚实轨迹**:tracking_info 落单节点「已发货 + 轨迹待更新」,不再伪造
   揽收/运输/派送三节点(数据诚实律;坐席推物流卡会把假轨迹变成顾客可见断言)。
另钉幂等重放:同单同运单号重发 = 幂等成功(网络重试不误报 409),异运单号 409。
"""

from __future__ import annotations

import json
import uuid as _uuid

import pytest
import sqlalchemy as sa

from gateway_py.merchant_db import ensure_merchant_tables, merchant_engine
from tests.merchant_seed_helpers import seed_merchant_order

_TAG = "SHP"
_UID = "CUST-SHP-1"


async def _seed_order(order_id: str, status: str = "PAID") -> None:
    await ensure_merchant_tables()
    async with merchant_engine().begin() as conn:
        await seed_merchant_order(
            conn,
            order_id=order_id,
            customer_id=_UID,
            total_amount=100.0,
            business_id="aurora",
            status=status,
            on_conflict_update=True,
        )


async def _cleanup() -> None:
    async with merchant_engine().begin() as conn:
        await conn.execute(
            sa.text("DELETE FROM merchant_order_items WHERE order_id LIKE :p"), {"p": f"{_TAG}-%"}
        )
        await conn.execute(sa.text("DELETE FROM merchant_audit_logs WHERE order_id LIKE :p"), {"p": f"{_TAG}-%"})
        await conn.execute(
            sa.text("DELETE FROM merchant_orders WHERE order_id LIKE :p OR customer_id = :u"),
            {"p": f"{_TAG}-%", "u": _UID},
        )


@pytest.fixture(autouse=True)
async def _ship_env():
    await _cleanup()
    yield
    await _cleanup()


def _order_id(tag: str) -> str:
    return f"{_TAG}-{tag}-{str(_uuid.uuid4())[:8].upper()}"


async def _fetch_order(order_id: str) -> dict:
    async with merchant_engine().connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT status, tracking_info, is_address_modifiable FROM merchant_orders WHERE order_id = :o"),
                {"o": order_id},
            )
        ).mappings().first()
    return dict(row) if row else {}


async def _ship_audit_rows(order_id: str) -> list[dict]:
    async with merchant_engine().connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT action_type, operator, result FROM merchant_audit_logs "
                    "WHERE order_id = :o AND action_type = 'SHIP' ORDER BY created_at ASC"
                ),
                {"o": order_id},
            )
        ).mappings().all()
    return [dict(r) for r in rows]


class TestShipContract:
    async def test_ship_paid_success_audit_and_honest_tracking(self, client, staff_auth):
        """PAID 单发货:状态流转 + 地址锁定 + SHIP 审计(operator=员工 email)+
        诚实单节点轨迹(承运商译名、无伪造节点)。"""
        order_id = _order_id("OK")
        await _seed_order(order_id, status="PAID")

        r = await client.post(
            "/api/admin/orders/ship",
            json={"orderId": order_id, "trackingNo": "SHP1001", "carrierCode": "JD"},
            headers=staff_auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        row = await _fetch_order(order_id)
        assert row["status"] == "SHIPPED"
        assert row["is_address_modifiable"] is False
        ti = row["tracking_info"] or {}
        assert ti["carrier"] == "京东快递", f"承运商须译名: {ti.get('carrier')}"
        assert ti["trackingNumber"] == "SHP1001"
        timeline = ti.get("timeline") or []
        assert len(timeline) == 1, f"诚实轨迹 = 单节点: {timeline}"
        assert "已发货" in timeline[0].get("status", "")
        assert "轨迹待更新" in timeline[0].get("description", "")
        assert "揽收" not in json.dumps(ti, ensure_ascii=False), "不得再伪造揽收/运输/派送节点"

        audits = await _ship_audit_rows(order_id)
        assert len(audits) == 1, f"发货必须落一条 SHIP 审计: {audits}"
        assert audits[0]["operator"] == "test@example.com", "审计 operator = 发货员工 email"
        assert "SHP1001" in json.dumps(audits[0]["result"], ensure_ascii=False)

        # 详情端点审计时间线可见(订单详情抽屉消费面)
        d = await client.get(f"/api/admin/orders/{order_id}", headers=staff_auth)
        assert d.status_code == 200
        audit_types = [log["action_type"] for log in d.json().get("auditLogs") or []]
        assert "SHIP" in audit_types

    async def test_ship_non_paid_conflict_409_zero_side_effect(self, client, staff_auth):
        """REFUNDED 单直打发货:409 状态冲突,订单纹丝不动、零审计。"""
        order_id = _order_id("REF")
        await _seed_order(order_id, status="REFUNDED")

        r = await client.post(
            "/api/admin/orders/ship",
            json={"orderId": order_id, "trackingNo": "SHP2001"},
            headers=staff_auth,
        )
        assert r.status_code == 409, f"非 PAID 发货必须 409: {r.status_code} {r.text}"
        body = r.json()
        assert body["success"] is False
        assert "REFUNDED" in body.get("message", "")

        row = await _fetch_order(order_id)
        assert row["status"] == "REFUNDED", "冲突发货不得落任何副作用"
        assert not row.get("tracking_info")
        assert await _ship_audit_rows(order_id) == []

    async def test_ship_same_tracking_idempotent_replay(self, client, staff_auth):
        """同单同运单号重发(网络重试形):幂等成功,审计不重复落;换承运商
        同号重发 = 冲突(重放判定比对承运商,防旧承运商文案冒充新提交)。"""
        order_id = _order_id("IDEM")
        await _seed_order(order_id, status="PAID")
        payload = {"orderId": order_id, "trackingNo": "SHP3001", "carrierCode": "SF"}

        r1 = await client.post("/api/admin/orders/ship", json=payload, headers=staff_auth)
        assert r1.status_code == 200 and r1.json()["success"] is True
        r2 = await client.post("/api/admin/orders/ship", json=payload, headers=staff_auth)
        assert r2.status_code == 200, f"同运单号重发须幂等 200: {r2.status_code} {r2.text}"
        assert r2.json()["success"] is True
        assert r2.json().get("replay") is True

        assert len(await _ship_audit_rows(order_id)) == 1, "幂等重放不得重复落审计"

        # 同号换承运商:不再按幂等放行(首笔事实已定),走状态冲突
        r3 = await client.post(
            "/api/admin/orders/ship",
            json={"orderId": order_id, "trackingNo": "SHP3001", "carrierCode": "JD"},
            headers=staff_auth,
        )
        assert r3.status_code == 409

    async def test_ship_shipped_new_tracking_conflict_409(self, client, staff_auth):
        """已发货单换运单号再发:409(不得覆盖既有运单)。"""
        order_id = _order_id("RETR")
        await _seed_order(order_id, status="PAID")
        r1 = await client.post(
            "/api/admin/orders/ship", json={"orderId": order_id, "trackingNo": "SHP4001"}, headers=staff_auth
        )
        assert r1.json()["success"] is True

        r2 = await client.post(
            "/api/admin/orders/ship", json={"orderId": order_id, "trackingNo": "SHP4002"}, headers=staff_auth
        )
        assert r2.status_code == 409
        row = await _fetch_order(order_id)
        assert (row["tracking_info"] or {}).get("trackingNumber") == "SHP4001", "冲突重发不得覆盖既有运单"
