# smartServe-Agent 项目知识点详解(新手学习版)

> 项目仓库:`~/Desktop/test/ai/agent-all`(GitHub: weizheng1992/smartServe-agent)
> 本文定位:**纯知识点讲解**——每个知识点先讲通用背景(是什么/为什么),再讲本项目怎么用、代码在哪、新手容易懵的点。不假设你已懂 LangGraph、SSE、事务发件箱这些词,遇到都会先解释。
> 架构决策见 `docs/adr/0001~0011`。

**学习路径建议**:第一部分(全景)必读 → 第二/三部分按兴趣选一条 Agent 主线精读 → 第四部分扫读 → 第五部分(质量体系与常见坑)扫读 → **第六部分(实战三根轴)做自检** → 附录 A/B 当字典查。

---

# 第一部分 全景:这个项目是什么

## 1.1 一段话讲清楚

smartServe-agent 是一个**生产级多租户智能体平台**:一个仓库(Monorepo)里同时跑两个 AI Agent——

1. **智能客服 Agent**:电商售前售后客服。用户在聊天窗问「我的订单到哪了」「帮我把 ORD-123 退了」「推荐一款冲锋衣」,Agent 走一条 LangGraph 决策图,能查真库、能执行退款(带人工审批)、能推荐商品。
2. **商户数据分析 Agent**:商户老板在后台问「本月销售额 Top10」「为什么销量跌了」,Agent 把口语解析成结构化查询,在真实数据库上执行,返回图表卡片。

「多租户」指一套系统服务多家商户(aurora/nike/adidas…),数据互相隔离。「智能体(Agent)」指 LLM 不只是聊天,而是能**理解意图 → 拆任务 → 调工具 → 检查结果 → 回答用户**的闭环程序。

## 1.2 仓库结构(先认路)

```
agent-all/
├── apps/                    # 4 个前端(Vite 6 + React 19)
│   ├── web/            3000 端口,终端用户聊天窗
│   ├── admin/          3001,平台运维控制台(HITL 审批台在这里)
│   ├── merchant/       3005,商城消费者门户(真登录/促销/领券)
│   └── merchant-admin/ 3006,商户员工后台(数据分析 Agent 的宿主)
├── services/
│   ├── gateway-py/     FastAPI 网关(端口 4000):所有 HTTP/SSE 入口
│   └── engine-py/      LangGraph 决策引擎:两个 Agent 的大脑
├── packages/
│   ├── ui/             零依赖原子组件(四端共享)
│   └── types/          冻结的前后端契约类型
├── docs/adr/           11 份架构决策记录(重大取舍的判决书)
└── eval/               评测集与跑分脚本
```

**为什么要 Monorepo(单仓多包)**:契约类型 `packages/types` 改一处四个前端立即可见;跨包重构一个提交原子完成;工具链统一。代价是仓库大、需要任务编排器(Turborepo 按依赖图做增量构建)。JS 依赖由 Bun workspaces 管理,Python 两个服务由 uv workspace 管理。

**两个 Python 服务怎么分工**:gateway-py 只做「接入层」——路由、认证、限流、SSE 推流,不含业务决策;engine-py 做「决策层」——LangGraph 图、意图解析、SQL 编译、记忆。职责线画在「连接 vs 思考」上,这条线让两边都能独立扩容(接入多就多起网关,决策重就多起引擎)。

## 1.3 怎么跑起来(动手第一课)

```bash
bun install                       # 装前端依赖
bun run docker:up                 # 起 PostgreSQL + Redis(数据与缓存)
bun run db:push                   # 数据库建表(Alembic 迁移)
bun run db:seed                   # 灌种子数据(商品/订单/客户)
bun run dev:server                # 起网关 4000
bun run dev:merchant-admin        # 起商户后台 3006(数据分析 Agent 在这)
# 登录:test@example.com / agent-all-dev(种子老板账号)
```

新手第一个坑:网关必须带环境变量启动(`--env-file .env`),漏了 `AI_BASE_URL` 会静默回退到一个死端口,症状像「AI 没反应」,实为「请求根本没发出去」。

## 1.4 基础概念速通(后文会反复用到)

- **Monorepo**:见 1.2。
- **SSE(Server-Sent Events)**:服务器向浏览器**单向推送**的 HTTP 长连接(`Content-Type: text/event-stream`)。浏览器 `EventSource` 原生自带断线重连 + `Last-Event-ID` 续传。**vs WebSocket**:WS 是双向全双工、要协议升级。选型口诀:单向推送选 SSE(如 AI 回答流式输出),双向协作才选 WS(如客服坐席接管,本项目用 socket.io)。
- **多租户隔离三模式**:① database-per-tenant(最强隔离最贵);② schema-per-tenant(折中);③ shared schema + 行级 `business_id` 过滤(最常见,靠纪律保证不漏)。本项目是混合:平台库 shared + 行过滤,商户真账独立库。
- **HITL(Human-In-The-Loop)**:敏感动作(退款)不让 AI 直接执行,先挂起生成审批单,人工批准后程序才继续。「挂起 → 人工 → 恢复」的工程化见第九章。
- **RAG(Retrieval-Augmented Generation)**:检索增强生成——先从知识库里检索相关片段,再把片段塞进 prompt 让 LLM 据此回答。治 LLM「一本正经胡说」的标准药方。
- **Embedding(向量嵌入)**:文本 → 稠密向量(本项目 bge-small-zh,384 维),语义相近的文本向量方向也相近;「余弦相似度」衡量两向量夹角,与长度无关。是语义检索/相似度去重的地基。

---

# 第二部分 客服 Agent:LangGraph 决策图

## 2.1 LangGraph 是什么,为什么需要它

**背景知识**:LangChain 是 LLM 组件库(模型调用、提示词模板);LangGraph 是它之上的**状态机编排框架**——用 `StateGraph` 显式声明节点、边、条件边,一个共享状态(State)在节点间流转。

**为什么 Agent 需要图而不是链**:链(Chain)是有向无环的,表达不了 Agent 的三件本质需求——①**循环**(执行失败要重试或换路);②**条件分支**(结果不同走不同路);③**中断恢复**(挂起等人工,之后从断点继续)。LangGraph 用「条件边 + 共享 State + 外部持久化」三件套把这三样变成一等公民。

**新手容易懵的点**:LangGraph 的图是**单回合**的——每次 `ainvoke` 跑一轮就结束,所谓「恢复」是开新一轮、把上轮存好的计划塞回状态。「挂起即持久化,恢复即重入」这个心智模型很重要。

## 2.2 本项目的图拓扑

6 节点 + 条件边(`services/engine-py/src/engine_py/graph/build_graph.py`):

```
START → triage → planner → merge → executor → validator → finish → END
                                       ↑         │
                                       └──(需要)─┘   validator 条件边三路由
```

- **triage(分流)**:判断用户想干什么(查订单?退款?闲聊?),产出意图与槽位。
- **planner(规划)**:把意图拆成子任务列表(task_plan),每个子任务绑定一个工具/技能。
- **merge**:轻量归并(预留的缝合点,让 planner 可整体替换)。
- **executor(执行)**:逐个子任务调工具或技能。
- **validator(校验)**:检查执行结果,决定「继续下一个 / 回炉 executor / 回炉 planner / 收工」。
- **finish(收口)**:组装最终回复、写记忆、发卡片。

**条件边(顺序即语义)**——validator 按序检查:
1. 熔断:全图状态转移 ≥22 次或工具错误 ≥3 次 → 强制收工(防死循环烧钱);
2. 任一子任务 `waitingForApproval` → finish( HITL 安全挂起,不是失败);
3. 执行失败 + 被管理员驳回且未重规划 → **planner(认知回溯重规划)**——「执行不了就换个思路」;
4. 子任务全部完成(或下标 ≥10)→ finish;
5. 其余 → executor 继续下一子任务。

**图构建原文**(`graph/build_graph.py`——30 行读完全局):

```python
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("triage", triage_node)
    graph.add_node("planner", planner_node)
    graph.add_node("merge", merge_node)
    graph.add_node("executor", executor_node)
    graph.add_node("validator", validator_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "triage")
    graph.add_conditional_edges("triage", route_after_triage, {"planner": "planner", "finish": "finish"})
    graph.add_edge("planner", "merge")
    graph.add_edge("merge", "executor")
    graph.add_edge("executor", "validator")
    graph.add_conditional_edges("validator", route_after_validator,
                                {"executor": "executor", "planner": "planner", "finish": "finish"})
    graph.add_edge("finish", END)
    return graph.compile()
```

**熔断数字的校准故事**(新手学「常量要有物理依据」):循环上限旧值 10 会把 5 步合法计划误杀——每个子任务 executor+validator 各算一次转移,合法物理上限是 20;2026-09-27 事故后校准为 `2×MAX_PLAN_STEPS+2 = 22`。常量不是拍的,是算出来的。

## 2.3 State 与 reducer(多写入者一致性)

**背景知识**:LangGraph 的 State 是一个 `TypedDict`,同一字段可能被多个节点写入——「后写覆盖先写」是默认,但计数器要累加、列表要追加怎么办?LangGraph 用 `Annotated[类型, reducer函数]` 声明**合并策略**(reducer)。

