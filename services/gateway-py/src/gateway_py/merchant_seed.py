"""商户独立库种子数据 — 源自退役的 apps/merchant/src/db/seed.ts(SPU/SKU/多规格矩阵),
并在其基础上扩容为多品类目录。

6 大品类 18 个 SPU(户外机能 / 潮流T恤 / 下装裤类 / 潮流鞋靴 / 背包收纳 / 露营装备),
每类 3 个 SPU、每个 SPU 带 2-6 个 SKU。测试客户 CUST-8801 名下三单,配合
docs/assets/ 下三张破损测试图覆盖售后视觉链路的三条道:

- AURORA-ORD-2026-9081 冲锋衣(PAID)  ← damaged-jacket.png(衣服破损,无单号,走商品归属消歧)
- AURORA-ORD-2026-9082 工装裤(SHIPPED) ← 双重退款回放基线单(engine 测试引用)
- AURORA-ORD-2026-9083 咖啡套装(SHIPPED 已签收) ← damaged-order-9083.png(面单 OCR 单号)+
  damaged-coffee-set.png(商品破损,无单号,走消歧与破损定责)

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
_IMG_PUFFER = "https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=800&auto=format&fit=crop&q=60"
_IMG_SOFTSHELL = "https://images.unsplash.com/photo-1596783074918-c84cb06531ca?w=800&auto=format&fit=crop&q=60"
_IMG_SHIRTS = "https://images.unsplash.com/photo-1523381210434-271e8be1f52b?w=800&auto=format&fit=crop&q=60"
_IMG_RACK = "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?w=800&auto=format&fit=crop&q=60"
_IMG_DENIM = "https://images.unsplash.com/photo-1475178626620-a4d074967452?w=800&auto=format&fit=crop&q=60"
_IMG_JOGGER = "https://images.unsplash.com/photo-1520975954732-35dd22299614?w=800&auto=format&fit=crop&q=60"
_IMG_TRAIL = "https://images.unsplash.com/photo-1533867617858-e7b97e060509?w=800&auto=format&fit=crop&q=60"
_IMG_BOOT = "https://images.unsplash.com/photo-1520639888713-7851133b1ed0?w=800&auto=format&fit=crop&q=60"
_IMG_BACKPACK_CITY = "https://images.unsplash.com/photo-1553062407-98eeb64c6a62?w=800&auto=format&fit=crop&q=60"
_IMG_BACKPACK_HIKE = "https://images.unsplash.com/photo-1491637639811-60e2756cc1c7?w=800&auto=format&fit=crop&q=60"
_IMG_SLING = "https://images.unsplash.com/photo-1564859228273-274232fdb516?w=800&auto=format&fit=crop&q=60"
_IMG_COFFEE = "https://images.unsplash.com/photo-1442512595331-e89e73853f31?w=800&auto=format&fit=crop&q=60"
_IMG_TENT = "https://images.unsplash.com/photo-1504280390367-361c6d9f38f4?w=800&auto=format&fit=crop&q=60"
_IMG_CAMP = "https://images.unsplash.com/photo-1517824806704-9040b037703b?w=800&auto=format&fit=crop&q=60"
_IMG_SLEEP = "https://images.unsplash.com/photo-1510312305653-8ed496efae75?w=800&auto=format&fit=crop&q=60"

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
        "code": "SPU-AURORA-005",
        "title": "极光 800蓬白鹅绒可收纳轻量羽绒中间层夹克",
        "subtitle": "800蓬RDS鹅绒 | 20D防绒面料 | 1.2L收纳袋随身带",
        "description": "90% 白鹅绒 800 蓬松度填充，配 20D 高密防绒尼龙外壳与无氟 DWR 防泼水处理。可整件卷入自带收纳袋压缩至 1.2L，通勤打底与营地保暖两相宜。",
        "category": "户外机能",
        "main_image": _IMG_PUFFER,
        "banners": [_IMG_PUFFER, _IMG_1B],
        "dimensions": [
            {"name": "颜色", "values": ["曜石黑", "岩石灰", "苔原绿"]},
            {"name": "尺码", "values": ["S", "M", "L", "XL"]},
        ],
        "specs": {
            "填充物": "90/10 白鹅绒 800蓬松度 (RDS认证)",
            "充绒量": "180g (M码)",
            "面料": "20D 尼龙防绒 + 无氟DWR防泼水",
            "收纳体积": "约1.2L 自带收纳袋",
            "适用场景": "中间层保暖/城市通勤",
        },
        "image": _IMG_PUFFER,
        "skus": [
            ("AURORA-SKU-005-BLK-M", "800蓬羽绒中间层 曜石黑 M码", {"颜色": "曜石黑", "尺码": "M"}, 899.0, 1199.0, 45, "690123400201"),
            ("AURORA-SKU-005-BLK-L", "800蓬羽绒中间层 曜石黑 L码", {"颜色": "曜石黑", "尺码": "L"}, 899.0, 1199.0, 60, "690123400202"),
            ("AURORA-SKU-005-GRY-L", "800蓬羽绒中间层 岩石灰 L码", {"颜色": "岩石灰", "尺码": "L"}, 899.0, 1199.0, 38, None),
            ("AURORA-SKU-005-GRN-M", "800蓬羽绒中间层 苔原绿 M码", {"颜色": "苔原绿", "尺码": "M"}, 929.0, 1199.0, 22, None),
        ],
    },
    {
        "code": "SPU-AURORA-006",
        "title": "极光 四向弹力防泼水软壳夹克",
        "subtitle": "无氟DWR | 8000g透气 | 3D人体工学剪裁",
        "description": "双织弹力软壳面料，92% 聚酰胺 + 8% 氨纶四向高弹，内侧磨毛抓绒轻量锁温。无氟 DWR 防泼水应对阵雨，春秋徒步与城市通勤的均衡之选。",
        "category": "户外机能",
        "main_image": _IMG_SOFTSHELL,
        "banners": [_IMG_SOFTSHELL],
        "dimensions": [
            {"name": "颜色", "values": ["石墨黑", "雾霾蓝"]},
            {"name": "尺码", "values": ["M", "L", "XL"]},
        ],
        "specs": {
            "面料材质": "92%聚酰胺 + 8%氨纶双织弹力软壳",
            "防泼水": "无氟DWR持久处理",
            "透气指数": "8000g/m²/24h",
            "剪裁": "3D人体工学拼接",
            "适用场景": "春秋徒步/城市通勤",
        },
        "image": _IMG_SOFTSHELL,
        "skus": [
            ("AURORA-SKU-006-BLK-M", "弹力软壳夹克 石墨黑 M码", {"颜色": "石墨黑", "尺码": "M"}, 649.0, 849.0, 58, "690123400203"),
            ("AURORA-SKU-006-BLK-L", "弹力软壳夹克 石墨黑 L码", {"颜色": "石墨黑", "尺码": "L"}, 649.0, 849.0, 72, "690123400204"),
            ("AURORA-SKU-006-BLU-L", "弹力软壳夹克 雾霾蓝 L码", {"颜色": "雾霾蓝", "尺码": "L"}, 649.0, 849.0, 40, None),
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
        "code": "SPU-AURORA-007",
        "title": "极光 17.5微米美利奴羊毛天然温控短袖T恤",
        "subtitle": "新西兰美利奴 | 无侧缝一体织 | 天然抗味",
        "description": "17.5 微米细支美利奴羊毛，190g/m² 轻量平织，天然温控吸湿排汗且抗菌抗味，多日穿着无异味。无侧缝一体编织工艺消除长途徒步磨点。",
        "category": "潮流T恤",
        "main_image": _IMG_SHIRTS,
        "banners": [_IMG_SHIRTS, _IMG_2],
        "dimensions": [
            {"name": "颜色", "values": ["燕麦色", "炭灰", "藏青"]},
            {"name": "尺码", "values": ["S", "M", "L", "XL"]},
        ],
        "specs": {
            "面料材质": "100% 17.5μm 新西兰美利奴羊毛",
            "克重": "190g/m² 轻量平织",
            "特性": "天然温控 + 抗菌抗味",
            "工艺": "无侧缝一体编织",
            "适用场景": "贴身基础层/长途旅行",
        },
        "image": _IMG_SHIRTS,
        "skus": [
            ("AURORA-SKU-007-OAT-M", "美利奴羊毛T恤 燕麦色 M码", {"颜色": "燕麦色", "尺码": "M"}, 399.0, 499.0, 85, "690123400205"),
            ("AURORA-SKU-007-OAT-L", "美利奴羊毛T恤 燕麦色 L码", {"颜色": "燕麦色", "尺码": "L"}, 399.0, 499.0, 90, "690123400206"),
            ("AURORA-SKU-007-GRY-L", "美利奴羊毛T恤 炭灰 L码", {"颜色": "炭灰", "尺码": "L"}, 399.0, 499.0, 64, None),
            ("AURORA-SKU-007-NVY-L", "美利奴羊毛T恤 藏青 L码", {"颜色": "藏青", "尺码": "L"}, 399.0, 499.0, 48, None),
        ],
    },
    {
        "code": "SPU-AURORA-008",
        "title": "极光 凉感抗菌速干机能POLO衫",
        "subtitle": "Q-max≥0.4接触凉感 | 银离子抗菌 | 商务运动两穿",
        "description": "77% 锦纶 + 23% 氨纶凉感纱线，接触凉感系数 Q-max≥0.4，汗液扩散速干。银离子抗菌处理抑制异味，修身剪裁高尔夫与通勤皆宜。",
        "category": "潮流T恤",
        "main_image": _IMG_RACK,
        "banners": [_IMG_RACK],
        "dimensions": [
            {"name": "颜色", "values": ["月光白", "火山黑"]},
            {"name": "尺码", "values": ["M", "L", "XL", "XXL"]},
        ],
        "specs": {
            "面料材质": "77%锦纶 + 23%氨纶凉感纱",
            "接触凉感": "Q-max ≥ 0.4",
            "抗菌": "银离子抗菌处理",
            "版型": "修身 商务/运动两穿",
            "速干": "汗液扩散 <3s",
        },
        "image": _IMG_RACK,
        "skus": [
            ("AURORA-SKU-008-WHT-M", "凉感速干POLO 月光白 M码", {"颜色": "月光白", "尺码": "M"}, 459.0, 559.0, 70, "690123400207"),
            ("AURORA-SKU-008-WHT-L", "凉感速干POLO 月光白 L码", {"颜色": "月光白", "尺码": "L"}, 459.0, 559.0, 82, "690123400208"),
            ("AURORA-SKU-008-BLK-L", "凉感速干POLO 火山黑 L码", {"颜色": "火山黑", "尺码": "L"}, 459.0, 559.0, 66, None),
            ("AURORA-SKU-008-BLK-XL", "凉感速干POLO 火山黑 XL码", {"颜色": "火山黑", "尺码": "XL"}, 459.0, 559.0, 35, None),
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
        "code": "SPU-AURORA-009",
        "title": "极光 3L全压胶防水登山冲锋裤",
        "subtitle": "20K防水 | 全侧开YKK拉链 | 防磨护踝",
        "description": "3L 复合膜面料 20000mmH2O 防水 15000g 透气，全衣 13mm 压胶条。侧身 YKK 全开防水拉链穿脱不脱靴，膝部立体剪裁与下摆防磨护踝经久耐用。",
        "category": "下装裤类",
        "main_image": _IMG_DENIM,
        "banners": [_IMG_DENIM, _IMG_3],
        "dimensions": [
            {"name": "颜色", "values": ["曜石黑", "岩灰"]},
            {"name": "尺码", "values": ["M (30腰)", "L (32腰)", "XL (34腰)"]},
        ],
        "specs": {
            "面料材质": "3L 复合膜 20K/15K 防水透气",
            "压胶": "全衣 13mm 压胶条",
            "侧拉链": "YKK 全侧开防水拉链",
            "加固": "膝部立体剪裁 + 防磨护踝",
        },
        "image": _IMG_DENIM,
        "skus": [
            ("AURORA-SKU-009-BLK-M", "3L冲锋裤 曜石黑 M码", {"颜色": "曜石黑", "尺码": "M (30腰)"}, 1099.0, 1399.0, 30, "690123400209"),
            ("AURORA-SKU-009-BLK-L", "3L冲锋裤 曜石黑 L码", {"颜色": "曜石黑", "尺码": "L (32腰)"}, 1099.0, 1399.0, 42, "690123400210"),
            ("AURORA-SKU-009-GRY-L", "3L冲锋裤 岩灰 L码", {"颜色": "岩灰", "尺码": "L (32腰)"}, 1099.0, 1399.0, 26, None),
        ],
    },
    {
        "code": "SPU-AURORA-010",
        "title": "极光 420g重磅毛圈棉抽绳束脚慢跑裤",
        "subtitle": "420g毛圈棉 | 后防盗拉链袋 | 高弹罗纹收口",
        "description": "420g 重磅毛圈棉混纺，垂坠有型不起球。侧插袋 + 后防盗拉链袋，裤脚高弹罗纹收口配抽绳，宽松锥形版型居家露营两相宜。",
        "category": "下装裤类",
        "main_image": _IMG_JOGGER,
        "banners": [_IMG_JOGGER],
        "dimensions": [
            {"name": "颜色", "values": ["炭黑", "浅麻灰", "橄榄绿"]},
            {"name": "尺码", "values": ["S", "M", "L", "XL"]},
        ],
        "specs": {
            "面料材质": "420g 重磅毛圈棉混纺",
            "口袋": "侧插袋 + 后防盗拉链袋",
            "裤脚": "高弹罗纹收口 + 抽绳",
            "版型": "宽松锥形 Easy Fit",
        },
        "image": _IMG_JOGGER,
        "skus": [
            ("AURORA-SKU-010-BLK-M", "重磅束脚慢跑裤 炭黑 M码", {"颜色": "炭黑", "尺码": "M"}, 349.0, 429.0, 110, "690123400211"),
            ("AURORA-SKU-010-BLK-L", "重磅束脚慢跑裤 炭黑 L码", {"颜色": "炭黑", "尺码": "L"}, 349.0, 429.0, 96, "690123400212"),
            ("AURORA-SKU-010-GRY-L", "重磅束脚慢跑裤 浅麻灰 L码", {"颜色": "浅麻灰", "尺码": "L"}, 349.0, 429.0, 70, None),
            ("AURORA-SKU-010-GRN-M", "重磅束脚慢跑裤 橄榄绿 M码", {"颜色": "橄榄绿", "尺码": "M"}, 349.0, 429.0, 52, None),
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
    {
        "code": "SPU-AURORA-011",
        "title": "极光 全掌碳板深齿抓地越野跑鞋",
        "subtitle": "5mm深齿粘性橡胶 | PEBA超临界中底 | 单只245g",
        "description": "全掌碳板 + PEBA 超临界发泡中底，能量回馈 82%。5mm 深齿粘性橡胶大底征服泥地碎石，TPU 防石纱网鞋面轻量抗撕裂，单只仅 245g。",
        "category": "潮流鞋靴",
        "main_image": _IMG_TRAIL,
        "banners": [_IMG_TRAIL],
        "dimensions": [
            {"name": "颜色", "values": ["荧光橙/黑", "湖蓝/白"]},
            {"name": "尺码", "values": ["40码 (250mm)", "41码 (255mm)", "42码 (260mm)", "43码 (265mm)"]},
        ],
        "specs": {
            "大底": "5mm 深齿粘性橡胶",
            "中底": "全掌碳板 + PEBA 超临界发泡 (能量回馈82%)",
            "鞋面": "TPU 防石纱网",
            "重量": "单只 245g (42码)",
            "适用场景": "山地越野/竞速训练",
        },
        "image": _IMG_TRAIL,
        "skus": [
            ("AURORA-SKU-011-ORG-41", "碳板越野跑鞋 荧光橙 41码", {"颜色": "荧光橙/黑", "尺码": "41码 (255mm)"}, 1099.0, 1299.0, 24, "690123400213"),
            ("AURORA-SKU-011-ORG-42", "碳板越野跑鞋 荧光橙 42码", {"颜色": "荧光橙/黑", "尺码": "42码 (260mm)"}, 1099.0, 1299.0, 32, "690123400214"),
            ("AURORA-SKU-011-BLU-42", "碳板越野跑鞋 湖蓝 42码", {"颜色": "湖蓝/白", "尺码": "42码 (260mm)"}, 1099.0, 1299.0, 20, None),
            ("AURORA-SKU-011-BLU-43", "碳板越野跑鞋 湖蓝 43码", {"颜色": "湖蓝/白", "尺码": "43码 (265mm)"}, 1099.0, 1299.0, 15, None),
        ],
    },
    {
        "code": "SPU-AURORA-012",
        "title": "极光 ePE防水膜低帮徒步登山鞋",
        "subtitle": "Vibram TC5+大底 | 头层牛皮 | TPU抗扭中桥",
        "description": "头层牛皮与防泼水网布拼接鞋面，ePE 环保防水膜全天候保持干爽。Vibram TC5+ 多向齿纹大底，TPU 中桥抗扭支撑，一日轻装徒步利器。",
        "category": "潮流鞋靴",
        "main_image": _IMG_BOOT,
        "banners": [_IMG_BOOT],
        "dimensions": [
            {"name": "颜色", "values": ["岩石棕", "纯黑"]},
            {"name": "尺码", "values": ["41码 (255mm)", "42码 (260mm)", "43码 (265mm)", "44码 (270mm)"]},
        ],
        "specs": {
            "鞋面材质": "头层牛皮 + 防泼水网布",
            "防水": "ePE 环保防水膜",
            "大底": "Vibram® TC5+ 多向齿纹",
            "支撑": "TPU 中桥抗扭",
            "适用场景": "一日徒步/轻装登山",
        },
        "image": _IMG_BOOT,
        "skus": [
            ("AURORA-SKU-012-BRN-42", "低帮徒步登山鞋 岩石棕 42码", {"颜色": "岩石棕", "尺码": "42码 (260mm)"}, 799.0, 999.0, 36, "690123400215"),
            ("AURORA-SKU-012-BRN-43", "低帮徒步登山鞋 岩石棕 43码", {"颜色": "岩石棕", "尺码": "43码 (265mm)"}, 799.0, 999.0, 30, None),
            ("AURORA-SKU-012-BLK-42", "低帮徒步登山鞋 纯黑 42码", {"颜色": "纯黑", "尺码": "42码 (260mm)"}, 799.0, 999.0, 44, None),
        ],
    },
    {
        "code": "SPU-AURORA-013",
        "title": "极光 城市通勤防泼水双肩包",
        "subtitle": "500D考杜拉 | 16寸悬浮电脑仓 | 蜂窝透气背板",
        "description": "500D Cordura 防泼水面料，26L 版配 16 英寸悬浮减震电脑仓。蜂窝透气背板 + 胸扣减压设计，通勤装载与周末短途一包搞定。",
        "category": "背包收纳",
        "main_image": _IMG_BACKPACK_CITY,
        "banners": [_IMG_BACKPACK_CITY],
        "dimensions": [
            {"name": "颜色", "values": ["午夜黑", "军绿灰"]},
            {"name": "容量", "values": ["18L 轻量版", "26L 电脑仓版"]},
        ],
        "specs": {
            "面料材质": "500D Cordura 防泼水尼龙",
            "电脑仓": "16英寸悬浮减震仓 (26L版)",
            "背板": "蜂窝透气 + 胸扣减压",
            "重量": "890g (26L版)",
        },
        "image": _IMG_BACKPACK_CITY,
        "skus": [
            ("AURORA-SKU-013-BLK-18L", "通勤双肩包 午夜黑 18L", {"颜色": "午夜黑", "容量": "18L 轻量版"}, 499.0, 649.0, 65, "690123400216"),
            ("AURORA-SKU-013-BLK-26L", "通勤双肩包 午夜黑 26L", {"颜色": "午夜黑", "容量": "26L 电脑仓版"}, 569.0, 699.0, 80, "690123400217"),
            ("AURORA-SKU-013-ARM-26L", "通勤双肩包 军绿灰 26L", {"颜色": "军绿灰", "容量": "26L 电脑仓版"}, 569.0, 699.0, 45, None),
        ],
    },
    {
        "code": "SPU-AURORA-014",
        "title": "极光 高山徒步轻量化背包 38L/45L",
        "subtitle": "210D Robic尼龙 | 铝合金可调背架 | 自带防雨罩",
        "description": "210D Robic 高韧尼龙 + UHMWPE 纤维加强，铝合金中空可调节背架适配背长。自带防雨罩与水袋仓，45L 版自重仅 1.35kg。",
        "category": "背包收纳",
        "main_image": _IMG_BACKPACK_HIKE,
        "banners": [_IMG_BACKPACK_HIKE],
        "dimensions": [
            {"name": "颜色", "values": ["熔岩红", "苔原绿"]},
            {"name": "容量", "values": ["38L", "45L"]},
        ],
        "specs": {
            "面料材质": "210D Robic 尼龙 + UHMWPE 加强",
            "背负": "铝合金中空可调节背架",
            "重量": "1.35kg (45L版)",
            "配置": "防雨罩 + 水袋仓 + 冰镐挂点",
        },
        "image": _IMG_BACKPACK_HIKE,
        "skus": [
            ("AURORA-SKU-014-RED-45L", "徒步背包 熔岩红 45L", {"颜色": "熔岩红", "容量": "45L"}, 899.0, 1099.0, 28, "690123400218"),
            ("AURORA-SKU-014-GRN-38L", "徒步背包 苔原绿 38L", {"颜色": "苔原绿", "容量": "38L"}, 829.0, 999.0, 20, None),
            ("AURORA-SKU-014-GRN-45L", "徒步背包 苔原绿 45L", {"颜色": "苔原绿", "容量": "45L"}, 899.0, 1099.0, 24, None),
        ],
    },
    {
        "code": "SPU-AURORA-015",
        "title": "极光 多功能防泼水斜挎胸包",
        "subtitle": "4L主仓 | UTX扣具 | 磁吸快拉仓",
        "description": "420D 防泼水尼龙 4L 容量，主仓磁吸快开，隐藏背板袋收纳证件。UTX/Duraflex 扣具与可调织带，通勤骑行轻装出行。",
        "category": "背包收纳",
        "main_image": _IMG_SLING,
        "banners": [_IMG_SLING],
        "dimensions": [
            {"name": "颜色", "values": ["战术黑", "沙色"]},
        ],
        "specs": {
            "面料材质": "420D 防泼水尼龙",
            "容量": "4L 主仓 + 隐藏背板袋",
            "扣具": "UTX / Duraflex",
            "特色": "磁吸快开主仓",
        },
        "image": _IMG_SLING,
        "skus": [
            ("AURORA-SKU-015-BLK", "机能斜挎胸包 战术黑", {"颜色": "战术黑"}, 259.0, 329.0, 120, "690123400219"),
            ("AURORA-SKU-015-TAN", "机能斜挎胸包 沙色", {"颜色": "沙色"}, 259.0, 329.0, 95, None),
        ],
    },
    {
        "code": "SPU-AURORA-016",
        "title": "极光 户外便携手冲咖啡套装 (耐热玻璃分享壶)",
        "subtitle": "高硼硅玻璃分享壶 | 陶瓷扇形滤杯 | 钛合金保温壶",
        "description": "营地晨间咖啡方案：600ml 高硼硅耐热玻璃分享壶（耐温差 150℃，玻璃制品运输易碎）、#02 陶瓷扇形滤杯与钛合金外壳保温壶。全家福套装另配手摇磨豆机。",
        "category": "露营装备",
        "main_image": _IMG_COFFEE,
        "banners": [_IMG_COFFEE, _IMG_CAMP],
        "dimensions": [
            {"name": "颜色", "values": ["原野绿", "皓月白"]},
            {"name": "规格", "values": ["滤杯套装 (壶+滤杯)", "全家福套装 (+手摇磨)"]},
        ],
        "specs": {
            "分享壶": "600ml 高硼硅耐热玻璃 (耐温差150℃)",
            "滤杯": "#02 陶瓷扇形滤杯",
            "保温壶": "600ml 钛合金外壳",
            "易碎提示": "玻璃制品，运输需加固防护",
            "适用场景": "露营/居家手冲",
        },
        "image": _IMG_COFFEE,
        "skus": [
            ("AURORA-SKU-016-GRN-BASIC", "手冲咖啡套装 原野绿 滤杯套装", {"颜色": "原野绿", "规格": "滤杯套装 (壶+滤杯)"}, 329.0, 429.0, 58, "690123400220"),
            ("AURORA-SKU-016-GRN-FULL", "手冲咖啡套装 原野绿 全家福套装", {"颜色": "原野绿", "规格": "全家福套装 (+手摇磨)"}, 459.0, 599.0, 36, "690123400221"),
            ("AURORA-SKU-016-WHT-FULL", "手冲咖啡套装 皓月白 全家福套装", {"颜色": "皓月白", "规格": "全家福套装 (+手摇磨)"}, 459.0, 599.0, 29, None),
        ],
    },
    {
        "code": "SPU-AURORA-017",
        "title": "极光 轻量化双人双层露营帐篷",
        "subtitle": "20D硅涂尼龙 | 防水3000mm | 3分钟快搭",
        "description": "双层交叉杆自立结构，20D 硅涂尼龙外帐防水 3000mm，全帐压胶。双人版自重 2.4kg，前庭双门对流，3 分钟一人可搭。",
        "category": "露营装备",
        "main_image": _IMG_TENT,
        "banners": [_IMG_TENT, _IMG_CAMP],
        "dimensions": [
            {"name": "颜色", "values": ["极光绿", "落日橙"]},
            {"name": "规格", "values": ["双人 2.4kg", "三人 2.9kg"]},
        ],
        "specs": {
            "结构": "双层交叉杆自立帐",
            "外帐面料": "20D 硅涂尼龙 防水3000mm",
            "重量": "2.4kg (双人) / 2.9kg (三人)",
            "搭建": "3分钟快搭",
        },
        "image": _IMG_TENT,
        "skus": [
            ("AURORA-SKU-017-GRN-2P", "双人帐篷 极光绿 双人", {"颜色": "极光绿", "规格": "双人 2.4kg"}, 1299.0, 1599.0, 25, "690123400222"),
            ("AURORA-SKU-017-ORG-2P", "双人帐篷 落日橙 双人", {"颜色": "落日橙", "规格": "双人 2.4kg"}, 1299.0, 1599.0, 30, "690123400223"),
            ("AURORA-SKU-017-ORG-3P", "双人帐篷 落日橙 三人", {"颜色": "落日橙", "规格": "三人 2.9kg"}, 1499.0, 1799.0, 18, None),
        ],
    },
    {
        "code": "SPU-AURORA-018",
        "title": "极光 700蓬鹅绒木乃伊睡袋 (舒适温标-5℃)",
        "subtitle": "700蓬RDS鹅绒 | 15D防绒尼龙 | 1.1kg轻量",
        "description": "700 蓬 RDS 白鹅绒填充，15D 防绒尼龙面料，立体风琴隔舱杜绝冷点。0℃ / -5℃ 两档温标，压缩后 35×22cm，自重仅 1.1kg。",
        "category": "露营装备",
        "main_image": _IMG_SLEEP,
        "banners": [_IMG_SLEEP, _IMG_CAMP],
        "dimensions": [
            {"name": "颜色", "values": ["石墨灰", "湖蓝"]},
            {"name": "温标", "values": ["舒适0℃", "舒适-5℃"]},
        ],
        "specs": {
            "填充物": "700蓬 RDS 白鹅绒",
            "面料": "15D 防绒尼龙",
            "温标": "舒适 0℃ / -5℃ 两档",
            "收纳": "35×22cm 压缩袋",
            "重量": "1.1kg",
        },
        "image": _IMG_SLEEP,
        "skus": [
            ("AURORA-SKU-018-GRY-0C", "木乃伊睡袋 石墨灰 舒适0℃", {"颜色": "石墨灰", "温标": "舒适0℃"}, 899.0, 1099.0, 32, "690123400224"),
            ("AURORA-SKU-018-GRY-M5C", "木乃伊睡袋 石墨灰 舒适-5℃", {"颜色": "石墨灰", "温标": "舒适-5℃"}, 999.0, 1199.0, 26, "690123400225"),
            ("AURORA-SKU-018-BLU-M5C", "木乃伊睡袋 湖蓝 舒适-5℃", {"颜色": "湖蓝", "温标": "舒适-5℃"}, 999.0, 1199.0, 20, None),
        ],
    },
]

_ADDR_GUOMAO = {
    "recipientName": "张伟",
    "phone": "13800138000",
    "fullAddress": "北京市朝阳区建国门外大街1号国贸大厦A座 3801室",
}
_ADDR_ZHONGGUANCUN = {
    "recipientName": "张伟",
    "phone": "13800138000",
    "fullAddress": "北京市海淀区中关村南大街1号院8号楼1201室",
}

# 订单清单:数据与 INSERT 循环分离,断言期望值由 len() 派生(播种不断言=假绿)
_ORDERS = [
    {
        "order_id": "AURORA-ORD-2026-9081",
        "status": "PAID",
        "total": 1299.0,
        "address": _ADDR_GUOMAO,
        "tracking": None,
        "returnable": True,
        "address_modifiable": True,
        "items": [
            {
                "spu": "SPU-AURORA-001",
                "sku": "AURORA-SKU-002",
                "title": "极光三合一全天候户外硬壳冲锋衣 (2026款旗舰版)",
                "sku_title": "极光三合一冲锋衣 曜石黑 L码 (旗舰主推)",
                "quantity": 1,
                "price": 1299.0,
                "image": _IMG_1,
                "spec": "曜石黑 / L (175/92A)",
            }
        ],
    },
    {
        "order_id": "AURORA-ORD-2026-9082",
        "status": "SHIPPED",
        "total": 589.0,
        "address": _ADDR_ZHONGGUANCUN,
        "tracking": {
            "carrier": "SF",
            "trackingNumber": "SF10829384729",
            "status": "IN_TRANSIT",
            "latestLocation": "北京顺丰分拨中心",
        },
        "returnable": True,
        "address_modifiable": False,
        "items": [
            {
                "spu": "SPU-AURORA-003",
                "sku": "AURORA-SKU-003-BLK-L",
                "title": "极光 Cordura考杜拉耐磨多袋机能工装裤",
                "sku_title": "Cordura机能工装裤 战术黑 L码",
                "quantity": 1,
                "price": 589.0,
                "image": _IMG_3,
                "spec": "战术黑 / L (32腰)",
            }
        ],
    },
    {
        # OCR/破损链路测试单:易碎玻璃制品,已签收开箱破损,与 docs/assets/ 两张咖啡套装测试图配套
        "order_id": "AURORA-ORD-2026-9083",
        "status": "SHIPPED",
        "total": 459.0,
        "address": _ADDR_GUOMAO,
        "tracking": {
            "carrier": "SF",
            "trackingNumber": "SF10829384731",
            "status": "DELIVERED",
            "latestLocation": "北京朝阳国贸营业点",
        },
        "returnable": True,
        "address_modifiable": False,
        "items": [
            {
                "spu": "SPU-AURORA-016",
                "sku": "AURORA-SKU-016-GRN-FULL",
                "title": "极光 户外便携手冲咖啡套装 (耐热玻璃分享壶)",
                "sku_title": "手冲咖啡套装 原野绿 全家福套装",
                "quantity": 1,
                "price": 459.0,
                "image": _IMG_COFFEE,
                "spec": "原野绿 / 全家福套装",
            }
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
                        "VALUES (:c, :t, :subtitle, :d, :cat, 'AURORA 极光', :img, :banners, :dims, :specs, 'ON_SALE') "
                        "RETURNING id"
                    ),
                    {
                        "c": spu["code"],
                        "t": spu["title"],
                        "subtitle": spu["subtitle"],
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
                # 地址与订单侧 shipping_address 同源:复用 _ADDR_* 常量,不再三字段逐字双写
                "addrs": json.dumps(
                    [
                        {"id": "addr_01", **_ADDR_GUOMAO, "isDefault": True},
                        {"id": "addr_02", **_ADDR_ZHONGGUANCUN, "isDefault": False},
                    ],
                    ensure_ascii=False,
                ),
                "tags": json.dumps(["高净值客户", "户外发烧友", "偏好曜石黑配色"], ensure_ascii=False),
            },
        )

        for order in _ORDERS:
            await conn.execute(
                text(
                    "INSERT INTO merchant_orders (order_id, customer_id, status, total_amount, currency, "
                    "shipping_address, tracking_info, is_returnable, is_address_modifiable) "
                    "VALUES (:oid, 'CUST-8801', :status, :total, 'CNY', :addr, :tracking, :ret, :modif)"
                ),
                {
                    "oid": order["order_id"],
                    "status": order["status"],
                    "total": order["total"],
                    "addr": json.dumps(order["address"], ensure_ascii=False),
                    "tracking": json.dumps(order["tracking"], ensure_ascii=False) if order["tracking"] else None,
                    "ret": order["returnable"],
                    "modif": order["address_modifiable"],
                },
            )
            for it in order["items"]:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, "
                        "price, image_url, spec_summary) "
                        "VALUES (:oid, :spu, :sku, :t, :sku_title, :q, :p, :img, :spec)"
                    ),
                    {
                        "oid": order["order_id"],
                        "spu": it["spu"],
                        "sku": it["sku"],
                        "t": it["title"],
                        "sku_title": it["sku_title"],
                        "q": it["quantity"],
                        "p": it["price"],
                        "img": it["image"],
                        "spec": it["spec"],
                    },
                )

        # 行数断言:播种静默假绿防线(DELETE 后按清单逐条 INSERT,缺行/多行必须炸出来)
        spu_rows = (await conn.execute(text("SELECT COUNT(*) FROM merchant_spus"))).scalar_one()
        sku_rows = (await conn.execute(text("SELECT COUNT(*) FROM merchant_skus"))).scalar_one()
        order_rows = (await conn.execute(text("SELECT COUNT(*) FROM merchant_orders"))).scalar_one()
        item_rows = (await conn.execute(text("SELECT COUNT(*) FROM merchant_order_items"))).scalar_one()
        expected_skus = sum(len(spu["skus"]) for spu in _SPUS)
        expected_items = sum(len(order["items"]) for order in _ORDERS)
        assert spu_rows == len(_SPUS), f"SPU 落库 {spu_rows} 行,预期 {len(_SPUS)}"
        assert sku_rows == expected_skus, f"SKU 落库 {sku_rows} 行,预期 {expected_skus}"
        assert order_rows == len(_ORDERS), f"订单落库 {order_rows} 行,预期 {len(_ORDERS)}"
        assert item_rows == expected_items, f"订单行落库 {item_rows} 行,预期 {expected_items}"

    print(
        f"[Merchant DB] 播种完成:{len(_SPUS)} SPU / {expected_skus} SKU / "
        f"{len(_ORDERS)} 订单(含破损链路测试单 AURORA-ORD-2026-9083)"
    )


if __name__ == "__main__":
    asyncio.run(seed_merchant_data())
