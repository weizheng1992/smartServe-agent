---
description: LangGraph 状态机决策图、Skills 技能开放架构、Temporal 工作流编排、四象限记忆与双层画像隔离规范
paths: ["services/engine-py/**/*"]
---

# 智能体核心决策引擎规范 (Agent Engine)

本服务是整个平台的核心中枢（`services/engine-py/src/engine_py/`），负责 LangGraph DAG 状态图调度、Skills 技能分发、四象限记忆体系、双层客户画像隔离、多模态视觉定责、Contextual RAG 检索、审批门禁与 Temporal 分布式工作流。行为规格以退役的 TS 实现为基线，由影子双跑（`shadow/`）与 pytest 契约测试钉死。

## 1. 核心架构与拓扑流程

### 1.1 状态转移拓扑 (Graph Topology)

- **状态总线**：基于 `graph/state.py` 的 `AgentState` 承载全局状态（`thread_id`、`intents`、`task_plan`、`short_memory`、`long_memory_facts`、`output`、`cards` 等；Python 侧 snake_case，但 `task_plan` 内部键与 SSE 载荷保持 camelCase 冻结契约）。
- **DAG 状态转移图**：
  - 起点 ➔ `triage`（意图分流与多模态感知）
  - 分流分支：日常寒暄/简单单意图走**极速直达旁路**（`executor_fast_path.py`）直接路由至 `finish`；复杂多意图路由至 `planner`。
  - 核心执行环：`planner` ➔ `merge` ➔ 循环 [`executor` ⇄ `validator`] ➔ 校验通过进入 `finish`；未通过或需回溯时退回 `executor`。
- **双模运行引擎**：优先连接 Temporal 工作流（端口 `7239`，队列 `agent-tasks-py`）编译执行 `temporal/workflows.py`；当 Temporal 离线时平滑回退至本地 LangGraph 仿真模拟器。
- **事件主干**：用户态进度事件经 `event_bus.py` 写入 Redis Streams（INCR 序号 + XADD maxlen），网关 SSE 直接以该流为事件源。

### 1.2 Skills 技能分发与开放集成架构 (Skills Pipeline)

- **技能基类 (`skills/base_skill.py`)**：所有业务技能（如 `OrderRefundSkill`）必须继承 `BaseSkill`，提供统一的元数据、依赖工具声明、SOP 策略以及多阶段执行管道（`validate` ➔ `pre_execute` ➔ `execute` ➔ `post_execute`）。
- **执行器调度 (`graph/nodes/step_execution_engine.py`)**：
  - 优先通过 Skills 注册表检索匹配的 Skill 实例执行业务逻辑；
  - 若无特定 Skill，则回退至标准 Tool 工具分发执行（`asyncio.gather` 并行调度依赖无关节点）。
  - 工具白名单（`base_tools`）范围（2026-09-07 扩容）：订单/退款基础工具 + 导购/购物车技能（须用注册表真实 id `skill_shopping_guide`/`skill_cart_manage`，TS 基线伪名是死路）+ 只读商品工具（`searchProducts`/`compareProducts`/`queryProductSkus`/`queryProductReviews`/`queryProductRanking`/`getCartSummary`）；**写操作购物车工具严禁入白名单**——加购/改量必须走技能 SOP 管道，不允许 LLM 兜底直调。特例（遗留二期 2026-09-13）：`saveUserAddress`/`getUserAddresses`/`checkoutCart` 入列 —— 地址簿是顾客自有低风险写（不入列则快轨子任务空转致幻觉成功），checkoutCart 是结算本体（与商城页 create_order_from_cart 同一真账本，顾客自有资金下单与商城页同权，spec 明示豁免 HITL），两者均有确定性快路径；addToCart/updateCartItem 仍严禁入列。
- **租户级技能配置重载 (Tenant Skill Config Overrides)**：
  - 支持多租户在 `TenantBusinessConfig` 中动态覆写技能参数（启用/禁用、退款限额阈值 `maxAutoRefundAmount`、退款有效窗口 `maxRefundDays`、强制人工审核开关 `requireApproval`、自定义通知 Webhook 等）。

