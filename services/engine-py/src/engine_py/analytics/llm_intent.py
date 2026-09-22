"""L3 LLM 意图兜底(08-D1:LLM 只做语义解析、永不写 SQL;ADR-0005)。

问句 → 闭集结构化意图(metric/方向/limit/时间窗/品类)+ 实体提及;
实体提及经 dimensions 确定性落库解析:唯一命中 → 绑定意图实体槽;
多命中 → clarify 反问(entity 类,前端点选后原词回问);零命中 → 响亮失败。

治理:
- metric 只能取注册表闭集;越权/未注册 → UnsupportedQuery(08-P1)。
- AI_INTENT_L3=off 整体关闭(回滚 = 删环境变量);LLM 异常一律放行到
  响亮失败,严禁静默兜底。
"""

from __future__ import annotations

import asyncio
import os

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from . import dimensions
from .engine import StructuredQueryIntent, UnsupportedQuery
from .tools_registry_bridge import metric_semantic_registry

ENTITY_REQUIRED: dict[str, str] = {
    "promo_effect": "promotion",
    "promo_sku_compare": "promotion",
    "promo_compare": "promotion",
    "customer_orders": "customer",
}
_VALID_TIME = ("last_7d", "last_30d", "last_month")
_VALID_CATEGORY = ("户外机能", "潮流T恤", "下装裤类", "潮流鞋靴", "背包收纳", "露营装备", "衬衫", "配饰", "运动配件")


class LlmIntent(BaseModel):
    """LLM 结构化输出契约(全部可空:null = 未表达,由确定性层校验)。"""

    metric: str | None = Field(None, description="指标 key,必须取自闭集;无法确定则为 null")
    direction: str | None = Field(None, description="ASC=升序(最差/最低);DESC=降序(最好/最高);默认 null")
    limit: int | None = Field(None, description="Top N;未表达为 null")
    time_window: str | None = Field(None, description="last_7d|last_30d|last_month|null")
    category: str | None = Field(None, description="九品类之一或 null")
    entity_kind: str | None = Field(None, description="只能是 promotion|customer|spu 三值之一(promotion=活动 customer=客户 spu=商品);涉及具体实体时必填")
    entity_mention: str | None = Field(None, description="实体提及原文(活动名/客户名或手机号/商品名),原样摘取")
    compare_mention: str | None = Field(None, description="对比目标款(商品名/编码),仅对比类问题")


def l3_enabled() -> bool:
    return os.environ.get("AI_INTENT_L3", "on").strip().lower() not in ("0", "off", "false")


# 实体种类闭集别名(弱模型实测会输出 product/中文;归一到 dimensions 三值,
# 未知值在解析侧响亮拒绝 —— 与 08-P1 同一纪律)
_ENTITY_KIND_ALIASES = {
    "promotion": "promotion", "customer": "customer", "spu": "spu",
    "product": "spu", "商品": "spu", "活动": "promotion", "客户": "customer",
}


def _system_prompt(allowed: list[str] | None) -> str:
    rows = []
    for key, m in metric_semantic_registry().items():
        if allowed and key not in allowed:
            continue
        rows.append(f"- {key}({m['label']}): {m['description'][:60]}")
    return (
        "你是商户数据问答的意图解析器。把用户问题解析为 JSON,规则:\n"
        f"- metric 只能从闭集中选,闭集:\n{chr(10).join(rows)}\n"
        "- 问法/措辞任意,但含义不在闭集内(如问原因、问竞品、闲聊)→ metric=null\n"
        "- time_window ∈ last_7d|last_30d|last_month|null(「昨天/本周」等闭集外时间也置 null 并在 metric 选择时保守处理)\n"
        "- direction:问最差/最低/垫底 → ASC;最好/最高/Top → DESC;未表达 null\n"
        "- 问某活动的销售/效果 → entity_kind='promotion',entity_mention=活动名原文\n"
        "- 问某客户/某人的订单 → entity_kind='customer',entity_mention=客户名或手机号原文\n"
        "- entity_kind 只允许 promotion/customer/spu 三个英文值,禁止 product/商品 等其他写法\n"
        "- 问活动里某款对比其他款 → metric=promo_sku_compare,entity_kind='promotion',"
        "entity_mention=活动名,compare_mention=目标款商品名或编码\n"
        "- 问「选中的/勾选的订单」「两个订单对比/这两单差异」→ metric=order_overview"
        "(实体由页面勾选集提供,entity_kind/entity_mention 留空)\n"
        "- 问两个活动的对比(如「A活动 对比 B活动 哪个好」「两个活动哪个效果好」)→ "
        "metric=promo_compare,entity_kind='promotion',entity_mention=第一个活动名,"
        "compare_mention=第二个活动名\n"
        "- 实体提及必须摘取用户原话,不要改写"
    )


