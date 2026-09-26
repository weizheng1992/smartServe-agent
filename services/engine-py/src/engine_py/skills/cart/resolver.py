"""购物车话术解析器 — 正则词表与目标行解析的单一事实源。

删除与改量两动词的目标解析链(序数 → 商品名 → lastModified → 首款)此前
逐行复制两份,判据漂移即事故(2026-09-15 双规格去重判据补 skuCode 时要人肉
同步多处);现收敛为 resolve_cart_item 一条缝。全部正则常量在此单点维护,
动作表(actions.py)只消费不定义。"""

from __future__ import annotations

import re

_ORDINAL_RE = re.compile(r"(?:把)?第\s*(\d+|[一二三四五六七八九十两])\s*[件款个双]?")
# 数字串经 ordinal_to_index 换算(支持「第10件」多位),汉字查表
_INDEX_MAP = {"一": 0, "二": 1, "两": 1, "三": 2, "四": 3, "五": 4, "六": 5, "七": 6, "八": 7, "九": 8, "十": 9}
# 词表外大序数兜底(第十一/第100…):只在「诚实反问」时作存在性判定用
_ORD_ANY_RE = re.compile(r"第\s*[0-9一二三四五六七八九十百千]+")
_ORDINAL_FULL_RE = re.compile(
    r"(?:把)?第\s*(\d+|[一二三四五六七八九十两])\s*[件款个双]"
    r"|买第\s*(\d+|[一二三四五六七八九十两])"
    r"|第\s*(\d+|[一二三四五六七八九十两])\s*款"
)
# 结算分支的 S6 序数形(「就要第一个,直接下单」):限 1-6,词表外大序数走
# _ORD_ANY_RE 的存在性判定不进此守卫
_ORDINAL_CHECKOUT_RE = re.compile(r"第[一二三四五六1-6][款个件]")
_ADD_ALL_RE = re.compile(r"(?:全部|所有|都)")

_VIEW_ONLY_RE = re.compile(
    r"(?:查看购物车|看下购物车|购物车总价|看购物车|购物车里|购物车有什么|多少钱|算下总价|结算|去买单|去结算)"
)
_VIEW_EXCLUDE_RE = re.compile(r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购|买第|要第|改成|修改|删除|移除|删掉)")
_DELETE_RE = re.compile(r"(?:删除|移除|删掉|去掉|不要了|清空)")
_CLEAR_RE = re.compile(r"(?:清空|全部删除|全删)")
_ADD_RE = re.compile(r"(?:加购物车|加入购物车|放进购物车|放入购物车|加购)")
# 真·聊天下单触发(遗留二期,2026-09-13):拦截在查看分支前;裸「结算」保持
# 查看摘要旧契约,「下单/去结算/提交订单/付款」才开真实订单。
_CHECKOUT_RE = re.compile(r"(?:结算下单|去结算|提交订单|付款|[^\s]下单|^下单|(?:然后|再|接着|帮忙|帮我|给我)结算)")
# 否定/非结算形守卫:「我还没下单」「先不付款」「货到付款」严禁开出真单
_CHECKOUT_NEG_RE = re.compile(r"(?:还没|没有|不用|不要|先不|暂不|别|[^\s]个下单|货到付款|未付款)")
_CHECKOUT_ADDR_RE = re.compile(r"(?:寄到|送到|地址为|地址是|邮寄到)\s*([^,，。!！?？\n]+)")
# 检索/推荐诉求(2026-09-13):在场时禁用加购的历史回溯候选(幻影守卫)。
# 销量榜词族(2026-09-26 症状③):「销量最好的裤子放购物车」曾被当字面商品名
# 去货架直配,必然 miss 后谎称「店内没有」—— 榜词族是检索半而非点名。
_SEARCH_INTENT_RE = re.compile(r"(?:推荐|询|问|看看|看看有|找|挑|评价|口碑|热销|爆款|有什么|销量最好|销量最佳|卖得最好|最好卖|卖得好|畅销|热卖)")
# 销量榜诉求(症状③):命中即加购目标未经用户挑款,走货架检索反问,严禁
# 静默落候选[0](候选池可能是上游幻觉搜索的垃圾)。
_BEST_SELLER_RE = re.compile(r"(?:销量最好|销量最佳|卖得最好|最好卖|卖得好|畅销|热卖|热销|爆款)")
# 订单→购物车桥接:「订单(里)的 X 加入购物车」—— X 为历史购买商品关键词
_BRIDGE_KEYWORD_RE = re.compile(
    r"(?:订单|买过)[^。！？]{0,10}里?[面中]?的([^,，。！？]+?)(?:加入|加购|放进|放入|扔进|来一|买一)"
)
_QTY_UPDATE_RE = re.compile(r"(?:改成|修改为|数量设为|变成|改为|调整为|增加到|减少到)\s*(\d+)\s*件?")
_VAGUE_RE = re.compile(r"(?:第几|哪件|哪款|哪一个)")
_QTY_BUY_RE = re.compile(r"(?:数量|买|要|加|购)\s*(\d+)\s*件?")
_HISTORY_ITEM_RE = re.compile(r"(\d+)\.\s*【([^】]+)】\s*¥?(\d+(?:\.\d+)?)")
# 点名直配的剥词表(2026-09-14):加购动作词剥净后仍有实质内容 = 用户点了名。
# 刻意不含单字「的/吧」以外的规格字 —— 「曜石黑 M码」「POLO衫」必须原样留存
# 供货架直配评分;注意「码」不可剥(M码/L码 是规格判别词)。
_ADD_ACTION_STRIP_RE = re.compile(
    r"加入购物车|放进购物车|放入购物车|加购物车|加购|购物车|帮我|给我|麻烦|我想|想要|"
    r"放到|放进|放入|装进|扔进|丢进|"
    r"下单|结账|来一[件个个只]|一[件个个只]|\d+\s*[件个个只]|加入|谢谢|最后|这个|那个|一下|买|要|加|吧|呗|哦|哈|把|"
    r"第\s*[0-9一二三四五六七八九十百千]*"
)
# 纯指代判别(2026-09-15):配不中后剥指代词,剥完为空 = 用户在指代上下文
# 商品(「刚才那个」),交回槽位/候选链由 planner 消解;仍有实质 = 点名了
# 货架确认不了的东西,诚实反问。
_NAMED_DEIXIS_STRIP_RE = re.compile(
    r"那个|这个|它|刚才|刚刚|同款|上一?轮|上一?个|之前|一样|那件|这件"
)
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z]{2,}")
# 品牌与通用款型词不计分:点名"A款"不得因共享 Nike/Run 等泛词误中"B款"
_GENERIC_NAME_TOKENS = {"nike", "run", "air"}