### 1.3 分流与意图消歧 (Triage & Disambiguation)

- **仲裁化意图架构（intent-arbitration，2026-09-10）**：「正则建议、LLM 仲裁」——非 LLM 层（规则/槽位/锚点）是**提议者**而非终局裁判，LLM 是仲裁员与终局。逐层判定以 `{layer, intent, confidence}` 快照累积进 `proposals`，终局决策经 `log_intent_to_db` **单点落库** `intent_logs`（同一输入只允许一次写：fast-track 命中以 bypass 内写为准，槽位层不预写）：`candidates` 承载各层提议、`winner` 取首个 primary、`arbitration_reason` 记裁决理由（旁路默认即路由键）。终局权分层：规则前置层（空/符号/超长/问候/退出/语义重复，罐头回复错判代价为零）与技能快轨照旧零 LLM 闭环；**锚点 oos（Step 2 判定 4）降为提议者**——≥0.86 疑似出范畴只记 `embedding(out_of_scope)` 提议后 fallthrough Step 3，由 LLM 确认收尾（`llm_out_of_scope`，+1 确认调用经 `llm_call_logs` node 归因单列可见）或改判（咨询直答/动作管线）；route key `embedding_out_of_scope` 已退役。**规则直通前置的两个登记成员（意图写动作形）**：`metric_query`（ADR-0003 利润×排行共现，`profit_ranking_precheck`）与 `address_manage`（多意图一期 2026-09-12，地址簿创建/查询检测器 `detect_address_manage`，`address_manage_precheck`；复合候选形不直通、由 Step3 注入器提为 primary）——两者直通的错判代价同为近零（检测器双词族共现/显式动词锚定），且词表缺口下 LLM 仲裁层反而必然误判（分类器 10 类目无档位可落），属 §1.3 枚举的如实扩员而非破例。
- **仲裁留痕的两个消费方**：① 坏例池冲突信号源（§1.8，`badcase/intent_signals.py` 的 `detect_intent_conflict`）——candidates 跨意图族（动作形 × 咨询侧：consult/general_query/out_of_scope/chat/chitchat）且来自**不同层**即入 `intent_conflict` 候选；「宣称 out_of_scope × 落库 general_query 不符」另有独立信号源；信号只入池不直接成为断言。② 冲突触发仲裁的数据底盘（07 决策：393 行留痕审计靶形状 0 例，显式接受残余不加 LLM 调用；零调用标记 `is_consult_shaped_marker` 挂槽位层动作终局，命中记 `consult_shaped_gate` 提议，残余复现对信号源可见，与 ① 同口径消费）。
- **咨询类直答快轨（`triage/consult_fast_path.py`，2026-09-09）**：挂 triage Step 1.4（寒暄规则后、槽位抽取前）—— 政策/尺码/物流时效等「问知识」型输入（`is_consult_query`：咨询话题 × 疑问语气，否定动作形/复合意图/显式订单号/带图）在此闭环：语义缓存先查（≥0.96 秒回）→ 复用 run_agent 预取的 RAG 切片（top 相似度 ≥0.55 才直答）→ 单次 LLM 调用（人设+切片+历史）strictly grounded 直答 → 答案回填语义缓存；旁路 planner/executor/finish 终稿全程（咨询类 3-4 次串行调用 → 1 次，重复问 → 0 次）。RAG 空弱/直答失败回落 general_query 零规划旁路（finish 诚实作答），严防 Step 1.5「退货」字样误判动作形反问订单号、Step 2 判定 3 关键词误判 refund 动作进 planner 深度规划。意图体系同步补 `consult` 档位（`AgentIntentType.CONSULT` + structured_classifier 类目 10），分类器判 consult 时走同一快轨。缓存信任模型：`is_consult_query` 的动作形否定模式即读写两侧防投毒闸，无需过 `is_action_query`（「退货政策」会被 OrderRefundSkill 兜底正则嗅探成动作形，对咨询形输入是误报）。**答案调用兼任仲裁员（05，2026-09-10）**：直答 prompt 带 ROUTING VETO 规则，发现用户实为请求执行动作时返回 `__ROUTE_TO_ACTION__` 哨兵而非作答——快轨放行 fallthrough 完整管线（Step 1.4 侧）或降级 general_query 零规划（Step 3 侧，consult 落 planner 会失控深规划）；否决进 candidates（`consult_arbiter` 层 intent 记 None），标记回复严禁写语义缓存。零新增调用：p50 咨询路径仍是那一次直答调用，只是从「答案生成器」升级为「答案生成器+意图复核员」。
- **第一道防线（语义去重旁路）**：`triage/semantic_cache.py` 计算与前序查询的余弦相似度（≥ 0.98），直接命中缓存返回。
- **重复提问拦截器的多模态豁免（2026-09-10 误退事故收口）**：Step 0 区的文本重复拦截器（`坏了`==上一轮文本 → `duplicate_bypass` 重放上一轮答复）**带图轮次整体豁免**——图证即新证据，文本相等不足以判「同一问题」；否则带图重发会在 Step 0.5 图证（OCR 单号/破损定责）被消费之前就把会话关成过期答复的重放（事故：重放修复前的旧消歧卡，引导用户挑本店真单对外店单误起退款审批）。与 `is_operational_action` 同为去重豁免闸，由 `test_duplicate_bypass_image_turn.py` 钉死（含纯文本真重复照旧重放的对照组）。
- **问候旁路同源化（new-user-onboarding D，2026-09-10）**：问候/身份词表统一为 `rule_matchers.QUICK_GREETING_WORDS` 单一来源（旧 run_agent 身份问句表 × 旧 triage 时段问候表并集收口;`GREETING_RE` 由词表程序化派生,两层永不漂移;词条一律规整后形态——带空格的 "who are you" 在两层剥空白规整下本是死词条,统一为 `whoareyou`）。`run_agent` 极速旁路（`is_quick_greeting`,triage 之前拦截,零 LLM）与 triage Step 1 规则层（`is_greeting`,纵深防御兜底）罐头回复统一消费租户 `onboarding_config`（`resolve_onboarding_config` + `build_entry_cards`,与网关建线程欢迎行同一份配置——杜绝两套自我介绍）,welcomeText + quick_replies 入口卡带卡落库;零 LLM、`rule_greeting` 路由键与仲裁留痕口径不变,由 `test_greeting_bypass_onboarding.py` 钉死。
- **低置信度归档与槽位消歧**：分类置信度不足时，自动写入 `low_confidence_logs` 表，并触发 `triage/slot_extractor.py` 引导用户补充缺失关键槽位。
- **多模态视觉定责**（`vision/analyzer.py`，2026-09-08 移植 TS visionAnalyzerService）：挂 triage Step 0.5，视觉 LLM 精判 + 启发式规则双通道（模型失败降级启发式，绝不炸会话）；快递面单/包装条形码 OCR 实体提取（如 `ORD-XXXXX`、`SFXXX`），商品成色与破损智能定责评级（`negligible` / `minor` / `severe`）；容灾超时 `AI_VISION_TIMEOUT_SECONDS` 可调（默认 30s，E2E 实测 GLM-4.6V 真实请求可超 15s，TS 的 1500ms 硬超时已废）。本地图（`/api/uploads/` 引用）以 base64 Data URL 直传（bigmodel 拉不到 localhost），模型独立经 `get_vision_model()` 配置（`AI_VISION_MODEL`，默认 glm-4.6v，结构化输出走 function_calling）。入图治理（005）：`run_agent` 构建初始状态时经 `normalize_image_urls` 收口 —— 剔除垃圾项、去重保序、**≤3 图/条**截断（与网关上传单张 10MB 限额对齐）；垃圾输入只少看图不抛错。
- **破损图商品归属消歧**（`triage/product_disambiguator.py`，2026-09-09）：闸门挂在**售后意图实际浮现的位置**而非固定某步——「坏了」这类模糊词槽位阶段判 `chat`，售后意图要靠 `damage_assessment` 在 Step 2 判定 3 才浮现（2026-09-09 事故：只挂 Step 1.6 时对典型措辞永不触发，退回 planner 深规划自由发挥）。三处生效：Step 1.6（槽位阶段已判售后）/ Step 2 判定 3（damage_assessment 令关键词成立）/ Step 3（分类器精判，`vision_disambig_matched` 令注入前的陈旧 missingSlots 澄清让位）；无候选/多候选统一经 `_vision_disambig_bypass` 收口。触发前提：带图 + 售后意图（`order_return`/`refund`）+ 缺 `orderId`（文本/已确认上下文/图内 OCR 三通道皆无）。三态：`matched`（置信度 ≥0.8 且命中项原样在候选集内，防幻觉键集校验）注入 `order_context.targetOrderId` 并重跑槽位抽取；`ambiguous`（多候选/低置信/模型失败）出商品选择 `quick_replies` 卡，点选文本带单号下一轮走 `ORDER_ID_RE` 正则闭环；`no_orders` 明示指引。候选池走 `OrderDomainService.get_recent_product_lines` 门面 —— **商户真单（`agent_merchant.merchant_orders`）优先、engine 本地表兜底**（两库优先级与订单列表同源；商户用户在 engine 表无单，直查 detailed 永远空候选）。消歧失败绝不炸会话，最坏多问一次。
- **图内 OCR 单号消费**（2026-09-09 事故收口）：`vision_analysis.extractedOrderId` 与文本单号同语义消费（Step 0.5 计算 `vision_order_id`，Step 1.5 注入后重跑槽位抽取）——此前算完即丢，图内明示单号对流程零贡献。优先级 **文本显式 > 已确认上下文（TaskMemory.orderContext，Step 1.5 同步进 state）> 图内 OCR > 历史回填**，OCR 永不覆盖已确认单号；**历史回填单号（通用 `extract_order_id` 反向扫历史的续聊启发）不写入 `order_context` 冒充已确认、不充当消歧闸的已解析通道**（2026-09-10 误退事故第二层：旧消歧卡里的本店真单借此在 OCR 失效轮次被当 confirmed 直接自动退款；回填值留在 slots 仅供查询类快轨续聊）。Step 2 各判定单号融合 `matched_order_id or confirmed_order_id or vision_order_id`，判定返回透传 `order_context`。OCR/文本单号三库查无此单时由执行器幽灵单前置拦截（§1.6）诚实报错。

