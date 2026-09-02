"""商户独立库种子数据 — 移植 apps/merchant/src/db/seed.ts(SPU/SKU/多规格矩阵 1:1)。

用法::

    cd services/gateway-py && uv run python -m gateway_py.merchant_seed
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from .merchant_db import ensure_merchant_tables, merchant_engine

_IMG_1 = "https://images.unsplash.com/photo-1551028719-00167b16eac5?w=800&auto=format&fit=crop&q=60"
_IMG_1B = "https://images.unsplash.com/photo-1544441893-675973e31985?w=800&auto=format&fit=crop&q=60"
_IMG_2 = "https://images.unsplash.com/photo-1521572267360-ee0c2909d518?w=800&auto=format&fit=crop&q=60"
_IMG_3 = "https://images.unsplash.com/photo-1624378439575-d8705ad7ae80?w=800&auto=format&fit=crop&q=60"
_IMG_4 = "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=800&auto=format&fit=crop&q=60"

_SPUS = [
    {
        "code": "SPU-AURORA-001",
        "title": "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)",
        "subtitle": "暴雨级防水 | GORE-TEX 3L级面料 | 智能温控锁温",
        "description": "专为高海拔严苛户外探险打造，采用全压胶三层复合微孔纳米膜，抗暴风雨兼顾极高透气性。配有 YKK 双向防水拉链、立体可调节防风帽及雪裙系统。",
        "category": "户外机能",
        "main_image": _IMG_1,
        "banners": [_IMG_1, _IMG_1B],
        "dimensions": [
            {"name": "颜色", "values": ["曜石黑", "极夜绿", "雪山白"]},
            {"name": "尺码", "values": ["M (170/88A)", "L (175/92A)", "XL (180/96A)"]},
        ],
        "specs": {
            "面料材质": "100% 聚酰胺纤维 + 3L微孔复合膜",
            "防水指数": "20000mmH2O (暴雨级)",
            "透气指数": "15000g/m²/24h",
            "拉链品牌": "YKK 双向全防水压胶拉链",
            "适用季节": "秋冬/四季通用",
            "版型": "3D立体剪裁",
        },
        "image": _IMG_1,
        "skus": [
            ("AURORA-SKU-001-BLK-M", "极光三合一冲锋衣 曜石黑 M码", {"颜色": "曜石黑", "尺码": "M (170/88A)"}, 1299.0, 1599.0, 45, "690123400101"),
            ("AURORA-SKU-002", "极光三合一冲锋衣 曜石黑 L码 (旗舰主推)", {"颜色": "曜石黑", "尺码": "L (175/92A)"}, 1299.0, 1599.0, 60, "690123400102"),
            ("AURORA-SKU-001-BLK-XL", "极光三合一冲锋衣 曜石黑 XL码", {"颜色": "曜石黑", "尺码": "XL (180/96A)"}, 1299.0, 1599.0, 30, "690123400103"),
            ("AURORA-SKU-001-GRN-M", "极光三合一冲锋衣 极夜绿 M码", {"颜色": "极夜绿", "尺码": "M (170/88A)"}, 1299.0, 1599.0, 25, "690123400104"),
            ("AURORA-SKU-001-GRN-L", "极光三合一冲锋衣 极夜绿 L码", {"颜色": "极夜绿", "尺码": "L (175/92A)"}, 1299.0, 1599.0, 38, "690123400105"),
            ("AURORA-SKU-001-WHT-L", "极光三合一冲锋衣 雪山白 L码", {"颜色": "雪山白", "尺码": "L (175/92A)"}, 1349.0, 1699.0, 15, "690123400106"),
        ],
    },
    {
        "code": "SPU-AURORA-002",
        "title": "极光2026春夏款 320g重磅精梳纯棉复古印花短袖T恤",
        "subtitle": "高支高密 | 领口防变形织带 | 环保活性印花",
        "description": "采用320克双纱精梳纯棉面料，挺括有型不透肉。领口加固高弹罗纹与双针通肩压条，多次洗涤依旧平整不垮领。",
        "category": "潮流T恤",
        "main_image": _IMG_2,
        "banners": [_IMG_2],
        "dimensions": [
            {"name": "颜色", "values": ["水洗灰", "纯净白", "暗夜黑"]},
            {"name": "尺码", "values": ["S", "M", "L", "XL"]},
        ],
        "specs": {
            "面料材质": "100% 精梳棉 (320g 重磅双纱)",
            "工艺": "水洗做旧 + 环保活性数码喷绘",
            "版型": "宽松落肩 Loose Fit",
            "领口设计": "加厚高弹罗纹 + 通肩防变形嵌条",
            "安全类别": "GB 18401-2010 B类 (直接接触皮肤)",
        },
        "image": _IMG_2,
        "skus": [
            ("AURORA-SKU-002-GRY-M", "重磅纯棉复古T恤 水洗灰 M码", {"颜色": "水洗灰", "尺码": "M"}, 269.0, 329.0, 120, None),
            ("AURORA-SKU-002-GRY-L", "重磅纯棉复古T恤 水洗灰 L码", {"颜色": "水洗灰", "尺码": "L"}, 269.0, 329.0, 95, None),
            ("AURORA-SKU-002-WHT-L", "重磅纯棉复古T恤 纯净白 L码", {"颜色": "纯净白", "尺码": "L"}, 269.0, 329.0, 80, None),
            ("AURORA-SKU-002-BLK-XL", "重磅纯棉复古T恤 暗夜黑 XL码", {"颜色": "暗夜黑", "尺码": "XL"}, 269.0, 329.0, 50, None),
        ],
    },
    {
        "code": "SPU-AURORA-003",
        "title": "极光 Cordura考杜拉耐磨多袋机能工装裤",
        "subtitle": "防泼水特氟龙涂层 | 8口袋收纳系统 | 磁吸战术扣件",
        "description": "精选 Cordura 500D 强韧耐磨面料，搭载 Teflon 纳米抗污防泼水涂层，内置模块化快拆腰带与多层立体风琴口袋。",
        "category": "下装裤类",
        "main_image": _IMG_3,
        "banners": [_IMG_3],
        "dimensions": [
            {"name": "颜色", "values": ["战术黑", "荒漠卡其", "橄榄绿"]},
            {"name": "尺码", "values": ["M (30腰)", "L (32腰)", "XL (34腰)"]},
        ],
        "specs": {
            "面料材质": "Cordura 500D 尼龙 + 特氟龙(Teflon)防泼水图层",
            "口袋数量": "8个立体多功能风琴袋 + 隐藏拉链仓",
            "腰带系统": "Fidlock 德国磁吸快拆扣",
            "耐磨等级": "工业级抗撕裂",
        },
        "image": _IMG_3,
        "skus": [
            ("AURORA-SKU-003-BLK-M", "Cordura机能工装裤 战术黑 M码", {"颜色": "战术黑", "尺码": "M (30腰)"}, 589.0, 799.0, 40, None),
            ("AURORA-SKU-003-BLK-L", "Cordura机能工装裤 战术黑 L码", {"颜色": "战术黑", "尺码": "L (32腰)"}, 589.0, 799.0, 55, None),
            ("AURORA-SKU-003-KHK-L", "Cordura机能工装裤 荒漠卡其 L码", {"颜色": "荒漠卡其", "尺码": "L (32腰)"}, 589.0, 799.0, 35, None),
        ],
    },
    {
        "code": "SPU-AURORA-004",
        "title": "极光 Vibram黄金大底 复古解构运动老爹鞋",
        "subtitle": "Vibram防滑湿地大底 | OrthoLite透气鞋垫 | 头层牛反绒拼接",
        "description": "解构美学设计，鞋面融合头层反绒皮与防刮尼龙网布。搭载意大利 Vibram Megagrip 顶级湿地防滑橡胶大底与高弹 EVA 缓震中底。",
        "category": "潮流鞋靴",
        "main_image": _IMG_4,
        "banners": [_IMG_4],
        "dimensions": [
            {"name": "颜色", "values": ["水泥灰/荧光绿", "复古白/深海蓝"]},
            {"name": "尺码", "values": ["40码 (250mm)", "41码 (255mm)", "42码 (260mm)", "43码 (265mm)"]},
        ],
        "specs": {
            "鞋面材质": "头层牛反绒皮革 + 高透气 Cordura 网布",
            "大底材质": "意大利 Vibram® Megagrip 止滑大底",
            "中底配置": "高回弹 超临界发泡 EVA 减震材料",
            "鞋垫": "OrthoLite® 抑菌排汗鞋垫",
        },
        "image": _IMG_4,
        "skus": [
            ("AURORA-SKU-004-GRY-41", "Vibram复古老爹鞋 水泥灰 41码", {"颜色": "水泥灰/荧光绿", "尺码": "41码 (255mm)"}, 899.0, 1099.0, 20, None),
            ("AURORA-SKU-004-GRY-42", "Vibram复古老爹鞋 水泥灰 42码", {"颜色": "水泥灰/荧光绿", "尺码": "42码 (260mm)"}, 899.0, 1099.0, 28, None),
            ("AURORA-SKU-004-WHT-42", "Vibram复古老爹鞋 复古白 42码", {"颜色": "复古白/深海蓝", "尺码": "42码 (260mm)"}, 899.0, 1099.0, 18, None),
        ],
    },
]


async def seed_merchant_data() -> None:
    await ensure_merchant_tables()
    print("[Merchant DB] 开始执行独立商户多规格领域数据 Seed 初始化...")

    async with merchant_engine().begin() as conn:
        for table in (
            "merchant_order_items",
            "merchant_audit_logs",
            "merchant_orders",
            "merchant_customers",
            "merchant_skus",
            "merchant_spus",
        ):
            await conn.execute(text(f"DELETE FROM {table}"))

        for spu in _SPUS:
            spu_id = (
                await conn.execute(
                    text(
                        "INSERT INTO merchant_spus (spu_code, title, subtitle, description, category, brand, "
                        "main_image, banner_images, spec_dimensions, specs, status) "
                        "VALUES (:c, :t, :st, :d, :cat, 'AURORA 极光', :img, :banners, :dims, :specs, 'ON_SALE') "
                        "RETURNING id"
                    ),
                    {
                        "c": spu["code"],
                        "t": spu["title"],
                        "st": spu["subtitle"],
                        "d": spu["description"],
                        "cat": spu["category"],
                        "img": spu["main_image"],
                        "banners": json.dumps(spu["banners"], ensure_ascii=False),
                        "dims": json.dumps(spu["dimensions"], ensure_ascii=False),
                        "specs": json.dumps(spu["specs"], ensure_ascii=False),
                    },
                )
            ).scalar_one()

            for code, title, attrs, price, original, stock, barcode in spu["skus"]:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_skus (spu_id, sku_code, sku_title, spec_attributes, price, "
                        "original_price, stock, barcode, image_url) "
                        "VALUES (:spu, :code, :title, :attrs, :price, :orig, :stock, :barcode, :img)"
                    ),
                    {
                        "spu": str(spu_id),
                        "code": code,
                        "title": title,
                        "attrs": json.dumps(attrs, ensure_ascii=False),
                        "price": price,
                        "orig": original,
                        "stock": stock,
                        "barcode": barcode,
                        "img": spu["image"],
                    },
                )

        await conn.execute(
            text(
                "INSERT INTO merchant_customers (customer_id, name, phone, email, member_level, addresses, tags) "
                "VALUES ('CUST-8801', '张伟', '13800138000', 'zhangwei@example.com', '黑金SVIP', :addrs, :tags)"
            ),
            {
                "addrs": json.dumps(
                    [
                        {
                            "id": "addr_01",
                            "recipientName": "张伟",
                            "phone": "13800138000",
                            "fullAddress": "北京市朝阳区建国门外大街1号国贸大厦A座 3801室",
                            "isDefault": True,
                        },
                        {
                            "id": "addr_02",
                            "recipientName": "张伟",
                            "phone": "13800138000",
                            "fullAddress": "北京市海淀区中关村南大街1号院8号楼1201室",
                            "isDefault": False,
                        },
                    ],
                    ensure_ascii=False,
                ),
                "tags": json.dumps(["高净值客户", "户外发烧友", "偏好曜石黑配色"], ensure_ascii=False),
            },
        )

        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "shipping_address, tracking_info, is_returnable, is_address_modifiable) "
                "VALUES ('AURORA-ORD-2026-9081', 'CUST-8801', 'PAID', 1299.0, 'CNY', :addr, NULL, TRUE, TRUE)"
            ),
            {
                "addr": json.dumps(
                    {
                        "recipientName": "张伟",
                        "phone": "13800138000",
                        "fullAddress": "北京市朝阳区建国门外大街1号国贸大厦A座 3801室",
                    },
                    ensure_ascii=False,
                ),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, price, "
                "image_url, spec_summary) "
                "VALUES ('AURORA-ORD-2026-9081', 'SPU-AURORA-001', 'AURORA-SKU-002', "
                "'极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)', '极光三合一冲锋衣 曜石黑 L码 (旗舰主推)', "
                "1, 1299.0, :img, '曜石黑 / L (175/92A)')"
            ),
            {"img": _IMG_1},
        )

        await conn.execute(
            text(
                "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                "shipping_address, tracking_info, is_returnable, is_address_modifiable) "
                "VALUES ('AURORA-ORD-2026-9082', 'CUST-8801', 'SHIPPED', 589.0, 'CNY', :addr, :tracking, TRUE, FALSE)"
            ),
            {
                "addr": json.dumps(
                    {
                        "recipientName": "张伟",
                        "phone": "13800138000",
                        "fullAddress": "北京市海淀区中关村南大街1号院8号楼1201室",
                    },
                    ensure_ascii=False,
                ),
                "tracking": json.dumps(
                    {
                        "carrier": "SF",
                        "trackingNumber": "SF10829384729",
                        "status": "IN_TRANSIT",
                        "latestLocation": "北京顺丰分拨中心",
                    },
                    ensure_ascii=False,
                ),
            },
        )
        await conn.execute(
            text(
                "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, price, "
                "image_url, spec_summary) "
                "VALUES ('AURORA-ORD-2026-9082', 'SPU-AURORA-003', 'AURORA-SKU-003-BLK-L', "
                "'极光 Cordura考杜拉耐磨多袋机能工装裤', 'Cordura机能工装裤 战术黑 L码', 1, 589.0, :img, '战术黑 / L (32腰)')"
            ),
            {"img": _IMG_3},
        )

    print("[Merchant DB] 独立物理数据库 SPU/SKU/Specs 多规格数据初始化完成！")


if __name__ == "__main__":
    asyncio.run(seed_merchant_data())
