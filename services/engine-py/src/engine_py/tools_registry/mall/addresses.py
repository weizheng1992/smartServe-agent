"""地址簿簇(增存删 + 默认地址 + 默认行解析)。"""

from __future__ import annotations

import json
import secrets
import time

from sqlalchemy import text

from ..order_domain import OrderDomainService

MallDomainService = None  # service.py 类定义后回填(调用时经本模块全局解析,patch 面不漂移)


class AddressesMixin:
    """簇方法集;经 service.MallDomainService 合并为一类(全部 staticmethod)。"""

    @staticmethod
    async def get_user_addresses(
        user_id: str | None = None, business_id: str | None = None, thread_id: str | None = None
    ) -> dict:
        """1. 查询用户收货地址簿(单账本:商户侧 merchant_customers.addresses,
        与商城前端「我的地址」同一存储 —— 双库分裂曾致聊天新增在前端永不可见,
        2026-09-14 用户实报)。"""
        from .. import order_domain as _order_domain

        effective_user_id = user_id
        if not effective_user_id and thread_id:
            ctx = await OrderDomainService.get_thread_session_context(thread_id)
            effective_user_id = effective_user_id or ctx["userId"]
        if not effective_user_id:
            return {"total": 0, "userId": "current_user", "addresses": []}

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=effective_user_id
                        )
                    )
                ).scalar()
        except Exception as err:
            print(f"[MallDomain] 地址簿查询失败(诚实空): {err}")
            raw = None
        entries = raw if isinstance(raw, list) else []
        addresses = [
            {
                "addressId": e.get("id"),
                "receiverName": e.get("recipientName"),
                "receiverPhone": e.get("phone"),
                "fullAddress": e.get("fullAddress"),
                "isDefault": bool(e.get("isDefault")),
            }
            for e in entries
            if isinstance(e, dict)
        ]
        return {
            "total": len(addresses),
            "userId": effective_user_id,
            "addresses": addresses,
            "message": f"共 {len(addresses)} 个收货地址。" if addresses else "地址列表为空。",
        }

    @staticmethod
    @staticmethod
    async def save_user_address(params: dict) -> dict:
        """保存或新增用户收货地址(单账本:商户侧 merchant_customers.addresses,
        与商城前端同一存储 —— 双库分裂曾致聊天新增在前端永不可见)。"""

        def _mask(phone: str | None) -> str:
            phone = str(phone or "")
            return phone[:3] + "****" + phone[-4:] if len(phone) == 11 else phone

        # 必填字段防线(2026-09-13 M7 实弹):缺参曾直接 KeyError 炸图熔断
        missing_fields = [
            key
            for key in ("province", "city", "district", "detailAddress", "receiverName", "receiverPhone")
            if not params.get(key)
        ]
        if missing_fields:
            return {
                "success": False,
                "missingFields": missing_fields,
                "message": "收货地址信息不完整（缺：" + "、".join(missing_fields) + "），请补充后再保存。",
            }

        from .. import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，无法保存地址，请稍后重试。"}

        full_address = (
            f"{params['province']}{params['city']}{params['district']}{params['detailAddress']}"
        )
        entry = {
            "id": params.get("id") or f"ADDR_{int(time.time() * 1000)}_{secrets.token_hex(2)}",
            "recipientName": params["receiverName"],
            "phone": _mask(params["receiverPhone"]),
            "province": params["province"],
            "city": params["city"],
            "district": params["district"],
            "detailAddress": params["detailAddress"],
            "fullAddress": full_address,
            "isDefault": bool(params.get("isDefault")),
        }

        try:
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                row = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).mappings().first()
                current = (row.get("addresses") if row else None) or []
                updated = [dict(a) for a in current if isinstance(a, dict)]
                # 首条自动设默认;显式默认时清除其它默认(与商城前端同语义)
                should_default = entry["isDefault"] or not updated
                if should_default:
                    updated = [{**a, "isDefault": False} for a in updated]
                entry["isDefault"] = should_default
                existing = next((i for i, a in enumerate(updated) if a.get("id") == entry["id"]), -1)
                if existing >= 0:
                    updated[existing] = entry
                else:
                    updated.append(entry)
                await conn.execute(
                    text(
                        "INSERT INTO merchant_customers (customer_id, name, phone, addresses) VALUES "
                        "(:uid, :name, :phone, CAST(:a AS jsonb)) ON CONFLICT (customer_id) DO UPDATE "
                        "SET addresses = EXCLUDED.addresses"
                    ).bindparams(
                        uid=user_id, name=entry["recipientName"], phone=entry["phone"],
                        a=json.dumps(updated, ensure_ascii=False),
                    )
                )
        except Exception as err:
            print(f"[MallDomain] saveUserAddress(merchant ledger) failed: {err}")
            return {
                "success": False,
                "message": "收货地址保存失败，请稍后重试或联系人工客服。",
                "addressId": None,
                "fullAddress": full_address,
            }

        return {
            "success": True,
            "message": "收货地址保存成功",
            "addressId": entry["id"],
            "fullAddress": full_address,
            "isDefault": entry["isDefault"],
        }

    @staticmethod
    async def delete_user_address(params: dict) -> dict:
        """删除收货地址(2026-09-15 能力补齐):按收件人/full_address 子串定位
        顾客账本条目并移除;找不到/歧义如实说明。"""
        from .. import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        target = (params.get("addressId") or params.get("receiverName") or params.get("fullAddress") or "").strip()
        if not user_id or not target:
            return {"success": False, "message": "请告诉我要删除哪个收货地址（收件人或地址）。"}

        try:
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
            entries = raw if isinstance(raw, list) else []
            hits = [
                e for e in entries
                if isinstance(e, dict) and (
                    target in (e.get("fullAddress") or "")
                    or target in (e.get("recipientName") or "")
                    or e.get("id") == target
                )
            ]
            if not hits:
                return {"success": False, "message": f"地址簿里没有找到与「{target}」匹配的收货地址。"}
            if len(hits) > 1:
                names = "、".join(f"「{h.get('fullAddress')}」" for h in hits)
                return {"success": False, "message": f"找到 {len(hits)} 条匹配地址：{names}，请指明要删除哪一条。"}
            remaining = [e for e in entries if e is not hits[0]]
            await conn.execute(
                text(
                    "UPDATE merchant_customers SET addresses = CAST(:a AS jsonb) WHERE customer_id = :uid"
                ).bindparams(uid=user_id, a=json.dumps(remaining, ensure_ascii=False))
            )
            return {
                "success": True,
                "message": f"已删除收货地址：{hits[0].get('fullAddress')}",
            }
        except Exception as err:
            print(f"[MallDomain] deleteUserAddress failed: {err}")
            return {"success": False, "message": "地址删除失败，请稍后重试。"}

    @staticmethod
    async def set_default_address(params: dict) -> dict:
        """设默认收货地址(2026-09-15 S8 能力补齐):按 receiver_name 或地址 id
        定位顾客账本条目,置 is_default 并清除其它默认;找不到如实说明。"""
        from .. import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，请稍后重试。"}
        target = (params.get("addressId") or params.get("receiverName") or "").strip()

        try:
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
            entries = raw if isinstance(raw, list) else []
            if not entries:
                return {"success": False, "message": "您的地址簿还是空的，暂无可设为默认的地址。"}
            hit = None
            for e in entries:
                if not isinstance(e, dict):
                    continue
                name = (e.get("recipientName") or "")
                addr = (e.get("fullAddress") or "")
                # 子串双向匹配(「王五」含于「王五 的地址」等 LLM 转述形态)
                if target and (
                    e.get("id") == target
                    or target in name
                    or name in target
                    or target in addr
                ):
                    hit = e
                    break
            if hit is None:
                names = "、".join(str(e.get("recipientName") or "未命名") for e in entries if isinstance(e, dict))
                return {"success": False, "message": f"地址簿里没找到「{target or '该地址'}」。现有：{names}"}
            for e in entries:
                if isinstance(e, dict):
                    e["isDefault"] = e is hit
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                await conn.execute(
                    text(
                        "UPDATE merchant_customers SET addresses = CAST(:a AS jsonb) "
                        "WHERE customer_id = :uid"
                    ).bindparams(uid=user_id, a=json.dumps(entries, ensure_ascii=False))
                )
            return {
                "success": True,
                "message": (
                    f"已将【{hit.get('recipientName')}】的地址（{hit.get('fullAddress')}）设为默认收货地址。"
                ),
                "addressId": hit.get("id"),
            }
        except Exception as err:
            print(f"[MallDomain] setDefaultAddress failed: {err}")
            return {"success": False, "message": "默认地址设置失败，请稍后重试。"}

    @staticmethod
    async def _default_address_row(user_id: str) -> dict | None:
        """地址簿默认条目(商户账本 merchant_customers.addresses,is_default
        优先无则最新一条);账本不可达/无地址返回 None —— checkout 诚实追问。"""
        from .. import order_domain as _order_domain

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                raw = (
                    await conn.execute(
                        text("SELECT addresses FROM merchant_customers WHERE customer_id = :uid").bindparams(
                            uid=user_id
                        )
                    )
                ).scalar()
        except Exception as err:
            print(f"[MallDomain] 地址簿查询失败(按无地址处理): {err}")
            return None
        entries = raw if isinstance(raw, list) else []
        if not entries:
            return None
        chosen = next((e for e in entries if e.get("isDefault")), entries[0])
        return {
            "receiver_name": chosen.get("recipientName"),
            "receiver_phone": chosen.get("phone"),
            "full_address": chosen.get("fullAddress"),
        }

    @staticmethod
    async def _resolve_purchasable_sku(conn, *, spu_id: str | None = None, spu_code: str | None = None, sku_code: str | None = None) -> dict | None:
        """解析当前可购 SKU:sku_code 直配优先,否则 SPU(按 id 或 code)在售
        且有库存的最低价 SKU;不可售返回 None。"""
        if sku_code:
            row = (
                await conn.execute(
                    text(
                        "SELECT k.sku_code, k.price, k.stock, k.sku_title, k.spec_attributes, "
                        "k.cost_price, k.image_url, s.id AS spu_id, s.spu_code AS spu_code, "
                        "s.title AS spu_title, s.main_image "
                        "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                        "WHERE k.sku_code = :code AND s.status = 'ON_SALE' LIMIT 1"
                    ).bindparams(code=sku_code)
                )
            ).mappings().first()
            if row:
                return dict(row)
        if spu_id or spu_code:
            # items.spu_id 的事实契约是 spu_code(排行/桥接 join 口径),但历史
            # 数据两形态并存(UUID 文本/编码)—— 双匹配统一兼容
            bind = {"sid": str(spu_id or spu_code)}
            row = (
                await conn.execute(
                    text(
                        "SELECT k.sku_code, k.price, k.stock, k.sku_title, k.spec_attributes, "
                        "k.cost_price, k.image_url, s.id AS spu_id, s.spu_code AS spu_code, "
                        "s.title AS spu_title, s.main_image "
                        "FROM merchant_skus k JOIN merchant_spus s ON s.id = k.spu_id "
                        "WHERE (s.id::text = :sid OR s.spu_code = :sid) "
                        "AND s.status = 'ON_SALE' AND k.stock > 0 "
                        "ORDER BY k.price ASC LIMIT 1"
                    ).bindparams(**bind)
                )
            ).mappings().first()
            if row:
                return dict(row)
        return None