### 1.4 四象限记忆与双层画像隔离 (Quad-Memory & Dual-Tier Persona)

- **短期记忆 (`memory/short_memory.py`)**：基于 `messages` 物理表读取最近 10 轮对话，内存为空时触发自愈补全。
- **消息写所有权(multimodal 005 治理)**：用户行唯一由**网关**写入(dispatch/SPI/商户 store_chat 三个入口,唯一持有 `imageUrls` 的位置;store_chat 补写系 2026-09-09 修复——商户用户消息此前完全不落库,历史恢复缺用户行);引擎侧零写用户行(`run_agent` 主链/问候旁路/Temporal activity 均不插,历史经 `short_memory.get_messages` 读网关副本),否则时间线双插 user×2(一行带图一行不带)。assistant 行仍归引擎(`short_memory.add_message`),由 `test_user_message_single_write.py` 钉死;唯一例外是网关建线程时写入的 welcome/greet 引导行(new-user-onboarding C,详见 server-gateway.md §1.1)。
- **长期偏好记忆 (`memory/long_memory.py`)**：大模型提取用户习惯，向量化存储至 `long_memory_facts`，检索时基于余弦相似度（硬阈值 ≥ 0.65）召回 Top-5。
- **情境记忆 (`memory/episodic_memory.py`)**：关键业务事件按重要性（1-10分）向量化落盘。
- **任务记忆 (`memory/task_memory.py`)**：持久化保存挂起和未完成的任务规划步骤。
- **双层画像物理隔离**：
  - 严格区分 `scope: 'global'`（客观生理属性，如脚长/过敏史）与 `scope: 'tenant'`（品牌专属偏好/会员积分）。
  - 上下文装配召回时严格限定：`WHERE user_id = :1 AND (scope = 'global' OR business_id = :2)`，严禁跨租户泄漏画像。

