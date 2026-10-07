"""导购词族与问句解析(纯函数;cart/resolver 先例)。

正则编译与检索前的文本分析在此单一落点 —— 不触数据通路。ShoppingGuideSkill
类上的四个别名(_FALLBACK_RE/_ABSENCE_ANCHOR_RE/OUTFIT_RE/CLOTHING_ANCHOR_RE)
是给 routing / 词族之家测试的兼容面:同一编译对象,永不漂移。
"""

from __future__ import annotations

import re

from ...triage.intent_registry import (
    ABSENCE_EXTRA_FAMILY,
    CLOTHING_ANCHOR_FAMILY,
    GUIDE_CORE_FAMILY,
    _alt,
    _grp,
)

# 规格问句识别(2026-09-12):命中即对检索首位商品直查真货架 SKU
SPEC_ASK_RE = re.compile(r"(规格|尺码|尺寸|颜色|码数|参数|型号)")

# 上下文指代式对比(2026-09-14):「最贵的和最便宜的对比」—— 无品类词,
# 指代上一轮检索
COMPARE_RE = re.compile(r"(?:对比|不同|差别|区别|比一比)")

# 价位带指代(S5,2026-09-15):「有没有中间价位的」—— 无品类词指代上轮
PRICE_BAND_RE = re.compile(r"(?:中间价位|中间价|价位段|中等价位)")

# 与 slot_extractor 的 SHOPPING_GUIDE 规则同源补词(2026-09-07):热门/爆款类
# 措辞也须被 is_action_query 视作动作形输入,拒绝命中语义回复缓存。
# 2026-09-12:补入 卖得好/卖的好(与 slot_extractor 同步,见该处注释)。
GUIDE_FALLBACK_RE = re.compile(
    _grp(*GUIDE_CORE_FAMILY),
    re.IGNORECASE,
)

# 否定购买意向(2026-09-14 N2 实报):「我不想买了/别推荐」严禁再搜索推荐
NEGATIVE_INTENT_RE = re.compile(r"(?:不想买|别.{0,2}推荐|不要推荐|不再推荐|停止推荐)")

# 🧳 搭配形态(2026-09-27 实弹事故):「搭配一套…装备和衣服」是多族组合
# 诉求。单脚整句检索下「装备」ILIKE 命中品类列「露营装备」即把 limit 全部
# 吃满(3 件露营装备零衣服),而「衣服」在货架零词法足迹(货架以 衬衫/
# T恤/裤/夹克 命名),硬命中非空又令 L2 语义补位永不触发 —— 族缺口必须
# 以裸锚词补一脚(裸词「衣服」经 L2 语义实测正确落 T恤/衬衫)。
OUTFIT_RE = re.compile(r"(?:搭配|一套|套装|一整套)")

# 衣着族锚词:输入命中 = 有衣着诉求;商品名命中 = 该商品属衣着族。
# 词面收上 intent_registry.CLOTHING_ANCHOR_FAMILY(Gen-3 域A,缺席面同源)。
CLOTHING_ANCHOR_RE = re.compile(_alt(*CLOTHING_ANCHOR_FAMILY))

# 缺席反问(2026-09-27 实弹事故):「没有衣服呢」是顾客指出上轮推荐缺了
# 某族,不是新的字面搜索词 —— 整句直查词元「没有衣服」必然诚实空,空分支
# 再把原话当描述引用(「未能找到符合“没有衣服呢”」)二次伤害。剥否定框
# 取品类名词直查;仅当名词含购物锚词才劫持,订单域负句(「没有收到货」)
# 不劫持(那些轮次本不该路由到本技能,防御纵深)。
ABSENCE_RE = re.compile(r"^(?:怎么|是不是)?没有(.+?)[呢吗么嘛]?\s*[？?]?\s*$")
ABSENCE_ANCHOR_RE = re.compile(
    _alt(*CLOTHING_ANCHOR_FAMILY, *ABSENCE_EXTRA_FAMILY)
)

