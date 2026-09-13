"""商户独立库种子数据 — 源自退役的 apps/merchant/src/db/seed.ts(SPU/SKU/多规格矩阵),
并在其基础上扩容为多品类目录。

9 大品类 30 个 SPU(户外机能 / 潮流T恤 / 下装裤类 / 潮流鞋靴 / 背包收纳 / 露营装备 /
衬衫 / 配饰 / 运动配件),92 个 SKU。另含 27 笔演示历史交易(ADR-0002 Q5/Q8):
销量聚合有真实感分布(头部 4~8 件 / 腰部 1~3 件 / 约 1/3 SPU 零销量),含 REFUNDED
单供「排除退款」聚合验证;聚合永远运行时真算,严禁写死成「热度」。测试客户 CUST-8801 名下三单,配合
docs/assets/ 下三张破损测试图覆盖售后视觉链路的三条道:

- AURORA-ORD-2026-9081 冲锋衣(PAID)  ← damaged-jacket.png(衣服破损,无单号,走商品归属消歧)
- AURORA-ORD-2026-9082 工装裤(SHIPPED) ← 双重退款回放基线单(engine 测试引用)
- AURORA-ORD-2026-9083 咖啡套装(SHIPPED 已签收) ← damaged-order-9083.png(面单 OCR 单号)+
  damaged-coffee-set.png(商品破损,无单号,走消歧与破损定责)

破损测试图为合成标注图(docs/assets/gen_damage_fixtures.py 确定性生成,random.seed(2026)):
真实商品底图上绘制红圈/裂纹/破洞与中文标注文本 —— vision 链路依赖标注文本与
面单印刷单号定责,合成图可控可复现;底图与产物逐字节入仓,重跑脚本时
damaged-order-9083.png 与 damaged-coffee-set.png 两张必须 MD5 不变。
damaged-jacket.png 的底图与 _IMG_1 是同一张照片(黑色硬壳冲锋衣,一处换图两处受益)。

用法::

    cd services/gateway-py && uv run python -m gateway_py.merchant_seed
"""

from __future__ import annotations

import asyncio
import json
import zlib

from sqlalchemy import text

from .merchant_db import ensure_merchant_tables, merchant_engine

# 黑色硬壳冲锋衣(面料带水珠,贴「暴雨级防水」卖点);damaged-jacket.png 底图同源
_IMG_1 = "https://images.unsplash.com/photo-1654719796836-62b889d4598d?w=800&auto=format&fit=crop&q=60"
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


_COST_RATIOS = (0.42, 0.45, 0.48, 0.52)


def _demo_cost(price: float, sku_code: str) -> float:
    """演示进价(ADR-0003 Q1):按 SKU 编码 crc32 确定性取成本系数(42%~52%),
    跨进程可复现;排行毛利永远运行时真算,严禁把这里的系数写死成任何「利润」。"""
    return round(price * _COST_RATIOS[zlib.crc32(sku_code.encode()) % len(_COST_RATIOS)], 2)


# 品类评价模板(2026-09-13):{模板池} × crc32 取模确定性生成 —— 评价是演示
# 数据(商品即演示商品),内容写真实感口碑,严禁编造具体性能参数。
_REVIEW_TEMPLATES: dict[str, list[tuple[int, str]]] = {
    "服装": [
        (5, "面料厚实有垂感，做工走线工整，洗了两水没有起球变形，好评。"),
        (5, "版型正，上身效果和详情页一致，颜色耐看，值得回购。"),
        (4, "整体满意，尺码按建议买的正合适，快递也快。"),
        (4, "质感对得起价格，缝线细节到位，家人也说好看。"),
        (3, "款式不错，不过面料手感比想象中略硬一点，穿穿应该会软。"),
    ],
    "鞋靴": [
        (5, "上脚舒服，缓震回弹明显，走一天不累脚，五星。"),
        (5, "鞋楦宽松适合我的脚型，做工没得挑，第二次买这个牌子了。"),
        (4, "颜值和舒适度都在线，码数按脚长买的正好，防滑也不错。"),
        (4, "透气性可以，走路轻，就是新鞋略有磨合期。"),
        (3, "外观好看，偏码半码，建议按脚长选。"),
    ],
    "背包": [
        (5, "背负系统给力，装满走一天肩膀不勒，分区设计合理。"),
        (5, "做工扎实，拉链顺滑，容量比看着能装，通勤徒步都能用。"),
        (4, "自重轻，收纳位多，防泼水效果下小雨够用。"),
        (4, "扣具结实，背板透气，性价比可以。"),
        (3, "功能没问题，颜色比图片深一点。"),
    ],
    "露营": [
        (5, "搭起来快，防水经受住一夜大雨，内帐不返潮。"),
        (5, "做工和细节都在线，收纳体积友好，露营体验加分包。"),
        (4, "稳定性不错，风夜里撑得住，配件齐全。"),
        (4, "防水面料质感好，搭建说明清楚，新手也能搞定。"),
        (3, "整体可以，重量对徒步党略友好度一般，自驾无所谓。"),
    ],
    "配饰": [
        (5, "细节精致，材质摸着舒服，送人也拿得出手。"),
        (5, "实用又好看，日常百搭，物超所值。"),
        (4, "做工可以，功能实用，满意度高。"),
        (4, "质感不错，包装也体面。"),
        (3, "中规中矩，符合预期。"),
    ],
}