本项目(`graph/state.py`):

```python
def _counter_reducer(current: int, update: int) -> int:
    return 0 if update == -1 else current + update      # -1 = 归零语义

def _merge_dict_reducer(current: dict, update: dict | None) -> dict:
    return {**current, **update}                        # 浅合并

def _concat_reducer(current: list, update: list) -> list:
    return current + update                             # history 追加
```

新手易懵点:State 内部键保持 camelCase(`task_plan.goal`),因为它是**冻结的 SSE 契约**——前端解析的就是这个形状,内部重构不能改线格式。

## 2.4 Triage:9-Stage 意图分流管线

**要解决的问题**:用户一句话进来,先搞清楚「他想干什么」。方法谱系从便宜到贵:关键词规则(零成本,脆)→ 检索式锚点匹配(零训练,可解释)→ 小模型分类(要训练,快)→ LLM 兜底(通吃长尾,贵)。**分层不是历史包袱,是成本-准确率前沿**——越便宜的越靠前,贵的只兜底。

本项目 9 个 Stage 顺序执行,任一 Stage 给出终局即返回:

```
ConfirmationResumeStage → SystemResumeStage → VisionParseStage → RuleWhitelistStage
→ DuplicateInterceptStage → ConsultFastTrackStage → SlotFusionStage
→ EmbeddingAnchorStage → LlmRefineStage
```

挑三个讲透:

- **DuplicateInterceptStage(重复拦截)**:与前问相似度 ≥0.98 **且数字指纹一致**(单号/门牌相同)才重放上一轮答案——用户换了订单号就是新请求,相似度再高也不能重放。
- **EmbeddingAnchorStage(锚点打分)**:每个意图配一组「锚点句」(如 order_status 有 13 句「查物流/到哪了…」),把用户输入和锚句都变成向量,取最大余弦为该意图得分;分数过阈值直达意图。**可解释性**是这个设计的隐藏优点:被判成退款,可以拿出「因为与你最像的锚句是 XXX」给运营看。学术原型是 Prototypical Network(原型网络)思想。
- **置信度级联**:综合置信 <0.5 → 澄清反问(①②③选项);动作域意图豁免澄清;<0.65 落 `low_confidence_logs` 表(这是数据飞轮的输入之一,见第三部分)。

**锚点句库长这样**(`triage/semantic_cache.py`——order_status 组节选):

```python
DEFAULT_ANCHOR_PHRASES: dict[str, list[str]] = {
    "order_status": [
        "帮我查询订单物流状态", "看看我的订单发货了吗", "查询我的快递进度",
        "ORD-98712 的物流信息", "这个快递到哪里了", "查运单号进度",
        "想看一下我的订单状态", "哪些订单可以退货", "我可以退货的订单有哪些",
        "查一下支持退款的订单列表", "查询我名下的订单", "我买了什么东西", "查看近期的购物单据",
    ],
    "refund": [ ... ],        # 8 句
    "out_of_scope": [ ... ],  # 8 句:「今天天气怎么样」「帮我订一张电影票」…
}
```

## 2.5 咨询直答快轨(一次性能优化的完整案例)

**问题**:纯咨询问题(「退货政策是什么」)也会被 planner 深规划——单次 5163 token、73.7 秒,用户等一分钟得到一段本可以秒回的政策文本。

**解法(ConsultFastTrackStage)**:话题词 × 疑问语气命中咨询形 → ①先查语义缓存(相似 ≥0.96 直接回);②否则复用预取的 RAG 切片,相似 ≥0.55 就**单次 LLM grounded 直答**;③直答前 LLM 先复核「这是不是动作请求」——是则返回哨兵 `__ROUTE_TO_ACTION__` 放行完整管线。

**三条纪律**(值得新手背):
1. 哨兵回复**严禁写语义缓存**(动作形输入的答案没有知识依据,缓存会让后续同形输入被资讯回复截胡);
2. 确定性闸前置:首人称取消语(「不想要了」)直接改判动作路由,零 LLM——不依赖模型自觉(模型漂移后曾出过事故);
3. 路由决策权归确定性规则 + 哨兵协议,LLM 只有回答权,没有路由权。

**效果**:咨询类响应 57~114 秒 → 秒级。这是一个「先测量、再定位成本大头、再针对性优化」的标准案例。

**哨兵协议与回填原文**(`triage/consult_fast_path.py` 节选):

```python
    if answer.strip() == ROUTE_TO_ACTION_MARKER:
        if job_id:
            await emit_status(job_id, "🔎 复核为操作请求,转入任务处理管道(意图仲裁员改判)...", node="triage")
        return ROUTE_TO_ACTION_MARKER, [], 0.0      # 快轨放行,不写缓存

    # 回填语义缓存:咨询形输入非动作、回答有 RAG 切片依据,后续相似提问秒回
    if vector:
        add_query_to_semantic_cache(tenant_id, input_text, answer.strip(), vector)
    return answer, [{"intent": AgentIntentType.CONSULT, "confidence": 0.95, "type": "primary"}], 0.95
```

## 2.6 技能系统(Skills):业务动作的插件化

**要解决的问题**:「退款」「加购」「改地址」这些业务动作,逻辑分散在各处没法管——统一成**技能**插件:每个技能声明自己能处理什么意图、需要什么工具、要不要审批,执行体是一个 `execute` 方法。

- **interface(调用方需要知道的)**:`metadata`(id/触发意图/审批阈值/category)+ `can_handle(context)` + `async execute(context) -> SkillResult`。类型化契约 `SkillContext`/`SkillResult` 冻结线格式(黄金快照钉死)。
- **注册与路由**:`SkillRegistry` 登记全部技能;`find_matching_skill` **已决意图精确命中优先**,关键词兜底只服务未决输入——防止导购的「推荐」词面截胡已判成优惠查询的输入(实弹事故案例)。2026-10-07 起匹配内脏收口 `skills/routing.py` 单点(路由知识曾散落五处,一处补词四处仍缺——实弹 A11/c21)。
- **刻意没有 pre_execute/post_execute 钩子**:钩子是隐式控制流;SOP 校验和 HITL 挂起是业务逻辑的一部分,显式写在 execute 里更好读更好测。
- **结构先例**:`skills/cart/`(skill 69 行薄壳 + actions 817 行动词表 + resolver 词族 + cards)、`skills/guide/`(同款四件套)、`skills/routing.py`(路由单点)——「薄壳 + 深模块文件」是包内已验证的拆解范式。

**技能清单**:OrderRefundSkill(退款+SOP)、OrderAddressModificationSkill(改址+多单反问)、ProductInquirySkill(第三方目录穿透)、ShoppingGuideSkill(多轮导购)、PromotionQuerySkill(优惠查询)、CartManageSkill(购物车八动词)。

**interface 原文**(`skills/base_skill.py` + 一技能声明样例):

```python
class BaseSkill(ABC):
    metadata: dict                       # id/name/triggerIntents/category/审批阈值

    @classmethod
    def get_effective_config(cls, tenant_id): ...   # 租户配置覆写(阈值/开关)

    @abstractmethod
    async def execute(self, context: SkillContext) -> SkillResult: ...

# order_skills.py —— OrderRefundSkill 声明
metadata = {
    "id": "skill_order_refund",
    "name": "订单退款 SOP",
    "triggerIntents": ["refund", "order_return"],
    "category": "after_sale",             # 资金否决只让非售后域技能让位
    "approvalThresholdAmount": 50,        # 租户可覆写
}
```

**端到端走查**(「帮我把 ORD-123 退了,98 块」):

1. triage:EmbeddingAnchorStage 锚点命中 refund ≥0.88 → 意图 `refund`;
2. planner 拆子任务 → executor 命中 OrderRefundSkill;
3. execute:SPI 查单 → 双退款检查(status=refunded 即拒)→ 金额 98 > 租户阈值 50 且未审批 → `suspend_for_approval`:开工单 + 计划落 TaskMemory → 返回 `next_action="require_approval"`;
4. validator 见 waitingForApproval → finish(安全挂起),前端出审批卡片;
5. 管理员批准 → 恢复链路见 2.7。

## 2.7 HITL 人工审批:事务发件箱与分布式三件套

**场景**:用户说「帮我把 ORD-123 退了」。退款是资金动作,AI 不能自作主张——正确流程:AI 查单核实 → 生成审批单 → 人工批准 → 系统才真正执行退款。

**这背后是四个分布式系统经典问题**,本项目各有一个教科书级解法(新手把这一节吃透,面试后端分布式基本够用):

**(1) 挂起与恢复——「挂起即持久化,恢复即重入」**
LangGraph 图单回合跑完就结束,「挂起」不是停在半路,而是:生成 `pending_approvals` 审批单 + 把剩余任务计划写进 TaskMemory 表 + 返回 `waitingForApproval` 让图收工。人工批准后,系统开**新一轮** run_agent,JobId 用确定性格式 `job_resume_{approval_id}`——同一审批无论派发几次,JobId 相同,天然防重。