# 承接式反问(A-not-B,2026-09-28 实弹):「两件短袖呢，不用帐篷吗？」
# —— 前半承接上轮推荐(数量+品类+呢),后半指出缺席族。ABSENCE_RE 只认
# 「(没有)X」框,此形态接不住:整句当字面搜索词必诚实空,空分支再引用
# 原话(finish 终稿还曲解成「不希望包含帐篷」的过滤条件)。捕获「不用/
# 不要/不带/不需 X 吗」框内品类词,锚词校验同缺席反问纪律;框锚定句尾
# 防中间形态误抢(「不用帐篷的话可以…」),框内词无锚词不劫持(「不用
# 退了吗」是动作域)。词条均不在册(词表契约),锚词走家族引用拼接。
# 语气词含 啊/呀/吧(「是不是不用睡袋啊」同为缺席指出)。
A_NOT_B_RE = re.compile(
    r"(?:不用|不要|不需|不带)(?:带|用)?\s*([^,，。?？!!\s]{1,6}?)[呢吗么嘛啊呀吧]\s*[？?]*\s*$"
)


def detect_absence(user_input: str) -> tuple[str | None, bool]:
    """缺席反问 + 承接式反问(A-not-B)剥框:返回 (品类名词, 是否承接式)。

    检索词与空分支措辞都换成品类名词,严禁把顾客反问原话当搜索描述引用;
    框内词无锚词不劫持(「不用退了吗」是动作域)。"""
    m = ABSENCE_RE.match(user_input)
    if m:
        noun = m.group(1).strip()
        if noun and ABSENCE_ANCHOR_RE.search(noun):
            return noun, False
    rhetoric_m = A_NOT_B_RE.search(user_input)
    if rhetoric_m:
        noun = rhetoric_m.group(1).strip()
        if noun and ABSENCE_ANCHOR_RE.search(noun):
            return noun, True
    return None, False


def extract_preferences(user_input: str) -> tuple[dict, set[str]]:
    """偏好特征提取(命中即记 touched = 本轮实际说出的偏好键)。

    返回 (本轮新提取偏好, touched 键集) —— 调用方负责与承接面合并;诚实
    口径(2026-09-30 实弹):承接的旧偏好从不参与检索,也永不上展示句。"""
    extracted: dict = {}
    touched: set[str] = set()
    if re.search(r"男|男生|男款", user_input, re.IGNORECASE):
        extracted["gender"] = "男款"
        touched.add("gender")
    if re.search(r"女|女生|女款", user_input, re.IGNORECASE):
        extracted["gender"] = "女款"
        touched.add("gender")
    if re.search(r"透气|清爽|夏", user_input, re.IGNORECASE):
        extracted["feature"] = "透气轻便"
        touched.add("feature")
    if re.search(r"缓震|护膝|慢跑|马", user_input, re.IGNORECASE):
        extracted["scenario"] = "专业缓震慢跑"
        touched.add("scenario")
    if re.search(r"黑|白|红", user_input):
        color_match = re.search(r"(?:黑|白|红|蓝|灰)色?", user_input)
        if color_match:
            extracted["color"] = color_match.group(0)
            touched.add("color")

    budget_match = re.search(r"(?:预算|低于|不超过|最高|价位)\s*(\d+)", user_input)
    if budget_match:
        max_price = int(budget_match.group(1))
        extracted["budget"] = f"¥{max_price}以内"
        touched.add("budget")
        return extracted, touched, max_price
    return extracted, touched, None


def is_very_vague(
    user_input: str,
    *,
    max_price: int | None,
    extracted_prefs: dict,
    clarification_round: int,
) -> bool:
    """超模糊查询判定(多轮追问):短输入 + 无预算/场景/性别 + 首轮 + 模糊
    购物词面。"""
    return (
        len(user_input) <= 4
        and not max_price
        and not extracted_prefs.get("scenario")
        and not extracted_prefs.get("gender")
        and clarification_round == 0
        and bool(re.search(_grp("买东西", "买鞋", "买衣服", GUIDE_CORE_FAMILY[0], "逛逛"), user_input, re.IGNORECASE))
    )


def parse_requested_limit(user_input: str, absence_rhetoric: bool) -> int:
    """数量语义(2026-09-12 用户实报「我要2个商品」被无视):「N个/N件」
    显式数量 → 推荐 N 款(上限 8,与品类快捷区一致);「几件/几款」
    或未提 → 维持默认 3。承接式反问(数量词指上轮商品)不计入本次推荐数。"""
    if absence_rhetoric:
        return 3
    requested_count = re.search(r"([2-9]|1[0]|两|三|四|五|六|七|八|九|十)\s*[个件款条双只]", user_input)
    if not requested_count:
        return 3
    raw = requested_count.group(1)
    cn = {"两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    limit = int(raw) if raw.isdigit() else cn.get(raw, 3)
    return max(1, min(limit, 8))
