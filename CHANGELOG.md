# 🚀 CHANGELOG.md

系统中所有重要升级、重大架构重构、Breaking Changes 以及功能演进均记录在案。

---

## [2.6.4] - 2026-09-10 (意图仲裁化:正则建议、LLM 仲裁 —— 留痕/信号源/快轨仲裁员/锚点降级/评测伞)

起点(`/grill-me` 评审):`graph/nodes` 的意图解析是否需要优化。结论:分流瀑布本身高效,病灶在**终局权分配**——非 LLM 层(正则/槽位/锚点)独自把对话判死后无迹可查、无信号可救。四轮评审定下「正则建议、LLM 仲裁」模型,8 张工单(spec:`.scratch/intent-arbitration/`)分两阶段落地:

### ✨ Features (阶段 1:留痕与信号底座)

- **仲裁留痕(01)**:各判定层以 `{layer, intent, confidence}` 快照累积 `proposals`,终局经 `log_intent_to_db` **单点落库** `intent_logs`(`candidates` 列 + `winner` + `arbitration_reason`)——修复槽位层与 skill_fast_track 同输入双写;`llm_call_logs` 补 `node` 归因,每笔 LLM 调用可溯源到图节点(延迟统计/成本归因的地基)。
- **坏例池两个新信号源(02)**:`intent_conflict`(candidates 跨意图族:动作形 × 咨询侧,须来自不同层)与 `intent_mismatch`(LLM 宣称 out_of_scope × 落库 general_query 不符),挂单点落库后入池;信号只入池不直接成为断言,经人工 triage 并入评测语料。
- **评测伞扩展(03)**:统一套件意图分类用例改测**真引擎**(`agent_provider._triage_full`,经 intent_logs 带出仲裁留痕),classify 回声 provider 退役;新增 `intentF1`/`notOosCanned`/`arbitrationTrace`/`ragDirect`/`sameAskConsistency`/`slotClarification` 文件化 scorer(promptfoo 0.111 内联箭头函数断言不执行,必须 file://);伞面 54+8,基线全钉绿。
- **意图注册表合一(04)**:消费方驱动收敛——`AgentIntentType` 枚举为唯一事实源,F1/评测断言/分流路由同源消费。

### ✨ Features (阶段 2:终局权重分配)

- **咨询快轨终局权收编(05)**:直答 prompt 带 ROUTING VETO——用户实为请求执行动作时返回 `__ROUTE_TO_ACTION__` 哨兵,快轨放行 fallthrough 完整管线(正则误命中的代价从「答非所问且关会话」降为多走一次既有管道);Step 3 侧否决降级 general_query 零规划。零新增调用/延迟:p50 咨询路径仍是单次直答,答案生成器升级为生成器+复核员;标记回复严禁写语义缓存。
- **锚点 oos 终局权收编(06)**:Step 2 判定 4(29 锚句余弦 ×0.86 硬阈值)不再独自关会话——记 `embedding(out_of_scope)` 提议后 fallthrough Step 3 精判:确认出范畴照旧收尾(`llm_out_of_scope`,candidates 呈现 embedding→structured_llm 确认链),改判走咨询直答/动作管线。实测靶案例「买个东西怎么买」(oos 锚句相似 1.000 的购买流程咨询)从罐头「超出服务范围」转判 shopping_guide;route key `embedding_out_of_scope` 退役。真 oos +1 确认调用,node 归因单列可见,p50 咨询路径不含此路径。
- **冲突触发仲裁·数据定夺(07)**:01 留痕 393 行直接审计「槽位/锚点判动作 × 咨询形措辞」靶形状 **0 例**(冲突 33 例全为 slot(chat)×动作胜出的良性形状)——显式记录「接受残余,不加 LLM 仲裁调用」决策(硬上会令礼貌措辞的真动作平白 +1 调用);补零调用观测标记 `is_consult_shaped_marker` 挂槽位层动作终局,命中记 `consult_shaped_gate` 提议,残余复现对坏例池信号源可见(此前单层动作终局无 consult 侧候选,残余不可见无从积累数据)。

### ✅ 验证 (Verification,如实)

- engine pytest **291 passed**(阶段 1 基线 276 + 阶段 2 新增 15:锚点仲裁 3 + 冲突标记 12),ruff 干净;网关契约 100 passed。
- 延迟/调用数实测(`llm_call_logs` node 归因):咨询直答缓存未命中 **1 次调用**(直答兼任仲裁员,与 2.6.2 快轨持平)/ 复问 **0 次调用 0.1s**(语义缓存)/ 真 oos **1 次确认调用 5-6.5s**(06 引入,p50 咨询路径不含)/ 动作查询带单号 triage 阶段 **0 次 LLM 调用**(技能快轨)。05 仲裁员否决路径实弹验证(5-token 哨兵 → fallthrough → 动作管道),02 冲突信号同步入池。
- promptfoo 统一伞 54 用例 + planner 伞 8 用例终钉全绿(基线 README 数字同步)。
- 已知残余(如实记录):无标点「谁」系疑问句(「改地址的话转寄运费谁承担的呀」)对快轨闸门与 07 标记同时隐形,槽位层判动作反问单号而知识库有答案——留痕可见、待放量后凭 02 信号复盘,不在本批硬修。

---

## [2.6.3] - 2026-09-09 (破损图 OCR 单号消费 + 消歧闸门意图浮现点补全 + 幽灵单前置拦截)

诊断起点（/diagnosing-bugs）:用户上传破损鞋图（图内印有「破损投诉 ORD-77777」字样）+「坏了」，机器人却回问"是 9081 还是 9082 哪笔订单出了问题"。vision 实弹输出完全正确（`extractedOrderId=ORD-77777` / ocrText / severe 0.95）——错在引擎把识别结果丢掉了，三层缺陷连环：

1. **OCR 单号算完即丢**：`vision_analysis["extractedOrderId"]` 全链零消费，不进 intents.entities / order_context / 槽位 → 引擎"看不到"图内单号 → 回问订单（intent_logs 佐证 entities 恒空）。
2. **消歧闸门时序错位**：2.6.0 的商品归属消歧只挂 Step 1.6（认 SlotExtractor 阶段的 intentType），而「坏了」这类模糊损坏词槽位阶段判 `chat`，售后意图要到 Step 2 判定 3 才由 `damage_assessment` 浮现 → 为本场景造的选择卡对典型措辞**永不触发** → planner 深规划 ~50s 由 finish 自由发挥。
3. **幽灵单直达 HITL（连带发现的存量缺陷）**：OCR 出的或随手敲的单号（ORD-77777 / ORD-99999 三库查无此单）直接开 waiting 审批工单，finish 终稿还谎称"已为您发起退款申请"——文本路径同样中招（实测「帮我退款 ORD-99999」），非本次回归。

### 🐛 Fixes

- **OCR 单号消费（`triage/intent_triage_engine.py`）**：Step 0.5 计算 `vision_order_id`；Step 1.5 同步已确认上下文（TaskMemory.orderContext）进 state（此前已确认单号在轮间丢失）+ OCR 注入后重跑槽位抽取（退款严格抽取器经 `orderContext.targetOrderId` 取到，与消歧 matched 注入同型）。消费优先级 **文本显式 > 已确认上下文 > 图内 OCR**，OCR 永不覆盖已确认单号。Step 2 各判定单号融合 `matched_order_id or confirmed_order_id or vision_order_id`，判定 1/2/3 返回透传 `order_context`。
- **消歧闸门补到全部意图浮现点（同文件）**：Step 2 判定 3（模糊损坏词由 damage_assessment 浮现）与 Step 3（分类器精判浮现）带图缺单号同样过 `disambiguate_product`；Step 3 侧 `vision_disambig_matched` 令注入前的陈旧 `missingSlots` 澄清让位（结构化输出的 missingSlots 是注入前的快照）。两态收口统一走新增 `_vision_disambig_bypass`（无候选明示指引 / 多候选商品选择卡），与 Step 1.6 共用。
- **幽灵单前置拦截（`approvals/gatekeeper.py` + `graph/nodes/step_execution_engine.py`）**：`check_double_refund` 补 `orderFound` 契约（经 `find_order_by_id` 三源按归属查询；查询异常 fail-open，物理分发层兜底）；执行器 4.1.1 在审批门（4.4）**之前**对查无此单诚实失败（"未查询到订单 [X]，或该订单不属于当前账户，请核对订单号"），不开 HITL 工单、不虚构退款进度。技能 fast-track 路径本就有同款校验（`order_skills.py`），执行器在此对齐。

### ✅ 验证 (Verification，如实)

- 新增 `tests/test_vision_order_consumption.py` 5 用例（事故回放：实弹 vision 输出 + 锚向量定向 refund——OCR 单号流入实体/上下文、已确认单号不被 OCR 覆盖、模糊损坏词出选择卡、OCR 有单号跳过消歧、Step 3 浮现同样出选择卡）；`tests/test_double_refund_replay.py` 补幽灵单用例（红→绿：修复前 `status=pending` 开工单，修复后 `failed` 且工单数不变）。engine 全量 **234 passed**（2.6.2 基线 227 + 7），ruff 干净。
- 实弹矩阵（dev 网关 + GLM-4.6V，全部绿）：
  - **OCR 路径**：事故原图（带 ORD-77777 字样）+「坏了」→ OCR 单号被消费 → 幽灵单拦截诚实失败"未查询到订单 [ORD-77777]，或该订单不属于当前账户"，幽灵工单 0 新增；
  - **选择卡路径**：裁掉文字的破损鞋图（OCR 无单号）+「坏了」→ `vision_disambig` 路由（intent_logs 钉死）→ 商品选择卡（9081 冲锋衣 / 9082 工装裤，点选载荷带单号下一轮走 `ORDER_ID_RE` 正则闭环）。
- dev 库 8 张 ORD-77777/ORD-99999 waiting 幽灵工单系修复前实弹测试残留，已清理（现 0 张）。
- 网关契约套件由人工 `bun run test:eval` 复验（本次改动均在 engine 侧，不触网关契约）。
- 文档同步：`.claude/rules/agent-engine.md` §1.3（消歧浮现点 + OCR 消费条目）/ §1.6（幽灵单前置拦截）；`docs/architecture/multimodal-and-rich-cards.md` §2.3（OCR 消费语义落地）/ §6.0（闸门时序表）/ §6.3（幽灵单拦截）；README 商户悬浮窗能力描述。

---

## [2.6.2] - 2026-09-09 (商户聊天分钟级延迟治理:思维链关闭 + planner 封顶 + 咨询类 RAG 直答快轨)

诊断起点:「查询等了好几分钟没有回复」。根因非 db:seed(RAG 空有冷启动自愈),而是 glm-4.7 **默认开 thinking**——每次调用先吐大量 reasoning token(裸测同题 79.9s vs 关闭 7.5-18s),而客服管线一次提问串行 3-4 次调用(triage 分类 → planner 深度规划 → executor → finish 终稿),叠加即 57-114s。政策类问题还有额外病灶:planner 曾对「退货政策」生成 5163 token(73.7s),且咨询类在意图体系里没有独立档位,按措辞随机误落三处(反问订单号 / 误判 refund 动作进深规划 / general_query 两跳)。按用户「按顺序解决」三刀切:

### ✨ Features (新功能)

- **思维链关闭(`llm/chat.py` `_get_request_payload` 单点收口)**:`AI_THINKING=disabled`(默认)时统一经 `extra_body` 注入 `{"thinking":{"type":"disabled"}}`——thinking 非 openai SDK 标准参数,顶层直塞 create() 即炸 `unexpected keyword argument`,必须走 extra_body 通道;`setdefault` 尊重调用方覆写;`enabled` 不注入(换不支持该参数的提供方时规避 400)。finish/executor 等全部聊天调用默认受益,4-10 倍延迟改善。契约由 `tests/test_llm_chat_model.py::TestThinkingDisabled` 钉死。
- **planner 输出封顶(`graph/nodes/planner.py` `planner_llm()` 工厂)**:`bind(max_tokens=AI_PLANNER_MAX_TOKENS)`,默认 2000——封顶防失控,截断 JSON 落 planner 兜底单步计划(降级不炸会话);bind 仍包 `_ResilientChatOpenAI`,熔断/遥测不丢失。契约由 `tests/test_planner_token_cap.py` 钉死。
- **咨询类直答快轨(`triage/consult_fast_path.py`,挂 triage Step 1.4)**:政策/尺码/物流时效等「问知识」型输入单次 LLM 调用直答,旁路 planner/executor/finish 终稿全程(3-4 次串行调用 → 1 次;重复问 → 0 次):
  - `is_consult_query` 咨询形判定:咨询话题 × 疑问语气,三重否定闸(显式订单号 / 动作形与复合意图措辞 / 带图——带图售后走视觉定责管道);≤12 字裸话题(「退货政策」)省略式也算。
  - 编排 `run_consult_direct_answer`:语义缓存先查(≥0.96 秒回,先于 RAG 闸使 FAQ 复放不受知识库空弱影响)→ 复用 run_agent 预取的 RAG 切片(零额外检索,top 相似度 ≥0.55 才直答)→ 单次调用(品牌人设 + 切片 + 近期历史)strictly grounded 直答 → 答案回填语义缓存;熔断穿透,其余失败回落。
  - RAG 空弱/直答失败回落 general_query 零规划旁路(finish 诚实作答),**严防旧误路由**:Step 1.5「退货」字样误判动作形反问订单号、Step 2 判定 3 关键词误判 refund 动作进 planner 深度规划。
  - 意图体系同步补 `consult` 档位:`AgentIntentType.CONSULT` + structured_classifier 类目 10(问知识非办事、永不与订单号共存),分类器判 consult 时走同一快轨。
  - 缓存信任模型:`is_consult_query` 的动作形否定模式即读写两侧防投毒闸,刻意不过 `is_action_query`(「退货政策」会被 OrderRefundSkill 兜底正则嗅探成动作形,对咨询形输入是误报)。

### 🔍 Findings (核查结论,未动代码)

- **商户悬浮窗等待期无 thought 播报(#7)**:widget 仅订阅 Redis pubsub `thread:{id}:message`(终稿回复),引擎 `${jobId}:status` 进度事件走 Redis Streams 网关 SSE,商户侧从未订阅——等待期只有静态 spinner。属产品决策(要不要接进度流),本次未接线。

### ✅ 验证 (Verification,如实)

- 新增 `tests/test_consult_fast_path.py` 33 用例:咨询形判定 11 正例 × 13 反例(动作形/订单号/复合意图/域外全覆盖)、直答编排(RAG 过线单次调用 + 缓存回填/弱相关不发调用/空 RAG/带图守卫/异常回落/熔断穿透/缓存命中 0 调用)、triage 接线(直答命中旁路 output + 空弱回落 general_query 不再误判动作形反问订单号)。
- engine 全量 227 passed(含 #5/#6 套件 7 用例),零回归;ruff 干净;`.env.example` 补 `AI_THINKING` / `AI_PLANNER_MAX_TOKENS` 注释条目;`.claude/rules/agent-engine.md` §1.3/§2 同步。

---

## [2.6.1] - 2026-09-09 (商户 aurora RAG 知识库:docs/knowledge 文档驱动摄取,种子不再写死)

商户门户(极光潮品,businessId `aurora`)此前在 `rag_documents` 无任何切片——商户聊天问退换货/尺码/保养,ContextualRAG 检索恒空,只能靠 LLM 通识硬答。本次补齐知识,且按用户要求**知识不写死在种子里**:文档即数据源,种子与冷启动自愈同源读取 `docs/knowledge/*.md` 切片入库。

### ✨ Features (新功能)

- **知识文档驱动摄取 (`rag/knowledge_files.py`)**:
  - 承接 TS 退役 `updateRag.ts` 的角色,规格对齐 `docs/rag-chunking-and-search.md` §2:frontmatter(title/businessId/category)声明归属租户(缺 businessId 整份跳过,多租户安全——绝不猜测归属);`#`/`##`/`###` 维护章节路径 headerPath;SOP 有序列表原子不拆;超长章节按空行段落贪心打包(≤500 字符);确定性上下文摘要(Anthropic Contextual Retrieval 形态,零 LLM 调用)。
  - `docs/knowledge/aurora_store_and_products.md`:极光潮品门店与商品知识指南(售后退换货 7 天无理由/尺码版型/户外面料压胶护理/顺丰物流/门店会员),内容对齐 `merchant_seed` SPU 域数据与售后时效基准(`get_return_window_days` 无租户覆写默认 7 天),知识与技能行为不打架。
- **种子改为读文件 (`db/seed.py`)**:`_seed_rag_documents` 内联硬编码三元组(2026-09-09 前)退役,改为摄取 `docs/knowledge/` 全部文档(现有 nike/adidas/ecommerce 文档一并纳入,nike=2/adidas=2/ecommerce=2/aurora=5 切片);幂等语义从裸 INSERT(重复 reseed 无限堆行、挤占检索 Top-N)改为按 (business_id, source_url=文件名) 整组替换(TS `replaceKnowledgeFile` 同义),管理端人工新增行不受影响;另一次性清理三条伪 URL 旧行。
- **冷启动自愈同源 (`rag/contextual_rag.py`)**:`_ensure_seed_data` 空表时优先摄取知识文件(与种子同一数据源),文件缺失/不可读回退 TS 基线内联 SEED_DOCS(原行为不动);切片 metadata 带 docTitle/headerPath,检索与 admin RAG 列表可直接展示。

### ✅ 验证 (Verification,如实)

- 新增 `tests/test_merchant_rag_knowledge.py` 6 用例全绿:解析器(frontmatter/SOP 原子/无归属跳过)+ 播种幂等(双跑行数稳定、伪 URL 旧行清理、人工行保留)+ 检索租户隔离(aurora 只召回 aurora,Nike/Adidas/三里屯/淮海路零泄漏)+ 空表冷启动文件摄取;engine 全量 190 passed;ruff 双服务干净。
- 真实 embedding 实弹冒烟(dev 库 `db:seed` 后):「冲锋衣怎么洗」→ 户外面料护理(0.669)、「退换货政策」→ 售后退换货(0.667)、「鞋码怎么选」→ 尺码版型(0.713)、「顺丰多久到」→ 物流配送(0.664),语义路由全部命中正确章节且过 0.4 断路阀;双跑 `db:seed` 后按租户行数稳定(nike=2/adidas=2/ecommerce=2/aurora=5),dev 库幂等实证。已供环境重跑 `bun run db:seed` 即生效;知识目录可经 `RAG_KNOWLEDGE_DIR` 覆写。
- 双轴 code-review(Standards/Spec)收敛修复:种子 DELETE 补租户限定(同名异租户行不得误伤,测试钉死)、chunk→row 组装收敛 `KnowledgeChunk.metadata_dict()`(seed/自愈共用)、知识目录缺失时回退显式播报、`docs/rag-chunking-and-search.md` §5/§6 由退役 TS 脚本 SOP 换为 Python 摄取现实。

---

## [2.6.0] - 2026-09-09 (商户端多模态 + 破损图商品归属消歧:发破损图自动关联订单)

2.5.0 收官后的两个追加交付(grilling 共识→直接实现):商户悬浮客服接入图片链路;破损图不再机械追问订单号——vision 摘要 × 近单商品行 LLM 消歧,高置信自动关联。期间连带挖出并修复 **bigmodel glm-4.7 结构化调用全量 400** 的管线级缺陷。

### ✨ Features (新功能)

- **商户悬浮客服多模态接入 (`83acb98`)**:
  - `FloatingChatWidget` 补齐图片能力:回形针上传(复用 `POST /api/chat/upload`)→ chips 缩略预览(可移除)→ `POST /api/store/chat` 携带 `imageUrls` → 气泡上方缩略图渲染 + 点击放大遮罩;空文本有图以兜底文案发送;历史接口 `imageUrls` 三处映射还原(localStorage 缓存随消息对象整体序列化,自动兼容)。
  - **网关 `store_chat` 补写用户行(治 005 回归)**:web 的 `dispatch_chat` 落库用户行而 merchant 的 `store_chat` 从未落库——005 治理把引擎侧用户行写入拔除后,商户用户消息完全不落库、历史恢复缺用户行;对齐 dispatch 语义(读 `imageUrls`/透传 `AgentJobInput`/显式落库),契约两用例入册(带图持久化还原 + 空文本无图 400)。
- **破损图商品归属消歧 (`aed3238`)**:
  - triage Step 1.6(`triage/product_disambiguator.py`):售后意图带图但缺订单号(图内 OCR 亦无单号)时,vision 视觉摘要 × 近单商品行交 LLM 消歧,替代机械"请提供订单号"。三态:**matched**(置信度 ≥0.8 且命中项原样在候选集内,防幻觉键集校验)注入 `targetOrderId` + SSE 播报 + 重跑槽位抽取(本轮直接带上 orderId,免二次澄清);**ambiguous**(多候选/低置信/模型失败)出商品选择 `quick_replies` 卡,点选文本带单号下一轮走 `ORDER_ID_RE` 正则闭环;**no_orders** 明示指引。消歧失败绝不炸会话。

### 🐛 Bug Fixes (缺陷修复)

- **消歧候选源查错库 (`ba05718`)**:候选池原直查 engine 本地表 `get_user_orders_detailed`——商户用户真单在 `agent_merchant.merchant_orders`,engine 表无单,**永远空候选**,消歧三态里的 matched/ambiguous 对商户用户从未成立(冒烟实证 no_orders 假象)。修复:`OrderDomainService.get_recent_product_lines` 门面,商户真单优先(先截断再拉商品行)、engine 本地表兜底,两库优先级与订单列表同源(2026-09-05 同源裁决的延伸)。
- **bigmodel glm-4.7 结构化调用全量 400 (`1b15979`)**:langchain-openai 1.6.0 的 `with_structured_output(function_calling)` 固定发送三个 OpenAI 专有参数,glm-4.7 全部拒收(HTTP 400 code 1210)——`parallel_tool_calls`(任意组合)、`stream:false` 与 tools 同现、`tool_choice` 对象形式;glm-4.6v 均收,vision 通路因此幸免。后果:triage 意图分类器、商品消歧等全部结构化调用失败,**被关键词兜底静默掩盖**(会话看似正常,意图判定长期降级)。修复:`_ResilientChatOpenAI._get_request_payload` 单点收口(invoke/ainvoke/stream 全路径)——剥前两者、`tool_choice` 对象**改写**为 `"required"`(不能剥除:实测去掉后模型遇闲聊 prompt 不调工具,结构化解析即失败;`"required"` 强制语义等价且 bigmodel 收)。诊断链:echo 服务器抓真实请求体 + curl 参数矩阵逐项二分。

### 📝 Docs (文档同步)

- `docs/architecture/multimodal-and-rich-cards.md`:总览图补 merchant 入口与消歧挂点;§5.1 写入方三入口;新增 §5.2 商户多模态接入、§6 消歧三态与候选池门面、§7 bigmodel 参数兼容矩阵。
- `.claude/rules/agent-engine.md`:§1.3 补消歧条目、§1.4 消息写所有权补 store 入口、§2 规则 2 补 bigmodel 参数兼容事实。
- `.wayfinder/multimodal-image-chat/map.md`:商户端图片输入从"Not yet specified"移入收官后追加;"消歧并入用户文本 prompt"立为新的观察项。
- `README.md` 商户悬浮窗特性清单补多模态图片上传。

### ✅ 验证 (Verification,如实)

- engine 三套件 36/36 全绿(消歧 13 + payload 卫生 2 + 韧性 21);gateway 契约 100/100(含 store_chat 带图两用例);ruff 双服务干净。
- 真实 bigmodel 实弹:`with_structured_output` 返回 `ok=True`(修复前 1210)。
- 端到端冒烟(上传真图 → store/chat):选择卡候选已来自商户真单(9081 冲锋衣/9082 工装裤)——候选源修复实锤;matched 分支真实 LLM 判 0.85 自动关联 9082 工装裤;端到端走 ambiguous 系 glm-4.6v 诚实判定(测试图为牛仔裤,与候选确实不符),非 bug。
- promptfoo 基线未复跑:triage 分类器此前一直走关键词兜底,结构化判定恢复后 Classify 分册判定理论上有变化空间,建议下次 `bun run test:prompt:compare` 复验后视漂移重钉。

---

## [2.5.0] - 2026-09-09 (多模态图片客服:上传→看图定责→卡片回复→刷新还原全链贯通)

wayfinder 执行图 `multimodal-image-chat` 收官(001-005 五票):回收 TS 退役时留下的四个断点——上传端点 404、triage 视觉 TODO、messages 无图列、历史不还原图。用户在 web 聊天发物流面单/破损商品图,平台真实"看图办事"。

### ✨ Features (新功能)

- **图片上传端点 `POST /api/chat/upload` (`52d87ed`+`ae64ac6`,wayfinder 002)**:
  - MIME 白名单(jpeg/png/webp/gif)、流式读取实测 10MB 上限(超限删半成品返 413)、UUID 文件名落盘 `public/uploads`(path-traversal 免疫)、StaticFiles `/api/uploads` 回读;契约三用例入册,契约路由 41→42 三处文档同步;新增 `python-multipart` 依赖。
- **engine 视觉模块 `vision/analyzer.py` (`7c31510`+`2047521`,wayfinder 003)**:
  - 移植 TS visionAnalyzerService(考古基准 f71f7fa / b75fb78^)并修三大 TS 缺陷:①手写 ```json 围栏剥离 → `with_structured_output(method="function_calling")`(GLM-4.6V 无 response_format);②1500ms 硬超时 → `AI_VISION_TIMEOUT_SECONDS` 可配(默认 15s);③本地图 `/api/uploads/` 引用 → base64 Data URL 直传(bigmodel 拉不到 localhost)。
  - 挂 triage Step 0.5(📷 状态播报 + try/except 保险带,视觉失败绝不炸分流);OCR 单号正则(ORD-/SF/YTO/ZTO/EMS/TRACK)、破损三级定责(negligible/minor/severe)、LLM 失败降级启发式(confidence 0.88)、PII 脱敏复用 scrubber;`get_vision_model()` 入 `llm/chat.py` 统一入口(`AI_VISION_MODEL` 默认 glm-4.6v,刻意不入韧性层——视觉失败域独立)。
- **图片持久化与会话还原 (`8647697`,wayfinder 004)**:
  - Alembic 0006 增列 `messages.image_urls`(JSONB 引用,inspection 幂等守卫,只存 URL 不存 blob);gateway `append_message` 透传落库、dispatch 用户消息带图入库(此前 AgentJobInput 带图但落库丢弃)、`get_conversation_timeline` 带出 camelCase `imageUrls`(web 聊天历史与 admin 会话时间线共用);前端零改动(002 已备 `Message.imageUrls` 与缩略图渲染),发图→刷新→图与对话俱在。
- **入图归一化与限额治理(wayfinder 005)**:
  - `normalize_image_urls` 收口(剔非字符串/空白、去重保序、**≤3 图/条**截断),挂 `run_agent` 初始状态构建;与网关单张 10MB 限额对齐;垃圾输入只少看图不抛错。E2E 夹具 + `chat-multimodal-damage.e2e.ts`(选图上传→破损图→damage_assessment 卡→刷新还原,chromium)。
  - E2E 实测三修:①`AI_VISION_TIMEOUT_SECONDS` 默认 15s→30s(GLM-4.6V 真实请求可超 15s,超时即降级启发式丢定责);②启发式破损词表补 `断裂|开胶|脱胶`(「鞋底开胶断裂」原全不命中,降级后连兜底定责都丢);③`_uploads_dir()` 默认路径 `parents[4]`→`parents[5]`(原解析到不存在的 `services/public/uploads`,本地图全被跳过)。
- **用户消息单次落库治理(wayfinder 005)**:
  - 双插考古:网关 dispatch/SPI 持久化用户消息(带 imageUrls),`run_agent` 又沿 TS 基线 `shortMemory.addMessage` 盲插无图副本——TS 树里 `appendMessage` 并不存在,网关侧插入系 Python 移植新增,叠加后每条消息时间线 user×2(一行带图一行不带)。裁决:**用户行唯一写入方归网关**(imageUrls 只在入口可得),引擎三处(run_agent 主链/问候旁路/Temporal activity)拔除,assistant 行仍归引擎;`test_user_message_single_write.py` 两用例钉死所有权边界。

### 📝 Docs (文档同步)

- `docs/architecture/multimodal-and-rich-cards.md` TS 残留引用清账(源码路径、1500ms 超时叙述、上传路由位置全部对齐 Python 实况);`.claude/rules/agent-engine.md` §1.3 补入图治理条目;`.env.example` 补 `AI_VISION_MODEL`/`AI_VISION_TIMEOUT_SECONDS`。
- 评测裁决:`eval/testCases/ecommerce/multimodal-damage.json` 维持 `[image: ...]` 文本模拟基线不升级——promptfoo 供给方是文本 LLM 无图片输入位,真实图片链路已由 vision 单测 + E2E 覆盖;基线零改动零重钉。

### ✅ 验证 (Verification,如实)

- engine 169(vision 治理 +3、用户单写 +2)全绿;gateway 97(含图片持久化契约 +2)全绿;ruff 双服务干净。
- E2E chromium:选图上传→真实 GLM-4.6V 定责(severe / 0.95 /「鞋底开胶断裂，完全不能穿」)→damage_assessment 卡渲染→刷新 `?threadId=` 自愈还原图与卡,全链绿;健康链路端到端 ~26s。期间实证:上游 bigmodel 深度限流时链路可拖至 16 分钟(隔夜自愈),vision 超时降级启发式(0.88)仍出卡——双通道容灾按设计工作。
- 已知存量缺口(非本图引入,记录不修):侧栏历史列表依赖 `GET /api/chat/threads`,网关仅实现 POST/DELETE 返 405,刷新后列表恒空(当前线程靠 URL 自愈恢复)。
- `test:prompt:compare` 未跑:文本路径 prompt 零改动(vision 仅带图分支触发,归一化只影响入图数量),基线不可能漂移。

---

## [2.4.1] - 2026-09-07 (「查询热门商品」类措辞空转道歉修复:快轨补词 + 执行器白名单扩容)

### 🐛 Bug Fixes (缺陷修复)

- **「查询热门商品/爆款」类措辞空转 5 分钟后道歉降级 (`852e06c`)**:
  - 事故形态:用户说「查询热门商品」→ 不命中任何意图规则 → LLM 精判 → planner → executor,而 executor 的 `allowed_tools` 白名单继承 TS 基线仅含订单/退款 7 工具,商品工具与快轨伪名 `cart_manage`/`shopping_guide` 全被分发门槛拦截,子任务空转 "without needing tools" 直至 finish 道歉降级(实测一轮 5 分钟)。
  - 修复(四件):
    - `slot_extractor` SHOPPING_GUIDE 规则补入 热门/爆款/热销/热卖/畅销/上新/新品——该类措辞于 Triage 快轨直达 `ShoppingGuideSkill`(实测决策链 35ms、零 LLM 调用);
    - `guide_skills._FALLBACK_RE` 同源补词,动作形嗅探(`is_action_query`)据此拒绝热门类输入命中语义回复缓存;
    - `executor_fast_path` 快轨返回伪名改为 SkillsRegistry 真实技能 id(`skill_cart_manage`/`skill_shopping_guide`)——伪名既不在白名单也查不到注册表,自 TS 移植以来即为永不触发的死路;子串匹配同步修正(裸 `hot` 会误中 what/shot,改用完整词 popular/trending/best seller);
    - `step_execution_engine` base_tools 白名单纳入导购/购物车技能与只读商品工具(`searchProducts`/`compareProducts`/`queryProductSkus`/`queryProductReviews`/`queryProductRanking`/`getCartSummary`),LLM 兜底选择器补第 9 条商品工具指引。
  - **安全边界保持**:写操作购物车工具(`addToCart`/`updateCartItem`)仍不入白名单——加购/改量必须走技能 SOP 管道,不允许 LLM 兜底直调。

### 📝 Docs (文档同步)

- **新增 Git 提交规范 (`01513ef`,CLAUDE.md §6)**:提交作者固定 `weizheng1992`(仓库局部 git config 已覆盖,推送走 SSH key);提交信息只写说明本身,不加 `Co-Authored-By` / `Generated with` 之类的尾注或署名。

### ✅ 验证 (Verification,如实)

- ruff 双服务 clean;功能实测记录(提交时):快轨决策链 35ms、零 LLM 调用;修复前空转 5 分钟道歉路径已复现确认。
- promptfoo 基线未随本提交复跑——SHOPPING_GUIDE 规则扩词理论上可影响 Classify 分册判定,建议下次 `bun run test:prompt:compare` 复验。

---

## [2.4.0] - 2026-09-07 (wayfinder「单实例真实可运营」收官:mock/假兜底全量换成真能力)

六张执行票全部关闭(见 `.wayfinder/single-instance-production/`),平台在单实例部署下真实可运营:真实登录、真实限流、真实熔断、评测真实入库、熔断信号真实入池。

### 🚀 Features (功能演进)

- **auth/login 真实化 (`31e844d`,票 001)**:bcrypt 凭证校验 + JWT 会话(30 天无刷新)+ Redis jti 登出黑名单;新增 `GET /api/auth/me` 静默重校验(用户 UUID 漂移自愈);前端 localStorage 假兜底删除,E2E 切真实凭证。其余用户 `password_hash = NULL` 安全缺省,仅种子账号可登录(admin 侧发券/改密入口为地图遗留 fog)。
- **租户+IP 双维 Redis 滑动窗口限流 (`8742b55`,票 002)**:`RateLimitMiddleware`(ZSET 滑动窗口 + 多键 all-or-nothing Lua 原子扣减)挂 `/api/chat` 与 `/api/v1/spi` 高频入口;XFF 仅可信反代采信最右跳;admin `all` 视图跳租户桶只按 IP 计;Redis 故障 fail-open 不阻断业务。
- **LLM 熔断/指数退避/超时三件套 (`36ded04`,票 003,TS 1:1 移植)**:全局 CircuitBreaker 单例 + 3 次指数退避 + `wait_for` 超时,挂 `_ResilientChatOpenAI` 公共 `invoke/ainvoke` 全覆盖(构造期 callbacks 不穿透 `with_structured_output` 的坑已绕开);熔断中断的会话 job 级降级道歉并落 `resolution_status='llm_circuit_breaker'`;4 节点兜底前置熔断豁免上抛。阈值经 `LLM_CIRCUIT_*` / `LLM_RETRY_*` / `LLM_TIMEOUT_SECONDS` env 可调。
- **promptfoo 评测真实结果入库 (`d66a86f`,票 005)**:结果经 `engine_py.evals.promptfoo_import` 单事务写 `eval_runs`/`eval_results` 三表(`bun run test:prompt:record` 三套件链式自动入库 + `evals:import` 独立通道);`POST /api/evals/run` 返回 410 指引真实通道,随机评测生成器退役为契约测试 fixture,`isMock` 全链路消失;admin `/api/evals/results` 与 `/api/logs` 只消费真值,无数据处返回真实 0。CLI `__main__` 守卫缺失曾致零入库,已补测钉死。
- **熔断信号入坏例候选池 (`844302d`,票 006)**:`run_agent` 会话收口处两路熔断(上游 LLM 级 + 图级转移≥10/工具错误≥3)入池,先验 `suspected_defect`;`record_badcase_signal` 增 opt-in dedupe 幂等护栏;摘要按 source 分组自动收纳。

### 🐛 Bug Fixes (缺陷修复)

- **HITL 挂起计划不落库竞态(`584b1f8`,票 004 E2E 钉出)**:审批工单创建后前端 2s 轮询立即可见,而挂起计划要等运行收口才 `save_task_state` —— 核签窗口内 `job_resume_*` 读到空计划,triage 误判查单,退款永不执行。修复:挂起即落库 + 空 thread_id 拒写 TaskMemory("") 共享键。
- **`POST /api/chat/threads` 契约缺失(`cc7a5d4`,票 004)**:TS 基线服务端从未实现,web「开启新一轮对话」fetch 404 被静默吞掉,按钮长期失效。补齐幂等建线程路由;归属守卫:同 id 异租户/异用户重放 409 不回显他人元数据,无主线程自愈认领。**契约路由 39 → 41**(另含票 001 的 `/api/auth/me`;新增路由均同批补 pytest 契约钉死,冻结 carve-out 见地图 Notes)。
- **tz-aware 送达日期炸退款 + 三方镜像表裸 except 连坐(`584b1f8`,票 004)**:`estimated_delivery` 为 text 列,`NOW()` 写入带时区偏移直接炸日期解析;镜像表更新失败但事务已中止,主退款 UPDATE 的 commit 静默失效、工具照报成功。修复:tz 归一 + 退款/改址/商品补全三处 `begin_nested` SAVEPOINT 隔离 + 显式中文日志。
- **种子 `rag_documents` 绑定参数 `:m::jsonb` 语法炸库(`41fe4ca`)**:改 `CAST(:m AS jsonb)`。

### 🧪 E2E 基建 (票 004)

- 新增 `chat-approval-flow.e2e.ts`(超阈值退款挂起 → 审批卡 → 核签 → 真实物理退款 → 会话落定)与 `circuit-breaker.e2e.ts`(独立 `playwright.breaker.config.ts`,死 LLM 注入 + 阈值 1)。**熔断 spec 关键发现**:问候/订单/退款输入全走 triage 确定性旁路零 LLM 调用,熔断永不触发——须价保咨询类输入必达 Step 3 精判。
- `e2e/globalSetup.ts` 幂等就绪(docker:up → db:push → db:seed,种子 DO UPDATE 重置可重复执行);webServer 显式数组化(gateway 4000 / web 3000 / admin 3001 / merchant 3005);`testIgnore` 围栏(breaker 独占运行 + `.claude/worktrees` 幽灵 spec);admin 陈旧 spec 全量修缮(Combobox 按 cmdk `role="option"` 交互、`getByRole('link')` 防同名撞车);webkit/firefox 浏览器二进制补装。

### ✅ 验证 (Verification,如实)

- gateway 契约 **91 passed**(密封 testcontainers);engine 回放 **5 passed**(含挂起落库回归);HITL/熔断两 E2E spec 单独绿(19.7s / 18.7s);ruff 双服务 clean、biome e2e clean。
- **全量 `playwright test` 未收口**:修复已知根因后 25 passed / 18 failed —— 14 个 firefox 二进制缺失(已补装)、4 个 admin spec 选择器缺陷(已修,基于组件源码静态核对),均待下次全量跑复验。`test:prompt:compare` 未跑(engine 改动仅 HITL 挂起路径,不触 Classify/Planner 提示词)。

### ⚠️ Notes (注意事项)

- 运行中的 dev 网关需重启 `dev:server` 方可生效(uvicorn reload 不监视 engine-py)。
- E2E 全量套件的既有用例回归待一次完整复跑收口(本环境按指示停止测试)。
- 仅种子账号(`test@example.com` / `agent-all-dev`)可登录;真实运营的 admin 侧改密/发券入口未做(地图 fog 记录,立票另议)。

---

## [2.3.7] - 2026-09-05 (双退款事故三层旁路封死 + SPI 技能链路线程上下文透传)

### 🐛 Bug Fixes (缺陷修复)

- **未指明订单号的退款申请静默重退历史已退款订单 (`b355170`,三层修复)**:
  - 事故(2026-09-05 19:08,线程 `merchant_thread_CUST-8801_aurora_*`):用户「我想申请退款」想退 9081,系统把旧回合(04:16)已退款的 9082 物理重退,且全程未发新审批工单。
  - 根因链(DB 证据钉死):线程无已存任务状态 → 槽位提取器全历史反向扫描(含 assistant 消息)回填 9082 → missingSlots=[] 不澄清 → planner fast-path 零 LLM 单步计划 → `check_double_refund` 只查 engine orders 表(商户真单在 `agent_merchant` 库,全盲)→ 线程扫描复用 03:07 旧 `approved` 工单绕过 HITL → `process_refund` 无 REFUNDED 幂等校验 → 商户真单物理重退。
  - 修复(三层防线,自上游到底线):③ 资金类意图(order_return/refund)订单号禁历史回填——只认当前输入与用户已确认 orderContext,缺失强制追问澄清(`slot_extractor` 严格提取 + planner fast-path 降级门 + 深度规划 prompt 例外指令);② HITL 旁路封死——线程扫描只认领 `waiting` 工单,`approved` 等终态只能经 existingApprovalId(审批恢复路径)复用;① 幂等底线——`process_refund` 对任何来源(engine/merchant/third_party)已 REFUNDED 订单拒绝物理重退,`check_double_refund` 改三源判定并按用户归属匹配。
  - 回归:`test_double_refund_replay.py` 3 例红灯转绿(密封 testcontainers PG + 商户镜像表回放事故执行链:重退物理指纹守卫 / 陈旧 approved 工单必须重开 waiting 票 / 缺单号必须澄清)。
- **SPI 技能链路丢弃线程上下文,商户真单被 third_party 过期数据遮蔽 (`25aea43`)**:
  - 根因:triage Skill Fast-Track 与执行器技能派发都把 threadId/userId 传入 `skill.execute(context)`,但 `OrderRefundSkill` 调 `LocalDbSpiAdapter` 时丢弃——`get_order_detail` 硬编码 user_id=None 跳过商户真单回退(`find_order_by_id` 按 user_id 严格归属匹配),拿到 third_party 过期种子状态(事故后 11:09 回复展示错误订单状态即此因);`execute_order_action` 硬编码 thread_id=None,使归属校验(IDOR)、REFUNDED 幂等守卫(2.3.7 上一条新增)、商户写穿透在技能链路全部失效——退款只假写 third_party/engine 表,商户真单纹丝不动。附带发现:adapter success 计算误读 `refundedAmount`(`process_refund` 返回键为 `refundAmount`),物理退款成功却向技能上报失败。
  - 修复:`OrderRefundSkill` / `OrderAddressModificationSkill` 把 context 中的 userId+threadId 透传进 `get_order_detail` 与 `execute_order_action`;adapter 侧 `process_refund` / `change_shipping_address` 改收 `req.threadId`,success/refundedAmount 键名对齐。
  - 回归:`test_spi_client_thread_context.py` 3 例红灯转绿(带身份详情必须读商户真单 / 已退款单经技能链路不再发生任何物理退款写,含 third_party 双侧指纹断言 / 合法退款必须写穿商户真单)。其中"盲退"断言曾因键名错配假绿(物理退款发生但恰好上报失败),补 third_party 物理指纹断言后真红——双断言必要性的一手案例。

### ✅ 验证 (Verification)

- engine-py 65 passed(62 存量 + 6 新增,含双退款回放与 SPI 上下文)/ gateway 契约 69 passed / ruff clean / 无 DEBUG 残留。

### ⚠️ Notes (注意事项)

- 运行中的 dev 网关需重启 `dev:server` 方可生效(uvicorn reload 不监视 engine-py,见 docs/deployment.md 踩坑清单)。
- 退款意图的订单号现强制"当前输入或已确认 orderContext"——多单用户说「我要退款」会收到追问,属预期行为变化(此前静默回填历史订单正是事故根因)。

---

## [2.3.6] - 2026-09-05 (启动与部署指南:dev Temporal 流程与线上部署 runbook 成文)

### 📝 Docs (文档同步)

- **新增 `docs/deployment.md`**:dev 启动流程(基础设施/启动顺序/四种踩坑:dev:all 无 worker、engine 改动不热重载、uv workspace 精确 sync 互剥依赖、7239 端口映射)与线上部署 runbook(部署形态矩阵、Temporal 三路线[暂不部署/Cloud/自托管]、发布步骤、就绪验收、env 矩阵、排障入口)。
- **澄清拓扑真相**:Python 网关从不向 Temporal 提交工作流(全仓无 `start_workflow` 调用方,请求路径为网关进程内 `run_agent` 直跑);worker 的现实角色是 scheduler 载体 + 休眠的 workflow 注册。README §6 服务表"Temporal 离线时本地仿真回退"的 TS 时代表述已修正,并补 §3 未来启用 Temporal 编排的演进步骤(submitter、幂等续跑、SSE 桥接、Schedule 迁移)。CLAUDE.md §5 挂载索引。

---

## [2.3.5] - 2026-09-05 (多实例部署指南:单实例假设盘点与迁移方案成文)

### 📝 Docs (文档同步)

- **新增 `docs/architecture/multi-instance-deployment.md`**:兑现不变量 #3 挂账的"多实例部署前需分布式锁或迁移 Temporal Schedule"。盘点存量组件就绪度(SSE 裸 XREAD 天然安全、outbox SKIP LOCKED 行级安全、审批 Redis SETNX 跨实例互斥、embedding 串行护栏按进程设计无需改、Temporal worker 原生扩容),钉死两个硬缺口:① scheduler 单实例假设(三方案:环境变量止损 → Temporal Schedule 目标态);② socket.io 房间为进程内存态,须加 `AsyncRedisManager` 跨实例广播,否则人工接管双端失联。附扩容前置清单(Redis 升硬依赖、PG 连接池预算、uvicorn 单 worker 假设)与多实例开发约定(新周期任务幂等、进程内存态仅限降级)。CLAUDE.md §5 挂载索引。

---

## [2.3.4] - 2026-09-05 (worker 兼容 temporalio 新 API;本地 embedding 并发推理段错误串行化护栏)

### 🐛 Bug Fixes (缺陷修复)

- **`bun run worker` 启动即退 (`engine_py/temporal/worker.py`)**:
  - 症状:报"temporalio 未安装"误导信息,实为 `ImportError: cannot import name 'Connection'`——`uv sync --extra worker` 解析到 temporalio 1.32.0,该版本把 `Connection` 并入 `Client`(classmethod `connect`),Worker 首参即 `Client`。
  - 修复:改用 `Client.connect(address)`;验证:worker 正常启动,Temporal Server 离线时按设计退化为纯周期任务进程。
- **本地 embedding 并发推理段错误 (`engine_py/llm/chat.py`)**:
  - 症状:两个线程同时经本地 torch embedding(sentence-transformers)encode → 进程级 SIGSEGV(exit 139)。触发面极广:网关任意两个并发聊天请求的 triage 向量化、审批恢复与新聊天同跑、worker 一轮对账派发多条事件;进程连同全部 SSE 连接一起死。最小复现:`asyncio.gather` 两个 `aembed_query` 即崩(与 temporalio 无关,单独加载模型正常)。
  - 修复:`get_embedding_model()` 本地分支包 `_SerializedEmbeddings`——进程内 `asyncio.Lock` 串行化 `aembed_query/aembed_documents`(openai 提供方为网络客户端不经包装;同步方法透传)。锁可在线程中构造(预热线程)、loop 中使用,3.14 验证通过。
  - 回归:engine 侧新增 `test_embedding_concurrency.py`(3 并发 aembed 钉死;修复前 pytest 进程直接被 SIGSEGV 杀死),套件 33/33 绿。

### ✅ 验证 (Verification)

- **发件箱对账兜底实跑验证**(2.3.3 修复的补偿路径):启动 worker 后,scheduler 首轮扫描即捞出 2 条滞留事件(processedCount=2, dispatchedCount=2);重派发经真实 run_agent 执行后双双落 `completed`(retry 2 = 一次段错误尝试 + 一次兜底成功),商户订单幂等无损。修复前滞留的 2 条事件(含用户原始工单)已全部闭环。

### ⚠️ Notes (注意事项)

- engine 侧新增用例已实跑全绿(33/33);gateway 契约套件无涉改,按约定仍由人工 `bun run test:eval`。
- dev 环境如需对账兜底常驻,单独跑 `bun run worker`(scheduler 随其启动);`dev:all` 不含 worker。

---

## [2.3.3] - 2026-09-05 (商户退款审批通过后店铺无变化:HITL 恢复派发链路断裂修复)

### 🐛 Bug Fixes (缺陷修复)

- **审批通过后退款不执行、店铺订单无变化 (`engine_py/approvals/gatekeeper.py`)**:
  - 症状:商户门店聊天申请退款 → admin 审批通过(接口返回 success)→ 商户库 `merchant_orders` 状态永不翻转,顾客与店铺侧均"没反应"。
  - 根因(用户复现工单 + 发件箱错误信息直接钉死):工单创建路径(`evaluate_pending_approval_state` / `create_pending_approval_ticket`)不写 `pending_approvals.business_id`(NULL);审批 Fast-Path 把 `record.business_id`(None)显式传入 `AgentJobInput(businessId=...)`,**显式 None 绕过 pydantic 默认值**直接校验崩溃 → resume 任务永不派发,事件滞留 `approval_outbox_events.status='pending'`(error: `AgentJobInput businessId Input should be a valid string, input_value=None`)。对账 Worker 本可 10s 后兜底重放(payload 侧有 `or "ecommerce"` 回退),但其随 Temporal worker 入口启动,`dev:all` 不含 worker → 兜底也不在场,链路彻底断裂。
  - 修复:① 新增 `_thread_owner_context` 助手(threads 表事实源),两个工单创建点落库 `business_id`;② 派发点 `process_approval_action` 以 `record.business_id → 线程归属租户 → "ecommerce"` 三级回退构造派发载荷与 `AgentJobInput`(存量 NULL 旧工单同样可恢复);③ outbox payload 同步携带真实租户。
  - 回归:gateway 契约新增 `TestApprovalResumeDispatch`(走执行器真实创建分支 → 断言工单落租户、Fast-Path 派发后 outbox `completed` 且载荷携带真实租户;修复前断言 `pending`+校验错误)。旧用例 `test_resolve_fixture_approval` 之所以从未拦住:fixture 直插 SQL 自带 business_id,绕过了出问题的创建分支,且断言只看 HTTP success——派发崩溃恰好也返回 success。反馈回路脚本 `scripts/debug/refund-approval-e2e.sh` 保留(红→绿实测:审批后 3s `PAID→REFUNDED`)。

### ⚠️ Notes (注意事项)

- 新增 pytest 用例按仓库约定由人工触发 `bun run test:eval` 验证。
- 开发环境若依赖发件箱对账兜底,需单独启动 `bun run worker`(scheduler 随其启动);仅跑 `dev:all` 时兜底不在场,Fast-Path 是唯一派发路径——本次修复后 Fast-Path 已可靠。
- 修复前创建的存量工单 `business_id` 仍为 NULL(派发点回退已兼容,无需数据迁移);历史"已批准未执行"的订单可由顾客重新发起退款走新链路。

---

## [2.3.2] - 2026-09-05 (商户聊天查单与订单列表双库统一、租户注册门禁、语义缓存防投毒双闸门、admin 十大模块全面接真实后端)

### 🐛 Bug Fixes (缺陷修复)

- **商户聊天查单与订单列表展示不一致 (`engine_py/tools_registry/order_domain.py` + `gateway-py/merchant_domain.py`)**:
  - 根因:订单数据三个物理存储物理隔离——商城下单只写 `agent_merchant.merchant_orders`(列表页数据源),而聊天 `listUserOrders` 只读 engine 本地 `agent_platform.orders`;后者空结果时还会**自愈播种 2 笔虚构演示订单**(¥199/¥89),且两侧查询均带 `OR user_id='CUST-8801'` 跨用户回退,任何用户都会混入演示用户订单 → 两视图永久发散。
  - 修复:order_domain 新增 `_merchant_reader_engine`(URL 推导对齐 gateway `merchant_db`,lru_cache 单例)直读商户库,聊天列表商户真单优先、严格 `customer_id` 归属、绝不播种;按单号查询 engine → merchant → third_party 三级回退(全链严格归属);退款/改地址**写穿透**商户库(聊天侧退款后 `merchant_orders.status` 真实翻转);商户库不可达时优雅降级 engine 本地表。列表页 `/api/store/orders` 同步移除 OR CUST-8801。
  - 回归:engine 侧 4 用例(商户源优先/空不播种/兜底 SQL 严格归属/按号查询回退+防跨用户泄漏)+ gateway 契约 `TestStoreOrdersStrictScoping` 2 例;反馈回路脚本 `scripts/debug/order-view-diff.sh` 保留(三演示用户全 GREEN)。
- **admin 会话列表恒空 (`apps/admin/conversations`)**:`/api/conversations` 契约返回 `{conversations, total}`,页面却判断 `res.items` —— 字段名错配使真实数据永远走不进渲染分支,此前被假数据掩盖,清空假数据后暴露。

### 🔐 安全加固 (Security Hardening)

- **商户路径租户注册门禁 A 档 (`gateway-py/routers/merchant.py`)**:商户服务路径从不咨询 tenants 注册表,自报 `businessId`(如 ghost-tenant-999)即可获全套引擎服务并收到品牌扮演回复。新增 `check_tenant_registered`:tenants 表须存在且 `status='active'` 否则 403;注册表不可用 503(fail-closed);"all" 聚合视图放行。覆盖 `/api/store/chat`、`/api/store/chat/messages`、`/api/admin/conversations{,/{id}}`、`/api/admin/approvals` 五个客户端可传租户身份的入口。
- **补遗失的 CORS 中间件 (`gateway-py/main.py`)**:TS 基线 AppModule 有、Python 移植遗失。此前 admin(3001) 直连 4000 被浏览器预检拦截,`/tenants` 页静默回退前端硬编码假租户,掩盖真实注册行。
- **语义缓存防投毒双闸门 (`engine-py/skills/` + `graph/nodes/finish.py` + `triage/`)**:幻觉"已成功 XX"回复会无条件回填语义缓存,相似请求以 ≥0.96 相似度永久命中、绕过真实技能执行。新增 `is_action_query()` 动作嗅探(任一技能 `can_handle` 即动作形,嗅探失败按动作处理——宁可缓存失效,不可放行投毒):动作形输入**禁写**(finish 无工具背书的终稿不得回填)且**禁读**(triage 不查缓存,必须落真实执行管道)。12 用例钉死双闸门。

### 🧹 数据真实性清理 (Data Truthfulness)

- **admin 十大模块全面接真实后端 (`apps/admin` + `gateway-py`)**,三连修:
  - 清空 10 页(tenants/skills-tools/conversations/audits/rag-studio/evals/guardrails/personas/billing/system-logs)`INITIAL_*` 硬编码演示数据与 fetch 兜底假数据;`useAdminCrud` localStorage 持久化仅限本地模式;网关 `/api/tenant/list` 移除硬编码演示租户兜底(空表返回空列表)。
  - 租户筛选器改为 `loadTenantsFromServer()` 从真实注册表动态加载(仅 active),移除最后一处硬编码演示租户。
  - tenants 不可编辑修复:网关新增 `PUT /api/tenant/{id}`(tenant_configs 合并式覆写 + jsonb 显式 CAST);`api.ts` 对齐冻结契约(ragApi.search→`POST /api/rag/query`、billing 配额→`PUT`、补 tenants.update / guardrails.create / delete);移除 skills-tools 与 rag-studio 的假创建/假编辑;billing/evals 统计卡改真实接口汇总。浏览器实弹验证 10 页全过。

### ⚠️ Notes (注意事项)

- 本批次 pytest 契约套件新增用例(`TestMerchantTenantGate` 5 例、`TestStoreOrdersStrictScoping` 2 例、语义缓存 12 例)按仓库约定由人工触发 `bun run test:eval` 验证;engine 侧单测已实跑全绿(32/32)。
- 订单三库约定:商户租户订单读写必须经 order_domain 的 merchant reader,不要往 engine orders 表加同步副本;聊天退款已写穿透商户库,但**改地址仅更新 shipping_address 快照**,不触发商户侧物流系统。

---

## [2.3.1] - 2026-09-04 (契约测试套件首次全绿:SSE 静默断流、审批恢复跨租户搬家、商户中继延迟三大生产缺陷修复)

### 🐛 Bug Fixes (缺陷修复)

- **SSE 流空闲 5 秒必静默断流 (`engine_py/event_bus.py` + `gateway-py/routers/chat.py`)**:
  - 根因:redis-py asyncio 默认 `socket_timeout=5`(`redis/_defaults.py`),小于 `XREAD BLOCK 15000` 的服务端阻塞时长 → 空闲 5s 后 `xread` 必抛 `TimeoutError`(注意 `redis.exceptions.TimeoutError` 不继承内建 `TimeoutError`),chat 路由 `except Exception: return` 将其吞成空响应。生产环境一直靠浏览器 `Last-Event-ID` 自动重连掩盖。
  - 修复:`get_client` 显式 `socket_timeout=20`(> 最大 BLOCK 时长 + 余量,阻塞命令上线必检不变量);chat SSE 对 `RedisTimeoutError` 降级为心跳续命而非断流,其他总线异常 print 不吞错。
- **审批恢复把线程跨租户"搬家"(违反架构不变量 #1 多租户隔离,`engine_py/run_agent.py` + `approvals/`)**:
  - 根因:`_ensure_thread` 的 `ON CONFLICT DO UPDATE` 会覆盖已有线程的 `business_id`;而审批恢复派发(gatekeeper 同步 Fast-Path 与 outbox_worker 对账补偿)均未携带 `businessId` → 默认 `ecommerce` 直接改写 nike 租户线程归属,品牌配置、画像、会话列表全部错位。
  - 修复:upsert 只续 `updated_at`,线程租户归属创建时冻结;两处恢复派发显式携带审批单的 `record.business_id`,outbox payload 补 `businessId` 字段。
- **商户 SSE 中继消息延迟 15~30s (`gateway-py/routers/merchant.py`)**:
  - 根因:`get_message()`(默认 `timeout=0.0`)非阻塞轮询实测会吞一轮消息——消息已到达,第一次轮询仍返回 None,须下一轮才可见;叠加 `sleep(15)` 心跳节拍,每条 pub/sub 转发被拖一个完整周期。
  - 修复:改阻塞式 `get_message(timeout=15.0)`(客户端 socket_timeout=20 > 15 保证不误杀),实测转发 30.08s → 0.30s;顺带 `pubsub.close()` → `aclose()` 消除弃用告警。
- **asyncpg 对 uuid 列 raw SQL 绑定缺 CAST(审批 resolve 500 根因)**:gatekeeper ×3(含超时解挂的潜伏同类 bug)与 outbox_worker ×2 的 `UPDATE ... WHERE id = :id` 全部补 `CAST(:id AS uuid)`。
- **Alembic 0002 在全新库 `DuplicateTable`**:0001 基线是动态 `Base.metadata.create_all`(非冻结快照),后续迁移必须幂等 → 加 inspector 守卫,并固化约定。
- **健康路由缺统一包络**:`/api/health` 补 `success: true`。

### 🧪 Testing (测试基建)

- **契约套件首次全绿:29 passed / ~5s**(起点为迁移直接报错、整套跑不完;亦说明移植后从未完整执行过,本次等于把冻结契约真正钉死)。全程密封 testcontainers(PG 15 + Redis 7),任一裸机可复跑 `bun run test:eval`。
- **SSE 类测试统一切 `live_server` 真网络栈**:httpx `ASGITransport` 会把整个 ASGI app 跑到完成才进入 stream 上下文(body 全缓冲),"连接后灌事件/订阅后 publish"在 in-process 传输下结构性死锁——此前一次 22 分钟挂死即源于此。
- 商户流测试修复 httpx 流式响应二次迭代(`StreamConsumed`),改为单迭代内"connected → publish → 断言转发"。
- **macOS Docker Desktop 下 ryuk 必死**:默认 context 指向 `~/.docker/run/docker.sock`,该路径挂进 ryuk 容器不通 → 启动竞态与容器泄漏;conftest 按平台探测禁用 ryuk + atexit 兜底回收。
- gateway-py dev 依赖补 `aiohttp`(python-socketio AsyncClient websocket 传输前置,契约测试 `transports=["websocket"]` 所需)。

### ⚠️ Notes (注意事项)

- 涉及文件 ruff 检查与 HEAD 基线持平(仅自动整理 2 处新增 import 排序);存量告警(DTZ005/S110 等)未动。
- 阻塞命令使用约定:任何 `XREAD BLOCK` / `BLPOP` 类调用的 BLOCK 时长必须 < 客户端 `socket_timeout`(现 20s),新增阻塞调用前先核对该不变量。

---

## [2.3.0] - 2026-09-03 (坏例候选池闭环 v1、outbox 对账补偿修复、网关数据真实性清理)

### 🌟 Major Highlights (重大亮点)

- **坏例候选池与半自动闭环 (`engine_py/badcase/`,测试生命周期第五阶段 v1,2026-09-03 评审锁定 23 项决策)**:
  - 新表 `badcase_candidates`(Alembic `0002`):信号源、会话引用(`thread:` / `approval:` / `fact:`)、租户、先验类别、状态机 `candidate → confirmed/dismissed → converted`。**仓库零原始数据**——只存引用不存对话/画像原文。
  - 信号挂接(零契约变更):人工接管发起、审批驳回(`approvals/gatekeeper.py`)、画像事实删除(`gateway-py/routers/crud.py`)实时入池,携带信号先验(删除→`suspected_defect`、驳回→`expected_behavior`、接管→中性);入池失败静默降级不阻断宿主事务。
  - 熔断落盘:`run_agent` 检测全局转移 ≥10 或工具错误 ≥3 触发熔断时,以 `resolution_status='circuit_breaker'` 写入 `session_metrics`(新增 `global_transitions_count` / `tool_errors_count` 列),子任务指标不再计入。
  - 已知值脱敏(`badcase/redaction.py`):库内已知 PII(地址/收件人/手机号/邮箱)精确替换 ➔ `scrubber` 正则兜底的两层管道。
  - triage CLI(`python -m engine_py.badcase.cli`):`list / show(原文 vs 脱敏对照) / triage / draft / expire`;`draft` 只产 `expectedTools` / `not-contains` 断言(断言最小化,禁整句黄金答案),带 `origin: badcase:{id}` 溯源标记。
  - 保留期:candidate 90 天自动转 dismissed、dismissed 30 天清除(`badcase/digest.py`)。
- **周期任务框架与 outbox 对账补偿修复 (`engine_py/scheduler.py` + `approvals/outbox_worker.py`)**:
  - 原 outbox worker 为死代码(全仓无调用点)且旧实现存在"事件循环未运行静默返回"与"create_task 后立刻标 completed 的假完成"两个缺陷。重构为 `process_pending_events`:`FOR UPDATE SKIP LOCKED` 防多实例重复捞取、10s 年龄阈值避开与 gatekeeper 同步 Fast-Path 竞争、`processing` 停滞 >5min 重入队(重试上限 5)、派发任务自身回写终态(真完成)。
  - 新增 `scheduler.py` 单进程 asyncio 周期调度(间隔 + 抖动、逐 tick 容错):outbox 对账(30s)+ 坏例池摘要/保留期(6h);随 Temporal worker 入口启动,Temporal 离线时进程退化为纯周期任务进程仍在线。**单实例假设**,`ENGINE_SCHEDULER_ENABLED=0` 可整体关闭。
- **网关数据真实性清理 (`gateway-py/routers/crud.py`,契约增量字段、无路由变更)**:
  - `/api/logs` 接真实数据:intent 分支不再编造 `350/45/395/280` token/延迟假数(返回真实 0);metric 分支去掉 `or 1000` / `or 500` 兜底与虚构的 0.8/0.2 拆分;`rawDetail` 增量透出 `globalTransitionsCount` / `toolErrorsCount`。
  - `/api/evals/*` 响应显式携带 `isMock: true`(记录全部来自本地随机生成器),坏例看板/BI 数据源据此排除。

### 📝 Docs (文档同步)

- CLAUDE.md 不变量 #3、`.claude/rules/agent-engine.md` §1.6:outbox worker 表述由"从未被任何入口启动(技术债)"修正为"scheduler 每 30s 对账补偿"。
- `.claude/rules/agent-engine.md` 新增 §1.8(坏例候选池与周期任务);`database-schema.md` 补 `badcase_candidates` 表与 `session_metrics` 熔断列;`observability.md` 补熔断落盘;`server-gateway.md` 补 isMock/真实值约定与画像删除入池挂接。
- README §4.2 发件箱恢复机制描述与实现对齐(Fast-Path + 30s 对账,替代此前的"指数退避"误述)。
- `docs/agent-lifecycle-testing.md` 第五阶段落地批次:前置清理与 v1 标记已落地;附录技术债 #1(outbox 死代码)标记已修复。

### ⚠️ Notes (注意事项)

- pytest 契约套件按仓库约定未自动执行,需人工运行 `bun run test:eval`;`isMock` / `rawDetail` 增量字段如有精确匹配断言需同步契约测试。
- `docs/architecture/*.md` 仍整体为 TS 时代路径(77 处 `packages/` 引用),系迁移遗留债务,本次未零散修订,建议单独立案整体重写。

---

## [2.2.2] - 2026-09-03 (Python 后端运行时修复包: 商户 SSE 流 500、工具注册表解析失效、.env 环境注入)

### 🐛 Bug Fixes (缺陷修复)

- **商户端 SSE 流式通道 500 修复 (`gateway-py/src/gateway_py/routers/merchant.py`)**:
  - `/api/store/chat/stream` 曾以普通 `Response` 包装 async generator,Starlette `render()` 对非 bytes 内容调用 `.encode` 触发构造期 `AttributeError`,请求未写出任何响应头即 500。改用 `StreamingResponse`(与 `/api/chat/{jobId}/stream` 的既有惯例一致)。
  - 契约套件新增 `TestMerchantStoreChatStream` 回归钉:断言 200 + `text/event-stream` + `event: connected` 首帧 + Redis pub/sub 频道 `thread:{threadId}:message` 消息转发(此前该路由无任何契约覆盖)。
- **工具注册表解析失效修复 (`engine-py/src/engine_py/graph/nodes/step_execution_engine.py`)**:
  - 延迟导入 `..skills` / `..tools_registry` 相对深度少写一个点,实际解析到不存在的 `engine_py.graph.*` → `ImportError` 被优雅缺位逻辑吞掉 → Skills/Tools 解析器为 `None` → **全部 20 个电商工具**经执行引擎调度时一律落入 `"Tool or Skill ... not found in registry."`(症状首见于 `listUserOrders`)。修正为三个点(`...skills` / `...tools_registry`),恢复 Skills 优先、Tools 回退的调度链。
- **开发脚本 .env 环境注入修复 (`package.json`)**:
  - `dev:server` / `worker` / `db:push` / `db:seed` 统一改为 `uv run --env-file ../../.env ...`。此前 gateway 进程拿不到任何 `AI_*` 环境变量(`config.py` 只读 `os.environ`,dev 脚本也不注入),LLM base_url 回落到缺省的 `http://127.0.0.1:11211/...`(无服务监听),导致 validatorNode / finishNode / 画像 Profiler Agent 全线 `Connection error`;数据库与 Redis 仅因代码缺省值恰好与 dev 容器一致而"看似正常"。
  - README 快速启动章节补充 `.env` 准备步骤与环境变量自动加载说明。

---

## [2.2.1] - 2026-08-27 (意图去重旁路与画像审计自愈、富交互卡片闭环修复)

### 🌟 Major Highlights (重大亮点)

- **意图去重拦截器旁路修复与卡片透传保证 (`intentTriageEngine.ts`)**:
  - 在意图分流层的语义去重拦截器（`Triage Duplicate Shield`）中增加业务操作类指令（订单、物流、退款、导购等）豁免规则，杜绝连续/重复订单查询被静态缓存拦截而丢失富交互卡片。
  - 增强 `handleImmediateBypass` 逻辑，透传并保留现有卡片数据（`effectiveCards`），确保快速直达通道与前台 UI 卡片渲染不脱节。
- **画像审计专职 Agent 异步加载自愈 (`longMemory.ts`)**:
  - 修复 `LongMemory.runProfileAudit` 中动态加载 `db` 模块在 ESM/TS 运行时的 undefined 异常，改为静态顶层安全导入并执行 PostgreSQL 订单流水查询。
- **多模态卡片交互分发与选单链路闭环 (`FloatingChatWidget.tsx`, `ChatWidget.tsx`)**:
  - 在商户端与主站客户端浮窗中完善 `select_order`、`track_order`、`request_refund` 等富卡片交互事件派发与自动对话触发。

---

## [2.2.0] - 2026-08-27 (多模态订单选择弹窗、SPI 独立商户查单与状态回退增强)

### 🌟 Major Highlights (重大亮点)

- **多模态订单选择弹窗与富卡片交互 (`OrderPickerCard` & `cardSynthesizer.ts`)**:
  - 新增 `OrderPickerCard` 组件与弹窗选择交互模式，当用户查询多个订单时，以结构化弹窗形式完整展示订单编号、金额、承运商、运单号及履约状态。
  - 修复 `cardSynthesizer.ts` 中订单编号被错误截断（如 `ordId.slice(-8)` 导致 `AURORA-ORD-2026-9082` 变为 `026-9082`）的缺陷，确保全格式订单号展示与回调。
  - 移除冗余重复的快捷回复胶囊，统一由弹窗交互驱动选单与状态下钻。
- **SSE 流式通道与 HTTP 响应消息双向去重与卡片文本协同优化 (`FloatingChatWidget.tsx`, `finish.node.ts`)**:
  - 在商户端 API 路由统一 `messageId` 标识，并在客户端聊天浮窗中建立 SSE 流式推送与同步 HTTP fetch 响应的双重去重屏障，彻底解决“查询我的全部订单”等高频场景下出现重复两条气泡回复的竞态问题。
  - 优化 `finishNode` 总结生成规则，当交互式订单选择卡片已挂载时，避免在文本中冗余重复输出全量订单 Markdown 列表，实现图文协同轻量化。
- **多租户/SPI 独立商户订单查询与越权防御增强 (`orderDomainService.ts`)**:
  - 在 `findOrderById` 与 `getOrderStatus` 中建立从主站 `orders` 表到第三方独立商户 SPI 数据表 `third_party_orders` 的平滑回退检索机制，彻底解决商户独立订单查询时被误判为“越权阻止或未找到订单”的 IDOR 假阳性问题。
  - 完善订单商品明细关联（`third_party_order_items`），自动补全商品名称、单价及数量。
  - 同步适配 `changeShippingAddress` 与 `processRefund` 在三方商户订单表中的状态变更。
- **全格式订单编号正则与意图消歧提取修复 (`utils.ts`, `intentTriageEngine.ts`, `planner.node.ts`)**:
  - 升级订单号正则识别规则（匹配带有品牌前缀与多段横杠的订单号，如 `AURORA-ORD-2026-9081`），确保意图分流、槽位提取及规划节点准确提取实体。
- **文档与测试套件完善**:
  - 新增 `apps/merchant/tests/merchantCardInteractionFlow.test.ts` 订单卡片选择与物流查询端到端全链路测试套件。
  - 在 `README.md` 与 `docs/merchant-onboarding-guide.md` 中补充 Agent SOP 业务技能开发、商户对接与测试实战指南。

---

## [2.1.0] - 2026-08-26 (多轮导购序号指代消解与商户端实时流式会话升级)

### 🌟 Major Highlights (重大亮点)

- **多轮导购序号指代消解与购物车上下文跨轮次持久化 (Multi-Turn Shopping Guide Ordinal Resolution & Cart Coreference)**:
  - 彻底打通从“导购推荐商品”到“把第1件加入购物车”、“买第2款”、“把第几件加入购物车”等多轮自然语言指代消解与加购闭环。
  - 在 `ShoppingGuideContext` 中引入 `candidateProducts` 结构化元数据（包含真实商品 ID、名称、单价、库存、规格与配图），解决上下文仅有基础 ID 缺乏商品快照的问题。
  - 强化 `TaskMemory` 跨请求任务状态管理，将 `guideContext`、`cartContext`、`orderContext` 深度持久化至 PostgreSQL `pending_intents`，并在图构建启动时自愈恢复，根除无状态 HTTP 导致的跨轮次推荐上下文丢失。
  - 升级 `CartManageSkill` 与 `slotExtractor.ts`：
    - 支持精准提取中文及阿拉伯数字序号（“第1件”、“第一款”、“第二件”等），自动映射到 `guideContext.candidateProducts` 并调用 `MallDomainService.addToCart`；
    - 支持短期对话历史（`shortMemory`）回溯兜底，若上下文丢失可自愈解析历史推荐消息；
    - 针对用户原样输入或复制引导语“把第几件加入购物车”提供智能友好提示与候选列表引导。
  - 新增 `packages/engine/tests/shoppingToCartMultiTurn.test.ts` 5 轮端到端全链路自动化集成测试。
- **商户端实时 SSE 流式推送与会话隔离优化 (Merchant SSE Stream & Session Isolation)**:
  - 彻底移除商户端前端浮窗 3 秒高频 HTTP 轮询，改用基于 Server-Sent Events (SSE) 协议的实时事件流（`/api/store/chat/stream`），大幅降低服务端无谓开销并提升交互即时性。
  - 优化新会话初始化与隔离逻辑：刷新或新建会话时展示专属路由问候语，隔离旧会话霸屏，同时支持通过历史记录面板按需恢复与回放既往对话。
- **多段式订单编号支持与会话回放增强 (Multi-Segment Order IDs & Timeline Playback)**:
  - 增强订单编号正则与提取器，支持包含多段横杠与复杂前缀的真实商户订单号。
  - 优化控制台全景会话工作台的实时坐席同步与抽屉历史流式回放。

---

## [2.0.0] - 2026-08-24 (重大架构重构与 SaaS 平台升级)

### 🌟 Major Highlights (重大亮点)

- **NestJS 企业级 API 网关与标准化契约 (`apps/server`)**:
  - 彻底解耦传统单体服务，构建基于 NestJS 核心框架的企业级 API Gateway，统一管理路由分发、依赖注入（DI）、全局异常过滤器与日志切面。
  - 规范 RESTful API 路由设计（涵盖 `/api/chat`、`/api/skills`、`/api/tenants`、`/api/tools` 等）。
  - 全局启用 `ValidationPipe({ forbidNonWhitelisted: true, whitelist: true, transform: true })`，严格阻断未知字段与参数注入，建立坚实的多租户物理与逻辑边界。
- **多租户 SQL 物理层下推隔离与越权防御 (Physical SQL Push-Down Tenant Isolation)**:
  - 彻底改造底层数据仓储与审批流核心方法（如 `ConversationRepository.getConversationTimeline`、`ApprovalGatekeeper.listPendingApprovals` 等），强制将 `business_id` 参数下推至 PostgreSQL 物理 SQL 约束（`WHERE business_id = $1`），彻底杜绝全表加载后在应用层 JavaScript 内存过滤带来的越权风险（IDOR）与内存泄漏隐患。
  - 重构 `TenantRegistryService.updateTenantSkillConfig`，采用安全的物理主键查更机制取代脆弱的 `ON CONFLICT` 语法，完美兼容版本化多租户配置表。
- **实时协同坐席接管与 SSE 流式弹性回放机制 (Live Desk Takeover & SSE Stream Resiliency)**:
  - 落地 WebSocket 双向即时坐席接管网关（`ConversationGateway`），基于 Socket.io 与 Redis Pub/Sub 实现分布式会话接管。坐席端一键发起 `takeover_conversation`，会话状态机原子跃迁至 `human_takeover` 并即时暂停 AI 自动回复；释放时通过 `release_takeover` 毫秒级归还 AI 托管。
  - 在 `ChatService` 中构建跨连接 Job 级事件缓存队列（`jobEventStore`）与单调递增序列号体系（`id: ${seq}`）。当客户端因网络抖动重连并携带 `Last-Event-ID` 请求头时，服务端精准回放掉线期间丢失的思考步骤（`thought`）、工具调用（`tool`）、富媒体卡片（`cards`）与最终结果（`result`），保障多模态对话流 100% 幂等与无缝连续。
- **Admin SaaS 控制台全面重构与 10 大路由 CRUD 模块 (`apps/admin`)**:
  - 基于 React Router 7 + `@agent-all/ui` 纯组件重构企业级 SaaS 控制台，完整落地 10 大标准业务管理子系统：
    1. **商户入驻与管理 (Tenants)**：多租户生命周期与品牌心智配置；
    2. **技能编排中心 (Skills)**：SOP 技能启闭、审批阈值与自定义 Prompt 动态生效；
    3. **工具注册中心 (Tools)**：OpenAPI 动态工具工厂与 MCP/SPI 插件元数据治理；
    4. **HITL 审批工作台 (Approvals)**：敏感业务操作人机协同核签抽屉与状态机流转；
    5. **全渠道会话工作台 (Conversations)**：多租户会话全景树、深层链路 Trace 追溯与实时坐席接管；
    6. **双层用户画像中心 (Personas)**：全局基础生理偏好与租户专有消费习惯分层管理；
    7. **RAG 知识库工坊 (RAG Studio)**：分块检索演练场、切片预览与幂等入库管理；
    8. **安全合规护栏 (Guardrails)**：Prompt 注入防御策略、PII 脱敏规则与风控红线配置；
    9. **大模型评测中心 (Evals)**：自动化 Promptfoo 评测集管理与指标准确率矩阵看板；
    10. **用量与账单中心 (Billing)**：租户级 Token 算力消耗明细、换算成本与财务配额限制。
  - 提炼标准化、零外部组件库依赖的通用 CRUD 套件（`useAdminCrud`、`DataTable`、`FilterBar`、`DetailDrawer`、`FormModal`、`ConfirmDialog`），无缝对接 NestJS API Gateway。
- **BaseSkill 领域技能编排与开放集成生态 (`packages/engine`, `packages/tools`)**:
  - 所有领域技能统一继承 `BaseSkill` 标准抽象类，实现 `canHandle` ➔ `validate` ➔ `execute` ➔ `postExecute` 四阶段标准流水线。
  - 支持商户针对不同技能单独配置启用状态（`enabled`）、免签核准阈值（`approvalThresholdAmount`）以及定制化 SOP 提示词（`customPolicyPrompt`），实现零代码热更新。
- **AST 参数化 NL2SQL 沙箱、双层用户画像与 Transactional Outbox (Security, Persona & Outbox)**:
  - NL2SQL 采用 AST 抽象语法树校验，硬性限制仅允许执行 `SELECT` 查询，强制注入租户物理边界与 `LIMIT 50` 分页保护，并在只读短事务内执行。
  - 落地 Dual-Tier Persona 架构：物理区分 `scope = 'global'`（跨商户通用客户画像）与 `scope = 'tenant'`（品牌私有画像），兼顾个性化服务与商户数据隔离合规。
  - 引入金融级 Transactional Outbox 机制 (`approval_outbox_events`)，保障人机协同审批状态变更与异步工作流恢复的严格原子性与最终一致性。
- **标准化自动化测试套件与持续回归保障**:
  - 新增 `codeReviewFixes.test.ts` 专项测试，针对多租户物理 SQL 下推隔离、SSE 断线重放机制、Skills RESTful 配置 API 进行全量断言验证。
  - Monorepo 全量单元测试、集成测试及 Admin 控制台自动化套件持续保持 100% 绿色通过。

---

## [1.11.0] - 2026-08-22

### 🌟 Major Highlights (重大亮点)

- **工单审核全链路客户身份穿透与长期画像偏好展示 (Approval Identity Resolution & Customer Persona)**:
  - 解决工单列表、工单审核详情抽屉与独立 IM 弹窗中客户身份缺失及画像无法获取的问题。
  - 在 `approvalService.ts` 中通过 `leftJoin(users, eq(threads.userId, users.id))` 实现会话与用户账户的物理关联合并投影，直接透传 `userEmail` 与 `userId`。
  - 扩展 `/api/chat/preferences` 接口支持 `?userId=...` 参数化精准过滤，并关联用户邮箱。
  - 全面升级工单详情抽屉（`ApprovalDetailView`）、人工客服 IM 实时工作台（`HumanChatModal`）与工单列表（`ApprovalList`）：直观展示实名客户邮箱、UUID、商户标识，并动态渲染客户在 `long_memory_facts` 中沉淀的长期画像偏好标签（如尺码偏好、材质避雷、品牌偏好及提取置信度）。
- **RAG 知识库切片物理去重与幂等入库体系 (RAG Ingestion Idempotency & Deduplication Engine)**:
  - 彻底根除 `rag_documents` 物理表中由于反复执行测试与导入导致的切片数据与 Embedding 向量冗余污染（通过 `check-and-clean.ts` 物理清理 574 条重复记录）。
  - 在全链路知识库入库管道（`ingestTxtFiles.ts`、`updateRag.ts`、`seed-rag.ts` 及 `/api/tenant/knowledge/upload`）落地原子化预清理与唯一键检查策略，确保知识入库全流程具备 100% 幂等性。
  - 新增 `packages/engine/tests/ragDeduplication.test.ts` 专属去重与幂等入库防回归测试套件。
- **细粒度 LLM 算力调用审计与低置信度意图主动学习归档 (Granular LLM Telemetry & Active Learning Logging)**:
  - 激活 `llm_call_logs` 物理审计追踪：在 `callLLMWithRetry.ts` 中深度捕获单次 LLM 调用的 Prompt Tokens、Completion Tokens、单次调用耗时（`latencyMs`）、财务成本换算（`costUsd`）、LangGraph 节点名称（`triage`, `planner`, `executor`, `validator`, `finish`）、模型 ID 及 `threadId`。
  - 激活 `low_confidence_logs` 主动学习归档：在 `intentTriageEngine.ts` 中当意图置信度 $<0.65$ 时自动归档用户原始输入与候选意图概率分布，用于线上意图漂移分析与提示词调优。
- **全链路自动化测试套件回归 (Full Test Suite Regression)**:
  - 全量 161 个测试用例（覆盖 47 个测试文件、786 个断言）全部 100% 绿色通过。

---

## [1.10.0] - 2026-08-22

### 🌟 Major Highlights (重大亮点)

- **PostgreSQL 确定性角色时序排序与历史对话防错乱引擎 (Deterministic Message Ordering & Monotonic Clock)**:
  - 彻底根除刷新页面后对话历史次序颠倒（AI 回复跑到用户提问前）的顽疾。
  - 在 `packages/db/src/client.ts` 物理查询层引入确定性角色权重排序：`ORDER BY timestamp ASC, CASE role WHEN 'system' THEN 1 WHEN 'user' THEN 2 WHEN 'assistant' THEN 3 ELSE 4 END ASC, id ASC`，消除同一毫秒并发写入导致 UUID 字典序随机颠倒的缺陷。
  - 在 `packages/engine/src/memory/shortMemory.ts` 引入基于逻辑时钟的角色单调递增时间戳生成机制（`getMonotonicTimestamp`），保证 `assistant` 响应在时钟逻辑上严格晚于 `user` 提问。
  - 通过 `packages/engine/tests/messageOrdering.test.ts` 并发时序验证，确保全场景历史记录 100% 严格按先后交互顺序呈现。
- **SaaS 多租户品牌身份物理锚定与动态脱敏 (Multi-Tenant Brand Identity Anchor & JIT Sanitization)**:
  - 修复多租户会话中商户品牌（如 Nike、Adidas）在历史消息中被降级为 `[ECOMMERCE]` 占位符的问题。
  - 强化 `db.createThread` 租户保护屏障：现有商户会话拒绝被未指定或默认的 `ecommerce` 身份覆盖。
  - 在 `/api/chat/messages` 接口层引入 `sanitizeTenantResponse`，在历史记录拉取阶段结合会话所属商户动态清洗品牌心智。
- **输入框生命周期管理与即时清空机制 (Chat Input State Lifecycle & Instant Clearing)**:
  - 修复发送消息后输入框依然残留上一轮文本的交互缺陷，解耦表单提交与发送逻辑。
  - 在 `ChatArea.tsx` 的 `onSubmit` 与 `useChatMessages.ts` 的 `handleSend` 中实现状态无条件清空，并清空附件图片列表。
  - 增加 `apps/web/tests/chatInputState.test.ts` 单元测试验证输入状态生命周期。
- **人工客服接管生命周期与乐观加载态隔离 (HITL Takeover Lifecycle & State Isolation)**:
  - 修复转人工后用户继续提问导致界面永久卡在“正在全速运行多模态有向有环图节点，智能调用工具链中...”以及 AI 错误抢答的缺陷。
  - 在 `useChatMessages.ts` 收到 `isHumanActive: true` 时立即清理乐观加载态（`isLoading: true` / `pending-job`），并调用 `loadHistory(force=true)` 同步真实数据库消息。
  - 严格保障人工客服接管期间（`status = 'waiting'`）用户消息直通数据库并实时同步，直到人工专员明确点击“🏁 结束人工服务 (切回 AI)”（`status = 'resolved_by_human'`）后才平滑恢复 AI 智能调度。
- **运行时连接池单例化与 HMR 缓存防护 (GlobalThis Singleton Pool Management)**:
  - 修复 Next.js 热重载（HMR）过程中反复建立物理 PostgreSQL 连接池、Redis 客户端和 Temporal Client Promise 的问题，统一通过 `globalThis` 实现单例生命周期管理。

---

## [1.9.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **商城全功能数据库体系与领域服务 (Comprehensive E-Commerce Schema & Mall Domain Service)**:
  - 物理构建高标准 SaaS 关系型商城数据库结构：
    - `user_addresses`: 用户多地址簿（默认地址、详细门牌、收货人与联系电话）；
    - `product_skus`: 商品多规格属性（尺码、颜色、SKU 编码、库存与差异化价格）；
    - `logistics_packages`: 订单履约包裹表（多包裹拆单履约、承运商与主运单号）；
    - `logistics_tracks`: 物流时序轨迹流水（时间戳、物理节点站点、派送状态与描述）；
    - `product_reviews`: 用户商品评价与晒单（星级打分、文本评论与图片证据）；
    - `after_sale_tickets` & `after_sale_logs`: 售后服务工单与流转状态机跟踪。
  - 封装 `MallDomainService` 领域服务，提供标准查询与状态流转接口。
- **意图-槽位状态机与缺失参数即时反问机制 (Intent-Slot State Machine & Fast-Path Clarification)**:
  - 实现结构化槽位与意图抽取器 `SlotExtractor`，严格定义高风险业务必填槽位映射表 `REQUIRED_SLOTS_MAP`（如修改收货地址必须具备 `orderId` 与 `newAddress`）。
  - 在 `IntentTriageEngine` 阶段引入槽位缺失拦截守卫，参数不足时毫秒级生成即时精准反问并写入 `TaskMemory` 多轮上下文记忆；参数补齐后高置信度放行直达 DAG 调度，彻底阻断由于缺少参数导致的自旋与大模型幻觉。
  - 接入 Promptfoo 专属槽位评测集 `slot-clarification.json` 与 `slotClarification.scorer.ts` 自定义评分器，评测通过率 100%。
- **Temporal 真实编排实时状态 SSE 桥接与防假死架构 (Temporal SSE Real-Time Status Stream)**:
  - 重构 `/api/chat/[jobId]/stream` 路由，在真实 Temporal 模式下建立 300ms 毫秒级 `currentStatusQuery` 与 `currentPlanQuery` 轮询推送机制，将底层节点执行状态实时桥接至 Web UI。
  - 在 LangGraph `buildAgentGraph` 及 Temporal `agentWorkflow` 中统一 `isBypass` 判定守卫（`state.output` 存在或 `bypass_step`），保证槽位即时反问与规则旁路毫秒级直达 `finishNode`，避免误入 Planner 自旋。
- **泛订单查询极速直达与批量富媒体卡片合成 (Fast-Path Order Listing & Rich Card Batching)**:
  - 细化泛查单意图与单笔物流追踪正则边界，消除“我的订单”被误拦截为缺失单号追问的缺陷，极速直达 `listUserOrders` 调度。
  - 扩展 `CardSynthesizer` 引擎支持 `result.orders` 批量订单交互卡片生成（查看物流轨迹、申请退款按钮及智能快捷回复胶囊），并内置多租户演示订单自动自愈机制。
  - Monorepo 全量 122 项单元与集成测试 100% 绿色通过（578 个断言）。

---

## [1.8.0] - 2026-08-21

### 🌟 Major Highlights (重大亮点)

- **Text-to-SQL 与 Headless BI 指标语义注册表体系 (Metric Semantic Registry v2)**:
  - 落地 `MetricDefinition v2` 契约标准，将 SQL 聚合公式、动态模板、业务规则约束、口语同义词、歧义冲突组（`conflictGroup`）、排序及展示单位结构化声明配置，从根源上杜绝大模型口径幻觉与硬编码 `if/else`。
  - 预置商场多维指标元数据字典（GMV 总销售额、出货销量件数、净毛利润收益、单品毛利率、滞销积压库存预警）。
  - 实现 `MetricSemanticResolver` 智能指标匹配器，自动识别自然语言同义词与冲突组（如 GMV 流水 vs 出货件数 vs 净毛利润 vs 毛利率）。
- **六大正交解耦 NL2SQL 查询语法树解析与动态编译器 (`packages/tools/src/nlQuery/`)**:
  - `TextNormalizer`：入口前置清洗语气词与虚词（“帮我/麻烦看一下/给我展示/对比看看”等），保护语义纯净度。
  - `TimeRangeResolver`：独立解析时序范围（“近30天/上个月/近7天/今年”），自动输出参数化 PostgreSQL 时间过滤子句。
  - `OrderLimitResolver`：解析“销售额最低/倒数/最少”等反向排序指令并动态改写 `directionOverride`，同时精准提取 TopN 数量限制。
  - `DimensionResolver`：动态解析分组维度（“按品类看/按商品维度”），解耦指标与 GROUP BY 物理列。
  - `FilterResolver`：解析“库存大于500/价格低于200/品类是鞋类”等多维数值与枚举过滤条件。
  - `NLQueryCompiler`：结合多租户上下文、负责人 `managerId` 与 AST 语法树动态安全渲染参数化物理 PostgreSQL 语句，支持防除零安全保护。
- **商场物理数据库扩展与多维分析服务 (`OrderDomainService.queryProductRanking`)**:
  - PostgreSQL 物理迁移：`products` 表扩充 `manager_id`、`category`、`cost_price` 字段，`order_items` 表扩充 `cost_at_purchase`（下单成本快照，防后续商品改价失真）。
  - 注入高保真商场种子数据（覆盖 Vaporfly 顶级竞速鞋、飞马跑鞋、长筒袜等不同销量/流水/毛利特性的商品与订单）。
- **声明式槽位消歧引擎与富交互卡片闭环 (`SlotDisambiguationEngine` & `ProductRankingCard`)**:
  - 实现通用槽位消歧引擎，结合 LongMemory 用户画像与 Default 策略推荐最佳指标。
  - `CardSynthesizer` 自动合成带有金银铜牌徽章、单价、累计销量、GMV 流水、净毛利润与毛利率的 `ProductRankingCard`。
  - 在卡片底部自动挂载 Quick Replies 一键切换口径胶囊（💰 按总销售额 / 📦 按出货销量 / 📈 按净毛利润 / 🎯 按单品毛利率 / ⚠️ 排查滞销库存），实现人机交互与口径切换闭环。
- **Promptfoo 质量评测与 Monorepo 全量测试保障**:
  - 新增 `eval/scorers/metricDisambiguation.scorer.ts` 与 `eval/testCases/ecommerce/metric-disambiguation.json` 评测用例集并在 `promptfooconfig.yaml` 中注册；
  - Monorepo 全量 100 个单元与集成测试 100% 绿色通过（494 个断言）。

---

## [1.7.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **多模态视觉感知与智能破损定责系统 (Multimodal Vision & Damage Assessment)**:
  - 引入 `VisionAnalyzerService`，在 Triage 首层直接支持图文多模态意图识别、快递面单 OCR 提取（运单号/订单号）与商品破损瑕疵智能定级（`negligible` / `minor` / `severe`）。
  - 内置手机号、身份证、银行卡 PII 敏感信息脱敏过滤器，并具备 1500ms 视觉超时与启发式降级兜底。
- **富交互结构化卡片与统一渲染引擎 (Rich Interactive Cards & Synthesizer)**:
  - 新增 `CardSynthesizer` 引擎与统一协议标准（`order_card`、`tracking_timeline`、`refund_confirmation`、`damage_assessment`、`quick_replies`）。
  - 在 `packages/ui` 中构建原生 SVG 图标的高保真卡片组件族与 `RichCardRenderer`，支持一键查看物流、申请退款、动态快捷回复胶囊交互。
- **图片安全上传端点与客户端多图预览 (Safe Image Upload & Client Preview)**:
  - 新增 `/api/chat/upload` 统一接口，强制校验 MIME Type（JPG/PNG/WebP/GIF）与 10MB 大小边界，落盘至持久化目录。
  - 前端输入区集成“📎 图片上传/粘贴”预览条与快捷移除卡片。

---

## [1.6.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **SaaS 商户自主入驻与配置中台 (Self-Service Tenant Hub & IAM)**:
  - 引入 `tenants`、`tenant_members`、`tenant_configs` 与 `tenant_tools` 实体，规范单层商户模型 (`businessId` 命名空间) 与 `Owner` / `Admin` / `Agent` 三级 RBAC 权限隔离。
  - 实现提示词与品牌心智配置的草稿调试（`draft`）与生产发布（`published`）双状态生命周期。
- **商户 API 凭证安全加密与运行时 JIT 脱敏 (Secrets KMS & JIT Injection)**:
  - 基于 Node.js 原生 `crypto` 与 RFC 5869 HKDF，利用主密钥与租户 ID 派生独立密钥，实施 `AES-256-GCM` (`iv:authTag:ciphertext`) 高强加密存储。
  - 动态工具调用时实行 JIT 即时解密注入 Header，全链路脱敏 Pino 日志、Langfuse Span 与 SSE 推送流。
- **OpenAPI 3.0 动态工具工厂与 SSRF 运行时安全沙箱 (Dynamic Tools & SSRF Guard)**:
  - 动态解析 OpenAPI JSON 并生成 Zod Schema 校验器，自动将 `x-requires-approval` 与变更路径路由至 HITL 待审批队列。
  - 内置 DNS 预解析与私网网段（`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `127.0.0.0/8`, `169.254.169.254`）硬拦截 SSRF 运行时沙箱，并施加 8 秒物理超时熔断。
- **知识库多格式异步切片与 Contextual RAG 摄入流水线 (Document Ingestion Pipeline)**:
  - 实现递归段落边界分块（~600 tokens 目标大小，100 tokens 重叠）并自动生成 Anthropic 标准情境摘要，批量注入 PostgreSQL `rag_documents`。
- **租户管理与配置 REST API 路由**:
  - 新增 `/api/tenant/onboard`、`/api/tenant/config`、`/api/tenant/tools` 与 `/api/tenant/knowledge/upload` 统一接口。

---

## [1.5.0] - 2026-08-20

### 🌟 Major Highlights (重大亮点)

- **纯物理真实 PostgreSQL 数据库架构 (Single Source of Truth)**: 彻底移除了 600+ 行内存模拟库（`FakePool`）及复杂的 SQL 正则匹配与降级分支，系统所有读写操作均直连物理真实 PostgreSQL 数据库与 Drizzle ORM，彻底杜绝数据脱节与幽灵数据。
- **聊天记录单调时序与会话级强隔离 (Message Ordering & Session Isolation)**:
  - 在 `ShortMemory` 与 `AgentMemoryEngine` 中引入单调递增时间戳与严格串行入库，数据库查询增加 `ORDER BY timestamp ASC, id ASC`，彻底解决高频与并发写入下刷新页面消息时序颠倒混乱的问题。
  - 重构前端 `useChatMessages` 与 `useChatThreads`，通过活跃会话 Ref 竞态防护拦截迟到异步响应，并在新建与切换会话时立即重置界面为默认欢迎语，彻底消除旧会话历史残留穿透。
- **公共标准订单创建领域服务 (`createOrder`)**: 在 `OrderDomainService` 中新增并暴露了标准 `createOrder` 工具，自动关联用户会话、多租户（SaaS Tenant）归属与订单明细条目，并在落盘后自动同步清除 Redis/本地缓存。
- **Admin 控制台客服介入 IM 工作台统一 (`HumanChatModal`)**: 抽离统一的 `packages/ui/src/components/chat/` 模块，配置 Tailwind CSS v4 `@source` Monorepo 扫描规则，彻底解决 Admin 工作台独立编译下的弹窗样式错位变形。
- **意图分流防误拦截 (Zero False-Positive Refund Interception)**: 优化 `intentTriageEngine`、`executorFastPath` 与 `stepExecutionEngine`，消除纯订单查询被误拦截为退款流程的逻辑缺陷。

### 🏗️ Major Refactoring (重大重构)

- **移除内存数据库模拟器 (`b05abd4`)**: 彻底删除了 `packages/db/src/fakePool.ts`，简化 `packages/db/src/client.ts` 使得所有 API、Agent 与工具直连真实 `pg.Pool` 连接池。
- **统一 HITL 审批中台组件与领域服务 (`11127ff`, `abd1832`)**: 对 HITL 审批工单、人工客服 IM 接管弹窗、订单领域服务及跨包类型进行了全量模块化收敛与编译修复。

---

## [1.4.0] - 2026-08-19

### 🌟 Major Highlights (重大亮点)

- **子任务并行执行器 (Parallel Subtask Executor)**: 在 `StepExecutionEngine` 中实现了基于 `Promise.all` 的无依赖子任务并行调度器，多意图复合查询执行延迟物理降低 50%+。
- **PII 敏感数据物理脱敏拦截器 (PII Scrubber Middleware)**: 在 `packages/tools` 中上线递归敏感数据脱敏切面，自动掩码手机号、身份证、银行卡号与邮箱，保障日志与 Trace 架构合规。

### 🚀 Features & Enhancements

- **并发子任务并行调度 (`cb52316`)**: 重构 `StepExecutionEngine`，自动检测 Fast-Path 独立子任务队列并通过 `Promise.all` 并发极速调起工具，极大缩短用户等待时间。
- **工具链 PII 脱敏切面 (`cb52316`)**: 统一封装 `registerTool` 执行层，所有工具输入/输出参数自动进行 PII 物理数据掩码。
- **TTFT 测速与压测大盘升级 (`cb52316`)**: 升级 `scripts/load-test.ts`，增加流式 SSE 首字响应延迟 (Time To First Token, TTFT) 检测与多租户并发测试能力。

---

## [1.3.0] - 2026-08-14

### 🌟 Major Highlights (重大亮点)

- **多意图分析与 Fast-Path 多步骤直达**: 实现了对多意图（如“查询物流+申请退款”）的精准识别、主次意图加权（Primary/Secondary Weighting）以及槽位提取，并在关联订单号时提供秒级极速直达通道（无需 LLM 规划消耗）。

### 🚀 Features & Enhancements

- **类型升级 (`30d6c25`)**: 为 `IntentResult` 增加了 `type` 与 `entities` 槽位，使分类图节点具备复合诉求提取能力。
- **极速调度优化 (`30d6c25`)**: 拓展 Planner 节点的 Fast-Path，支持复合意图直接组装多步骤子任务 DAG 链，将首字与步骤生成延迟降低 1.5s ~ 2.0s。

---

## [1.2.0] - 2026-08-12

### 🌟 Major Highlights (重大架构升级)

- **深模块门面重构 (Deep Module Facade Clean Up)**: 将原本膨胀的单体模块彻底拆解，提升系统测试性与可维护性。
- **Anthropic Contextual RAG 热更新管线**: 构建集 Markdown Chunking、Contextual Summary 提取、YAML Frontmatter 标注与零样本（Zero-shot）分类于一体的 RAG 数据入库管线。

### 🏗️ Major Refactoring (重大重构)

- **四层记忆统一门面 (`AgentMemoryEngine`) (`7aae5be`)**: 封装 Short、Long、Task、Episodic 四层记忆，实现单次并行获取 (`gatherContext`) 与增量并发归档 (`recordTurn`)。
- **网络流与 UI 渲染解耦 (`AgentStreamClient`) (`7aae5be`)**: 抽离 SSE 订阅客户端，彻底消除 React 渲染树对 EventSource 生命周期的依赖。
- **双模工作流统一调度器 (`WorkflowOrchestrator`) (`7aae5be`)**: 统一 Temporal 生产引擎与本地 LangGraph 极速模拟器的调度与降级逻辑。
- **安控网关拆分 (`StepExecutionEngine` & `ApprovalPolicyEngine`) (`7aae5be`)**: 将 800+ 行单体执行节点解耦为任务执行引擎与金融红线校验网关。
- **数据库仿真隔离 (`FakePool`) (`7aae5be`)**: 从 Drizzle 客户端解耦，提供隔离的 12+ 张关系型表的内存 SQL 仿真。

### 🚀 Features

- **SOP 生产上线标准检查清单 (`687f9dc`, `029e6f7`)**: 在 `README.md` 中集成包含数据库 Migration、Quotaguard 防刷、CircuitBreaker 熔断与 20 并发高吞吐压测脚本的生产上线 SOP 指南。

---

## [1.1.0] - 2026-08-11

### 🌟 Major Highlights (重大重构)

- **全局类型安全与领域仓储隔离**: 彻底剥离全代码库中的 Loose `any` 隐式类型，提炼独立的 `packages/types` 基础包。
- **人工客服 IM 实时接管系统**: 实现 LLM 断路触发、一键人工接管对话（`start_human_takeover`）及对话流安全挂起与恢复。

### 🏗️ Refactoring

- **独立类型共享包 (`packages/types`) (`d2e058f`, `d1a168c`, `b399025`)**: 按 `agent`, `approval`, `config`, `log`, `db`, `event`, `observability`, `tool` 进行模块化强类型声明。

### 🚀 Features & Fixes

- **断路器与人工客服 IM (`78b1e42`)**: 支持客服主管在控制台发起实时 IM 接管，安全打断 AI 决策，并在完成后平滑恢复 AI 智能应答。
- **Fast-Path 规划旁路 (`825b6ae`)**: 实现单意图查询/退款的零 LLM 消耗单步计划合成。

---

## [1.0.0] - 2026-08-10

### 🌟 Major Milestone (1.0 稳定版发布)

- **金融级多租户隔离与账单审计上线**: 正式落地 SaaS 多租户 SQL 物理隔离、Redis SETNX 分布式并发锁与高精度财务算力计费大盘。

### 🚀 Features

- **SaaS 物理隔离与分布式锁 (`537f794`)**: ORM 物理附加 `business_id` 过滤；引入 Redis SETNX 分布式并发防重入锁与 5s 短 TTL 内存降级锁。
- **算力审计大盘 (`537f794`)**: 异步写入 `session_metrics` 账单，提供毫秒级决策时效与 Autopilot 放行率统计。

---

## [0.9.0] - 2026-08-04

### 🔧 Stability & Critical Fixes (稳定性加固)

- **管道缺陷修复 (`66f2e73`)**: 修复包含高价值订单地址变更审核拦截、引用指针失效、死循环熔断以及数据库降级崩溃等 7 个关键 Pipeline Bug。
- **滑动历史窗口与容器防冻保护 (`eb26e4d`)**: 实现对话历史滑动窗口截断，增加 Serverless 容器解冻保护（`waitUntil`）。

---

## [0.8.0] - 2026-07-30

### 🚀 Performance & Multi-Turn Intelligence (性能与上下文优化)

- **Triage 极速优化 (`9567a8a`)**: 引入全局向量缓存（`embeddingCache`）与 Anchor 例句批量向量预加载，大幅提升意图分类速度。
- **上下文感知精判 (`8958721`, `ba10032`)**: 升级大模型意图分类 Prompt，使其具备结合前 4 轮历史上下文的深层语义理解能力。

---

## [0.7.0] - 2026-07-29

### 🏗️ Workspace Modularization (工作空间与 UI 重构)

- **解耦独立应用 (`0075c26`, `e086c89`)**: 将管理控制台（Admin）与用户主站（Web）迁移至 `app/home`，拆分为高内聚组件与 Hooks。
- **共享 UI 基础设施 (`da78d6d`, `f758aaa`)**: 抽离独立的 `packages/ui` 基础包，统一 Lucide Icons 图标导出与 Tailwind 样式模板。
- **HITL 轮询感知器 (`286037d`, `916abe5`)**: 实现前端高保真人工审核工单同步感知传感器，彻底解决多端并发状态竞争问题。

---

## [0.6.0] - 2026-07-28

### 🛡️ Security & Profiling (安全红线与用户画像)

- **IDOR 水平越权拦截 (`e9dc57f`)**: 物理拦截跨用户访问他人订单的 IDOR 漏洞。
- **异步画像 Agent (`5544d78`)**: 引入后台异步 `UserProfileAgent`，自动从多轮对话中提炼客户消费偏好与尺码卡片。
- **多租户物理沙箱 (`cc61d67`)**: 实现知识库向量检索的物理租户隔离沙箱与图级别死循环硬熔断。

---

## [0.5.0] - 2026-07-27

### 🚀 Admin Audit Desk & Advanced RAG (管理大屏与高级 RAG)

- **独立 Admin 中台 (`64698b6`, `6d74046`)**: 创建 Next.js 独立 `apps/admin` 管理工作区，部署可视化人工核签与审核大屏。
- **高级数学 RAG 混合检索 (`1a81b23`)**: 废弃简单关键字匹配，实现 Portable BM25 算法与 Reciprocal Rank Fusion (RRF k=60) 倒数排名融合。
- **自动化 Promptfoo 评测平台 (`5e53191`, `5c59226`)**: 搭建涵盖 Prompt 越狱防范、工具调用准确率与 LLM-as-a-judge 的自动化评估套件。

---

## [0.1.0] - 2026-07-24

### 🐣 Initial Project Release (项目初始发布)

- **智能客服中台初始化 (`3939a76`)**:
  - 核心 LangGraph Agent 决策图 (`triage` → `planner` → `merge` → [`executor` ⇄ `validator`] → `finish`) 构建。
  - 人工核签与认知回溯（HITL & Cognitive Backtracking）机制落地。
  - PostgreSQL + Drizzle ORM + Redis 架构搭建。
  - 支持 Nike / Adidas 多商户动态配置与退款免签额度防线。
