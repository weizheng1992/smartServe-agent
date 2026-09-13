"""咨询类直答快轨(2026-09-09)—— 政策/尺码/物流时效等「问知识」型输入的
单次 LLM 调用直答旁路。

背景:咨询类输入在意图体系里此前没有独立档位,按措辞随机误落三处 ——
1. 含「退货」字样 → Step 1.5 ORDER_RETURN 规则误判动作形,反问订单号;
2. 躲过正则 → Step 2 判定 3 关键词快车道误判 refund 动作意图 → planner
   深度规划(曾单次 5163 token/73.7s)→ executor → finish,3-4 次串行调用;
3. 落 general_query → 分类器 + finish 终稿 2 次调用,政策依据只经 finish 兜底注入。
咨询类回复 57-114s 的大头即源于此。

快轨(hang triage Step 1.4,分类器判 consult 时复用):
- is_consult_query:咨询形检测 —— 咨询话题 × 疑问语气,否定动作形/复合意图/
  显式订单号/带图输入(带图售后走视觉定责管道);
- 语义缓存先查(≥0.96):同题近题上次直答秒回,0 次调用;
- run_agent 预取的 RAG 切片复用(零额外检索),top 相似度过线才直答;
- 单次调用(品牌人设 + RAG 切片 + 近期历史)生成答案,strictly grounded;
- 答案回填语义缓存(咨询形非动作、有 RAG 依据,可安全缓存)。
RAG 空弱/直答失败返回 None,调用方回落原管道兜底。

答案调用兼任仲裁员(intent-arbitration 05,2026-09-10):直答 prompt 带
ROUTING VETO 规则 —— 用户实为请求执行动作(下单/退/改/查单)而非问知识时,
返回 ROUTE_TO_ACTION_MARKER 而非作答;快轨放行 fallthrough 完整管线,
用户拿到动作管道结果。标记回复不写语义缓存。零新增调用/延迟:p50 咨询
路径仍是那一次直答调用,只是从「答案生成器」升级为「答案生成器+意图
复核员」;正则误命中的代价从「答非所问且关会话」降为多走一次既有管道。

is_consult_shaped_marker(07,2026-09-10)是纯措辞侧的冲突标记(与
is_consult_query 分工:本模块快轨闸门 vs 槽位层动作终局的留痕观测),零
调用零路由影响 —— 「判动作 × 咨询形措辞」残余经仲裁留痕进坏例池信号源
观测,01 数据 393 行直接审计 0 例,不为其硬上 LLM 仲裁。
"""

from __future__ import annotations

import re

from ..event_bus import emit_status
from ..llm import CircuitBreakerOpenError, get_chat_model
from ..tenant import get_merchant_display_name, tenant_of_state
from .semantic_cache import SemanticVectorCache, add_query_to_semantic_cache
from .slot_extractor import ORDER_ID_RE, AgentIntentType

# RAG 直答最低相似度:run_agent 对任意输入都预取 2 条切片(阈值 0.4),
# 咨询直答要求 top 切片真正相关,否则回落常规管道(切片弱相关时 LLM 只会
# 「知识库未覆盖」兜底,白花一次调用)。bge-small-zh 同域中文通常 0.6+,
# 无关提问 0.3-0.45,0.55 取在分界上。
RAG_DIRECT_MIN_SIMILARITY = 0.55

# 直答兼任仲裁员的路由标记(intent-arbitration 05,2026-09-10):直答调用
# 发现用户实为请求执行动作(而非问知识)时,返回此标记令快轨放行、fallthrough
# 完整管线。刻意用长而唯一的 ASCII 哨兵 —— 正常中文直答不可能与之碰撞。
ROUTE_TO_ACTION_MARKER = "__ROUTE_TO_ACTION__"