**(2) 双写问题——事务发件箱(Transactional Outbox)**
批准动作要同时「改审批单状态」和「发一条恢复消息」。两个系统无法共享事务,直接双写必有一边丢(先改库后发消息,发的时候崩溃了消息就没了)。教科书解法:**把「要发的消息」当一行数据,和状态变更写进同一个数据库事务**,再由后台进程轮询投递。本项目:`begin_nested()` 里工单状态更新 + `approval_outbox_events` 插入同一事务原子提交。

**(3) 多实例抢任务——`FOR UPDATE SKIP LOCKED`**
PostgreSQL 行级悲观锁 + 跳过已被锁的行:多 worker 并发扫同一张任务表时互不阻塞、互不重复。配套条件都很讲究:只捞 pending/failed、或 processing 停滞 >5 分钟(崩溃遗留重入队);retry_count <5(补偿有上限,不做无限重试放大故障);**10 秒年龄阈值**(新鲜事件留给同步 Fast-Path,补偿链不抢跑)。

**(4) 并发双批——分布式锁 `SET NX PX`**
Redis `SET key val NX PX 5000`:NX = 不存在才设置(互斥),PX = 毫秒过期(持有者崩溃也不死锁)。**实弹坑**:redis-py 的 SET NX 成功返回 `True`、被持返回 `None`,不是字符串 `"OK"`——`str(result).upper()=="OK"` 恒假,导致每一次审批都 409(2026-10-02 实测钉死)。同时确立语义:锁被持必须 409,不许落内存锁放行第二次,否则并发双批。

**对账 Worker(outbox_worker)**:同步派发会被进程崩溃/发布重启打断——失败事件由 30 秒周期的对账任务补偿。「至少一次投递 + 消费端幂等 = 有效恰好一次」——分布式系统没有原生 exactly-once,这句话能答掉一大类面试追问。

**三段核心原文**:

锁的三态判定(`approvals/gatekeeper.py`):

```python
        result = await client.set(lock_key, "locked", px=5000, nx=True)
        # redis-py SET NX 成功返回 True / 被持返回 None,不是字符串 "OK" ——
        # str(result).upper()=="OK" 恒假,每一次审批都 409(2026-10-02 实测钉死)
        lock_acquired = result is True or result == "OK"
```

事务发件箱(同一事务原子提交):

```python
        async with session.begin_nested():
            record.status = next_status                     # 工单状态
            if next_status != "resolved_by_human":
                session.add(ApprovalOutboxEvent(..., status="pending", retry_count=0))
        await session.commit()
```

对账捞取 SQL(`approvals/outbox_worker.py`,SKIP LOCKED 是 PG 并发任务队列的标准配方):

```python
        select(ApprovalOutboxEvent)
        .where(
            or_(
                ApprovalOutboxEvent.status.in_(("pending", "failed")),
                and_(                            # processing 停滞 >5min → 崩溃遗留重入队
                    ApprovalOutboxEvent.status == "processing",
                    func.coalesce(ApprovalOutboxEvent.updated_at,
                                  ApprovalOutboxEvent.created_at) <= text("NOW() - INTERVAL '5 minutes'"),
                ),
            ),
            (ApprovalOutboxEvent.retry_count or 0) < 5,
            or_(                                 # 10s 年龄阈值:新鲜事件留给 Fast-Path
                ApprovalOutboxEvent.status == "processing",
                ApprovalOutboxEvent.created_at <= text(f"NOW() - INTERVAL '{older_than_ms} milliseconds'"),
            ),
        )
        .limit(20)
        .with_for_update(skip_locked=True)
```

**新手易懵**:审批挂起时图为什么是 finish 不是停在半路?——图是无状态单回合的;「24 小时审批过期后用户又问起」?——expired 状态走超时解挂,如实说明并引导重新发起,不会拿过期审批悄悄恢复执行。

## 2.8 四层记忆:不同生命周期的数据放不同的家

**背景知识(记忆类型学)**:认知科学把记忆分为工作记忆(当下对话)↔ 语义记忆(跨会话的事实)↔ 情景记忆(带时间戳的经历)↔ 程序性记忆(流程断点)。主流 Agent 记忆设计(MemGPT/Letta)都是这个四分法的工程化。

本项目四层,每层生命周期和写入策略完全不同——**分表是因为「数据形状决定存储形状」**,合库会把策略搅在一起:

| 层 | 存什么 | 写入策略 | 检索 |
|---|---|---|---|
| short | 对话滑窗(20 条) | 每轮自动 | 直接读 |
| long | 用户画像事实(「脚长 42」) | 审计 Agent 双通道 + **置信度红线** | top5,余弦 ≥0.55 |
| episodic | 动作形事件(「申请了退款」) | 只记动作回合(纯问答不写,省 embedding) | top3,≥0.55 |
| task | 挂起任务计划 | HITL 挂起瞬间落库 | by thread_id |

**两个精彩细节**:
1. **置信度红线**:审计抽出的画像事实,<0.60 丢弃、≥0.85 直接 approved、中间 pending 待审——「模型说什么就信什么」是记忆系统大忌。
2. **回声去重**:注入的记忆被模型复述一遍,审计又把它抽成新事实存回去——几轮后垃圾事实变成高置信事实。防御:与既有事实余弦 ≥0.90 判回声弃落。「记忆系统最大的隐坑是自我强化」,这个细节面试必讲。

**多租户在记忆层**:画像分 `scope=global`(脚长/过敏,跨商户客观)与 `scope=tenant`(品牌偏好),检索时 global 全放行、tenant 仅本 business_id——物理区分,不靠自觉。

**置信度红线与回声去重原文**(`memory/long_memory.py` 节选):

```python
        # 置信度红线路由:<0.60 丢弃;>=0.85 approved;其余 pending
        if confidence < 0.6:
            continue
        status = "approved" if confidence >= 0.85 else "pending"
        ...
        # 回声再吸收去重:注入的画像事实经 finish 措辞回到回复里,
        # 审计把 assistant 自述又抽成新事实(实弹:conf 0.6 pending 重复污染)
        if any(cosine_similarity(embedding, existing) >= _ECHO_DEDUP_THRESHOLD
               for existing in existing_embeddings):
            print(f"[Profiler Agent] 🔄 回声事实弃落(与既有画像近重复): {fact_text}")
            continue
```

## 2.9 Contextual RAG:混合检索与确定性增强

**本项目知识库**:客服 SOP 文档(Markdown),按商户隔离。检索要同时答对两类问题:「ORD-98712 的物流」(专有名词,要词面精确)和「退货流程怎么走」(同义改写,要语义泛化)——任何单一手段都只擅长一头。

**解法是混合检索三步**:
1. **双路召回**:BM25(改进 TF-IDF:词频饱和 k1=1.2 + 文档长度归一 b=0.75,倒排索引,对专名极强、对同义零能力)∥ 向量(bge 嵌入,恰好互补);
2. **RRF 融合**:两路分数异构(余弦 0~1 vs BM25 无界)不能直接加权,RRF 只用排名:`1/(k+rank)`,k=60 平滑头部差距(原论文经验值);
3. **加权混合分**:`0.8×cosine + 0.2×norm_bm25`,min_score 0.4 准入——**低于阈值就承认不知道**,不硬塞低分结果给 LLM(那等于注入噪声)。

**切片(Chunking)纪律**:按 Markdown 标题层级维护 headerPath;SOP 有序列表原子不拆(步骤 1-5 是整体);段落贪心打包 500 字符——chunk 太碎丢上下文、太大稀释向量表示。

**Contextual Retrieval 的确定性变体**:Anthropic 原版给每个 chunk 用 LLM 生成「这段在全文什么位置」的上下文再嵌入(灌库成本 O(n) 次 LLM);本项目用**确定性模板**(「本段切片出自商户 [X] 的文档《T》中「H」章节」)达到类似效果、零 LLM 成本——「先确定性后 LLM」是全仓通用哲学。

**自愈补灌**:进程内目录指纹(name, mtime_ns, size)未变即短路;变了按文件比对行数+MD5,变更文件整组重灌;失败不置位指纹下次重试。

**RRF 与确定性摘要原文**(`rag/contextual_rag.py`):

```python
def reciprocal_rank_fusion(vector_rank, bm25_rank, k: int = 60) -> dict[str, float]:
    """倒数排名融合(RRF)。两路分数异构不能直接加权,只看排名。"""
    rrf_scores: dict[str, float] = {}
    def _apply(rank_list):
        for index, item in enumerate(rank_list):
            rrf_scores[item["id"]] = rrf_scores.get(item["id"], 0) + 1 / (k + index + 1)
    _apply(vector_rank)
    _apply(bm25_rank)
    return rrf_scores

    def contextual_summary(self) -> str:
        """确定性上下文摘要(Contextual Retrieval 的 [Context] 前缀段,零 LLM 调用)。"""
        return f"本段切片出自商户 [{self.business_id}] 的文档《{self.doc_title}》中「{self.header_path}」章节。"

    def embedding_input(self) -> str:
        return f"[Context] {self.contextual_summary()}\n\n[Content] {self.chunk_text}"
```

## 2.10 可靠性:当 LLM 不可靠时,系统怎么仍然可靠

**前提认知**:LLM 会超时、会限流(429)、会被内容过滤拒答、会输出格式错乱、会幻觉。围绕一个不可靠组件构建可靠系统,工程上有标准三板斧:

**(1) 熔断 + 指数退避 + 全局预算**(llm/resilience.py)
- 指数退避重试 3 次:1s 起步翻倍,单次上限 120s;
- **全局预算 `LLM_TOTAL_DEADLINE_SECONDS=180`**——实弹教训:原配置 120s×3+退避 ≈ 6 分钟才降级,用户早跑了。「重试策略必须有全局 deadline」;
- 熔断器:连续 5 次失败跳闸 OPEN、30s 冷却后半开探测——防止对已死服务持续施压;
- 内容过滤(供应商 400 code 1301)确定性同判:**不重试、不计熔断**(同一输入必然同判,重试无意义)。

**(2) 确定性兜底分发器**(skills/fallback_dispatcher.py)
LLM 全挂了,系统降级但**能答的仍然真答**:优惠/券词面 → 真查库回在售活动;显式订单号 → 真查订单状态(含归属校验,非本人如实告知);复合句分段両答;都不命中才返回道歉罐头。**严禁假数据兜底**——「库可达但查无必须诚实空」。

**(3) 语义缓存防投毒**
纯咨询答案缓存(≥0.96 命中秒回),但**动作形输入永不读缓存**(技能层 is_action_query 嗅探)——否则技能层异常降级为 general_query 后,LLM 幻觉的「已成功加购」会经缓存反复扩散(2026-09-04 实弹事故的结构性加固)。

**新手要点**:这三层的顺序是「先让 LLM 更稳(重试/熔断),再让系统不依赖 LLM(兜底),最后让重复问题免费(缓存)」——可靠性不是单点技术,是分层假设。

**全局预算的配置原文**(`llm/resilience.py` 语义):

```
重试:3 次,1s 起步指数翻倍,单次上限 120s
总预算:LLM_TOTAL_DEADLINE_SECONDS=180(超即降级,实弹:原 120s×3+退避 ≈ 6 分钟才降级)
熔断:连续 5 次失败 OPEN → 30s 冷却 → 半开探测失败立即重回 OPEN
内容过滤:400 code 1301 → ContentFilterError 确定性同判,不重试不计熔断
```

**兜底分发器行为表**(`skills/fallback_dispatcher.py`):

| 输入形态 | 行为 |
|---|---|
| 优惠/券词面 | 真查库回在售活动 + 用户已领未用券 |
| 显式订单号 | 真查订单状态(归属校验,非本人如实告知) |
| 复合句(查单+看券) | 分段両答 |
| 都不命中 | None → 调用方保留道歉罐头 + 能力指引 |

---

# 第三部分 数据分析 Agent:语义层路线

## 3.1 核心决策:为什么 LLM 永不写 SQL

**业界现状**:Text-to-SQL(让 LLM 直接生成 SQL)在学术基准上执行准确率 60~87%,生产库 schema 更大更脏还要掉。真正的问题不是准确率,是**错误形态**:生成式错答是**静默的**——SQL 能跑、数字看着合理、但口径错了(比如把退款单算进销售额),用户无从发现。「答不上」可以优化,「答错了没人知道」危险一个量级。

**本项目的替代路线(语义层/Semantic Layer)**:
- 用户口语 → LLM 只做一件事:**把口语解析成闭集结构化意图** `{metric: "gmv", direction: "DESC", limit: 10, ...}`——metric 只能从注册表里选,选不出就诚实说不知道;
- SQL 由**确定性编译器**从指标声明拼装——口径(哪些单算成交、单价取哪个快照列)烧在编译逻辑里,不经过 LLM;
- 全量 SQL 过安全闸(sqlglot AST 审计)→ 只读事务执行。

**效果对比**:闭集内准确率 ~100%(选错指标会被评测集抓住),text-to-SQL 51~62.5% 且静默错。**语义层把正确性从「模型能力问题」变成「模板工程问题」**——这是 BI 领域的成熟思想(dbt metrics/Cube/LookML),Agent 时代的重新发现。

**实弹依据(为什么不是纸上谈兵)**:旧代码曾有三种生成式事故——SQL 注入面、指标定义三份漂移副本、「利润榜」静默兜底成「销量榜」。ADR-0004/0006 记录了完整取证与「拒绝 LangGraph+MetaRAG+GRPO 全家桶」的否决裁决。

## 3.2 意图四级解析:L0 → L1 → L2 → L3

用户问「上个月户外机能销售额 top10」,怎么变成结构化意图?四级降级,越便宜越靠前:

- **注入闸(最先)**:问句含 `;DROP`/`UNION SELECT`/「忽略以上指令」等注入形状 → 直接拒绝,裁决绝不交给后续任何层;
- **L0 词表归一(零 LLM 零时延)**:注册表的 key/label/synonyms 三路词面匹配,命中词最长优先;顺带解析槽位(limit/时间窗/品类,值域全部钳制);反向词(「最差/垫底」)翻转 ASC;
- **L1 小模型分类头(毫秒级)**:L0 词面没接住的长尾(「卖出多少双」≠「销量」词面)由 bge 编码 + 线性头分类(训练见 3.6);三态灰度 off/shadow(只记日志)/on(接管),低置信放行不静默错分;
- **L2 范例回放(免费重复)**:历史成功问句沉淀为范例(问句+意图+向量),新问句余弦 ≥0.90 直接回放其意图——L3 的成功变成下次的零成本;
- **L3 LLM 兜底**:prompt 里放指标闭集清单,LLM 结构化输出(pydantic 校验),metric 选不出 → null → 诚实「暂不支持」;成功则**自动沉淀新范例**;有会话历史时先 LLM 把追问改写成独立问句;
- **全层未命中**:落 `agent_unanswered` 表 + 前端诚实列出「可以试试这些问题」——覆盖缺口变成飞轮输入,绝不编造。

**L0 槽位抽取原文**(`analytics/l0_lexicon.py`):

```python
def extract_slots(clean: str) -> tuple[int, dict | None, str | None]:
    """开放槽位解析(limit/时间窗/品类);L0 命中路与分类头 on 路径共用。"""
    limit_match = LIMIT_RE.search(clean)
    limit = min(max(int(limit_match.group(1)) if limit_match else 5, 1), 50)   # 钳 1~50
    time_window = None
    for kind, pat in TIME_PATTERNS:
        m = pat.search(clean)
        if m:
            time_window = {"kind": kind}
            if kind == "last_months":
                n = int(m.group(1)) if m.group(1) and m.group(1).isdigit() else CN_MONTH_NUMS.get(m.group(1) or "", 6)
                time_window["n"] = min(max(n, 1), 24)      # 「N 个月」钳 1~24
            break
    cat_match = re.search(r"(户外机能|潮流T恤|下装裤类|潮流鞋靴|背包收纳|露营装备|衬衫|配饰|运动配件)", clean)
    return limit, time_window, cat_match.group(1) if cat_match else None
```

**L3 结构化输出契约**(`analytics/llm_intent.py`,pydantic,全部可空 = 未表达交确定性层校验):

```python
class LlmIntent(BaseModel):
    metric: str | None = Field(None, description="指标 key,必须取自闭集;无法确定则为 null")
    direction: str | None = Field(None, description="ASC=升序(最差/最低);DESC=降序;默认 null")
    limit: int | None = Field(None, description="Top N;未表达为 null")
    time_window: str | None = Field(None, description="last_7d|last_30d|last_month|null")
    category: str | None = Field(None, description="九品类之一或 null")
    entity_kind: str | None = Field(None, description="只能是 promotion|customer|spu 三值之一")
    entity_mention: str | None = Field(None, description="实体提及原文,原样摘取")
    chart_hint: str | None = Field(None, description="line=折线 bar=柱状 table=表格;未表达 null")
```

**端到端三例走查**:

1. **L0 命中**:「上个月户外机能销售额 top10」→ 词面「销售额」命中 gmv synonyms → extract_slots:limit=10、time_window=last_month、category=户外机能 → 意图 (gmv, DESC, 10) → 编译执行 → 柱状卡;
2. **L1 接管**:「上个月潮流鞋靴卖出去多少双」——不含「销量」任何词面,L0 未命中 → 分类头 (volume, 0.87) ≥0.5 接管 → extract_slots 兜到 last_month、潮流鞋靴;
3. **L3 沉淀**:「张伟最近的订单」→ L0/L1/L2 全未命中 → L3 解析 `metric=customer_orders, entity_mention=张伟` → 实体消解落库匹配 → 执行成功 → **自动沉淀范例** → 下次同问 L2 零成本命中。

**长尾五例(为什么 L0 没接住、L1 怎么接)**:

| 例句 | L0 为什么没接住 | L1 预测 |
|---|---|---|
| 上个月潮流鞋靴卖出去多少双 | 「卖出多少双」≠「销量」词面 | (volume, 0.87) |
| 这个店一个月流水多少 | 「流水」未入 synonyms | (gmv, 0.84) |
| 发出去的券有人用吗 | 「券+用」不在核销词面 | (coupon_redemption, 0.91) |
| 退回来的货多不多 | 「退回来」≠「退款」 | (refunds, 0.83) |
| 平均一单多少钱 | 描述性指代客单价 | (aov, 0.88) |

