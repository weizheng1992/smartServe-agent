"""破损链路三张测试图的确定性生成脚本(random.seed(2026),重跑逐字节复现)。

三张图覆盖售后视觉链路的三条道,与 gateway-py 商户种子的测试订单配套:

1. damaged-order-9083.png  面单 OCR 单号道:纸箱+物流面单(印完整订单号
   AURORA-ORD-2026-9083 与其自有运单号 SF10829384731)+破损章
2. damaged-coffee-set.png  商品损坏消歧道:咖啡套装商品图+玻璃分享壶碎裂标注,
   刻意不印任何单号(订单 9083)——OCR/文本/上下文三通道皆空才触发商品归属消歧
3. damaged-jacket.png      衣服破损消歧道:冲锋衣商品图+面料撕裂破洞标注,
   无单号(订单 9081)

设计决策(2026-09-11 收编留档):
- 破损痕迹为合成标注(红圈/裂纹/黑洞毛边 + 中文标注文本),非真实破损照片:
  vision 链路的定责评级与单号提取依赖标注文本与面单印刷单号,合成图可控可复现。
- 底图 fixture-base-coffee.jpg / fixture-base-jacket.jpg 逐字节入仓;
  重跑本脚本时 damaged-order-9083.png 与 damaged-coffee-set.png 必须 MD5 不变,
  换底图只允许影响对应产物(2026-09-11 品类对齐:旧 jacket 底图实为皮质机车夹克,
  与 SPU-AURORA-001 硬壳冲锋衣品类不符;现底图为黑色硬壳+面料水珠,与
  merchant_seed._IMG_1 同一张照片)。
- 字体锚定 macOS 系统字体(PingFang/Hiragino/Arial Bold),非 macOS 回落
  load_default 会改变字节;入仓的 PNG 是权威产物,本脚本仅供溯源与重生成。

用法::

    uv run --with pillow python docs/assets/gen_damage_fixtures.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import random

random.seed(2026)
OUT = str(Path(__file__).resolve().parent)
RED = (206, 32, 32)
WHITE = (252, 250, 246)
INK = (28, 26, 24)


def font(path: str, size: int):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


F_CN = "/System/Library/Fonts/PingFang.ttc"
F_CN_SB = "/System/Library/Fonts/Hiragino Sans GB.ttc"
F_EN_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def stamp(draw_img: Image.Image, text: str, xy: tuple[int, int], size: int = 88) -> None:
    """旋转红色圆章(破损/碎裂)"""
    f = font(F_CN_SB, size)
    w = size * len(text) + size * 1.6
    st = Image.new("RGBA", (int(w), int(size * 1.8)), (0, 0, 0, 0))
    sd = ImageDraw.Draw(st)
    sd.ellipse([6, 6, w - 6, size * 1.8 - 6], outline=RED + (255,), width=9)
    sd.ellipse([22, 22, w - 22, size * 1.8 - 22], outline=RED + (255,), width=3)
    sd.text((size * 0.8, size * 0.32), text, font=f, fill=RED + (255,))
    st = st.rotate(14, expand=True, resample=Image.BICUBIC)
    draw_img.paste(st, xy, st)


def cracks(d: ImageDraw.ImageDraw, start: tuple[int, int], n: int = 7, drift: int = 0, width: int = 3) -> None:
    """锯齿裂纹"""
    x, y = start
    pts = [(x, y)]
    for _ in range(n):
        x += random.randint(-70, 70) + drift * 6
        y += random.randint(10, 55)
        pts.append((x, y))
    d.line(pts, fill=(52, 42, 34), width=width, joint="curve")


# ---------------------------------------------------------------- 1) 面单 OCR 道
W, H = 1080, 810
CARD = (184, 155, 122)
img = Image.new("RGB", (W, H), CARD)
d = ImageDraw.Draw(img)
for _ in range(2600):
    d.point((random.randint(0, W - 1), random.randint(0, H - 1)),
            fill=random.choice([CARD, (158, 130, 100), (196, 168, 134), (170, 143, 112)]))
for x0, x1 in [(60, 300), (720, 1020)]:
    d.polygon([(x0, 0), (x1, 0), (x1 - 40, H), (x0 - 40, H)], fill=(216, 205, 178))
d.line([(0, 120), (W, 90)], fill=(158, 130, 100), width=6)
d.line([(0, 640), (W, 610)], fill=(158, 130, 100), width=6)

f_label, f_head = font(F_CN, 30), font(F_CN, 36)
f_order, f_small = font(F_EN_B, 58), font(F_CN, 26)
LX, LY, LW, LH = 150, 170, 780, 430
d.rounded_rectangle([LX, LY, LX + LW, LY + LH], radius=14, fill=WHITE, outline=INK, width=3)
d.text((LX + 36, LY + 30), "AURORA 极光潮品 · 物流面单", font=f_head, fill=INK)
d.line([(LX + 36, LY + 92), (LX + LW - 36, LY + 92)], fill=INK, width=2)
d.text((LX + 36, LY + 118), "订单号 ORDER NO.", font=f_small, fill=(110, 105, 98))
d.text((LX + 30, LY + 148), "AURORA-ORD-2026-9083", font=f_order, fill=INK)
d.text((LX + 36, LY + 232), "商品:极光 户外便携手冲咖啡套装(全家福)", font=f_label, fill=INK)
d.text((LX + 36, LY + 282), "收件人:张伟  138****8000", font=f_label, fill=INK)
d.text((LX + 36, LY + 332), "承运:顺丰速运 SF10829384731", font=f_label, fill=INK)
bx, by, x = LX + 36, LY + LH - 78, LX + 36
for w_ in random.choices([4, 7, 11, 14], k=28):
    d.rectangle([x, by, x + w_, by + 54], fill=INK)
    x += w_ + random.choice([5, 8, 10])
d.text((bx, by + 58), "6901 2340 0221", font=f_small, fill=INK)
for start, drift in [((880, 620), -6), ((300, 700), 5), ((560, 120), 4)]:
    cracks(d, start, drift=drift)
stamp(img, "破损", (640, 560))
d.text((150, 660), "开箱照片:玻璃分享壶碎裂,申请售后", font=f_label, fill=(70, 60, 50))
img.save(f"{OUT}/damaged-order-9083.png", "PNG")
print("1 ok", img.size)

# ---------------------------------------------------- 2) 咖啡套装商品破损消歧道
base = Image.open(f"{OUT}/fixture-base-coffee.jpg").convert("RGB")
if base.width > 1080:
    base = base.resize((1080, int(base.height * 1080 / base.width)))
img = base.copy()
d = ImageDraw.Draw(img, "RGBA")
W2, H2 = img.size
# 分享壶碎裂:壶身区域红圈 + 放射状裂纹 + 碎玻璃白点
cx, cy, rx, ry = int(W2 * 0.62), int(H2 * 0.45), int(W2 * 0.16), int(H2 * 0.22)
d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], outline=RED + (230,), width=7)
for ang in range(0, 360, 30):
    import math
    ex = cx + int(rx * 1.15 * math.cos(math.radians(ang)))
    ey = cy + int(ry * 1.15 * math.sin(math.radians(ang)))
    d.line([(cx, cy), (ex, ey)], fill=(240, 240, 240, 200), width=3)
for _ in range(60):
    px = cx + random.randint(-rx, rx)
    py = cy + random.randint(-ry, ry)
    d.line([(px, py), (px + random.randint(-14, 14), py + random.randint(-14, 14))],
           fill=(250, 250, 250, 230), width=2)
f_anno, f_tip = font(F_CN, 40), font(F_CN, 26)
tag = "分享壶玻璃碎裂"
tb = d.textbbox((0, 0), tag, font=f_anno)
d.rounded_rectangle([40, 36, 40 + tb[2] + 36, 36 + tb[3] + 28], radius=12, fill=RED + (235,))
d.text((58, 50), tag, font=f_anno, fill=(255, 255, 255, 255))
d.text((40, H2 - 56), "商品成色:破损(severe)·申请退货退款", font=f_tip, fill=WHITE)
d.rectangle([36, H2 - 62, 36 + d.textlength("商品成色:破损(severe)·申请退货退款", font=f_tip) + 10, H2 - 10],
            fill=(20, 20, 20, 160))
d.text((40, H2 - 56), "商品成色:破损(severe)·申请退货退款", font=f_tip, fill=WHITE)
stamp(img, "碎裂", (W2 - 300, H2 - 260), size=72)
img.save(f"{OUT}/damaged-coffee-set.png", "PNG")
print("2 ok", img.size)

# ------------------------------------------------------ 3) 冲锋衣衣服破损消歧道
base = Image.open(f"{OUT}/fixture-base-jacket.jpg").convert("RGB")
if base.width > 900:
    base = base.resize((900, int(base.height * 900 / base.width)))
img = base.copy()
d = ImageDraw.Draw(img, "RGBA")
W3, H3 = img.size
# 面料撕裂破洞:躯干中上部不规则黑洞 + 白色毛边 + 红圈标注
cx, cy = int(W3 * 0.5), int(H3 * 0.38)
hole = [(cx, cy)]
for ang in range(0, 360, 24):
    import math
    r = random.randint(38, 85)
    hole.append((cx + int(r * math.cos(math.radians(ang))), cy + int(r * 0.75 * math.sin(math.radians(ang)))))
d.polygon(hole, fill=(24, 22, 20, 255))
d.line(hole + [hole[0]], fill=(240, 240, 240, 220), width=4, joint="curve")
for _ in range(28):  # 撕裂毛边纤维
    a = random.uniform(0, 6.28)
    r0 = random.randint(70, 95)
    fx, fy = cx + int(r0 * math.cos(a)), cy + int(r0 * 0.75 * math.sin(a))
    d.line([(fx, fy), (fx + random.randint(-12, 12), fy + random.randint(-12, 12))],
           fill=(235, 235, 235, 210), width=2)
d.ellipse([cx - 130, cy - 110, cx + 130, cy + 105], outline=RED + (235,), width=7)
f_anno, f_tip = font(F_CN, 40), font(F_CN, 26)
tag = "面料撕裂破洞"
tb = d.textbbox((0, 0), tag, font=f_anno)
d.rounded_rectangle([40, 36, 40 + tb[2] + 36, 36 + tb[3] + 28], radius=12, fill=RED + (235,))
d.text((58, 50), tag, font=f_anno, fill=(255, 255, 255, 255))
d.rectangle([36, H3 - 62, 36 + d.textlength("衣服到货即破损,要求退货", font=f_tip) + 10, H3 - 10],
            fill=(20, 20, 20, 160))
d.text((40, H3 - 56), "衣服到货即破损,要求退货", font=f_tip, fill=WHITE)
stamp(img, "破损", (W3 - 280, H3 - 280), size=72)
img.save(f"{OUT}/damaged-jacket.png", "PNG")
print("3 ok", img.size)