# 咨询话题词:「问知识」域 —— 政策/流程/时效/尺码/洗护/费用/票据/会员
_CONSULT_TOPIC_RE = re.compile(
    r"(?:政策|规定|制度|规则|流程|手续|条件|要求"
    r"|时效|多久|几天|多长时间|什么时候|何时"
    r"|尺码|尺码表|码数|偏大|偏小|大一码|小一码|版型|合不合脚"
    r"|怎么洗|如何洗|洗护|保养|清洗|晾|缩水|起球|掉色"
    r"|退换|退货|退款|退钱|售后|无理由|吊牌|包装|原路"
    r"|包邮|运费|邮费|配送范围|配送吗|发货时间|发货速度|几天到|多久到"
    r"|发票|保修|三包|质保"
    r"|支付方式|货到付款|会员|积分|优惠券|折扣"
    r"|特点|参数|规格|材质|面料|卖点|功能|用途|配置)",
    re.IGNORECASE,
)
# 疑问形标记:咨询天然带提问语气/疑问词
_CONSULT_QUESTION_RE = re.compile(
    r"(?:什么是|是什么|什么叫|怎么|如何|怎样|怎么样|哪些|哪个|什么|多少|几|多久|何时"
    r"|吗|呢|？|\?|请问|想了解|想咨询|了解一下|麻烦问|问一下|问下|咨询)"
)
# 动作形/复合意图否定:命中即用户要办事(或问的是「我那单」),不是问知识
_CONSULT_ACTION_RE = re.compile(
    r"(?:帮我|给我|麻烦你|麻烦帮|我要|我想退|申请|办理|退掉|退了|取消"
    r"|改地址|修改地址|换地址|换货吧"
    r"|加购|加入购物车|购物车|结算|买单|买第|移出|清空"
    r"|转人工|找客服|联系人工"
    # 复合/退款口语形与 triage 词表同步(2026-09-13 nightly 收口);⚠️ 严禁把
    # 裸「退货|退款|换货」加进来 —— 会击穿「退货政策/退款流程」咨询直答
    r"|另外|同时|并且|顺便|还有|然后再|接着|以及|随后|其次|退一下|退我|给我退"
    r"|再(?=[查看买退加来试问改推结])"
    r"|发货了|到哪了|到了吗|到了没|签收"
    r"|查|查询|搜索|搜一下|订单|物流|快递|单号|ord-)",
    re.IGNORECASE,
)
# 短语裸话题(≤12 字且无疑问词也算):「退货政策」「尺码表」类省略式提问
_CONSULT_BARE_TOPIC_RE = re.compile(r"(?:政策|规定|流程|尺码|运费|发票|保修|保养|退换)")

# 冲突标记(intent-arbitration 07,2026-09-10):纯措辞侧的咨询形判定,零调用。
# 与 is_consult_query 的分工:后者是快轨闸门(命中即直答);本标记只用于
# 「槽位层判动作终局 × 措辞带咨询形」的冲突留痕 —— 话题词更宽(退货/退款
# 这类槽位规则关键词作名词出现也算),动作动词否定更严(我要/我想/查 全排除),
# 保证只有「措辞像问知识、判定却进了动作管道」的输入被标记。
_CONSULT_MARKER_QUESTION_RE = re.compile(r"(?:什么是|是什么|什么叫|怎么|如何|怎样|怎么样|哪些|哪个|什么|多少|多久|何时|吗|呢|？|\?|请问|想了解|想咨询|了解一下)")
_CONSULT_MARKER_TOPIC_RE = re.compile(
    r"(?:政策|规定|制度|流程|手续|条件|要求|时效|多久|几天|尺码|运费|发票|保修|三包|质保"
    r"|退换|退货|退款|退钱|售后|无理由|换货|会员|积分|优惠)"
)
_CONSULT_MARKER_ACTION_RE = re.compile(
    r"(?:帮我|给我|麻烦|我要|我想|申请|办理|退掉|退了|取消"
    r"|改地址|修改|改成|换货吧|加购|加入购物车|购物车|结算|下单|买单|买第"
    r"|转人工|找客服|查|查询|搜索|搜一下|订单|物流|快递|单号|ord-)",
    re.IGNORECASE,
)