**新手要点**:四级的本质是**成本-覆盖-准确率三角**——L0 吃高频、L1 吃长尾词面(推理零边际成本)、L2 把成功变免费、L3 保覆盖、落库保增长。分层不是炫技,是经济账。

## 3.3 语义模型与编译器:口径的单一事实源(ADR-0010)

**问题**:指标多了以后,「表怎么 join」「有效成交怎么定义」散在各处 SQL 里,改一处漏三处。

**解法(声明式语义层)**:`semantic_model.yaml` 声明 12 实体(表+列+别名)/9 join/8 维度/13 口径债务条目,加载即校验(悬空引用/别名冲突响亮失败);`semantic_compiler` 按指标 `compile` 块声明的**形状闭集**(spu_rank/dim_rank/total_single/trend)确定性渲染 SQL。merchant_order_items 的真实列名是 `price` 与 `cost_at_purchase`(成交价/成本快照),有效成交谓词 `status NOT IN (REFUNDED, CANCELLED)` 单点在 `semantic_model.valid_dealing_where()`——编译器、 bespoke 族、排行工具三方插值同一处。

**分层信任三通道(ADR-0010,2026-10-07)**:
- **T0 核验通道(默认)**:闭集指标编译,零 LLM 参与,结果卡挂 `verified` 章;
- **T1 组合通道(env 默认 off)**:闭集答不了的组合问题(「各品牌净销售额环比」),LLM 只产出「组合声明」(选哪些指标维度),SQL 仍由编译器拼装,挂 `composed` 章;
- **T2 探索通道(env 默认 off,仅 admin/老板角色)**:长尾问题 LLM 接地生成 SQL,但必须过完整守卫链(单语句→LIMIT≤50→表白名单→安全闸),生成 SQL 折叠展示可审计,挂 `explored` 章;
- 铁律改写为:「LLM 永不在**无守卫无标注**的情况下产 SQL」——通道化之后,信任是分级的、可标注的。

**新手要点**:这回答了「语义层太死板怎么办」——不是放弃语义层,而是把信任分级:确定性为底,LLM 逐级放权且每级都有守卫和标注。

**语义模型声明样例**(`semantic_model.yaml` 节选):

```yaml
entities:
  merchant_orders:
    database: merchant_db
    alias: o
    columns:
      status: 下单状态(PAID/SHIPPED/DELIVERED/REFUNDED/CANCELLED)
      total_amount: 实付金额(原价−优惠)
      ...
  merchant_order_items:
    alias: oi
    columns:
      quantity: 数量
      price: 成交价快照              # 真实列名 —— 双册互验防的就是写错它
      cost_at_purchase: 成交成本快照(NOT NULL)
dimensions:
  order_status:
    label: 订单状态
    kind: enum
    entity: merchant_orders
    column: status
    values: [PAID, SHIPPED, DELIVERED, REFUNDED, CANCELLED]
```

**有效成交谓词单点**(compiler/bespoke 族/排行工具三方插值):

```python
def valid_dealing_where(alias: str = "o") -> str:
    """退款/取消单不计入真实成交。加状态或改口径只改此处;
    状态集与 order_domain._ORDER_STATUS_ZH 互验钉 test_metric_registry。"""
    return f"{alias}.status NOT IN ('REFUNDED', 'CANCELLED')"
```

## 3.4 SQL 安全闸:四层纵深(每层防一种攻击)

1. **解析层(sqlglot AST)**:sqlglot 把 SQL 解析成语法树(AST),按节点类型 walk 校验——多语句拒绝、仅 SELECT/UNION、危险函数黑名单、表白名单。**为什么字符串正则不够**:正则防不住注释包裹、编码变形、子查询嵌套;AST 是 SQL 的结构本体。**实弹坑**:sqlglot 对未知名函数解析为 `Anonymous` 且 `sql_name()` 恒返 `'ANONYMOUS'`,真名在 `.this`——不特判,黑名单对 pg_sleep 全漏放。
2. **编译层断言**:AST 必须含 `business_id` 列引用(exp.Column 节点级断言,注释/字符串不算)——租户谓词服务端注入且不可剥离。
3. **DB 层**:会话级 `READ ONLY` + `statement_timeout 3s`(会话级兜底,非逐条手工);NullPool(引擎被跨事件循环复用,池化连接绑定建连时的循环会炸)。
4. **呈现层**:查询失败如实报「模板缺陷,非用户问题」,错误归因清晰。

**选型否决留档**:pglast(GPL 传染)、sqlparse(non-validating,作者自声明不能当安全边界)——「安全组件选型要查许可证和验证能力」。

**守卫核心原文**(`analytics/sql_guard.py`):

```python
def _func_name(node) -> str:
    """sqlglot 未知名函数解析为 Anonymous 且 sql_name() 恒返 'ANONYMOUS' ——
    真名在 .this,不取则黑名单对 pg_sleep/dblink 全漏放(实弹)。"""
    if isinstance(node, exp.Anonymous):
        return str(node.this or "").lower()
    return node.sql_name().lower()

def reject_unsafe(sql, schema, require_business_id=False):
    statements = sqlglot.parse(sql, read="postgres")
    if len(statements) != 1:
        raise UnsafeSqlError(f"多语句被拒({len(statements)} 条)")
    stmt = statements[0]
    if not isinstance(stmt, (exp.Select, exp.Union)):
        raise UnsafeSqlError(f"仅允许 SELECT/UNION,实际 {type(stmt).__name__}")
    _validate_expression(stmt, set(schema.get("tables", {})) if schema else None)
    if require_business_id:
        # AST 列引用断言(原为裸子串,注释/字符串字面量都能满足——收紧)
        if not any(isinstance(n, exp.Column) and n.name == "business_id" for n in stmt.walk()):
            raise UnsafeSqlError("缺租户谓词 business_id")
```

## 3.5 端到端走查:一次完整的 ask

```
用户:「本月销量 Top10」(merchant-admin 悬浮助手)
→ gateway POST /api/admin/analytics/ask
   (租户头 + JWT → staff 校验;生成 askId 写响应头;计算挂后台任务)
→ SSE: start → (引擎) 注入闸 → L0 词表命中 volume + extract_slots(limit=10, last_month)
→ compile(闭集模板 + bindparams + 安全闸) → 只读 reader 执行
→ 卡片帧(表格/条形 + 口径注记「排除退款/取消单」) → trace.record → __done__
→ 断线重连:带 X-Ask-Id + Last-Event-ID 回放剩余帧,不重算
→ 终局帧带 traceId → 用户点 👍 → analytics_feedback 台账 + 范例沉淀(反馈闭环)
```

## 3.6 数据飞轮与小模型:把「答不上」变成「能答上」

**飞轮七件套**(intent_flywheel CLI):答不上的问题落 `agent_unanswered` → 回捞重试四分类 → 高频缺口登记新意图族 → 词表弱标注造训练数据 → 训小模型分类头 → 影子灰度上线 → 分歧案例回流。

**小模型分类头(metric_head)训练全流程**(新手学 ML 工程的完整样本):
1. **弱标注造数据**:词面 × 模板程序化生成 590 句(人工零标注);
2. **防泄漏三件**:精确去重 + 评测集近邻过滤(cos≥0.90 剔除防泄漏)+ 分层切分 heldout 15%——「98.88% 准确率不可信,可信的是独立切分 + 泄漏防线 + shadow 分歧率三件套」;
3. **训练**:bge 冻结编码 + 只训 `Linear(384→12)` 约 4.6K 参数,CPU 2 分钟,heldout 98.88%;
4. **灰度部署**:shadow 跑 1~2 周看分歧率 → 达标切 on → 回滚 = 删一个环境变量。「ML 系统的上线不是部署事件,是观测周期」。

**SFT 轨(另一条)**:程序化生成 4478 条「问句→SemQL」样本(QLoRA 微调 Qwen2.5-7B,单卡 A10,token 准确率 99.6%,vLLM 部署)——替换 L3 的外部 LLM 端点。**LoRA 原理一句话**:微调权重变化 ΔW 具有低秩性,分解为两个小矩阵 BA(7B 模型只训 154MB adapter);QLoRA = 4bit 量化基座 + LoRA(7B 进 24GB 单卡)。

**数据纪律三铁律**:badcase 只存信号引用不存用户原文(仓库零原始数据);评测集是训练的纯门(blocklist 永不入训);每个环节有确定性闸门(intent eval ≥95%)。

**训练核心原文**(`scripts/training/train.py`):

```python
def train_linear_head(embeddings, label_idx, num_classes, *, epochs, batch_size, lr, seed, ...):
    """小批量 CE 训练单层线性头;全量放内存(闭集分类头数据量级 = 千句级)。"""
    torch.manual_seed(seed)
    head = nn.Linear(embeddings.shape[1], num_classes)
    opt = torch.optim.Adam(head.parameters(), lr=lr)
    loss_fn = nn.CrossEntropyLoss()
    for epoch in range(epochs):
        perm = torch.randperm(len(embeddings))
        for start in range(0, len(perm), batch_size):
            batch = perm[start:start + batch_size]
            opt.zero_grad()
            loss = loss_fn(head(embeddings[batch]), torch.tensor([label_idx[i] for i in batch.tolist()]))
            loss.backward(); opt.step()
        # 每 epoch 记 heldout_acc → metrics.json 曲线
```