async def llm_resolve(
    question: str,
    allowed: list[str] | None = None,
    business_id: str = "",
) -> StructuredQueryIntent:
    """未命中词表后的一跳:LLM 解析 → 实体落库解析 → 闭集意图。

    返回 StructuredQueryIntent(实体已绑槽);实体多命中/未指明必填实体时
    **抛出** _EntityClarify(由 graph 翻译成 clarify 帧);一切失败 → UnsupportedQuery。
    """
    if not l3_enabled():
        raise UnsupportedQuery("L3 意图层未启用")

    registry = metric_semantic_registry()

    async def _invoke_llm() -> str:
        """取回模型原始输出(SFT 本地优先,bigmodel API 兜底)。"""
        local_model = os.environ.get("AI_INTENT_L3_MODEL")
        if local_model:
            # QLoRA SFT 产物(见 scripts/training/sft_train.py)—— 摆脱 bigmodel API 限流依赖
            return await _sft_generate(local_model, _system_prompt(allowed), question)
        resp = await get_chat_model().ainvoke([
            SystemMessage(content=_system_prompt(allowed)),
            HumanMessage(content=question),
        ])
        return _content_text(resp)

    # 两分支共用同一失败语义:格式坏/网络/供应商故障 → 响亮失败,不静默兜底
    try:
        out = LlmIntent.model_validate(_parse_llm_json(await _invoke_llm()))
    except UnsupportedQuery:
        raise
    except Exception as err:
        print(f"[L3] 意图解析调用失败(响亮失败): {err}")
        raise UnsupportedQuery("意图解析服务暂不可用") from err

    if not out.metric or out.metric not in registry:
        raise UnsupportedQuery("问题含义未落在已注册指标闭集内")
    if allowed and out.metric not in allowed:
        raise UnsupportedQuery("当前角色无权查看该指标")

    if out.entity_kind:
        normalized = _ENTITY_KIND_ALIASES.get(out.entity_kind.strip().lower())
        if normalized is None:
            raise UnsupportedQuery(f"实体种类 {out.entity_kind!r} 不在闭集内(promotion/customer/spu)")
        out.entity_kind = normalized

    metric_meta = registry[out.metric]
    direction = out.direction if out.direction in ("ASC", "DESC") else metric_meta["direction"]
    limit = min(max(int(out.limit or 5), 1), 50)
    time_window = {"kind": out.time_window} if out.time_window in _VALID_TIME else None
    category = out.category if out.category in _VALID_CATEGORY else None

    intent = StructuredQueryIntent(
        metric=out.metric, direction=direction, limit=limit,
        time_window=time_window, category=category,
    )

    # 实体槽解析(确定性落库;提及 → 候选 → 绑定/反问/响亮失败)
    slots: dict[str, list[str]] = {}
    if out.entity_kind and out.entity_mention:
        candidates = await dimensions.resolve_entity(out.entity_kind, out.entity_mention)
        if not candidates:
            raise UnsupportedQuery(f"没有找到「{out.entity_mention}」对应的{dimensions.kind_label(out.entity_kind)}")
        # 逐字消歧:问句里已写明唯一候选名 → 直接绑定,不打断用户反问
        mentioned = [c for c in candidates if c["label"] in question]
        if len(mentioned) == 1:
            candidates = mentioned
        if len(candidates) > 1:
            raise _EntityClarify(out.entity_kind, candidates, question)
        slots[out.entity_kind] = [candidates[0]["id"]]

    required_kind = ENTITY_REQUIRED.get(out.metric)
    if required_kind and required_kind not in slots:
        raise _EntityClarify(required_kind, await dimensions.list_candidates(required_kind), question)

    if out.metric == "promo_sku_compare" and out.compare_mention:
        targets = await dimensions.resolve_entity("spu", out.compare_mention)
        if not targets:
            raise UnsupportedQuery(f"没有找到「{out.compare_mention}」对应的商品")
        slots["spu"] = [t["id"] for t in targets]

    if out.metric == "promo_compare":
        # 双活动实体:entity_mention + compare_mention 各解析一个活动
        for field, mention in (("entity", out.entity_mention), ("compare", out.compare_mention)):
            if not mention:
                continue
            cands = await dimensions.resolve_entity("promotion", mention)
            if not cands:
                raise UnsupportedQuery(f"没有找到「{mention}」对应的活动")
            if len(cands) > 1:
                raise _EntityClarify("promotion", cands, question)
            slots.setdefault("promotion", [])
            slots["promotion"].append(cands[0]["id"])
        slots["promotion"] = list(dict.fromkeys(slots.get("promotion") or []))
        if len(slots["promotion"]) < 2:
            raise UnsupportedQuery("请指明两个不同的活动,如「活动A 对比 活动B」")

    if slots:
        intent.entity_slot.update(slots)
    return intent


