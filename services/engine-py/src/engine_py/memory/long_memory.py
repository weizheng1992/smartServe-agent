"""长期偏好记忆 — 镜像 memory/longMemory.ts(双层画像隔离 + 专职画像 Agent)。"""

from __future__ import annotations

import datetime as _dt
import json
import re

from sqlalchemy import text

from ..db import LongMemoryFact, ProfileSlot, get_session
from ..llm import get_chat_model, get_embedding_model
from ..tenant_context import resolve_business_id
from ..vectors import cosine_similarity, parse_embedding
from .tenant_scope import tenant_scope_condition

PHYSIOLOGICAL_RE = re.compile(
    r"脚长|过敏|身高|体重|尺码|270mm|265mm|42码|43码|allergy|foot|size", re.IGNORECASE
)
_LINE_SPLIT_RE = re.compile(r"[\s,，、。!！?？\-_]+")

# 回声去重阈值(persona-hardening 13,2026-09-30):注入的画像事实经 finish
# 措辞回到回复里,审计把 assistant 自述又抽成新事实 —— 与该用户既有事实
# (approved + pending 皆算,pending 也在待审队列里)余弦 ≥ 此值即判回声弃落。
# 取 0.90,与范例回放(L2)近重复线同档;低于此值算真新事实照常落库。
_ECHO_DEDUP_THRESHOLD = 0.90

# ── 可变数字维度与第三人归属(2026-10-24 画像归属票)────────────────────
# 可变数字维度:身高/体重/脚长/尺码 —— 同 user+subject+dimension 的最新值
# 覆盖旧值(旧值转 'superseded',读侧 approved-only 自动隔离)。实弹探针
# (2026-10-24):体重 70→75 两条 approved 并存,且措辞雷同的改口会被回声
# 0.90 误杀 —— 维度路径显式豁免回声,按归一值三分。偏好类事实不参与覆盖
# (场合性偏好并存合法),沿用回声去重。
_DIMENSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("身高", re.compile(r"身[高長][^0-9]{0,6}(\d{3}(?:\.\d+)?)\s*(?:cm|厘米)?")),
    ("体重", re.compile(r"体[重視][^0-9]{0,6}(\d{2,3}(?:\.\d+)?)\s*(公斤|kg|KG|斤)?")),
    ("脚长", re.compile(r"脚[长長][^0-9]{0,6}(\d{2,3}(?:\.\d+)?)\s*(?:mm|毫米)?")),
    ("尺码", re.compile(r"尺[码碼][^0-9A-Za-z]{0,4}([A-Z]{1,2}|\d{2,3}(?:\.\d+)?)", re.IGNORECASE)),
    # 版型(2026-10-24 SOTA 对齐 P0-2):宽松/修身/紧身互斥 —— 同维度新值覆盖旧值
    # 是真语义;颜色/面料/品牌是集合型偏好(并存合法),刻意不进覆盖面(见
    # docs/memory-sota-upgrade.md 偏差决策 2)
    ("版型", re.compile(r"(宽松|修身|紧身|oversized?|合身)", re.IGNORECASE)),
)
# 槽位映射(2026-10-24 SOTA 对齐 P1#2):可变维度 → profile_slots 闭集 slot。
# 槽位表 = 尺码/荐品工具可消费的结构化档案(自由文本事实继续留长尾)。
_DIMENSION_TO_SLOT: dict[str, str] = {
    "身高": "height",
    "体重": "weight",
    "脚长": "foot_length",
    "尺码": "size",
    "版型": "fit",
}
_THIRD_PERSON_RE = re.compile(
    r"(妻子|老婆|爱人|女友|女朋友|男友|男朋友|丈夫|老公|母亲|妈妈|父亲|爸爸|儿子|女儿|闺蜜|朋友|同事)"
)