**一条真实训练样本**(SemQL,可推导):

```json
{
  "instruction": "你是商户数据问答的意图解析器。…指标闭集:…",
  "input": "上个月户外机能销售额",
  "output": "{\"metric\": \"gmv\", \"direction\": \"DESC\", \"limit\": 5, \"time_window\": {\"kind\": \"last_month\"}, \"category\": \"户外机能\"}"
}
```

注意第三问「张伟最近的订单」的正确输出 category=null —— SemQL 无 group-by 槽位,模型**没过度填槽**才是学到格式语义。

---

# 第四部分 平台基建:网关、前端与反馈闭环

## 4.1 网关四件套:限流 / 认证 / SSE 推流 / SPI

**(1) 限流——滑动窗口的 Redis Lua 实现**(`gateway_py/rate_limit.py`)

固定窗口限流有边界突刺(窗口交界处可能放过 2 倍流量),滑动窗口用 Redis ZSET 记每次请求的时间戳,统计窗口内的条数:

```python
# Lua:先清出窗口外的旧时间戳,再数窗口内数量,未超限则记录本次
local cutoff = now - window_ms
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then return 0 end
redis.call('ZADD', key, now, member)
```

限流键 = 租户 + IP 双维;已知取舍(面试主动说加分):SPI 租户键取自未验签的头且限流先于鉴权——攻击者可伪造头耗尽他人窗口,IP 维兜底,v1 留档。

**(2) 认证——bcrypt + JWT + 服务端派生身份**(`routers/auth.py`)

- 密码 bcrypt 哈希落库(自带盐,防彩虹表);
- 登录签发 JWT(HS256,30 天):`issue_token(email)` → payload 带 email claim;
- **身份服务端派生**:所有业务路由从 JWT 的 email 回查 `staff_members` 表拿角色——**严禁信任客户端自报的用户/租户**(冒充面)。
- 登出:JWT 的 jti 进 Redis 黑名单(30 天 TTL 与 token 同寿),「JWT 无法撤销」的标准补丁。

**(3) SSE 推流与断线回放**(`gateway_py/sse_tail.py` + `engine_py/event_bus.py`)

引擎把每个事件写进 Redis Stream(XADD),网关是**无状态消费者**:

```python
_PUBLISH_LUA = """
local seq = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], 'MAXLEN', '~', ARGV[1], '*', 'seq', tostring(seq),
           'type', ARGV[2], 'data', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return seq
"""
```

- 为什么 Lua:序号 INCR 和 XADD 必须原子(pipeline 拿不到中间值),两 key 带 `{jobId}` hash tag 保 Redis Cluster 同槽;
- SSE 线格式冻结:`id: {seq}\nevent: {type}\ndata: {json}\n\n`;
- 断线回放:客户端重连带 `Last-Event-ID`,网关先 XRANGE 补缺帧再 `XREAD BLOCK 15s` 尾随——**不丢帧、不重算**;
- 心跳 15s 续命;`socket_timeout` 必须 > XREAD block 时长,否则空闲断流(踩坑实录);
- 读流泵收口 `sse_tail.py` 单点(chat/analytics/store 三处共用——同一逻辑第三份手抄出现时收口)。

**(4) SPI 开放接口——HMAC 签名与防重放**(`routers/spi.py` + `hmac_signer.py`)

三方系统(如外部客服系统)替商户核销审批单,如何安全开放?HMAC-SHA256 签名 + 时间戳防重放(窗口 ≤300s):

```python
signature = hmac.new(api_secret, f"{method}{path}{timestamp}{body}".encode(), sha256).hexdigest()
# 服务端同密钥重算比对;时间戳超窗拒绝(防重放);api_key 定位租户
```

架构审查 #2 后补的三道闸(契约已钉 `test_spi_approval_resolve.py`):缺 `x-tenant-id` 头 → 400;工单归属他租 → 403 且工单原地不动(全局 key 不得跨租户核销);未知动作 → 400 诚实失败(不再静默当驳回)。

## 4.2 前端四端与共享 UI

- **无头原子组件**(`packages/ui`):只提供行为逻辑不绑样式,react 是 peerDependency、样式由宿主 Tailwind 提供——逻辑与样式分离,四端交互一致、视觉各异,且不受外部组件库大版本升级绑架。
- **契约类型**(`packages/types`):Card/Skill/Tool 的 DTO 冻结在此;卡片动作目录 `CARD_ACTIONS` 闭集(引擎新增动作时 web/merchant 两张分发表缺键多键编译期双红灯)。
- **SSE 解析**:`lib/sse.ts` 的 `createFrameParser` 增量解析(坏 JSON 跳帧不中断流);断线重连带 askId+lastEventId 只补缺帧。
- **数据分析宿主**(merchant-admin 3006):悬浮助手 + /analytics 全屏双入口,`ResultCard` 是唯一结果渲染缝(四处消费同形);ADR-0010 起卡片挂信任章(verified 零噪音/composed 蓝/explored 琥珀),探索通道的生成 SQL 折叠可审计。

## 4.3 反馈闭环:让用户评分变成系统能力(v3.1)

**数据流**:结果卡 👍/👎 → `POST /api/admin/analytics/feedback`(带终局帧的 traceId)→ `analytics_feedback` 台账(一次 trace × 一位员工一行,UNIQUE 三元 upsert,改判 last-wins)→ 双扇出:

- 👎 → 坏例池 `thumbs_down` 信号(dedupe 防双击);
- 👍 → `search_exemplar` 查重(≥0.90 跳过,严禁存他人范例 id)→ 未命中注册 `source="user"` 范例 —— 下次同问 L2 直接命中,零 LLM;
- 改判全补偿:👍→👎 撤回自己注册的范例(source 双保险,绝不碰 llm 范例)+ 补落坏例;👎→↑ 撤销坏例信号(candidate 态才可撤,人工裁决优先)。

**新手要点**:这一环把「用户反馈」从运营群里的截图变成了三条可计算的数据流(采纳率分子/坏例信号/范例语料)——「反馈不是客服,是燃料」。

---

# 第五部分 质量体系与架构演进

## 5.1 四层测试,各钉死什么

| 层 | 工具 | 钉什么 | 数量级 |
|---|---|---|---|
| 引擎单测/契约 | pytest(testcontainers 密封 PG+Redis) | 决策图行为、SQL 安全闸、记忆策略、编译器 | 1601 passed |
| 网关契约 | pytest + ASGITransport | HTTP/SSE 线格式、鉴权、租户闸、限流 | 375+3skip |
| 评测 | promptfoo / intent eval | LLM 输出质量(意图分类 F1、指标消歧),基线钉定 + compare 门禁 | 三册钉基线 |
| E2E | Playwright(三浏览器) | 商城购物车全链路、控制台鉴权 | 39+9 |

**核心思想(适应度函数)**:架构不变量不写成文档,写成自动化测试——路由冻结由契约套件钉死、39 指标闭集由 `test_metric_registry.py` 钉死(漂移即红)、「有效成交」口径单点由双册互验测试钉死。「改 YAML 必然撞到测试文件,防止闭集无声漂移」。

**LLM 评测的特殊性**:输出非确定性 → 评测集钉基线(promptfoo 三册)+ compare 门禁(重跑对比基线,语义退化即红)+ 确定性层单独跑分(intent eval 强制 `AI_INTENT_L3=off`,不烧 token 不随模型漂移)。

## 5.2 ADR 精选:重大决策与它们的否决记录

ADR(Architecture Decision Record)= 一份短文档:背景 → 备选 → 裁决 → 触发重评的条件。**否决记录和采纳记录同样重要**——防止未来的自己重新踩坑。

- **ADR-0007(Temporal 退役)**:曾引入 Temporal 做持久化执行,实测单机场景运维成本 > 收益,裁决退役(全仓零调用方后删除);规则:重引入须新 ADR。
- **ADR-0010(分层信任)**:四候选对比(闭集管线 / 单通道接地 Text-to-SQL / 分层信任梯度 / 全自由 Agent+KG),裁决 C:确定性为底 + LLM 逐级放权(T0 核验/T1 组合/T2 探索,详见 3.3);同册否决「多跳本体推理」。
- **ADR-0006(拒绝全家桶)**:有人提案 LangGraph 七节点 + MetaRAG + GRPO 训练全家桶,逐项「不采用 + 写明重新评估触发器」(指标 >50 再议 MetaRAG 等)——「拒绝过度设计」本身要有文档,不然会被反复重提。
- **ADR-0011(归因增强边界)**:关联指标对照(确定性)采纳;归因叙事(LLM 生成因果叙述)以「隔离章 + 数字可溯源硬校验(叙事数字必须数值等价于卡上数据,违者整段丢弃)+ 默认 off」受限采纳;多跳本体推理维持否决。

## 5.3 新手学习路径与常见坑清单