### 1.5 Contextual RAG 知识检索 (`rag/contextual_rag.py`)

- **上下文增强切片**：文档入库时切片，并由大模型为每个切片前缀生成包含全局文档背景的 Contextual Summary。
- **租户物理隔离检索**：向量检索与 SQL 过滤强制附带 `WHERE business_id = :tenant_id`，物理阻断跨租户政策混淆。

### 1.6 审批门禁与事务发件箱 (`approvals/gatekeeper.py` & `approvals/outbox_worker.py`)

- **HITL 安全挂起**：退款、改地址等高危动作触发挂起，记录写入 `pending_approvals`（ID 必须为 UUID 格式，网关校验）。
- **幽灵单前置拦截**（执行器 4.1.1，2026-09-09 OCR 事故收口）：`processRefund` 开 HITL 工单**之前**，经 `check_double_refund` 的 `orderFound` 契约（`find_order_by_id` 三源按归属查询，异常 fail-open）对三库查无此单（或非本人归属）的单号诚实失败（"未查询到订单 [X]，或该订单不属于当前账户"）——旧行为直达 waiting 工单且 finish 终稿谎称"已为您发起退款申请"（图内 OCR 与文本敲错单号同罪）。技能 fast-track 路径本就有同款校验（`order_skills.py`），执行器在此对齐。
- **事务发件箱（Transactional Outbox）**：审批动作与 `approval_outbox_events` 事件在同一数据库事务中原子提交。
- **确定性去重恢复**：恢复任务采用确定性标识 `job_resume_${approvalId}`。恢复由 `process_approval_action` 的同步 Fast-Path 派发（派发失败事件留 `pending`）；`outbox_worker.process_pending_events` 为失败事件的对账补偿（`FOR UPDATE SKIP LOCKED` 防多实例重复、10s 年龄阈值避开与 Fast-Path 竞争、`processing` 停滞 >5min 重入队），由 `scheduler.py` 周期调度（30s 间隔，随 Temporal worker 入口启动，单实例假设，`ENGINE_SCHEDULER_ENABLED=0` 关闭；2026-09-03 修复接入）。