def ordinal_to_index(token: str) -> int:
    """序数字符 → 0 基下标:数字串按位值换算(第10件=9),汉字查表。"""
    if token.isdigit():
        return int(token) - 1
    return _INDEX_MAP.get(token, 0)


def match_cart_item_by_name(user_input: str, items: list[dict]) -> dict | None:
    """按商品名定位购物车条目:标题整串包含优先,否则拉丁特征词得分匹配。

    - 仅取拉丁词(≥3字母)且忽略大小写;数字串不参与:改量/序数词指令中的
      数字("数量改成3"/"第2件")会与标题款号("Invincible Run 3")撞分致歧义。
    - 得分 <1 返回 None(如纯中文泛称"跑鞋"无法区分多款),交回原兜底链。
    """
    for item in items:
        title = str(item.get("title") or item.get("name") or "")
        if title and title in user_input:
            return item
    input_tokens = {t.lower() for t in _NAME_TOKEN_RE.findall(user_input)}
    best_item: dict | None = None
    best_score = 0
    for item in items:
        title = str(item.get("title") or item.get("name") or "")
        title_tokens = {t.lower() for t in _NAME_TOKEN_RE.findall(title)}
        score = len((title_tokens & input_tokens) - _GENERIC_NAME_TOKENS)
        if score > best_score:
            best_item, best_score = item, score
    return best_item if best_score >= 1 else None


def resolve_cart_item(
    user_input: str, current_items: list[dict], last_modified_id: str | None = None
) -> tuple[dict | None, int | None]:
    """删除/改量共用目标链:序数 → 商品名 → lastModified → 首款。

    返回 (目标行, 越界序数)。越界序数非 None 时调用方须诚实拦截
    (「购物车中没有第N件」),严禁静默落兜底误删/误改他款(2026-09-06)。"""
    ordinal_match = _ORDINAL_RE.search(user_input)
    if ordinal_match:
        target_index = ordinal_to_index(ordinal_match.group(1))
        if target_index >= len(current_items):
            return None, target_index
        return current_items[target_index], None
    target = match_cart_item_by_name(user_input, current_items)
    if target is None and last_modified_id:
        target = next((i for i in current_items if i.get("skuId") == last_modified_id), None)
    if target is None and current_items:
        target = current_items[0]
    return target, None


def named_query_remainder(user_input: str) -> str:
    """剥加购动作词/序数残词后剩余的实质内容:非空(≥2 字) = 用户点名了具体
    商品/规格。序数残词(「把第一件」剥完剩「把第」)严禁当商品名去货架查询。"""
    rest = _ADD_ACTION_STRIP_RE.sub(" ", user_input)
    rest = rest.strip(" \t,，。.!！?？:；;的了")
    return rest if len(rest) >= 2 else ""


def candidate_pool(guide_context: dict, short_memory: list[dict], user_input: str) -> tuple[list[dict], list[str]]:
    """候选池:guideContext 现候选优先;为空且无检索诉求时从近期对话历史
    回溯「推荐商品」清单(幻影守卫 2026-09-13:检索诉求在场一律禁用回溯,
    否则上一轮的别的商品会被当成「第一个」入车)。"""
    candidate_products = list(guide_context.get("candidateProducts") or [])
    candidate_list = list(guide_context.get("candidateProductIds") or [])
    if not candidate_list and short_memory and not _SEARCH_INTENT_RE.search(user_input):
        for msg in reversed(short_memory):
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), str) and "推荐商品" in msg["content"]:
                parsed = [
                    {"id": f"prod_recommend_{m.group(1)}", "name": m.group(2), "price": float(m.group(3))}
                    for m in _HISTORY_ITEM_RE.finditer(msg["content"])
                ]
                if parsed:
                    candidate_products = parsed
                    candidate_list = [p["id"] for p in parsed]
                    break
    return candidate_products, candidate_list