**建议学习顺序**(每步都有可验证产出):
1. 跑起来(1.3)→ 打一句「本月销量 Top10」看 SSE 帧;
2. 读 `graph/build_graph.py`(30 行)对着 2.2 的图走一遍;
3. 跑 `pytest tests/test_data_agent_graph.py -q` 读断言;
4. 挑一条主线精读:客服(第 2 部分顺序)或数据(第 3 部分顺序);
5. 改一个词族词面 → 跑对应测试看红转绿(理解「测试钉行为」)。

**常见坑清单**(每条都是实弹):
1. 网关漏 `--env-file` → AI 静默回退死端口;
2. 相对导入层级在拆包后错位(`.`/`..`/`...` 对应 包/仓/顶层);
3. 测试桩打错模块(`MallDomainService` 门面 vs 簇模块全局,patch 面必须打在代码真实解析的命名空间);
4. LLM 措辞每晚漂移 → 断言用词干级锚点;
5. 新增注册表字段先查读者(零读者的装饰字段会腐化,gmv expression 实证);
6. 后台任务输出别只信 tail——读完整任务文件。

---

# 第六部分 实战视角:真做过 Agent 才答得出的三根轴

**为什么有这一部分**:懂框架的人能讲 LangGraph 的节点和边;真做过 Agent 的人,能顺口说出「工具描述改一个词线上就漂」「结构化输出的 token 会漏计」「幻觉不是一种病是一族病」这类细节痛点。这一部分把前文散落在各章的机制,按三根实战之轴重新串起来——也是自检:每根轴你能不能合上文档讲五分钟。

## 6.1 轴一:工具描述质量——描述就是 prompt

**通用背景**:「工具描述怎么写」在外行眼里是文案问题,在行家眼里是超参数问题。LLM 选哪个工具、传什么参数,全靠描述文本决策——

- **措辞即权重**:描述里把「查询」换成「检索」,工具选择率可能整体漂移;而且同一份描述,隔一晚、换一次模型版本,选择行为都会变(非确定性)。
- **长度是税**:每个工具的描述都要进 system prompt。40 个工具 × 平均 80 token ≈ 3200 token 固定开销,对话还没开始就烧掉了;更糟的是描述越长注意力越稀释,选择反而更差。
- **重叠即摇摆**:两个工具描述边界模糊(「查询订单」vs「查询物流」),LLM 在近似输入上会摇摆——同类问题两次不同答案,测试跑不过,人也解释不了。
- **参数语义不清**:金额是元还是分?`status` 收哪些枚举?不传是 null 还是忽略?参数描述不钉死这些,LLM 必然传错。

**本项目的回应,不是「把描述写好」,而是把「靠描述做选择」的面积从根上削掉**。五层手段,越往上越釜底抽薪:

**第一层:能不靠描述选择,就不靠**。`graph/nodes/planner.py` 的计划主干是**规则分支**——已识别的意图直接映射到写死的计划(步骤 id/描述/依赖数组都是代码字面量),LLM 规划只兜长尾:

```python
# graph/nodes/planner.py —— 已识别意图出确定性计划,描述不承担"让 LLM 理解"的职责
{"id": "step_fast_list_orders", "description": "Call listUserOrders to fetch recent orders", "status": "pending"}
```

这些 `description` 的真实读者有两个:执行器(调度依据)+ 用户(经 `emit_status` 拼进中文进度文案)。它们不参与「LLM 读描述选工具」——选择在 triage 阶段就已闭环。

**第二层:要描述的场合,描述即词表,词表即测试**。数据 Agent 每个指标的「描述」不是一段自由文本,是 `tools_registry/metrics.yaml` 的结构化字段:`label / synonyms / aliases / sampleQueries`。**词表缺口 = 描述缺口**,这是实弹:

> 「为什么退款这么多,该找谁」曾稳定落 `unsupported`——根因是 `refund_rate` 的 synonyms 只有「退款率/退货率/退单率」,裸词「退款」不在册。修复 = 同义词册补一个词,同批离线册 22→30 例钉死。

描述质量的 bug 以 `unsupported` 形式暴露,修复以「词面 + 测试」形式落地——这就是「描述即词表,词表即测试」。

**第三层:断言用词干级锚点**。LLM 措辞每晚都漂,整句断言必炸;triage 锚点句库与夜测断言一律词干级(5.3 坑清单第 4 条)。

**第四层:工具面收敛纪律**。`base_tools` 白名单收口 LLM 能直调的工具面:加购/改量等写操作严禁入列,必须走技能 SOP 管道——**LLM 拿不到的工具,不存在选错的可能**。但收敛有反面教材:`saveUserAddress` 一度不在列,地址快轨子任务空转、终稿谎称成功——工具面「缺失」本身也是幻觉源。收窄与缺失必须一起权衡(白名单最终收了三个有确定性快路径的低风险写)。

**第五层(终极):描述变类型**。自由文本描述怎么写都不对——写少了 LLM 乱猜,写多了烧 token 还漂。终极解法是把「理解描述」降维成「闭集分类」:L3 的 `LlmIntent` 里 `metric` 字段只能取 39 个注册指标之一,LLM 做的不是「读懂 39 段描述再自由发挥」,而是「分类到闭集」。**描述质量的极限问题,变成了可用评测集钉死的分类问题**(5.1 的 F1 基线就是这么测出来的)。

**新手要点**:被问「工具描述怎么写才好」,行家答案不是修辞,是架构——**先把能从描述手里拿走的决策拿走**(规则/闭集),剩下的描述用词表承载、用测试钉死。

## 6.2 轴二:Token 成本——先计量,再优化,而计量本身就有坑

**通用背景**:Agent 的钱和延迟都是 token 堆出来的。行家的第一问不是「你怎么省 token」,是「**你怎么知道 token 花在哪**」——没有逐调用计量,一切优化都是猜。

**本项目的计量架构**(`llm/telemetry.py`,文件头注释就值回票价):

```python
# llm/telemetry.py —— 挂 get_chat_model() 单例,每次对话模型调用一行 llm_call_logs
async def on_llm_end(self, response, *, run_id, **kwargs):
    tokens_in, tokens_out = _extract_usage(generation)      # usage_metadata 优先,老版 token_usage 兜底
    cost_usd = (total_tokens / 1_000_000) * COST_PER_MTOK_USD   # 统一单价 $0.15/M
    # usage 缺失(提供方未回传)时 cost 记 NULL —— 真实值而非假数
    task = asyncio.create_task(_persist(row))               # fire-and-forget,严禁阻塞主状态机
```

每行带**节点归因**(这笔 token 是 triage 花的还是 planner 花的),会话级再聚合进 `session_metrics.total_tokens`。归因立起来之后,「钱花在哪」变成一条 SQL:按 node group by,大头立刻现形。

**计量本身的四个实弹坑**(每一个都真踩过,全是行家细节):

1. **结构化输出漏计**。构造期把 callbacks 塞进 ChatOpenAI,**不穿透** `with_structured_output` 组合——triage 的结构化分类调用整段漏采(实测才发现)。修法:挂点改到 `_ResilientChatOpenAI`,覆写公共 `invoke/ainvoke` 统一注入,组合层怎么包都在覆盖面内。
2. **围栏 JSON 二次漏计**。GLM 偶发把 JSON 包进代码围栏,SDK 严格解析抛错 → 不触发 `on_llm_end` → 这类消耗只经 fallback 的补救调用落盘,直调那份仍是漏的。已知、可解释的偏低,好过不知道偏低。
3. **异步时序坑**。落盘是 fire-and-forget(不阻塞主链路),但 run_agent 收尾聚合不等它写完就取值 → `session_metrics.total_tokens` 恒记 0。修:聚合前 `drain_llm_call_writes(thread_id)` 收口等待。
4. **归因坑**。LangGraph 以无 config 的 `ainvoke` 驱动,thread_id 根本不在 run metadata 里 → 用 ContextVar 携带(asyncio 子任务在创建时刻快照继承);实测落库行过半 node 为空 → `bind_llm_call_node` 兜底补齐。

**成本大头与治理谱系**(计量立起来之后,每一刀都砍在数据指的地方):

| 手段 | 砍的是什么 | 实弹数字 / 路径 |
|---|---|---|
| thinking 默认关闭 | reasoning token(隐形成本大头) | 同题 79.9s → 7.5~18s(`llm/chat.py` 经 extra_body 注入) |
| planner max_tokens 封顶 2000 | 失控长输出 | 「退货政策」曾生成 5163 token / 73.7s(§2.5) |
| 咨询直答快轨 | 整次深度规划调用 | 咨询类 57~114s → 秒级(§2.5) |
| L0 词表 + L2 范例回放 | 高频/重复问题的解析成本 | 余弦 ≥0.90 直接回放,「成功变免费」(§3.2) |
| 确定性 Contextual 模板 | O(n) 次 LLM 灌库成本 | 零 LLM 达到近似效果(§2.9) |
| 本地 embedding(bge-small-zh) | API 账单 | 免费;代价是并发段错误坑,必须走串行护栏单点 |
| 评测断 L3 | 评测本身烧钱 | `AI_INTENT_L3=off`,确定性层单独跑分(§5.1) |