def is_consult_shaped_marker(text: str) -> bool:
    """咨询形标记(07):疑问词 × 售后/政策话题词 × 无动作动词。

    只进仲裁留痕不改变路由 —— 槽位层判动作终局时若本标记成立,即
    「判动作 × 咨询形措辞」冲突候选,坏例池冲突信号源据此观测残余;
    01 留痕 393 行直接审计该形状 0 例,数据不支撑为其加 LLM 仲裁调用。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _CONSULT_MARKER_ACTION_RE.search(stripped):
        return False
    return bool(_CONSULT_MARKER_QUESTION_RE.search(stripped) and _CONSULT_MARKER_TOPIC_RE.search(stripped))


# 商品知识强信号(2026-09-13):「XX 特点/规格/材质」类问句是知识诉求,
# 不受 12 字裸话题长度限制 —— 商品知识入库 RAG 后在此接住直答
_CONSULT_KNOWLEDGE_SIGNAL_RE = re.compile(
    r"(?:特点|参数|规格|材质|面料|卖点|功能|用途|配置)"
)


def is_consult_query(text: str, has_image: bool = False) -> bool:
    """咨询形判定:问店铺知识,非要求执行动作。

    三重否定闸:显式订单号(冲具体订单而来)、动作形/复合意图措辞、带图
    (走视觉定责管道)。信任模型:本判定同时是语义缓存读写两侧的防投毒闸
    —— 动作形输入永远进不了本快轨,缓存里只可能有 RAG 直答。

    带图闸必须在本判定本体而非 run_consult_direct_answer 内部单独拒答:
    快轨挂载点(Step 1.4)对 None 一律回落 general_query 早退,若带图输入
    是进了快轨才被拒,咨询形措辞 × 破损图会被截胡绕过视觉定责与商品消歧
    (2026-09-09 评审修复)。
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if has_image:
        return False
    if ORDER_ID_RE.search(stripped):
        return False
    if _CONSULT_ACTION_RE.search(stripped):
        return False
    if not _CONSULT_TOPIC_RE.search(stripped):
        return False
    if _CONSULT_QUESTION_RE.search(stripped):
        return True
    if _CONSULT_KNOWLEDGE_SIGNAL_RE.search(stripped):
        return True
    return len(stripped) <= 12 and bool(_CONSULT_BARE_TOPIC_RE.search(stripped))


def _format_rag_chunks(rag_documents: list[dict]) -> str:
    return "\n".join(
        f'[Store Policy Rule {idx + 1}] (Context Summary: {doc.get("contextualSummary") or "N/A"}): '
        f'"{doc.get("chunkText")}"'
        for idx, doc in enumerate(rag_documents)
    )


async def answer_consult_from_rag(
    input_text: str, rag_documents: list[dict], history_msgs: list[dict], brand_name: str
) -> str:
    """单次 LLM 调用直答:品牌人设 + RAG 切片 + 近期历史,strictly grounded。

    失败上抛由调用方回落常规管道(CircuitBreakerOpenError 例外,须穿透到
    run_agent 走 job 级降级,与其他节点语义一致)。
    """
    recent_history = "\n".join(
        f"{'User' if m.get('role') == 'user' else 'Assistant'}: {m.get('content')}"
        for m in (history_msgs or [])[-4:]
    )
    prompt = (
        f"You are an advanced, professional AI Customer Support Agent representing {brand_name}.\n"
        "Answer the customer's informational question about the store in Chinese, strictly grounded "
        "on the store policy excerpts below.\n\n"
        f"[STORE POLICY EXCERPTS]:\n{_format_rag_chunks(rag_documents)}\n\n"
        f"[RECENT CONVERSATION]:\n{recent_history or 'No previous history.'}\n\n"
        f'Customer Question: "{input_text}"\n\n'
        "CRITICAL RULES:\n"
        "1. Answer ONLY based on the excerpts above. Do NOT invent policies, time windows, fees, "
        "or conditions.\n"
        "2. If the excerpts do not cover the question, honestly say in Chinese that you need to "
        "double-check with a colleague, and invite the customer to reply 「转人工」 for human help.\n"
        "3. Be concise, warm and professional. Quote concrete numbers/conditions from the excerpts "
        "when present (e.g. return window in days, tag/packaging requirements, who pays shipping).\n"
        f'4. Refer to the store strictly as "{brand_name}". Reply fully in Chinese.\n'
        "5. You may close with a light offer to help further (e.g. providing an order ID to process "
        "a return), but do NOT claim any action has already been executed.\n"
        "6. ROUTING VETO (intent arbitration duty): first check what the customer actually wants. "
        "If they are requesting that you EXECUTE a concrete action — placing/adding an order, "
        "cancelling, modifying an address, refunding/returning a specific order, or checking their "
        "own order/shipping/data — do NOT answer at all. This includes MIXED messages where the "
        "customer states a first-person intent to return/cancel/modify an item (e.g. 「我不想要了」"
        "「这单不要了」「想把它退了」) and then asks about timing or process — the underlying "
        "request is to execute the action, so veto. Pure general policy questions WITHOUT any "
        "first-person action intent (e.g. 「退货政策是什么」「退货的话运费谁出」) must still be "
        "answered normally. When vetoing, reply with EXACTLY this ASCII marker and nothing else: "
        "__ROUTE_TO_ACTION__"
    )
    response = await get_chat_model().ainvoke(prompt)
    content = response.content if hasattr(response, "content") else str(response)
    return str(content).strip()