_CATEGORY_TEMPLATE_KEY = {
    "潮流T恤": "服装", "衬衫": "服装", "下装裤类": "服装", "户外机能": "服装",
    "潮流鞋靴": "鞋靴", "背包收纳": "背包", "露营装备": "露营", "配饰": "配饰", "运动配件": "配饰",
}


def _demo_reviews(spu_code: str, category: str, title: str) -> list[tuple[int, str]]:
    """确定性评价生成:品类模板池,crc32 选起点与条数(4~5 条),星级 3-5
    分布模拟真实口碑分层。"""
    pool = _REVIEW_TEMPLATES[_CATEGORY_TEMPLATE_KEY.get(category, "配饰")]
    seed_val = zlib.crc32(spu_code.encode())
    count = 4 + (seed_val % 2)
    picked = [pool[(seed_val + offset) % len(pool)] for offset in range(count)]
    return picked


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
    {
        'code': "SPU-AURORA-019",
        'title': "极光 UPF40+ 速干透气户外机能长袖衬衫",
        'subtitle': "UPF40+防晒 | 速干排汗 | 拉链透气井",
        'description': "远足徒步与日常通勤两用的机能长袖衬衫,UPF40+ 抗紫外线面料配合速干排汗纤维,胸前拉链透气井与卷袖袢设计应对多变山野天气。",
        'category': "衬衫",
        'main_image': _IMG_SHIRTS,
        'banners': [_IMG_SHIRTS, _IMG_RACK],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["云白", "沙棕"],
            },
            {
                'name': "尺码",
                'values': ["M (170/88A)", "L (175/92A)"],
            },
        ],
        'specs': {
            '面料材质': "92% 锦纶 + 8% 氨纶",
            '防晒指数': "UPF40+",
            '功能': "速干排汗 / 抗紫外线",
            '版型': "常规修身",
        },
        'skus': [
            ("AURORA-SKU-019-WHT-M", "速干机能衬衫 云白 M码", {
                '颜色': "云白",
                '尺码': "M (170/88A)",
            }, 399.0, 499.0, 40, "690123419011"),
            ("AURORA-SKU-019-WHT-L", "速干机能衬衫 云白 L码", {
                '颜色': "云白",
                '尺码': "L (175/92A)",
            }, 399.0, 499.0, 52, "690123419012"),
            ("AURORA-SKU-019-SAN-M", "速干机能衬衫 沙棕 M码", {
                '颜色': "沙棕",
                '尺码': "M (170/88A)",
            }, 399.0, 499.0, 28, "690123419013"),
            ("AURORA-SKU-019-SAN-L", "速干机能衬衫 沙棕 L码", {
                '颜色': "沙棕",
                '尺码': "L (175/92A)",
            }, 399.0, 499.0, 33, "690123419014"),
        ],
        'image': _IMG_SHIRTS,
    },
    {
        'code': "SPU-AURORA-020",
        'title': "极光 磨毛法兰绒保暖格纹长袖衬衫",
        'subtitle': "磨毛法兰绒 | 复古格纹 | 起绒保暖",
        'description': "精梳棉磨毛法兰绒,双面起绒亲肤保暖;经典复古格纹,山系穿搭与秋冬通勤都能压得住场。",
        'category': "衬衫",
        'main_image': _IMG_RACK,
        'banners': [_IMG_RACK, _IMG_SHIRTS],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["铁灰格", "驼棕格"],
            },
            {
                'name': "尺码",
                'values': ["M (170/88A)", "L (175/92A)", "XL (180/96A)"],
            },
        ],
        'specs': {
            '面料材质': "100% 精梳棉(磨毛法兰绒)",
            '克重': "260g/㎡",
            '功能': "起绒保暖",
            '版型': "宽松落肩",
        },
        'skus': [
            ("AURORA-SKU-020-GRY-M", "法兰绒格纹衬衫 铁灰格 M码", {
                '颜色': "铁灰格",
                '尺码': "M (170/88A)",
            }, 459.0, 559.0, 25, "690123420011"),
            ("AURORA-SKU-020-GRY-L", "法兰绒格纹衬衫 铁灰格 L码", {
                '颜色': "铁灰格",
                '尺码': "L (175/92A)",
            }, 459.0, 559.0, 30, "690123420012"),
            ("AURORA-SKU-020-TAN-L", "法兰绒格纹衬衫 驼棕格 L码", {
                '颜色': "驼棕格",
                '尺码': "L (175/92A)",
            }, 459.0, 559.0, 18, "690123420013"),
        ],
        'image': _IMG_RACK,
    },
    {
        'code': "SPU-AURORA-021",
        'title': "极光 120g超轻可收纳防晒皮肤短袖衬衫",
        'subtitle': "超轻120g | 可收纳自带袋 | DWR防泼水",
        'description': "仅 120g 的超轻皮肤衬衫,自带收纳袋可压缩至掌心大小;DWR 防泼水处理应对夏日阵雨,UPF30+ 日常通勤防晒足够。",
        'category': "衬衫",
        'main_image': _IMG_SHIRTS,
        'banners': [_IMG_SHIRTS],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["云白", "湖蓝"],
            },
            {
                'name': "尺码",
                'values': ["M (170/88A)", "L (175/92A)"],
            },
        ],
        'specs': {
            '面料材质': "100% 锦纶 20D",
            '重量': "约120g(≈L码)",
            '功能': "防泼水 / UPF30+",
            '收纳': "自带掌心收纳袋",
        },
        'skus': [
            ("AURORA-SKU-021-WHT-M", "超轻皮肤衬衫 云白 M码", {
                '颜色': "云白",
                '尺码': "M (170/88A)",
            }, 329.0, 399.0, 36, "690123421011"),
            ("AURORA-SKU-021-WHT-L", "超轻皮肤衬衫 云白 L码", {
                '颜色': "云白",
                '尺码': "L (175/92A)",
            }, 329.0, 399.0, 42, "690123421012"),
            ("AURORA-SKU-021-BLU-L", "超轻皮肤衬衫 湖蓝 L码", {
                '颜色': "湖蓝",
                '尺码': "L (175/92A)",
            }, 329.0, 399.0, 20, "690123421013"),
        ],
        'image': _IMG_SHIRTS,
    },
    {
        'code': "SPU-AURORA-022",
        'title': "极光 亚麻混纺透气度假休闲短袖衬衫",
        'subtitle': "亚麻混纺 | 透气垂坠 | 度假廓形",
        'description': "55% 亚麻混纺带来天然透气与垂坠廓形,海岛度假与夏日 citywalk 都合适的松弛感短袖衬衫。",
        'category': "衬衫",
        'main_image': _IMG_SHIRTS,
        'banners': [_IMG_SHIRTS, _IMG_DENIM],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["米杏", "靛蓝"],
            },
            {
                'name': "尺码",
                'values': ["M (170/88A)", "L (175/92A)"],
            },
        ],
        'specs': {
            '面料材质': "55% 亚麻 + 45% 棉",
            '功能': "透气吸湿",
            '版型': "度假宽松廓形",
        },
        'skus': [
            ("AURORA-SKU-022-BEG-M", "亚麻度假衬衫 米杏 M码", {
                '颜色': "米杏",
                '尺码': "M (170/88A)",
            }, 379.0, 459.0, 22, "690123422011"),
            ("AURORA-SKU-022-BEG-L", "亚麻度假衬衫 米杏 L码", {
                '颜色': "米杏",
                '尺码': "L (175/92A)",
            }, 379.0, 459.0, 26, "690123422012"),
        ],
        'image': _IMG_SHIRTS,
    },
    {
        'code': "SPU-AURORA-023",
        'title': "极光 UPF50+ 可折叠双面戴渔夫帽",
        'subtitle': "UPF50+ | 可折叠随行 | 双面两戴",
        'description': "UPF50+ 防晒渔夫帽,帽檐定型可任意折叠不塌;双面两戴一帽两色,收纳进背包侧袋毫无存在感。",
        'category': "配饰",
        'main_image': _IMG_CAMP,
        'banners': [_IMG_CAMP],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["卡其", "藏青"],
            },
            {
                'name': "尺码",
                'values': ["均码 (56-60cm)"],
            },
        ],
        'specs': {
            '材质': "锦纶 + UPF50+ 涂层",
            '帽檐': "7.5cm 定型宽檐",
            '功能': "可折叠 / 双面两戴",
        },
        'skus': [
            ("AURORA-SKU-023-KH-F", "防晒渔夫帽 卡其 均码", {
                '颜色': "卡其",
                '尺码': "均码 (56-60cm)",
            }, 129.0, 159.0, 60, "690123423011"),
            ("AURORA-SKU-023-NVY-F", "防晒渔夫帽 藏青 均码", {
                '颜色': "藏青",
                '尺码': "均码 (56-60cm)",
            }, 129.0, 159.0, 55, "690123423012"),
        ],
        'image': _IMG_CAMP,
    },
    {
        'code': "SPU-AURORA-024",
        'title': "极光 防风保暖触屏魔术手套",
        'subtitle': "触屏指尖 | 防风抓绒 | 弹力贴合",
        'description': "防风抓绒外层搭配导电触屏指尖,冬天刷手机不用脱手套;四面弹力贴合手型,骑行通勤山野皆宜。",
        'category': "配饰",
        'main_image': _IMG_SLEEP,
        'banners': [_IMG_SLEEP],
        'dimensions': [
            {
                'name': "尺码",
                'values': ["M", "L"],
            },
        ],
        'specs': {
            '材质': "抓绒 + 导电纤维指尖",
            '功能': "触屏 / 防风保暖",
        },
        'skus': [
            ("AURORA-SKU-024-BLK-M", "触屏保暖手套 黑色 M码", {
                '尺码': "M",
            }, 99.0, 129.0, 48, "690123424011"),
            ("AURORA-SKU-024-BLK-L", "触屏保暖手套 黑色 L码", {
                '尺码': "L",
            }, 99.0, 129.0, 44, "690123424012"),
        ],
        'image': _IMG_SLEEP,
    },
    {
        'code': "SPU-AURORA-025",
        'title': "极光 速干无缝多功能魔术头巾围脖",
        'subtitle': "无缝编织 | 速干吸汗 | 12种戴法",
        'description': "无缝圆筒编织不勒头,速干吸汗面料;面罩、发带、围脖、头巾十二种戴法,是山野多面手。",
        'category': "配饰",
        'main_image': _IMG_CAMP,
        'banners': [_IMG_CAMP],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["曜黑", "雾灰"],
            },
            {
                'name': "尺码",
                'values': ["均码"],
            },
        ],
        'specs': {
            '材质': "90% 涤纶 + 10% 氨纶",
            '功能': "速干 / 无缝 / 多用途",
        },
        'skus': [
            ("AURORA-SKU-025-BLK-F", "魔术头巾围脖 曜黑 均码", {
                '颜色': "曜黑",
                '尺码': "均码",
            }, 59.0, 79.0, 80, "690123425011"),
            ("AURORA-SKU-025-GRY-F", "魔术头巾围脖 雾灰 均码", {
                '颜色': "雾灰",
                '尺码': "均码",
            }, 59.0, 79.0, 75, "690123425012"),
        ],
        'image': _IMG_CAMP,
    },
    {
        'code': "SPU-AURORA-026",
        'title': "极光 宽檐透气可调节防晒空顶帽",
        'subtitle': "宽檐大帽檐 | 空顶透气 | 围头可调节",
        'description': "空顶设计头顶散热,宽檐全向遮阳;围头魔术贴可调节,跑步徒步都不晃。",
        'category': "配饰",
        'main_image': _IMG_CAMP,
        'banners': [_IMG_CAMP],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["米白", "军绿"],
            },
            {
                'name': "尺码",
                'values': ["均码 (54-60cm)", "加大 (60-63cm)"],
            },
        ],
        'specs': {
            '材质': "轻量锦纶",
            '帽檐': "9cm 超宽檐",
            '功能': "空顶透气 / 可调节",
        },
        'skus': [
            ("AURORA-SKU-026-WHT-F", "防晒空顶帽 米白 均码", {
                '颜色': "米白",
                '尺码': "均码 (54-60cm)",
            }, 139.0, 169.0, 38, "690123426011"),
            ("AURORA-SKU-026-GRN-F", "防晒空顶帽 军绿 均码", {
                '颜色': "军绿",
                '尺码': "均码 (54-60cm)",
            }, 139.0, 169.0, 35, "690123426012"),
            ("AURORA-SKU-026-GRN-L", "防晒空顶帽 军绿 加大", {
                '颜色': "军绿",
                '尺码': "加大 (60-63cm)",
            }, 139.0, 169.0, 12, "690123426013"),
        ],
        'image': _IMG_CAMP,
    },
    {
        'code': "SPU-AURORA-027",
        'title': "极光 Tritan大容量便携弹盖运动水壶",
        'subtitle': "Tritan材质 | 1L大容量 | 弹盖直饮",
        'description': "食品级 Tritan 材质耐摔无异味,1L 大容量减少接水次数;单手弹盖直饮,登山骑行办公都顺手。",
        'category': "运动配件",
        'main_image': _IMG_CAMP,
        'banners': [_IMG_CAMP],
        'dimensions': [
            {
                'name': "容量",
                'values': ["750ml", "1L"],
            },
        ],
        'specs': {
            '材质': "食品级 Tritan",
            '耐温': "-10℃~96℃",
            '功能': "弹盖直饮 / 挂环便携",
        },
        'skus': [
            ("AURORA-SKU-027-750", "便携运动水壶 750ml", {
                '容量': "750ml",
            }, 79.0, 99.0, 66, "690123427011"),
            ("AURORA-SKU-027-1L", "便携运动水壶 1L", {
                '容量': "1L",
            }, 89.0, 109.0, 58, "690123427012"),
        ],
        'image': _IMG_CAMP,
    },
    {
        'code': "SPU-AURORA-028",
        'title': "极光 硅胶缓震环透气针织运动护膝",
        'subtitle': "硅胶缓震环 | 透气针织 | 左右通用",
        'description': "环形硅胶缓震垫稳定髌骨,三维针织逐区透气加压;跑步登山羽毛球,膝盖不舒服时它最懂。",
        'category': "运动配件",
        'main_image': _IMG_TRAIL,
        'banners': [_IMG_TRAIL],
        'dimensions': [
            {
                'name': "尺码",
                'values': ["M", "L", "XL"],
            },
        ],
        'specs': {
            '材质': "尼龙针织 + 硅胶缓震环",
            '功能': "缓震 / 加压 / 透气",
            '适用': "跑步 / 登山 / 球类",
        },
        'skus': [
            ("AURORA-SKU-028-M", "缓震运动护膝 M码", {
                '尺码': "M",
            }, 149.0, 179.0, 30, "690123428011"),
            ("AURORA-SKU-028-L", "缓震运动护膝 L码", {
                '尺码': "L",
            }, 149.0, 179.0, 34, "690123428012"),
            ("AURORA-SKU-028-XL", "缓震运动护膝 XL码", {
                '尺码': "XL",
            }, 149.0, 179.0, 16, "690123428013"),
        ],
        'image': _IMG_TRAIL,
    },
    {
        'code': "SPU-AURORA-029",
        'title': "极光 8mm加厚TPE双面防滑瑜伽垫",
        'subtitle': "8mm加厚 | TPE双面防滑 | 附绑带",
        'description': "8mm 加厚缓冲护膝护踝,TPE 双面防滑纹路抓地稳;自带绑带收纳,家练外出都轻便。",
        'category': "运动配件",
        'main_image': _IMG_CAMP,
        'banners': [_IMG_CAMP],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["紫灰", "暮蓝"],
            },
        ],
        'specs': {
            '材质': "TPE 双层",
            '厚度': "8mm",
            '功能': "双面防滑 / 附收纳绑带",
        },
        'skus': [
            ("AURORA-SKU-029-GRY", "TPE瑜伽垫 紫灰", {
                '颜色': "紫灰",
            }, 199.0, 239.0, 26, "690123429011"),
            ("AURORA-SKU-029-BLU", "TPE瑜伽垫 暮蓝", {
                '颜色': "暮蓝",
            }, 199.0, 239.0, 24, "690123429012"),
        ],
        'image': _IMG_CAMP,
    },
    {
        'code': "SPU-AURORA-030",
        'title': "极光 三档亮度USB-C磁吸露营营地灯",
        'subtitle': "三档亮度 | USB-C充电 | 磁吸悬挂",
        'description': "三档亮度一键切换,最高 300 流明照亮整顶帐篷;底部磁吸 + 提挂两用,USB-C 快充 6 小时续航。",
        'category': "运动配件",
        'main_image': _IMG_TENT,
        'banners': [_IMG_TENT],
        'dimensions': [
            {
                'name': "颜色",
                'values': ["曜黑", "军绿"],
            },
        ],
        'specs': {
            '亮度': "最高300流明/三档",
            '充电': "USB-C / 6小时续航",
            '安装': "磁吸 + 提挂两用",
        },
        'skus': [
            ("AURORA-SKU-030-BLK", "露营营地灯 曜黑", {
                '颜色': "曜黑",
            }, 169.0, 199.0, 32, "690123430011"),
            ("AURORA-SKU-030-GRN", "露营营地灯 军绿", {
                '颜色': "军绿",
            }, 169.0, 199.0, 28, "690123430012"),
        ],
        'image': _IMG_TENT,
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
        "days_ago": 30,
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
        "days_ago": 21,
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
        "days_ago": 14,
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


# ---------------------------------------------------------------------------
# 演示历史交易(ADR-0002 Q5/Q8):使销量聚合有真实感分布 —— 头部 4~8 件、
# 腰部 1~3 件、约 1/3 SPU 零销量(诚实长尾),并含 REFUNDED 单供「排除退款」
# 聚合逻辑真实验证。数据诚实边界:这是演示环境的合法 seed 数据;排行/热销
# 永远运行时真聚合,严禁任何代码把这里的行数写死成「热度」。
_HISTORY_ITEMS = [
    # (order_id, status, days_ago, [(spu_code, sku_code, qty), ...])
    ("AURORA-ORD-2026-9091", "PAID", 2, [("SPU-AURORA-002", "AURORA-SKU-002-GRY-M", 2), ("SPU-AURORA-027", "AURORA-SKU-027-750", 1)]),
    ("AURORA-ORD-2026-9092", "SHIPPED", 3, [("SPU-AURORA-001", "AURORA-SKU-002", 1)]),
    ("AURORA-ORD-2026-9093", "DELIVERED", 6, [("SPU-AURORA-004", "AURORA-SKU-004-GRY-41", 1), ("SPU-AURORA-002", "AURORA-SKU-002-GRY-L", 1)]),
    ("AURORA-ORD-2026-9094", "PAID", 9, [("SPU-AURORA-012", "AURORA-SKU-012-BRN-42", 1)]),
    ("AURORA-ORD-2026-9095", "SHIPPED", 12, [("SPU-AURORA-014", "AURORA-SKU-014-RED-45L", 1), ("SPU-AURORA-015", "AURORA-SKU-015-BLK", 1)]),
    ("AURORA-ORD-2026-9096", "DELIVERED", 14, [("SPU-AURORA-002", "AURORA-SKU-002-GRY-M", 2)]),
    ("AURORA-ORD-2026-9097", "PAID", 16, [("SPU-AURORA-005", "AURORA-SKU-005-BLK-M", 1)]),
    ("AURORA-ORD-2026-9098", "SHIPPED", 18, [("SPU-AURORA-017", "AURORA-SKU-017-GRN-2P", 1)]),
    ("AURORA-ORD-2026-9099", "REFUNDED", 20, [("SPU-AURORA-004", "AURORA-SKU-004-GRY-42", 2)]),
    ("AURORA-ORD-2026-9100", "SHIPPED", 22, [("SPU-AURORA-019", "AURORA-SKU-019-WHT-L", 1), ("SPU-AURORA-023", "AURORA-SKU-023-KH-F", 1)]),
    ("AURORA-ORD-2026-9101", "DELIVERED", 24, [("SPU-AURORA-004", "AURORA-SKU-004-GRY-41", 1), ("SPU-AURORA-012", "AURORA-SKU-012-BRN-43", 1)]),
    ("AURORA-ORD-2026-9102", "PAID", 26, [("SPU-AURORA-014", "AURORA-SKU-014-RED-45L", 2)]),
    ("AURORA-ORD-2026-9103", "SHIPPED", 28, [("SPU-AURORA-001", "AURORA-SKU-002", 1), ("SPU-AURORA-006", "AURORA-SKU-006-BLK-M", 1)]),
    ("AURORA-ORD-2026-9104", "DELIVERED", 30, [("SPU-AURORA-002", "AURORA-SKU-002-GRY-L", 1), ("SPU-AURORA-015", "AURORA-SKU-015-TAN", 1), ("SPU-AURORA-027", "AURORA-SKU-027-1L", 1)]),
    ("AURORA-ORD-2026-9105", "PAID", 32, [("SPU-AURORA-003", "AURORA-SKU-003-BLK-M", 1)]),
    ("AURORA-ORD-2026-9106", "SHIPPED", 34, [("SPU-AURORA-001", "AURORA-SKU-001-BLK-M", 1), ("SPU-AURORA-013", "AURORA-SKU-013-BLK-18L", 1)]),
    ("AURORA-ORD-2026-9107", "DELIVERED", 36, [("SPU-AURORA-004", "AURORA-SKU-004-GRY-41", 1), ("SPU-AURORA-011", "AURORA-SKU-011-ORG-41", 1)]),
    ("AURORA-ORD-2026-9108", "DELIVERED", 38, [("SPU-AURORA-005", "AURORA-SKU-005-BLK-L", 1), ("SPU-AURORA-016", "AURORA-SKU-016-GRN-BASIC", 1)]),
    ("AURORA-ORD-2026-9109", "SHIPPED", 40, [("SPU-AURORA-012", "AURORA-SKU-012-BRN-42", 1), ("SPU-AURORA-018", "AURORA-SKU-018-GRY-0C", 1)]),
    ("AURORA-ORD-2026-9110", "DELIVERED", 42, [("SPU-AURORA-002", "AURORA-SKU-002-GRY-M", 1), ("SPU-AURORA-004", "AURORA-SKU-004-GRY-41", 1)]),
    ("AURORA-ORD-2026-9111", "REFUNDED", 44, [("SPU-AURORA-014", "AURORA-SKU-014-GRN-38L", 1)]),
    ("AURORA-ORD-2026-9112", "SHIPPED", 46, [("SPU-AURORA-001", "AURORA-SKU-001-BLK-M", 1), ("SPU-AURORA-013", "AURORA-SKU-013-BLK-26L", 1)]),
    ("AURORA-ORD-2026-9113", "PAID", 48, [("SPU-AURORA-012", "AURORA-SKU-012-BRN-43", 1), ("SPU-AURORA-003", "AURORA-SKU-003-BLK-L", 1)]),
    ("AURORA-ORD-2026-9114", "SHIPPED", 50, [("SPU-AURORA-005", "AURORA-SKU-005-BLK-M", 1), ("SPU-AURORA-019", "AURORA-SKU-019-SAN-L", 1)]),
    ("AURORA-ORD-2026-9115", "DELIVERED", 52, [("SPU-AURORA-004", "AURORA-SKU-004-GRY-42", 1)]),
    ("AURORA-ORD-2026-9116", "SHIPPED", 54, [("SPU-AURORA-015", "AURORA-SKU-015-BLK", 1), ("SPU-AURORA-023", "AURORA-SKU-023-NVY-F", 1)]),
    ("AURORA-ORD-2026-9117", "SHIPPED", 57, [("SPU-AURORA-017", "AURORA-SKU-017-ORG-2P", 1)]),
]


def _build_history_orders() -> list[dict]:
    """从 _SPUS 目录派生历史单行项目(title/价格取自 SKU 真值,单一事实源)。"""
    sku_index = {sku[0]: (spu, sku) for spu in _SPUS for sku in spu["skus"]}
    orders: list[dict] = []
    seq = 1
    for oid, status, days_ago, items in _HISTORY_ITEMS:
        rows = []
        for spu_code, sku_code, qty in items:
            spu, sku = sku_index[sku_code]
            rows.append(
                {
                    "spu": spu_code,
                    "sku": sku_code,
                    "title": spu["title"],
                    "sku_title": sku[1],
                    "quantity": qty,
                    "price": float(sku[3]),
                    "image": spu.get("image") or spu["main_image"],
                    "spec": " / ".join(str(v) for v in sku[2].values()),
                }
            )
        tracking = None
        if status in ("SHIPPED", "DELIVERED"):
            tracking = {
                "carrier": "SF",
                "trackingNumber": f"SF10829385{seq:03d}",
                "status": "DELIVERED" if status == "DELIVERED" else "IN_TRANSIT",
                "latestLocation": "北京朝阳国贸营业点" if status == "DELIVERED" else "北京顺丰分拨中心",
            }
            seq += 1
        orders.append(
            {
                "order_id": oid,
                "status": status,
                "days_ago": days_ago,
                "total": sum(r["price"] * r["quantity"] for r in rows),
                "address": _ADDR_GUOMAO if int(oid[-1]) % 2 else _ADDR_ZHONGGUANCUN,
                "tracking": tracking,
                "returnable": True,
                "address_modifiable": status == "PAID",
                "items": rows,
            }
        )
    return orders


_ORDERS.extend(_build_history_orders())


async def seed_merchant_data() -> None:
    await ensure_merchant_tables()
    print("[Merchant DB] 开始执行独立商户多规格领域数据 Seed 初始化...")

    async with merchant_engine().begin() as conn:
        for table in (
            "merchant_product_reviews",
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
                        "original_price, stock, barcode, image_url, cost_price) "
                        "VALUES (:spu, :code, :title, :attrs, :price, :orig, :stock, :barcode, :img, :cost)"
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
                        "cost": _demo_cost(price, code),
                    },
                )

            # 商品评价(2026-09-13):确定性生成,品类模板 + spu_code 哈希取模选词
            # —— 「评价好的X」的真实数据面。评价为演示数据(商品即演示商品),
            # 内容按品类写真实感口碑,不入具体假参数。
            for rating, content in _demo_reviews(spu["code"], spu["category"], spu["title"]):
                await conn.execute(
                    text(
                        "INSERT INTO merchant_product_reviews (spu_id, customer_id, rating, content) "
                        "VALUES (:spu, :cust, :rating, :content)"
                    ),
                    {"spu": str(spu_id), "cust": None, "rating": rating, "content": content},
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
                    "shipping_address, tracking_info, is_returnable, is_address_modifiable, created_at) "
                    "VALUES (:oid, 'CUST-8801', :status, :total, 'CNY', :addr, :tracking, :ret, :modif, "
                    "NOW() - make_interval(days => :days))"
                ),
                {
                    "oid": order["order_id"],
                    "status": order["status"],
                    "total": order["total"],
                    "addr": json.dumps(order["address"], ensure_ascii=False),
                    "tracking": json.dumps(order["tracking"], ensure_ascii=False) if order["tracking"] else None,
                    "ret": order["returnable"],
                    "modif": order["address_modifiable"],
                    "days": order.get("days_ago", 0),
                },
            )
            for it in order["items"]:
                await conn.execute(
                    text(
                        "INSERT INTO merchant_order_items (order_id, spu_id, sku_code, title, sku_title, quantity, "
                        "price, image_url, spec_summary, cost_at_purchase) "
                        "VALUES (:oid, :spu, :sku, :t, :sku_title, :q, :p, :img, :spec, :cost)"
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
                        "cost": _demo_cost(it["price"], it["sku"]),
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