**新手要点**:token 成本问题的答案从来不是「换便宜模型」,而是**流量分层**——让零成本的确定性层(词表/快轨/缓存)吃掉大部分流量,贵的 LLM 只兜长尾,分层本身就是成本架构。另外记住计量纪律:usage 缺失记 NULL 不记 0——0 会污染聚合,NULL 诚实。

## 6.3 轴三:幻觉——不是一种病,是一族病,每族有专属闸

**通用背景**:「LLM 会幻觉」这句话对工程毫无指导意义。真做过的人会把幻觉**拆开**,因为每族的成因不同、闸的位置不同、闸的强度也不同。一张族谱表(全是本仓真实事故):

| 族 | 表现 | 本仓真实事故 | 闸 | 代码路径 |
|---|---|---|---|---|
| 能力幻觉 | 谎称做了没做的事 | 技能层异常降级后,LLM 编的「已成功加购」**经语义缓存反复扩散**(2026-09-04) | 动作形输入永不读缓存(`is_action_query` 嗅探)+ 兜底行为表(§2.10) | `skills/__init__.py` |
| 参数幻觉 | 编造/抄错关键参数 | 图内 OCR 单号三库查无,仍走完退款挂起,终稿谎称「已为您发起退款申请」 | 幽灵单前置拦截:开审批工单**前**查无此单即诚实失败 | `approvals/gatekeeper.py` |
| 事实幻觉 | 编政策/编数字 | 覆盖外的问题「尽力答」必然编 | 闭集 + 响亮失败:39 指标映射不上就 `unsupported`,严禁编造兜底答案;咨询 strictly grounded 只准用检索切片答 | `analytics/graph.py` |
| 数据幻觉 | 编表名列名(text-to-SQL 的天然病) | ——(架构上杜绝) | LLM 永不写 SQL + AST 白名单闸(§3.1/3.4) | `analytics/sql_guard.py` |
| 注入类 | 不可信内容污染动作字段 | 图内注入的「公告」把 minor 破损污染成 auto_refund(坏例探测 S06 实证) | 「图内文字不可信」prompt 规则 + **代码钳制**双保险;防幻觉键集校验(命中项必须原样在候选集内) | `vision/analyzer.py` |

两段最值得背的代码。**幽灵单前置拦截**——幻觉(编造的单号)在闸门处被现实校验击穿:

```python
# approvals/gatekeeper.py —— 开 HITL 工单之前先验单,查无此单诚实失败
return {"isDoubleRefund": False, "orderFound": order is not None}
# 查询异常 fail-open(orderFound=True):物理故障不冒充"查无此单",放行到人工闸
```

注意 fail-open 的方向:异常时放行到 HITL 而不是拒绝——**降级的终点是人工,不是更激进的自动拒绝**。

**ROUTING VETO 哨兵**——咨询直答快轨让「答案生成」兼任「意图复核员」,发现用户实为请求执行动作时返回哨兵而不是硬答(硬答正是能力幻觉的起点:拿知识问答的格式回应动作请求,顺着话头答应下来):

```python
# triage/consult_fast_path.py
ROUTE_TO_ACTION_MARKER = "__ROUTE_TO_ACTION__"
# 曾纯靠直答 prompt 的 ROUTING VETO 让 LLM 自行否决 —— hosted 模型漂移后失效,
# 补了确定性取消语正则前置,LLM 否决降为第二道。
```

这条注释本身就是教训:**靠 prompt 拒绝不如靠代码拒绝**——prompt 闸门建在概率上,代码闸门建在结构上。

**两个元层面的纪律**(比任何单点闸都重要):

- **错误不能变资产**。LLM 否决/低置信标记的回复严禁写语义缓存——否则错误答案永久化,每次命中都复现一次;反馈闭环的改判(👍→👎)要带全补偿,把曾被背书的范例撤干净(§4.3)。
- **幻觉的判定本身也会幻觉**。LLM-as-judge 评测里,judge 看不见数据库——评测集的 expectedRules 不写全真值,judge 会把**真实正确的值**当成编造扣分(本仓称「judge 事实基线律」)。评幻觉之前,先保证裁判有事实基线。

**新手要点**:对抗幻觉的工程答案,不是在 prompt 里写「请不要编造」——那是把闸门建在概率上。正确姿势是按「发生 → 扩散 → 留存」三步各插一道**结构闸**:发生前(闭集/白名单/前置校验)、扩散中(缓存闸/哨兵)、留存后(测试钉死/改判补偿)。

## 6.4 自检清单:十个顺口就能答的问题

行家不会问「你用什么框架」,会问下面这些。哪条答不出,就回哪一节:

1. 工具描述改一个词,线上行为为什么会变?你怎么防漂移?(6.1)
2. 你的系统 token 大头花在哪个节点?你怎么知道的?(6.2)
3. 为什么结构化输出的调用可能被漏计量?(6.2)
4. 用户问了一个没覆盖的指标,系统为什么宁可答「不支持」也不「尽力回答」?(6.3)
5. 「已帮您加购成功」但没有对应工具调用,这条消息是怎么产生的?怎么防复发?(6.3)
6. 图片里的文字为什么默认不可信?(6.3)
7. 为什么动作形输入永不读语义缓存?(6.3)
8. thinking 模式为什么默认关?开着会发生什么?(6.2)
9. 上线一条新指标,词表/评测/权限各要动哪里?(6.1 + 5.1)
10. 评测 judge 怎么才不会把正确答案当幻觉扣分?(6.3)

---

# 附录 A:术语表(字母序)

| 术语 | 一句话解释 | 详见 |
|---|---|---|
| ADR | 架构决策记录:背景/备选/裁决/触发器 | 5.2 |
| AST | 抽象语法树,SQL/代码的结构表示;安全校验 walk 的是它不是字符串 | 3.4 |
| 锚点句库 | 词干级词面锚点,LLM 措辞漂移下断言/路由仍稳定 | 6.1 |
| BM25 | 改进 TF-IDF 的词面检索(k1 饱和/b 长度归一) | 2.9 |
| 熔断器 | 连续失败跳闸、冷却半开探测的故障隔离模式 | 2.10 |
| Embedding | 文本→稠密向量,语义相近方向相近 | 1.4 |
| HITL | 人工在环:敏感动作挂起等人工审批 | 2.7 |
| LangGraph | 状态机式 Agent 编排框架(节点/边/条件边/reducer) | 2.1 |
| LoRA/QLoRA | 低秩适配微调 / 4bit 量化基座上的 LoRA | 3.6 |
| MCP | 工具互联标准协议(本仓登记未实现,见评审报告) | — |
| Monorepo | 单仓多包 + 任务编排 | 1.2 |
| 多租户 | 一套系统多商户,数据隔离 | 1.4 |
| 围栏 JSON | LLM 把输出的 JSON 包进代码围栏,SDK 严格解析会抛错 | 6.2 |
| 幻觉(五族) | 能力/参数/事实/数据/注入,各族成因与闸门位置不同 | 6.3 |
| Outbox | 事务发件箱:消息当数据同事务落库再投递 | 2.7 |
| RAG | 检索增强生成 | 1.4 |
| Reducer | LangGraph 同字段多写入者的合并策略 | 2.3 |
| RRF | 倒数排名融合(异构检索只看排名) | 2.9 |
| 结构化输出 | 强制 LLM 按 schema 产 JSON(function_calling) | 6.1 |
| 语义层 | 指标定义单一事实源,查询=选指标填参数 | 3.1 |
| SSE | 服务器单向推送 + 原生断线重连 | 1.4 |
| T0/T1/T2 | 分层信任三通道:核验/组合/探索 | 3.3 |

# 附录 B:关键代码路径索引

```
graph/build_graph.py            图拓扑(30 行读完全局)
graph/state.py                  State + reducer
triage/intent_triage_engine.py  9-Stage 分流(快轨+锚点+分类头)
skills/routing.py               技能路由单点
skills/cart/ · guide/           薄壳+深模块拆解范式
approvals/gatekeeper.py         HITL 锁/状态机/发件箱
approvals/outbox_worker.py      对账补偿(SKIP LOCKED)
memory/{short,long,episodic,task}_memory.py  四层记忆
rag/contextual_rag.py           混合检索+RRF
llm/telemetry.py                逐调用 token/成本/延迟计量(坑注释在文件头)
llm/chat.py                     模型单例统一入口(韧性层+思维链开关)
graph/nodes/planner.py          规则出计划(描述=调度语+进度文案)
analytics/graph.py              数据 Agent 编排
analytics/engine.py             resolve/compile/execute
analytics/semantic_compiler.py  语义模型→SQL(形状闭集)
analytics/sql_guard.py          四层安全闸
analytics/l0_lexicon.py         词表归一+槽位
analytics/llm_intent.py         L3 结构化输出
skills/spi_client.py            SPI 防腐适配
tools_registry/metrics.yaml     39 指标闭集
tools_registry/semantic_model.yaml  实体/join/维度声明
tools_registry/semantic_model.py    加载校验+有效成交谓词
tools_registry/mall/            商城域四簇(cart/catalog/addresses/fulfillment)
gateway_py/routers/analytics.py 40 条数据分析路由
gateway_py/sse_tail.py          SSE 读流泵单点
gateway_py/routers/spi.py       HMAC 开放接口
eval/nightly/                   夜间评测(58 用例)
```