def fact_dimension_value(fact_text: str | None) -> tuple[str, str] | None:
    """提取可变数字维度与归一值(体重 斤→kg;尺码统一大写)。无可变维度返回 None。"""
    if not fact_text:
        return None
    for dimension, pattern in _DIMENSION_PATTERNS:
        m = pattern.search(fact_text)
        if not m:
            continue
        raw = m.group(1)
        try:
            if dimension == "体重":
                unit = (m.group(2) or "").lower()
                value = float(raw)
                if unit == "斤" or (not unit and value >= 200):  # 斤 → kg 归一(140斤=70kg)
                    value = round(value / 2, 1)
                return dimension, f"{value:g}"
            if dimension == "尺码":
                return dimension, raw.upper()
            if dimension == "版型":
                return dimension, raw  # 字符串值(宽松/修身),严禁走 float 归一
            return dimension, f"{float(raw):g}"
        except (TypeError, ValueError):
            continue
    return None


def normalize_subject(raw) -> str:
    """主体归一:空/本人/self → 'self';第三人保留简短称谓(截 12 字防散文)。"""
    if not isinstance(raw, str):
        return "self"
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() in ("self", "user", "本人", "我"):
        return "self"
    return cleaned[:12]

# 画像审计 Agent 的系统提示词与 prompt 装配/解析提为模块级单一事实源
# (persona-hardening 07):eval/providers/persona_provider.py import 同一装配,
# 评测与生产永不漂移;_run_profile_audit 只负责订单流水获取、路由与落库。
PROFILE_AUDIT_SYSTEM_PROMPT = """
你是一位世界级的消费者行为学家与多租户用户画像专家。你的职责是通过分析【用户最新的对话细节】与【历史购买流水】，提炼出符合该用户特征的个性化消费画像标签，严格判定画像的生效作用域 (scope: 'global' | 'tenant')，并进行置信度（Confidence）评估。

[CRITICAL DUAL-TIER SCOPE RULES]:
1. 'global'（全局生理/客观事实）：
   - 用户客观生理特征，例如：脚长(如 270mm/265mm)、身高、体重、衣服标准尺码(如 XL/L)、布料过敏原(如 羊毛过敏、聚酯纤维过敏)、常用快递偏好(如 优先顺丰)。
   - 这类事实跨所有商户通用，不涉及具体商户私域利益。
2. 'tenant'（特定商户私域偏好）：
   - 特定品牌/商户专属的偏好或历史，例如：耐克 Flyknit/Air Jordan 偏好、阿迪达斯椰子鞋偏好、商户专享优惠券使用习惯、特定店铺客服互动偏好。
   - 这类事实严格归属于当前商户，严禁泄漏给其它竞品商户。

[CRITICAL ECHO RULE]:
Assistant 回复中对已注入画像事实的引用或转述（例如「根据您偏好黑色的习惯」）不算用户新陈述，
严禁将其作为新事实输出 —— 只提炼【用户】本人本轮明确表达的新偏好。

[CRITICAL SUBJECT RULE]:
区分陈述主体（2026-10-24 画像归属）：用户为自己陈述时 subject="self"；
用户为他人（妻子/朋友/家人等）代买或转述他人身材/喜好时，subject=关系称谓
（如 "妻子"），且必须把主体写进 fact 文本（如「用户的妻子身高约160cm」）——
严禁把他人的身高/体重/尺码记成用户本人的生理事实。

[CRITICAL INSTRUCTIONS]:
请不要生成任何解释性废话。你必须只输出一个合规的 JSON 对象，包含以下字段。
【op 裁决规则(2026-10-24)】对照输入里的【该用户既有画像事实】决定每条的操作：
- "ADD"： genuinely 新的事实（默认值，拿不准就用 ADD，引擎侧规则会兜底去重）；
- "UPDATE"：用户改口/修正了某条既有事实 —— 必须携带 targetId=既有事实的 id，
  且 fact 字段写「新值的完整表述」；
- "DELETE"：用户明确撤回某条事实（如「忘掉我的身高」「记错了，我没有…」）——
  必须携带 targetId，此时 fact 字段可留空串；
- "NOOP"：既有事实已覆盖本条表达，无需任何写入。
{
  "hasNewPreference": boolean,
  "extractedFacts": [
    {
      "fact": string,
      "scope": "global" | "tenant",
      "subject": "self" | 关系称谓,
      "confidence": number,
      "op": "ADD" | "UPDATE" | "DELETE" | "NOOP",
      "targetId": string | null
    }
  ]
}
"""


