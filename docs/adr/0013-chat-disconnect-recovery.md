# ADR-0013: 聊天断线收口(商店流 L1 重连补投 + 「继续」确定性重派)

日期: 2026-10-10。状态: **已采纳**(2026-10-11 用户裁决「通过」;grilling 两轮收官,决策点全部裁决,见「决策」括注)。
上位关系: 无被取代 ADR;与 ADR-0012 同为对话链路收口但域不同。实弹背景: 2026-10-10 用户问询「AI 回复断了、用户说继续如何处理」,诊断确认现行为纯靠 finish LLM 发挥、无任何确定性机制。

## 背景

1. **AI 回复有三条通路,「断」的另有其人**(2026-10-10 查证):商店 `POST /api/store/chat` 是 **sync=True 同步直跑**,响应携带完整 output+cards,且前端每轮发送后还有一次 `fetchHistory()` 兜底——AI 回复本身不依赖 SSE。pubsub 流(`/api/store/chat/stream` → `tail_pubsub`)独扛的是**人工接管期的坐席发言/系统消息**(realtime.py 桥接)与 POST 等待期断线窗口。pubsub 天然 fire-and-forget、无回放契约(`sse_tail.py:155` docstring 自认「断线期间消息由上层时间线拉取兜底」),断线期间发布的消息**永久丢失**,要重开面板/刷新才补。
2. **引擎事件主干已在发、无人消费**:store 回合走 `run_agent` 同步直跑,`job:events:{jobId}` Stream(status/cards/result 带 seq)全程在写——web 端 `/api/chat/{jobId}/stream` 消费它并获得 Last-Event-ID 重放;商店端无人订阅。
3. **「继续」零确定性处理**:全仓无 continue 意图;裸「继续」落 general_query → finish LLM 吃短期记忆自由发挥。且有两处既有契约必须绕开:`然后|接着` 已是 `MULTI_INTENT_CANDIDATE_RE` 多意图连接词(子串锚定必撞车);planner HOT-RESUME 测试**正拿裸「继续」当探针**,钉死「审批未决议时『继续』必须深规划」。

## 决策

1. **① 商店流 L1 重连补投**(裁决 Q5a):pubsub 活路原样保留,**message 帧补 `id:`(消息时间戳 epoch ms,数字语义与 chat.py Last-Event-ID 同款)**;连接建立时若带 Last-Event-ID(浏览器原生重连自动带 header,兼容 query),服务端从 **DB 时间线重放该时间戳之后的缺失消息**(上限 50 条,先重放再订阅 pubsub,重叠由前端既有按-id 幂等吸收)。payload 形状逐字节不变;**首连(无 Last-Event-ID)不重放**(首屏水合仍走 messages GET);属主闸/心跳/connected 首帧不动。前端**零改动**。
2. **② 「继续」确定性重派 = 引擎 triage 新 Stage `ContinueResumeStage`**(裁决 Q6a,挂 DuplicateIntercept 之后):命中五道闸即把 input **改写回上轮用户原问题**,落回正常 Stage 序——不是旁路重放(上轮无回复可放),是替用户把没被回答的问题**重新问一遍**,复用整条既有管线(语义缓存/槽位/技能全链)。web/store 两面同时受益。五道闸(硬约束):
   - 整句等值词表(规整后精确匹配):继续/继续说/请继续/接着说/然后呢/接着讲——`rule_matchers` 在册 frozenset(QUICK_GREETING_WORDS 同款,纯 in-谓词不触正则 lint);
   - 无带图(图证即新证据,豁免闸与 duplicate_intercept 同源纪律);
   - **无待决议审批**(task_plan pendingAction 未决议——HOT-RESUME 测试契约,此闸不可拆);
   - 上轮有 user 文本消息(纯图轮不可改写);
   - 上一条 assistant **缺失或 `is_failed_response`**(复用 rule_matchers 既有判定,duplicate_intercept 的「失败不重放」同源——用户明说「继续」时失败回复恰好该重答)。
3. **静默重答**(裁决 Q7a):不加「刚才的回复似乎没有送达」类前缀——补偿的本质是把用户要的东西给到,改写后的输出就是上轮问题的正常格式回答;零新增 finish 感知面。
4. **范围**(裁决 Q2a):本轮只收商店页流 + 「继续」(②天然双面);merchant-admin 悬浮助手(fetch 流、无自动重连)的 analytics 帧式 SSE **另立议题**。
5. **打包**(裁决 Q4a):一个 ADR 两决策——同一场断线事故的两半:①管「推送丢了但 DB 有」(传输层),②管「任务死了 DB 也没有」(引擎层),分层不重叠。