class _EntityClarify(Exception):
    """实体多命中/未指明必填实体 → 由 graph 翻译成 clarify 帧(选项即候选)。"""

    def __init__(self, kind: str, candidates: list[dict], question: str) -> None:
        self.kind = kind
        self.candidates = candidates
        self.question = question
        super().__init__(f"实体多命中: {kind}")


from ..llm import get_chat_model


def build_llm_resolver():
    """测试/注入缝:返回 llm_resolve 同签名协程(模型可替换)。"""

    async def _resolve(question: str, allowed: list[str] | None = None, business_id: str = ""):
        return await llm_resolve(question, allowed, business_id)

    return _resolve

def _content_text(resp) -> str:
    """LangChain 响应 → 文本(str 或 多模态分段)。"""
    content = resp.content
    if isinstance(content, str):
        return content
    return "".join(part.get("text", "") for part in content if isinstance(part, dict))


def _parse_llm_json(raw: str) -> dict:
    """剥 ```json 围栏 + 截取首尾大括号 + 尾逗号容错(glm 系模型常见输出形态)。"""
    import json
    import re as _re

    text = (raw or "").strip()
    text = _re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = _re.sub(r"\s*```\s*$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"响应中无 JSON: {text[:80]!r}")
    body = text[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # 弱模型常见坏形:尾逗号("..., }")、全角引号混入 —— 先做无损修补再交-
        # 仍失败则原样上抛(响亮失败,不猜测语义)
        repaired = _re.sub(r",\s*([}\]])", r"\1", body)
        repaired = repaired.replace("\u201c", '"').replace("\u201d", '"')
        return json.loads(repaired)


_SFT_PIPELINE = None


async def _sft_generate(model_path: str, system_prompt: str, question: str) -> str:
    """自托管 SFT 模型推理(懒加载单例;chat 模板与训练格式一致)。

    自托管豁免口径:本函数是「模型服务本体」而非外部 LLM API 客户端,
    不经 llm/chat.py 统一入口(无熔断/遥测语义可套);同步 transformers
    推理经 asyncio.to_thread 下放线程,不阻塞事件循环。
    """
    def _run() -> str:
        global _SFT_PIPELINE
        if _SFT_PIPELINE is None:
            from transformers import pipeline as hf_pipeline

            _SFT_PIPELINE = hf_pipeline("text-generation", model=model_path, device_map="auto")
        prompt = f"{system_prompt}\n\n问句:{question}\nSemQL:"
        results = _SFT_PIPELINE(prompt, max_new_tokens=256, do_sample=False, return_full_text=False)
        return results[0]["generated_text"]

    return await asyncio.to_thread(_run)