### 1.7 影子双跑与回放 (`shadow/diff.py` & `shadow/replay.py`)

- 迁移验收期工具：对冻结的 TS 基线输出做逐字段 diff 与历史流量回放；基线钉死后仅作回归参考。

### 1.8 坏例候选池与周期任务调度 (`badcase/` & `scheduler.py`,2026-09-03 第五阶段 v1)

- **半自动闭环**：信号收集/用例起草自动化，triage 定夺与入集人工化——信号**永不直接成为回归断言**。
- **信号源与先验**（`badcase/pool.py`）：人工接管 `human_takeover` / 画像事实删除 `persona_fact_deleted`（→ `suspected_defect`）/ 审批驳回 `approval_rejected`（→ `expected_behavior`）/ 熔断 `circuit_breaker`（→ `suspected_defect`；2026-09-07 起接入，挂 `run_agent` 会话收口处 —— 上游 LLM 熔断与图级熔断（转移 ≥10 / 工具错误 ≥3）两路均入池，挂点与 `session_metrics` 熔断落盘同位）/ 意图冲突 `intent_conflict` 与 宣称落库不符 `intent_mismatch`（→ `neutral`，intent-arbitration 02，2026-09-10：挂 `log_intent_to_db` 单点落库后，`detect_intent_conflict` 判 candidates 跨意图族（动作形 × 咨询侧，须来自**不同层**，单层内多意图不算）即入池；`intent_mismatch` 针对 LLM 精判宣称 out_of_scope × 落库 general_query 的矛盾行 —— 与 §1.3 仲裁留痕同源消费，也是冲突触发仲裁（07）的数据底盘）。入池接口 `record_badcase_signal` 失败静默降级（print 不吞错），**严禁阻断宿主事务**。
- **脱敏两层管道**（`badcase/redaction.py`）：库内已知值精确替换（地址/收件人/邮箱）➔ `scrubber` 正则兜底；`show` 输出"原文 vs 脱敏对照"，回归用例输入必须取脱敏侧（仓库零原始数据）。
- **triage CLI**：`python -m engine_py.badcase.cli`（list/show/triage/draft/expire）；`draft` 只产 `expectedTools`/`not-contains` 断言（断言最小化，禁整句黄金答案），带 `origin: badcase:{id}` 溯源，人工并入 `eval/testCases/` 后标 `converted`。
- **周期任务**（`scheduler.py`，随 Temporal worker 入口启动，Temporal 离线仍独立运行）：outbox 对账（30s）+ 坏例池摘要/保留期（6h）；**单实例假设**，`ENGINE_SCHEDULER_ENABLED=0` 关闭。