## 否决项(从零推演留档)

| 项 | 理由 |
|---|---|
| L2 全迁 job Stream 事件主干 | 前端要学 status/cards/result 新帧协议,POST 同步直跑模型跟着动;AI 回复本有 POST+fetchHistory 双兜底,为补投坐席消息通道不值 10 倍改动面 |
| 「继续」一律重派 | 正常完成后说「继续」会把同一份推荐再轰炸一遍(误伤);仅缺失补偿时,正常场景的「继续」交给 LLM 自由发挥本来就是对的 |
| 子串/正则锚定「继续」 | `然后|接着` 是既有 MULTI_INTENT 连接词,必撞车;「继续推荐便宜的」带新诉求的合法输入会被误劫持丢失新条件。漏接(整句等值)只是落回 LLM 发挥,无害;误劫持有害 |
| finish/网关层做补偿 | 引擎 Stage 改写双面受益且复用 ConfirmationResumeStage 先例;网关前置只覆盖商店页;finish 层拿到时已深规划过,浪费全链 |
| 补偿加「刚才似乎中断」前缀 | 多一个 finish 感知消费面;用户体感「继续→收到完整答案」本身已自然 |
| 引擎中断任务的持久化/主动重推 | run_agent 在进程内,中断即死是已知架构现状(ADR-0007 单实例假设);「继续」重派已是该现状下最短恢复路径,持久化执行属新 ADR 事务 |
| HTTP 轮询兜底强化(缩短 fetchHistory 触发面) | 治标;重连补投直接治因 |

## 非目标(后续独立议题)

merchant-admin 悬浮助手 fetch 流重连/补投(analytics 帧式,另立)/ 引擎任务持久化执行(须新 ADR)/ token 级流式输出 / web 端 chat 流的改动(它已可恢复)。

## 后果

- **实现偏差留痕(决策 2 挂点)**:「ContinueResumeStage」落地为 `run_agent` 入口的 `_maybe_continue_rewrite`(`run_agent.py`,问候旁路之前)——`StageContext` 的 input/clean_input 是不变组(13 出口/41 处读取共享同一可变事实的只读纪律),改写必须在 ctx 构造之前发生,Stage 层要么破契约要么 state 键与 `ctx.input_text` 双源漂移;语义与五闸与 ADR 完全一致,spec `.scratch/chat-disconnect-recovery/spec.md` §2.2 有全记录。闸③容灾口径:审批数据不可得 = 无法排除待决议,**保守放行**。
- **决策 1「前端零改动」修正(2026-10-13,①前端触发面收口,stream-reliability-push 01 号票)**:该假设被 aaa2aba(P7,2026-10-03 4xx 重连风暴收口)提前推翻——其 onerror 一律 close + 显式退避重建**禁用了原生重连**,重建的 EventSource 无法携带 Last-Event-ID header,服务端重放闸恒假,断线窗口消息仍丢(nightly 2026-10-12 实证,architecture-debt 当轮最重项)。修正采用 query 路线而非恢复原生重连(P7 的风暴防护是真实需求,不能回退):商店前端连接机(`FloatingChatWidget` → 新模块 `storeStreamConnection.ts`)把 message 帧 `id:` 行记为水位,退避重建时以 `lastEventId` query 带回;服务端 `store_chat_stream` 补 `lastEventId` Query 参数走 `query_fallback`(header 契约不动,isdigit 同闸);P7 退避语义原样保留并有连接机专册钉面(退避序列/open 重置/MAX_RETRY/水位带回/无 id 帧不污染水位)。
- 商店流断线期间的坐席/系统消息由「永久丢失、刷新才回」变为「重连即补」;契约测试同批更新(test_http_routes_contract store stream 段:id 帧断言 + 断线重连重放用例)。帧 id 统一 epoch ms:`sse_tail.frame_id_from_timestamp` 单点(live 发布帧=本地 naive iso,timeline 行=UTC 带偏移 iso,astimezone 归一;不可解析帧无 id 只 live 送达)。
- 「继续」从 LLM 发挥变为确定性重派:新册钉五闸(每闸一反例参数化)+ 词族在册验证;HOT-RESUME 既有探针测试必须照旧绿(闸③的验收线)。
- 重派走完整管线 = 重跑检索/技能,成本与用户手动重问一致(可接受;语义缓存命中时反而更便宜)。
- 实施批次(裁决通过后):`tail_pubsub` id 帧+重放 / `rule_matchers.CONTINUE_WORDS` / `stages/continue_resume.py` + Stage 序接线 / 两处测试 + 契约更新 / README 规则补记,一批提交。