async def run_consult_direct_answer(state: dict, history_msgs: list[dict]) -> tuple[str, list[dict], float] | None:
    """咨询直答编排:缓存先查 → RAG 过线单次直答 → 回填缓存。

    返回 (answer, intents, confidence);不满足直答条件或失败返回 None
    (调用方回落常规管道)。state 需带 input / rag_documents(run_agent 预取)
    / input_embedding(缺则现算)/ business_config。
    """
    input_text = (state.get("input") or "").strip()
    if not input_text or state.get("image_urls"):
        return None

    tenant_id = tenant_of_state(state)
    brand_name = get_merchant_display_name(tenant_id)

    # 语义缓存先查(≥0.96,先于 RAG 闸):同题近题上次直答秒回,且纯 FAQ 缓存
    # 复放不受知识库空弱影响。is_consult_query 的动作形否定模式即防投毒闸,
    # 与写侧同源信任;这里无需再过 is_action_query(「退货政策」会被
    # OrderRefundSkill 的 退货 兜底正则嗅探成动作形,但对咨询形输入该嗅探是
    # 误报,咨询快轨内以本模块判定为准)。命中 intents 记 general_query,
    # 与 Step 2 super_semantic_cache 旁路口径一致(纯 FAQ 复放,非新直答)。
    vector = state.get("input_embedding") or []
    if not vector:
        try:
            vector = await SemanticVectorCache.get_embedding_with_cache(input_text)
        except Exception as embed_err:
            print(f"[Consult Fast-Path] 向量化失败,跳过缓存读写: {embed_err}")
            vector = []
    if vector:
        cache_hit = SemanticVectorCache.find_best_semantic_match(tenant_id, vector, 0.96)
        if cache_hit:
            return (
                cache_hit["match"]["reply"],
                [{"intent": AgentIntentType.GENERAL_QUERY, "confidence": cache_hit["similarity"], "type": "primary"}],
                cache_hit["similarity"],
            )

    rag_documents = state.get("rag_documents") or []
    if not rag_documents:
        return None
    top_similarity = max((float(d.get("similarity") or 0.0) for d in rag_documents), default=0.0)
    if top_similarity < RAG_DIRECT_MIN_SIMILARITY:
        return None

    job_id = state.get("job_id")
    if job_id:
        await emit_status(
            job_id,
            "📚 已识别为政策/知识类咨询,正基于店铺知识库检索结果直答(已跳过任务规划与工具执行)...",
            node="triage",
        )
    try:
        answer = await answer_consult_from_rag(input_text, rag_documents, history_msgs, brand_name)
    except CircuitBreakerOpenError:
        raise
    except Exception as answer_err:
        print(f"[Consult Fast-Path] RAG 直答失败,回落常规管道: {answer_err}")
        return None

    # 🧭 仲裁员否决(intent-arbitration 05):直答调用发现动作形请求,改判路由
    # —— 快轨放行,调用方 fallthrough 完整管线;标记回复严禁写语义缓存
    #(动作形输入的答案没有知识依据,缓存会令后续同形输入被资讯回复截胡)。
    if answer.strip() == ROUTE_TO_ACTION_MARKER:
        if job_id:
            await emit_status(
                job_id,
                "🔎 复核为操作请求,转入任务处理管道(意图仲裁员改判)...",
                node="triage",
            )
        return ROUTE_TO_ACTION_MARKER, [], 0.0

    # 回填语义缓存:咨询形输入非动作、回答有 RAG 切片依据,后续相似提问秒回
    if vector:
        try:
            add_query_to_semantic_cache(tenant_id, input_text, answer.strip(), vector)
        except Exception as cache_err:
            print(f"[Consult Fast-Path] 语义缓存回填失败(不阻断直答): {cache_err}")

    return answer, [{"intent": AgentIntentType.CONSULT, "confidence": 0.95, "type": "primary"}], 0.95