def build_profile_audit_prompt(
    past_orders: list[dict],
    user_query: str,
    assistant_response: str,
    existing_facts: list[dict] | None = None,
) -> str:
    """装配画像审计 prompt(与 _run_profile_audit 生产调用同一份)。

    existing_facts(2026-10-24 op 裁决):该用户既有画像事实清单(id/subject/fact/
    status)—— LLM 据此裁决 ADD/UPDATE/DELETE/NOOP;缺省 None 时省略该段,
    LLM 按默认 ADD 输出(规则路径兜底,评测管道向后兼容)。"""
    sections = (
        f"{PROFILE_AUDIT_SYSTEM_PROMPT}\n\n[INPUT CONTEXT]:\n"
        f"1. 🛍️ 用户历史购买流水 (SQL Transaction Stream):\n"
        f"{json.dumps(past_orders, ensure_ascii=False, indent=2, default=str)}\n\n"
        f'2. 💬 本轮最新聊天交互 (Conversational Context):\n- Customer: "{user_query}"\n'
        f'- Assistant: "{assistant_response}"\n'
    )
    if existing_facts:
        sections += (
            f"\n3. 🧠 该用户既有画像事实 (Existing Profile Facts — op 裁决对照清单):\n"
            f"{json.dumps(existing_facts, ensure_ascii=False, indent=2, default=str)}\n"
        )
    return sections + "\n请进行画像分析并返回结果 JSON：\n"


def parse_profile_audit_response(content: str) -> dict:
    """解析画像审计返回(LLM 围栏 JSON 剥壳),与生产解析同一实现。"""
    clean_json = re.sub(r"^```json\s*", "", content.strip())
    clean_json = re.sub(r"```$", "", clean_json).strip()
    return json.loads(clean_json)


def _query_tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for seg in _LINE_SPLIT_RE.split(query.lower()):
        if not seg:
            continue
        if re.search(r"[a-z0-9]", seg) or len(seg) <= 2:
            tokens.append(seg)
        else:
            tokens.extend(seg[i : i + 2] for i in range(len(seg) - 1))
    return tokens