---

## 2. 编码与维护准则

1. **确定性拓扑**：修改 `graph/nodes/planner.py` 时必须严格声明 `dependencies` 依赖数组，供 `step_execution_engine.py` 并行调度。
2. **统一调用入口**：所有 LLM 与向量 Embedding 调用必须统一走 `llm/chat.py`（`get_chat_model` / `get_embedding_model` / `get_vision_model`，lru_cache 单例）；熔断/退避/超时由 `llm/resilience.py` 的全局 CircuitBreaker 承担（2026-09-07 起，挂 `_ResilientChatOpenAI` 公共 invoke/ainvoke 全覆盖），阈值经 `LLM_CIRCUIT_*` / `LLM_RETRY_*` / `LLM_TIMEOUT_SECONDS` env 可调。例外：`get_vision_model` 刻意不入韧性层 —— 视觉失败域独立，自带启发式兜底（wayfinder multimodal 003）。**bigmodel 参数兼容（2026-09-09，`_get_request_payload` 单点收口）**：glm-4.7 拒收 OpenAI 专有参数 —— `parallel_tool_calls`（任意组合 400 code 1210）、`stream:false` 与 tools 同现、`tool_choice` 对象形式；langchain `with_structured_output(function_calling)` 三者皆发，故 chat 模型统一剥前两者、把 `tool_choice` 对象**改写**为字符串 `"required"`（不能剥除——实测闲聊 prompt 下模型即不调工具，结构化解析失败；`"required"` 强制调用语义等价）。glm-4.6v 均收，vision 通路不受影响。契约由 `tests/test_llm_chat_model.py` 钉死。**思维链关闭（2026-09-09，同收口点）**：glm-4.7 默认开 thinking，琐碎调用也先生成大量 reasoning token（裸测同题 79.9s vs 关闭 7.5-18s），客服管线串行多次调用即分钟级回复；`AI_THINKING=disabled`（默认）时统一经 `extra_body` 注入 `{"thinking":{"type":"disabled"}}`（thinking 非 openai SDK 标准参数，顶层直塞 create() 即炸 unexpected keyword argument，必须走 extra_body 通道；setdefault 尊重调用方覆写；`enabled` 不注入，换不支持该参数的提供方时规避 400）。planner 深度规划走 `planner_llm()` 工厂（`bind(max_tokens=AI_PLANNER_MAX_TOKENS)`，默认 2000）——曾对「退货政策」类简单问题生成 5163 token（73.7s），封顶防失控，截断 JSON 落兜底单步计划；bind 仍包 `_ResilientChatOpenAI`，熔断/遥测不丢失。
3. **中文本地化日志**：Temporal Activity 与执行节点产生的所有用户态进度事件必须使用标准中文本地化文本。
4. **无异常冷启动**：记忆检索、租户配置加载等底层逻辑必须兼容空数据与冷启动，严禁未捕获抛错阻断状态机。
5. **环境自读取**：`config.py` 在导入时读取环境变量；任何测试基建必须先注入 `DATABASE_URL` / `REDIS_URL` 再导入 engine_py 模块。
