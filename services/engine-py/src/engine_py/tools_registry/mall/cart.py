"""购物车簇(车存储读写穿透 Redis + 八动词 + 结算优惠链)。storage 双属性(_cart_storage 进程一级缓存 / _CART_REDIS_PREFIX 命名空间)留在本簇类体 —— conftest 以类属性 patch 做 Redis 隔离,严禁下沉模块级。"""

from __future__ import annotations

import json
import re

from sqlalchemy import text

from .. import order_domain


class _CouponAlreadyUsedError(RuntimeError):
    pass


class _CheckoutStockRaceError(RuntimeError):
    pass


MallDomainService = None  # service.py 类定义后回填(调用时经本模块全局解析,patch 面不漂移)


class CartMixin:
    """簇方法集;经 service.MallDomainService 合并为一类(全部 staticmethod)。"""


    # 购物车存储(2026-09-08 重构):_cart_storage 降级为进程一级读缓存,真实
    # 状态写穿透 Redis(agent:cart:{userId})。此前纯进程内存,网关重启即失忆,
    # 与浏览器 localStorage 购物车分裂 —— 引擎对已遗忘的车重新播报「已成功
    # 加入」,前端按 skuCode 合并发现条目都在,quantity 原值覆盖原值,计数
    # 纹丝不动(用户症状:「说成功了但没加入」)。Redis 不可用时降级纯内存。
    _cart_storage: dict[str, list[dict]] = {}
    _CART_REDIS_PREFIX = "agent:cart:"

    # L2 语义召回缓存:spu_code → (嵌入文本 sha256 前 16 位, 向量)。进程内
    # 缓存足够 —— 重嵌只是几毫秒级 bge 推理,跨进程共享(pgvector)是目录

    @staticmethod
    async def _load_cart(cart_key: str) -> list[dict] | None:
        """读购物车:进程缓存命中优先,否则回源 Redis。None 表示两处皆无。"""
        if cart_key in MallDomainService._cart_storage:
            return MallDomainService._cart_storage[cart_key]
        try:
            from ...event_bus import get_client

            raw = await (await get_client()).get(f"{MallDomainService._CART_REDIS_PREFIX}{cart_key}")
            if raw is None:
                return None
            items = json.loads(raw)
            MallDomainService._cart_storage[cart_key] = items
            return items
        except Exception as err:
            print(f"[MallDomain] Cart Redis load degraded to memory view: {err}")
            return None

    @staticmethod
    async def _save_cart(cart_key: str, items: list[dict]) -> None:
        """写购物车:进程缓存与 Redis 同步写穿透;Redis 故障静默降级纯内存。"""
        MallDomainService._cart_storage[cart_key] = items
        try:
            from ...event_bus import get_client

            await (await get_client()).set(
                f"{MallDomainService._CART_REDIS_PREFIX}{cart_key}", json.dumps(items, ensure_ascii=False)
            )
        except Exception as err:
            print(f"[MallDomain] Cart Redis persist degraded to memory only: {err}")

    @staticmethod
    async def add_to_cart(params: dict) -> dict:
        """8. 购物车添加与管理。"""
        sku_id = params["skuId"]
        quantity = params.get("quantity") or 1
        title = params.get("title") or "精选商品"
        # 无价不入车(2026-09-12):旧兜底 899.0 恰为已拆除的 Pegasus 假商品价 ——
        # 编造价格会污染购物车总额,缺参必须如实拒绝(real-data-only/01)。
        if params.get("price") is None:
            return {
                "success": False,
                "message": "未能确定该商品的价格，无法加入购物车。请重新选择商品后再试。",
                "lastModifiedItemId": None,
            }
        price = params.get("price")
        cart_key = params.get("userId") or params.get("threadId") or "default_user"

        items = (await MallDomainService._load_cart(cart_key)) or []
        existing = next((i for i in items if i["skuId"] == sku_id), None)
        if existing:
            existing["quantity"] += quantity
        else:
            row = {
                "skuId": sku_id,
                "quantity": quantity,
                "title": title,
                "price": price,
                "spec": params.get("spec"),
                # 图片透传(2026-09-15 用户实报):车行缺图曾致前端卡片图不对
                "imageUrl": params.get("imageUrl"),
            }
            # 规格摘要(2026-09-15 用户实报:商城页「规格:」空白):入车即落
            # 可读摘要,卡片 specSummary 与商城页 skuTitle 直接消费
            spec = params.get("spec")
            if isinstance(spec, dict) and spec:
                row["specSummary"] = " / ".join(str(v) for v in spec.values())
            # 可选引用键(2026-09-14 点名直配):skuCode 钉住用户点名的确切规格
            # (结算 sku_code 直配优先,不再被「SPU 最低价」静默换规格);spuId
            # 供前端卡片/商城链接回指 SPU。缺省不落键,旧行形状不变。
            if params.get("skuCode"):
                row["skuCode"] = str(params["skuCode"])
            if params.get("spuId"):
                row["spuId"] = str(params["spuId"])
            items.append(row)
        await MallDomainService._save_cart(cart_key, items)

        total_amount = sum(i["price"] * i["quantity"] for i in items)
        return {
            "success": True,
            "message": f"已成功将 {quantity} 件商品加入购物车！",
            "lastModifiedItemId": sku_id,
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "items": items,
            },
        }

    @staticmethod
    async def has_cart(params: dict) -> bool:
        """购物车是否真实存在(storage 有键且非空)。

        get_cart_summary 对缺失键返回演示默认车(AJ1),调用方不可据其判空,
        否则会对空车播报幻影移除/改量(2026-09-06 修复)。
        """
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        return bool(await MallDomainService._load_cart(cart_key))

    @staticmethod
    async def hydrate_cart_from_storefront(params: dict) -> bool:
        """商城门户车 → 引擎车幂等合并(2026-09-14 空车谎报收口)。

        症状:商城 UI 加购只写浏览器 localStorage,引擎车在 Redis,两存储互不
        相通 —— 用户说「删除/结算/查看购物车」时引擎只见空车,谎报「购物车
        还是空的」。每封聊天请求携带商城车条目(storeCart),本方法把引擎车
        没有的条目并进去:引擎车是会话内权威车,聊天侧删除经 cart_card 快照
        回同步商城车,商城侧重加经下一封消息水合回来 —— 双向最终一致。

        契约:skuCode 已在引擎车(聊天侧同款)→ 跳过,严禁覆盖聊天侧数量;
        载荷空/全部无效 → False;垃圾条目逐条容错,绝不抛出 —— 水合失败只
        降级为「引擎车维持原状」,聊天主链路照常。无价条目不入车(镜像
        add_to_cart 的无价拒绝红线,严禁以 0/兜底价污染车总额)。
        """
        try:
            items = params.get("items") or []
            valid = [
                it
                for it in items
                if isinstance(it, dict)
                and isinstance(it.get("skuCode"), str)
                and it["skuCode"]
                and isinstance(it.get("price"), (int, float))
            ]
            if not valid:
                return False
            cart_params = {"userId": params.get("userId"), "threadId": params.get("threadId")}
            cart_key = cart_params.get("userId") or cart_params.get("threadId") or "default_user"
            existing_skus = {i.get("skuId") for i in ((await MallDomainService._load_cart(cart_key)) or [])}
            added = False
            for it in valid:
                # 行主键维持 SPU 粒度契约(skuId=spuId 优先,退回 skuCode);确切
                # 规格经 skuCode 钉住,结算直配不换规格
                row_key = str(it.get("spuId") or it["skuCode"])
                if row_key in existing_skus:
                    continue
                try:
                    quantity = max(1, int(it.get("quantity") or 1))
                except (TypeError, ValueError):
                    quantity = 1
                price = it.get("price")
                await MallDomainService.add_to_cart(
                    {
                        "skuId": row_key,
                        "quantity": quantity,
                        "title": it.get("title") or "精选商品",
                        "price": float(price) if isinstance(price, (int, float)) else None,
                        "spec": it.get("specAttributes"),
                        "imageUrl": it.get("imageUrl"),
                        "skuCode": str(it["skuCode"]),
                        "spuId": row_key,
                        "userId": cart_params.get("userId"),
                        "threadId": cart_params.get("threadId"),
                    }
                )
                added = True
            return added
        except Exception as err:
            print(f"[MallDomain] 商城车水合失败,引擎车维持原状: {err}")
            return False

    # ── 真·聊天下单与订单→购物车桥接(遗留二期,2026-09-13)────────────────
    # 结算与商城页 create_order_from_cart 同一真账本语义:FOR UPDATE 锁库存、
    # 校验并扣减、PAID、cost_at_purchase 快照、all-or-nothing(任一行失败整单
    # 不落)。购物车行是 SPU 粒度(skuId=spu_code,导购目录 id 契约),结算解析
    # 为该 SPU 当前 ON_SALE 且有库存的最低价 SKU —— 与展示价=MIN(price) 同
    # 语义,规格在回复中如实展示;skuId 直配 sku_code 时按商城页同源直取。

    @staticmethod
    async def checkout_user_cart(params: dict) -> dict:
        """真·聊天下单:购物车 → 商户真单(遗留二期,2026-09-13)。

        与商城页同一账本:任一行不可售整单不落(all-or-nothing);地址取显式
        提供 > 地址簿默认 > 诚实追问(严禁假地址兜底,real-data-only/01)。
        顾客自有资金的下单与商城页同权,不走 HITL。
        """
        from .. import order_domain as _order_domain

        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，无法结算，请稍后重试。"}

        items = (await MallDomainService._load_cart(user_id)) or []
        if not items:
            return {
                "success": False,
                "message": "购物车还是空的，先挑点商品加入购物车，再来对我说「结算下单」吧！",
            }

        # 复合「加购+下单」范围结算(2026-09-15 用户实报「说的第一个商品,为什么
        # 这么多」):同句既加购又下单时,executor 快路径经 cartContext.addedThisTurn
        # 注入 onlySkuIds —— 只结本轮加购的行,历史在车遗留品不得静默陪结,也不得
        # 被清车。范围显式为空(加购半未完成)→ 诚实拒结,绝不拿遗留品开单(S6
        # 跨品类错单守卫同哲学)。参数缺省(None)保持整车结算旧契约。
        only_sku_ids = params.get("onlySkuIds")
        scoped_checkout = only_sku_ids is not None
        all_items = list(items)
        if scoped_checkout:
            wanted = {str(i) for i in (only_sku_ids or []) if str(i)}
            items = [
                i
                for i in items
                if str(i.get("skuId") or "") in wanted or str(i.get("skuCode") or "") in wanted
            ]
            if not items:
                return {
                    "success": False,
                    "message": "本轮要结算的商品还没有加入购物车（加购可能未完成），已为您取消本次结算；购物车商品保持不变。",
                }

        # 收货地址:显式 > 地址簿默认 > 诚实追问
        raw_addr = params.get("shippingAddress")
        addr_dict: dict | None = None
        if isinstance(raw_addr, dict) and (raw_addr.get("fullAddress") or raw_addr.get("address")):
            addr_dict = {
                "recipientName": raw_addr.get("recipientName") or "顾客",
                "phone": str(raw_addr.get("phone") or ""),
                "fullAddress": raw_addr.get("fullAddress") or raw_addr.get("address"),
            }
        elif isinstance(raw_addr, str) and raw_addr.strip():
            # 收件人/电话取地址簿默认行真值;顾客口述地址通常只有地址本身,
            # 缺人名电话时如实占位(与 needsAddress 追问路径同一诚实口径)
            fallback_row = await MallDomainService._default_address_row(user_id)
            addr_dict = {
                "recipientName": (fallback_row or {}).get("receiver_name") or "顾客",
                "phone": str((fallback_row or {}).get("receiver_phone") or ""),
                "fullAddress": raw_addr.strip(),
            }
        if addr_dict is None:
            default_row = await MallDomainService._default_address_row(user_id)
            if default_row:
                addr_dict = {
                    "recipientName": default_row["receiver_name"],
                    "phone": str(default_row["receiver_phone"] or ""),
                    "fullAddress": default_row["full_address"],
                }
            else:
                return {
                    "success": False,
                    "needsAddress": True,
                    "message": "结算需要收货地址，您的地址簿还是空的。请告诉我收件人姓名、电话和详细地址，我为您创建后再结算。",
                }

        try:
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                resolved: list[dict] = []
                failures: list[str] = []
                for item in items:
                    qty = int(item.get("quantity") or 1)
                    # 行上钉了 skuCode(点名直配)优先按确切规格直取,严禁被
                    # 「SPU 最低价」静默换掉用户点名的规格;未钉 skuCode 的行
                    # (导购候选/SKU 直配)维持原解析次序
                    sid = str(item.get("skuCode") or item.get("skuId") or "")
                    sku = await MallDomainService._resolve_purchasable_sku(conn, sku_code=sid)
                    if sku is None:
                        sku = await MallDomainService._resolve_purchasable_sku(conn, spu_code=sid)
                    if sku is None:
                        failures.append(f"{item.get('title') or sid}：已下架或暂无库存")
                        continue
                    if sku["stock"] < qty:
                        failures.append(f"{sku['spu_title']}（{sku['sku_title']}）：库存不足，仅剩 {sku['stock']} 件")
                        continue
                    resolved.append({**sku, "quantity": qty})
                if failures:
                    return {
                        "success": False,
                        "message": "以下商品无法结算：" + "；".join(failures),
                        "failures": failures,
                    }

                # 订单号生成闸上收 order_domain.generate_order_id 单点
                # (架构审查 #4 步2:与 gateway merchant_domain 同一机制)
                order_id = await order_domain.generate_order_id(conn)
                if not order_id:
                    return {"success": False, "message": "订单号生成冲突，请稍后重试。"}

                total_amount = 0.0
                line_summaries: list[str] = []
                # 条件 UPDATE(stock >= qty)原子防超卖:resolve 与扣减之间读
                # COMMITTED 快照可被并发单改掉,rowcount=0 即并发失利 → 整单不落
                for r in resolved:
                    updated = await conn.execute(
                        text(
                            "UPDATE merchant_skus SET stock = stock - :qty "
                            "WHERE sku_code = :code AND stock >= :qty"
                        ).bindparams(qty=r["quantity"], code=r["sku_code"])
                    )
                    if not updated.rowcount:
                        # 异常退出触发整单回滚:裸 return 会令 begin() 正常提交,
                        # 前面已扣的库存无法随单回滚(_CheckoutStockRaceError 注释)
                        raise _CheckoutStockRaceError(
                            f"{r['spu_title']}（{r['sku_title'] or '默认规格'}）刚刚被抢购一空，库存不足，请稍后再试。"
                        )
                    total_amount += float(r["price"]) * r["quantity"]
                    line_summaries.append(
                        f"{r['spu_title']}（{r['sku_title'] or '默认规格'}）x{r['quantity']} ¥{r['price']}"
                    )

                # 主单先行:items.order_id 对 merchant_orders 有外键
                # 优惠结算(20-D3 用户决议启用):服务端唯一算价点;账本语义与
                # gateway 结算一致 —— total_amount 记实付,discount_amount 记优惠。
                # 叠加语义(2026-09-22 与商城页统一,共用 resolve_stacked_promotions
                # 算价口径):活动先减,最优券按余额叠加;核销流水分两笔落。
                promo_applied = None
                coupon_row_id = None
                stacked = None
                try:
                    # SAVEPOINT:优惠计算失败只回滚保存点,不毒化结算主事务
                    # (实弹:promotions 表缺失期间,裸 try 会把事务打进 aborted,
                    #  后续订单 INSERT 全部失败 —— InFailedSQLTransactionError)
                    async with conn.begin_nested():
                        from engine_py.analytics.promotion_engine import resolve_stacked_promotions

                        amount = round(total_amount, 2)
                        scope = {str(r["spu_code"]) for r in resolved}
                        stacked = await resolve_stacked_promotions(conn, user_id, amount, scope)
                except Exception as promo_err:
                    print(f"[MallDomain] 优惠计算失败,按原价结算: {promo_err}")

                activity_part = (stacked or {}).get("activity")
                coupon_part = (stacked or {}).get("coupon")
                if coupon_part:
                    coupon_row_id = coupon_part["coupon_row_id"]
                if activity_part or coupon_part:
                    # 用户券:落核销 + 标记已用(同事务,防重复使用);活动/券各
                    # 落一笔 promotion_redemptions(叠加时两笔,金额各归各)
                    from engine_py.analytics import promotions as _promo_svc

                    if coupon_part:
                        await _promo_svc.record_promo_redemption(
                            conn, coupon_part["promotion_id"], order_id, coupon_part["discount"]
                        )
                        # 条件核销防双花:False=券已被并发订单用掉,抛错回滚整单
                        if not await _promo_svc.mark_coupon_used(conn, coupon_row_id, order_id):
                            raise _CouponAlreadyUsedError(
                                "这张优惠券刚被另一笔订单使用了。商品未扣款、购物车未清空，"
                                "可换个说法重新结算（不选券或换一张）～"
                            )
                    if activity_part:
                        await _promo_svc.record_promo_redemption(
                            conn, activity_part["promo_id"], order_id, activity_part["discount"]
                        )
                    parts = [p["name"] for p in (activity_part, coupon_part) if p]
                    promo_applied = {
                        "promo_id": (activity_part or {}).get("promo_id"),
                        "name": " + ".join(parts),
                        "discount": (activity_part or {}).get("discount", 0.0) + (coupon_part or {}).get("discount", 0.0),
                        "kind": "stacked" if (activity_part and coupon_part) else ("coupon" if coupon_part else "auto"),
                    }

                # 账本语义与 gateway 结算一致(2026-09-21 bug 修复):total_amount=实付
                # (原价−优惠),discount_amount=优惠额。此前只写原价且无优惠列 ——
                # 券被核销而订单页显示全款(订单 1155 实证 ¥50 券白烧)。
                _discount = promo_applied["discount"] if promo_applied else 0.0
                # 主单/行项目插入走 order_domain 共享单点(架构审查 #4 步3)
                await order_domain.insert_merchant_order(
                    conn,
                    order_id=order_id, customer_id=user_id,
                    total_amount=total_amount - _discount, discount_amount=_discount,
                    shipping_address_json=json.dumps(addr_dict, ensure_ascii=False),
                )
                for r in resolved:
                    spec_summary = " / ".join(
                        f"{k}:{v}" for k, v in (r.get("spec_attributes") or {}).items()
                    )
                    await order_domain.insert_merchant_order_item(
                        conn,
                        order_id=order_id, spu_id=r["spu_code"], sku_code=r["sku_code"],
                        title=r["spu_title"], sku_title=r["sku_title"] or "",
                        quantity=r["quantity"], price=r["price"],
                        image_url=r.get("image_url"), spec_summary=spec_summary,
                        cost_at_purchase=r.get("cost_price") or 0,
                    )
        except _CheckoutStockRaceError as race_err:
            print(f"[MallDomain] checkout rolled back, stock race: {race_err}")
            return {"success": False, "message": str(race_err)}
        except _CouponAlreadyUsedError as coupon_err:
            print(f"[MallDomain] checkout rolled back, coupon already used: {coupon_err}")
            return {"success": False, "message": str(coupon_err)}
        except Exception as err:
            print(f"[MallDomain] checkout failed: {err}")
            return {"success": False, "message": "结算失败，请稍后重试或转人工客服处理。"}

        # 清车:整车结算清空;范围结算只移除已结的行,遗留品原样保留。
        # 按对象身份剔除(过滤保留了原行引用):旧车行形状 skuId=spu_code 时
        # 同款双规格两行 skuId 相同,按 skuId 键剔除会误删未结算规格。
        if scoped_checkout:
            settled_ids = {id(i) for i in items}
            remaining = [i for i in all_items if id(i) not in settled_ids]
            await MallDomainService._save_cart(user_id, remaining)
        else:
            await MallDomainService._save_cart(user_id, [])
        return {
            "success": True,
            "orderId": order_id,
            "totalAmount": round(total_amount, 2),
            "promo": promo_applied,
            "payableAmount": round(total_amount - (promo_applied["discount"] if promo_applied else 0), 2),
            "items": line_summaries,
            "shippingAddress": addr_dict["fullAddress"],
        }

    @staticmethod
    async def add_order_item_to_cart(params: dict) -> dict:
        """订单→购物车桥接(遗留二期,2026-09-13):按关键词在顾客商户真单
        明细里找买过的商品,解析当前在售最低价 SKU 真实回车。

        零命中/多命中/已下架一律如实回复:多命中列出候选让顾客挑,严禁静默
        选一个;历史成交价不等于当前售价,入车价必须取当前货架价。
        """
        from .. import order_domain as _order_domain

        keyword = (params.get("keyword") or "").strip()
        # 口语量词剥除:「那件冲锋衣/这款背包」→「冲锋衣/背包」,否则 ILIKE 落空
        keyword = re.sub(r"^(?:那|这|该|此)(?:件|款|个|只|台|条)", "", keyword).strip()
        user_id = params.get("userId")
        if not user_id and params.get("threadId"):
            ctx = await _order_domain.OrderDomainService.get_thread_session_context(params["threadId"])
            user_id = user_id or ctx["userId"]
        if not keyword:
            return {"success": False, "message": "请告诉我想把订单里的哪件商品加入购物车（说出商品名即可）。"}
        if not user_id:
            return {"success": False, "message": "未能识别您的身份，请稍后重试。"}

        try:
            async with _order_domain._merchant_reader_engine().connect() as conn:
                rows = (
                    await conn.execute(
                        text(
                            "SELECT oi.spu_id, MIN(oi.title) AS title FROM merchant_order_items oi "
                            "JOIN merchant_orders o ON o.order_id = oi.order_id "
                            "WHERE o.customer_id = :uid AND o.status NOT IN ('REFUNDED','CANCELLED') "
                            "AND (oi.title ILIKE :kw OR oi.sku_title ILIKE :kw) "
                            "GROUP BY oi.spu_id ORDER BY MIN(oi.title) LIMIT 20"
                        ).bindparams(uid=user_id, kw=f"%{keyword}%")
                    )
                ).mappings().all()
        except Exception as err:
            print(f"[MallDomain] 订单明细查询失败: {err}")
            return {"success": False, "message": "暂时查不到您的订单记录，请稍后再试。"}

        if not rows:
            return {"success": False, "message": f"您的订单里没有找到「{keyword}」相关的商品。"}
        if len(rows) > 1:
            titles = "、".join(f"「{r['title']}」" for r in rows)
            return {
                "success": False,
                "message": f"您的订单里有 {len(rows)} 件商品与「{keyword}」相关：{titles}。请告诉我要把哪一件加入购物车。",
            }

        row = rows[0]
        try:
            async with _order_domain._merchant_writer_engine().begin() as conn:  # 阶段①只读收紧:写事务必须走 writer
                sku = await MallDomainService._resolve_purchasable_sku(conn, spu_id=str(row["spu_id"]))
        except Exception as err:
            print(f"[MallDomain] 桥接 SKU 解析失败: {err}")
            return {"success": False, "message": "暂时无法确认该商品的在售状态，请稍后再试。"}
        if sku is None:
            return {"success": False, "message": f"「{row['title']}」目前已下架或无库存，暂时无法再次购买。"}

        add_res = await MallDomainService.add_to_cart(
            {
                "skuId": sku["sku_code"],
                "quantity": 1,
                "title": row["title"],
                "price": float(sku["price"]),
                "spec": sku["sku_title"] or "",
                "userId": user_id,
                "threadId": params.get("threadId"),
            }
        )
        if not add_res.get("success"):
            return add_res
        return {
            "success": True,
            "message": (
                f"已将您订单里的「{row['title']}」加入购物车"
                f"（当前在售规格：{sku['sku_title'] or '默认'}，¥{sku['price']}）。"
            ),
            "lastModifiedItemId": sku["sku_code"],
            "cart": add_res.get("cart"),
        }

    @staticmethod
    async def get_cart_summary(params: dict) -> dict:
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        # 空车诚实空(2026-09-12):旧 `or [AJ1 演示车]` 兜底有两层欺骗 —— 空车是
        # 合法真实态被顶替,且 [] 是 falsy,清空购物车后查看必现幻影 AJ1
        # (real-data-only/01 实测 100% 复现)。
        items = (await MallDomainService._load_cart(cart_key)) or []
        total_amount = sum(i["price"] * i["quantity"] for i in items)
        estimated_discount = 100 if total_amount >= 1000 else 0
        return {
            "success": True,
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "discount": estimated_discount,
                "payableAmount": total_amount - estimated_discount,
                "items": items,
            },
        }

    @staticmethod
    async def update_cart_item(params: dict) -> dict:
        sku_id = params["skuId"]
        quantity = params["quantity"]
        cart_key = params.get("userId") or params.get("threadId") or "default_user"
        items = (await MallDomainService._load_cart(cart_key)) or []

        if quantity <= 0:
            items = [i for i in items if i["skuId"] != sku_id]
        else:
            target = next((i for i in items if i["skuId"] == sku_id), None)
            if target:
                target["quantity"] = quantity

        await MallDomainService._save_cart(cart_key, items)
        total_amount = sum(i["price"] * i["quantity"] for i in items)
        return {
            "success": True,
            "message": "商品已从购物车移除" if quantity <= 0 else f"商品数量已更新为 {quantity} 件",
            # totalQuantity 与 add_to_cart 对齐:删除/改量后技能侧据此播报件数,
            # 缺键时 `or 0` 回退曾致"0 件商品,总金额 ¥2198"自相矛盾(2026-09-06)
            "cart": {
                "itemCount": len(items),
                "totalQuantity": sum(i["quantity"] for i in items),
                "totalAmount": total_amount,
                "items": items,
            },
        }