class LongMemory:
    def __init__(self, user_id: str, business_id: str | None = None) -> None:
        self.user_id = user_id
        self.business_id = business_id

    async def extract_and_store_fact(
        self,
        conversation_text: str,
        user_query: str | None = None,
        explicit_scope: str | None = None,
        explicit_business_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        if not self.user_id:
            print("[LongMemory] Cannot extract or store facts without userId")
            return

        # 🛡️ 专职画像 Agent 后台异步审计,不阻塞主链路
        if user_query:
            import asyncio

            asyncio.create_task(
                self._run_profile_audit(
                    user_query, conversation_text, explicit_scope, explicit_business_id, thread_id
                )
            )

        # 轻量正则匹配双重容灾
        for line in conversation_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            lower = line.lower()
            if "user prefers" in lower or "prefers" in lower or "fact:" in lower:
                fact_text = re.sub(r"^(fact:)", "", line, flags=re.IGNORECASE).strip()
                embedding = await get_embedding_model().aembed_query(fact_text)
                is_physiological = bool(PHYSIOLOGICAL_RE.search(fact_text))
                if explicit_scope:
                    calculated_scope = explicit_scope
                elif is_physiological:
                    calculated_scope = "global"
                elif self.business_id and self.business_id != "ecommerce":
                    calculated_scope = "tenant"
                else:
                    calculated_scope = "global"
                calculated_biz_id = (
                    resolve_business_id(explicit_business_id or self.business_id)
                    if calculated_scope == "tenant"
                    else None
                )
                # 第三人归属(2026-10-24 画像归属票):fact 文本含关系称谓即按
                # 主体落库,不混入本人档案
                subject = "self"
                m = _THIRD_PERSON_RE.search(fact_text)
                if m:
                    subject = normalize_subject(m.group(1))
                await self._ingest_fact(
                    fact_text=fact_text,
                    embedding=embedding,
                    scope=calculated_scope,
                    business_id=calculated_biz_id,
                    confidence=1.0,
                    status="approved",
                    source="regex_fallback",
                    subject=subject,
                )

    async def _run_profile_audit(
        self,
        user_query: str,
        assistant_response: str,
        explicit_scope: str | None = None,
        explicit_business_id: str | None = None,
        thread_id: str | None = None,
    ) -> None:
        past_orders: list[dict] = []
        try:
            async with get_session() as session:
                if self.business_id and self.business_id != "ecommerce":
                    sql = text(
                        'SELECT o.order_id AS "orderId", o.status, p.name AS "productName", '
                        "o.total_amount AS \"totalAmount\" FROM orders o "
                        "LEFT JOIN order_items oi ON o.order_id = oi.order_id "
                        "LEFT JOIN products p ON oi.product_id = p.id "
                        "WHERE o.user_id = :uid AND o.business_id = :bid LIMIT 5"
                    ).bindparams(uid=self.user_id, bid=self.business_id)
                else:
                    sql = text(
                        'SELECT o.order_id AS "orderId", o.status, p.name AS "productName", '
                        'o.total_amount AS "totalAmount" FROM orders o '
                        "LEFT JOIN order_items oi ON o.order_id = oi.order_id "
                        "LEFT JOIN products p ON oi.product_id = p.id "
                        "WHERE o.user_id = :uid LIMIT 5"
                    ).bindparams(uid=self.user_id)
                result = await session.execute(sql)
                past_orders = [dict(row) for row in result.mappings()]
        except Exception as sql_err:
            print(f"[Profiler Agent] Failed to fetch SQL transaction stream for audit: {sql_err}")

        # op 裁决对照清单(2026-10-24):该用户既有活跃事实(approved/pending 近 50
        # 条,id+subject+fact+status)随 prompt 提供给审计 LLM。租户过滤下沉同召回
        # 侧(code-review 2026-10-24:裸 user_id 查询是隔离缺口);superseded/deleted
        # 不进清单 —— LLM 据失效行判 NOOP 会静默吞掉真实改口,重改旧值由 ADD+
        # 维度覆盖路径自然接管。清单获取失败不阻断(LLM 按默认 ADD 输出)。
        existing_facts: list[dict] = []
        try:
            from sqlalchemy import select

            async with get_session() as session:
                fact_rows = (
                    (
                        await session.execute(
                            select(LongMemoryFact)
                            .where(
                                LongMemoryFact.user_id == self.user_id,
                                LongMemoryFact.status.in_(("approved", "pending")),
                                tenant_scope_condition(LongMemoryFact, self.business_id),
                            )
                            .order_by(LongMemoryFact.created_at.desc())
                            .limit(50)
                        )
                    )
                    .scalars()
                    .all()
                )
                existing_facts = [
                    {
                        "id": str(r.id),
                        "subject": r.subject or "self",
                        "fact": r.fact,
                        "status": r.status or "approved",
                    }
                    for r in fact_rows
                ]
        except Exception as facts_err:
            print(f"[Profiler Agent] 既有事实清单获取失败,本轮 op 裁决降级 ADD: {facts_err}")

        audit_prompt = build_profile_audit_prompt(
            past_orders, user_query, assistant_response, existing_facts=existing_facts
        )

        try:
            response = await get_chat_model().ainvoke(audit_prompt)
            content = response.content if hasattr(response, "content") else str(response)
            audit_result = parse_profile_audit_response(content)

            if not audit_result.get("hasNewPreference") or not audit_result.get("extractedFacts"):
                print("[Profiler Agent] 🍃 画像审计完成：本轮会话未检测到新的偏好特征变动。")
                return

            for item in audit_result["extractedFacts"]:
                try:
                    fact_text = item if isinstance(item, str) else item.get("fact")
                    confidence = 1.0 if isinstance(item, str) else item.get("confidence") or 1.0
                    # source 钉枚举(persona-hardening 13,2026-09-30):写时不信
                    # LLM 自填 —— 实弹模型把 source 填成中文叙述散文(「本轮对话
                    # -用户主动提及徒步行程」),归因查询全废。审计 Agent 产物
                    # 一律 agent_audit(legacy 字符串项形状照旧 agent_audit_legacy)。
                    source = "agent_audit_legacy" if isinstance(item, str) else "agent_audit"

                    # 第三人归属(2026-10-24 画像归属票):LLM 输出 subject 字段,
                    # 缺失/不可信时按 fact 文本关系称谓兜底
                    subject = "self"
                    if isinstance(item, dict):
                        subject = normalize_subject(item.get("subject"))
                    if subject == "self" and fact_text:
                        m = _THIRD_PERSON_RE.search(fact_text)
                        if m:
                            subject = normalize_subject(m.group(1))

                    # op 裁决(2026-10-24 SOTA 对齐 P1#1):LLM 对照既有事实清单
                    # 决定 ADD/UPDATE/DELETE/NOOP;op 缺失/不可信一律按 ADD 走
                    # 规则兜底(韧性纪律:裁决是增强不是依赖)。DELETE/UPDATE 是
                    # 用户明确撤回/改口 —— 权威语义,不受置信度门槛约束
                    # (code-review 2026-10-24:UPDATE 撞门槛会「废旧值又弃新值」
                    # 事实湮灭,新值最低落 pending)。
                    op = (item.get("op") or "ADD").strip().upper() if isinstance(item, dict) else "ADD"
                    target_id = item.get("targetId") if isinstance(item, dict) else None
                    if op not in ("ADD", "UPDATE", "DELETE", "NOOP"):
                        op = "ADD"
                    # 空 fact 守卫:prompt 允许 DELETE 的 fact 留空,严禁落空串事实行
                    if not (fact_text or "").strip() and op != "DELETE":
                        print("[Profiler Agent] ⚠️ 空 fact 丢弃")
                        continue
                    if op == "NOOP":
                        print(f"[Profiler Agent] ⏭️ op=NOOP(既有事实已覆盖): {fact_text}")
                        continue
                    if op in ("DELETE", "UPDATE") and target_id:
                        handled = await self._apply_target_op(
                            op=op,
                            target_id=str(target_id),
                            note_fact=fact_text or "",
                            thread_id=thread_id,
                        )
                        if handled and op == "DELETE":
                            continue
                        # DELETE 未命中目标:撤回无的放矢,不落"删除"为事实
                        if handled is False and op == "DELETE":
                            print(f"[Profiler Agent] ⚠️ DELETE 目标不存在或不属于该用户: {target_id}")
                            continue
                        # UPDATE 未命中目标 → 落到下方按 ADD 存新值

                    # 置信度红线路由:<0.60 丢弃;>=0.85 approved;其余 pending。
                    # 已生效的 UPDATE 豁免(撤回/改口是用户权威,新值最低落 pending)
                    authoritative_update = op == "UPDATE" and target_id is not None
                    if confidence < 0.6 and not authoritative_update:
                        continue
                    status = "approved" if confidence >= 0.85 else "pending"

                    is_physiological = fact_text and PHYSIOLOGICAL_RE.search(fact_text)
                    if explicit_scope:
                        item_scope = explicit_scope
                    elif isinstance(item, dict) and item.get("scope") in ("global", "tenant"):
                        item_scope = item["scope"]
                    elif is_physiological:
                        item_scope = "global"
                    elif self.business_id and self.business_id != "ecommerce":
                        item_scope = "tenant"
                    else:
                        item_scope = "global"
                    item_biz_id = (
                        explicit_business_id or self.business_id or "ecommerce"
                        if item_scope == "tenant"
                        else None
                    )

                    embedding = await get_embedding_model().aembed_query(fact_text)

                    # 回声/覆盖决策收口 _ingest_fact(同主体分组):可变数字维度
                    # 同值回声弃/异值覆盖,非维度事实回声三分(pending 再现升级=
                    # 再现审核闭环)
                    await self._ingest_fact(
                        fact_text=fact_text,
                        embedding=embedding,
                        scope=item_scope,
                        business_id=item_biz_id,
                        confidence=confidence,
                        status=status,
                        source=source,
                        subject=subject,
                    )
                except Exception as rag_err:
                    print(f"[Profiler Agent] Failed to vectorise and store extracted fact: {rag_err}")
        except Exception as err:
            print(f"[Profiler Agent Error] 画像 Agent 提取偏好发生异常: {err}")

    async def _apply_target_op(
        self, *, op: str, target_id: str, note_fact: str, thread_id: str | None
    ) -> bool:
        """对既有事实执行 UPDATE(转 superseded)/DELETE(转 deleted)。

        归属先验:id 必须属于本 user 且过租户过滤(code-review 2026-10-24:裸
        user_id 条件是隔离缺口,与召回侧 tenant_scope_condition 对齐)——不命中
        返回 False(调用方降级)。DELETE 同步清对应槽位(撤回身材后槽位残留会
        继续喂尺码工具,槽/事实分叉)。成功即入 badcase 候选池
        (SOURCE_PERSONA_FACT_DELETED,auto-draft 源):记忆 churn 是画像质量的
        第一手信号 —— note 只存维度引用不存画像原文(database-schema §1.1.6
        零原始数据纪律)。
        """
        from sqlalchemy import select

        from ..badcase.pool import SOURCE_PERSONA_FACT_DELETED, record_badcase_signal

        try:
            async with get_session() as session:
                row = (
                    (
                        await session.execute(
                            select(LongMemoryFact).where(
                                LongMemoryFact.id == target_id,
                                LongMemoryFact.user_id == self.user_id,
                                tenant_scope_condition(LongMemoryFact, self.business_id),
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
                if row is None:
                    return False
                old_fact = row.fact  # commit 前物化(会话关闭后访问 ORM 属性会 Detached)
                row_subject = row.subject or "self"
                dimension = fact_dimension_value(old_fact)
                row.status = "deleted" if op == "DELETE" else "superseded"
                if op == "DELETE" and dimension and _DIMENSION_TO_SLOT.get(dimension[0]):
                    await session.execute(
                        text(
                            "DELETE FROM profile_slots WHERE user_id = :u AND subject = :s AND slot = :slot"
                        ).bindparams(u=self.user_id, s=row_subject, slot=_DIMENSION_TO_SLOT[dimension[0]])
                    )
                await session.commit()
            await record_badcase_signal(
                SOURCE_PERSONA_FACT_DELETED,
                conversation_ref=f"thread:{thread_id}" if thread_id else f"user:{self.user_id}",
                business_id=self.business_id or "aurora",
                suggested_class="suspected_defect",
                note=(
                    f"op={op} target={target_id} "
                    f"dimension={dimension[0] if dimension else '非维度事实'} "
                    f"subject={row_subject}"
                ),
                dedupe=True,
            )
            print(
                f"[Profiler Agent] ✅ op={op} 已生效: 维度={dimension[0] if dimension else '非维度'} "
                f"subject={row_subject} -> {'deleted' if op == 'DELETE' else 'superseded'}"
            )
            return True
        except Exception as op_err:
            print(f"[Profiler Agent] op={op} 执行失败: {op_err}(调用方将跳过该条,不降级落 ADD)")
            return False

    async def _ingest_fact(
        self,
        *,
        fact_text: str,
        embedding: list[float],
        scope: str,
        business_id: str | None,
        confidence: float,
        status: str,
        source: str,
        subject: str,
    ) -> None:
        """事实落库单一决策点(2026-10-24 画像归属票):审计/正则两写路统一。

        - 分组键 = (user_id, subject):妻子的事实永不与本人互为回声、永不覆盖;
        - 可变数字维度(身高/体重/脚长/尺码):同维度同值=真回声(pending 顺带
          升级),异值=落新值+同维度旧值 superseded(修实弹「70/75 并存」与
          「措辞雷同改口被 0.90 吞」双失败模式);
        - 非维度事实:同主体回声 ≥0.90 弃;回声目标是 pending 时升级(再现即
          群众复核,补 pending 永无人审的闭环),approved 纯回声弃落。
        """
        from sqlalchemy import select

        try:
            async with get_session() as session:
                existing = (
                    (
                        await session.execute(
                            select(LongMemoryFact).where(
                                LongMemoryFact.user_id == self.user_id,
                                LongMemoryFact.subject == subject,
                                LongMemoryFact.status.in_(("approved", "pending")),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

                async def _promote(row: LongMemoryFact, incoming_conf: float) -> None:
                    """回声再现升级:置信度取双侧较高者 +0.05,达 0.85 即转 approved。"""
                    row.confidence = min(1.0, max(row.confidence or 0.0, incoming_conf) + 0.05)
                    row.status = "approved" if (row.confidence or 0.0) >= 0.85 else "pending"
                    await session.commit()
                    print(f"[LongMemory] 🔁 回声再现升级 pending 事实: {row.fact} -> {row.status}")

                dimension_value = fact_dimension_value(fact_text)
                if dimension_value is not None:
                    dimension, value = dimension_value
                    same_dim = [
                        row
                        for row in existing
                        if (dv := fact_dimension_value(row.fact)) and dv[0] == dimension
                    ]
                    twin = next(
                        (row for row in same_dim if fact_dimension_value(row.fact)[1] == value),
                        None,
                    )
                    if twin is not None:
                        if twin.status == "pending":
                            await _promote(twin, confidence)
                        else:
                            print(f"[LongMemory] 🔄 同值回声弃落: {fact_text}")
                        if _DIMENSION_TO_SLOT.get(dimension):
                            await self._upsert_profile_slot(
                                slot=_DIMENSION_TO_SLOT[dimension],
                                value=value,
                                confidence=confidence,
                                source=source,
                                subject=subject,
                            )
                        return
                    for row in same_dim:
                        row.status = "superseded"
                    session.add(
                        LongMemoryFact(
                            user_id=self.user_id,
                            business_id=business_id,
                            scope=scope,
                            fact=fact_text,
                            embedding=json.dumps(embedding),
                            type="preference",
                            confidence=confidence,
                            status=status,
                            source=source,
                            subject=subject,
                        )
                    )
                    await session.commit()
                    if same_dim:
                        print(
                            f"[LongMemory] ⏫ 维度新值覆盖: {fact_text}"
                            f"(superseded {len(same_dim)} 条旧值, subject={subject})"
                        )
                    if dimension_value is not None and _DIMENSION_TO_SLOT.get(dimension_value[0]):
                        await self._upsert_profile_slot(
                            slot=_DIMENSION_TO_SLOT[dimension_value[0]],
                            value=dimension_value[1],
                            confidence=confidence,
                            source=source,
                            subject=subject,
                        )
                    return

                echo = next(
                    (
                        row
                        for row in existing
                        if (emb := parse_embedding(row.embedding))
                        and cosine_similarity(embedding, emb) >= _ECHO_DEDUP_THRESHOLD
                    ),
                    None,
                )
                if echo is not None:
                    if echo.status == "pending":
                        await _promote(echo, confidence)
                    else:
                        print(f"[LongMemory] 🔄 回声事实弃落(与既有画像近重复): {fact_text}")
                    return

                session.add(
                    LongMemoryFact(
                        user_id=self.user_id,
                        business_id=business_id,
                        scope=scope,
                        fact=fact_text,
                        embedding=json.dumps(embedding),
                        type="preference",
                        confidence=confidence,
                        status=status,
                        source=source,
                        subject=subject,
                    )
                )
                await session.commit()
        except Exception as store_err:
            print(f"[LongMemory] 事实落库失败(user={self.user_id}): {store_err}")

    async def _upsert_profile_slot(
        self, *, slot: str, value: str, confidence: float, source: str, subject: str
    ) -> None:
        """结构化画像槽位 upsert(2026-10-24 SOTA 对齐 P1#2):同一 (user, subject,
        slot) 永远只有一行最新值 —— 尺码/荐品工具消费的结构化档案,自由文本
        事实层继续留长尾。失败打印不阻断(槽位是增强,不是事实层的依赖)。"""
        try:
            async with get_session() as session:
                await session.execute(
                    text(
                        "INSERT INTO profile_slots (user_id, subject, slot, value, confidence, source) "
                        "VALUES (:u, :s, :slot, :v, :c, :src) "
                        "ON CONFLICT (user_id, subject, slot) "
                        "DO UPDATE SET value = :v, confidence = :c, source = :src, updated_at = NOW()"
                    ).bindparams(u=self.user_id, s=subject, slot=slot, v=value, c=confidence, src=source)
                )
                await session.commit()
        except Exception as slot_err:
            print(f"[LongMemory] 槽位 upsert 失败(不阻断): {slot_err}")

    async def search_relevant_facts(self, query: str, precomputed_embedding: list[float] | None = None) -> list[dict]:
        if not self.user_id:
            return []

        query_embedding = precomputed_embedding
        if not query_embedding:
            query_embedding = await get_embedding_model().aembed_query(query)

        try:
            from sqlalchemy import select

            async with get_session() as session:
                # 候选集封顶(P6,2026-10-03):余弦打分在 Python 侧,旧行为全量
                # 拉取该用户 approved 事实随画像增长线性膨胀。上限 500 + 确定性
                # 新序(created_at/id 双键)—— 现实画像远低于此行为不变;超限
                # 时新事实让旧事实让位(新偏好覆盖旧偏好的自然取向)。
                rows = (
                    (
                        await session.execute(
                            select(LongMemoryFact)
                            .where(
                                LongMemoryFact.user_id == self.user_id,
                                LongMemoryFact.status == "approved",
                                # 租户过滤下沉 SQL(2026-09-21 拷问轮决议):候选窗口
                                # 不再被他租行挤占;Python 侧 _tenant_visible 保留为防御
                                tenant_scope_condition(LongMemoryFact, self.business_id),
                            )
                            .order_by(LongMemoryFact.created_at.desc(), LongMemoryFact.id.desc())
                            .limit(500)
                        )
                    )
                    .scalars()
                    .all()
                )
        except Exception as err:
            print(f"[LongMemory] cosine similarity search bypassed due to offline/failed DB: {err}")
            return []

        # 🛡️ 双层画像隔离:global 全放行;tenant 仅放行当前商户
        def _tenant_visible(row: LongMemoryFact) -> bool:
            if not row.scope or row.scope == "global":
                return True
            if row.scope == "tenant":
                if self.business_id and self.business_id != "ecommerce":
                    return row.business_id == self.business_id
                return not row.business_id or row.business_id == "ecommerce" or row.business_id == self.business_id
            return False

        visible_rows = [row for row in rows if _tenant_visible(row)]
        if not visible_rows:
            return []

        query_tokens = _query_tokens(query)
        scored = []
        for row in visible_rows:
            embedding_array = parse_embedding(row.embedding)
            similarity = cosine_similarity(query_embedding, embedding_array) if embedding_array else 0

            fact_lower = (row.fact or "").lower()
            keyword_matches = sum(1 for token in query_tokens if token in fact_lower)
            keyword_score = (
                0.55 + (keyword_matches / len(query_tokens)) * 0.45
                if query_tokens and keyword_matches > 0
                else 0
            )
            effective_score = max(similarity, keyword_score)
            scored.append(
                {
                    "fact": {
                        "id": str(row.id),
                        "fact": row.fact,
                        "category": row.type or "preference",
                        "timestamp": (row.created_at or _dt.datetime.now()).isoformat(),
                        "embedding": embedding_array or None,
                        "scope": row.scope or "global",
                        "subject": row.subject or "self",
                        "businessId": row.business_id or None,
                        "confidence": row.confidence if row.confidence is not None else 1.0,
                        "status": row.status or "approved",
                    },
                    "similarity": effective_score,
                }
            )

        scored.sort(key=lambda item: item["similarity"], reverse=True)
        threshold = 0.55
        filtered = [item for item in scored if item["similarity"] >= threshold]
        return [item["fact"] for item in filtered[:5]]


async def read_profile_slots(user_id: str, subject: str | None = None) -> list[dict]:
    """结构化画像槽位读取(2026-10-24 SOTA 对齐 P1#2):getProfileSlots 工具与
    尺码/荐品消费方的单一入口。subject 缺省返回全部主体(subject 字段标注)。"""
    from sqlalchemy import select

    if not user_id:
        return []
    try:
        async with get_session() as session:
            stmt = select(ProfileSlot).where(ProfileSlot.user_id == user_id)
            if subject:
                stmt = stmt.where(ProfileSlot.subject == subject)
            rows = (await session.execute(stmt.order_by(ProfileSlot.slot))).scalars().all()
        return [
            {
                "subject": r.subject or "self",
                "slot": r.slot,
                "value": r.value,
                "confidence": r.confidence if r.confidence is not None else 1.0,
                "source": r.source or "agent_audit",
                "updatedAt": (r.updated_at or _dt.datetime.now()).isoformat(),
            }
            for r in rows
        ]
    except Exception as err:
        print(f"[LongMemory] 槽位读取失败(user={user_id}): {err}")
        return []
