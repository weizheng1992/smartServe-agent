# 聊天不是 State:多轮任务状态管理设计与实施规划

> **状态:设计定稿(grilling 共识,2026-10-24),实施未开始。** 来源:外部课程《多轮任务失效检修》12 要点 + 2026-10 业界调研(429s 双通道实查)+ 本仓 12 项对照审计;12 条设计裁决经两轮 grilling 逐条确认(全部采纳推荐项)。
> **范围**:engine-py 商城链路 + d-ops 监控面;data-agent 评测面(d01-d06)不动。
> **关联**:[ai-usage-panel.md](ai-usage-panel.md)(用量面板/turn_path 基建)、[ADR-0006](adr/0006-data-agent-architecture-comparison.md)(不采用清单风格同源)、记忆库 agent-context-architecture(context_builder 六层装配)。

---

## 0. 一页结论

课程框架 = 任务型对话 DST(slot-filling)传统 + 2025 "context engineering" 主流的**正确复述**,方向对但非前沿;对应业界提法是 agent state management(LangGraph)/ context engineering(Anthropic)/ durable execution(Temporal 系)。

**本仓三大真缺口**(课程点名的病象在仓里真实存在):

1. **任务边界判定缺失**——普通用户新输入一律 `DEFAULT_TASK_PLAN` 重规划(`run_agent.py:814,828`,仅 `System:` 前缀才载回旧计划),正是课程⑦点名的"丢任务"病象;
2. **步级恢复缺失**——无 checkpointer(全仓 grep 为零),执行中崩溃只能整体降级道歉(`run_agent.py:330-334`),恢复粒度是计划级非步级;
3. **线上质量指标缺位**——完成率/参数补全准确率/切换准确率/tool 失败率四个命名指标不存在,只有 turn_path/resolution_status 工程遥测。

**本仓三大已领先**(课程里只是口号、仓里已是实物):context_builder 单点装配纪律(预算 2000 + 懒触发滚动摘要 + 失败回退不阻断)、eval 飞轮(badcase 池→起草→夜评 pass^3/意图 95 闸/双护栏,接近全自动)、护栏即文档(熔断阈值带事故校准注释)。

**实施**:六票,P0(task_state 小节 + 回灌 shadow)→ P1(边界判定器 + 四指标看板)→ P2(步级 journal + KV-cache 纪律)。明确不做:Temporal、tool result 清理、speculative tool call、ACE(各有重估触发器,见 §6)。

---

## 1. 课程 12 要点速览 × 本仓对照

| # | 课程要点 | 本仓现状 | 判定 |
|---|---|---|---|
| ① | 多轮指代丢失(无前态→参数无法补全) | ④⑤ 落地后自然消除 | — |
| ② | 参数补全错误(日期/地点/对象) | 澄清链路完整(slot_extractor 追问 + <0.5 置信澄清),但无执行前集中式 schema 硬校验 | 🟡 |
| ③ | 旧状态未退休(改了不写回,下游全错) | "有值才覆盖"堵个案(step_execution_engine.py:545 幻影 Nike);仅长记忆有 superseded 退休模式,**任务实体无通用退休** | 🟡 |
| ④ | 结构化 Task State(聊天不是 State) | 实体总线 guide/cart/order_context + historySummary 纯文本;**无"用户约束"字段、无结构化任务态** | 🟡 |
| ⑤ | 执行前参数装配 + 双校验 + 主动澄清 | 装配在 step_execution(schema 明示防发明实参),缺集中校验闸 | 🟡 |
| ⑥ | Context Editor(相关性 + Token Budget) | context_builder 单点装配 + 预算 2000 + 懒触发滚动摘要(≤300 字,截 600 防膨胀,失败回退不阻断) | 🟢 |
| ⑦ | 任务边界判定(modify vs new) | **级联只判意图类别不判任务边界;新输入一律重规划** | 🔴 |
| ⑧ | Checkpoint 异常恢复(退回最后稳定点) | HITL 计划级恢复强(PendingApproval 落库 + Plan-Preservation Bypass);**无步级,崩溃整体降级** | 🟡 |
| ⑨ | 三道护栏(session 超时/最大步数/任务超时) | 熔断 22 / tool_errors≥3 / MAX_PLAN_STEPS 10(带事故校准注释)+ vision 30s/接管 90s 等超时;缺图循环整体 wall-clock 超时 | 🟢 |
| ⑩ | 健康度五指标 + Bad Case 回灌 | turn_path 七值闭集落库 + d-ops 用量页;四质量指标无;回灌通道完整但差"自动起草"最后一公里 | 🔴/🟢 |
| ⑪ | 所有能力围绕同一套 State | 语义分层意识有(semantic_model.yaml 契约单点 + engine↔TS 影子 diff) | 🟢 |
| ⑫ | 结论:准确率/延迟/成本 | token 成本已入 session_metrics + llm_call_logs | 🟢 |

---

## 2. 业界调研结论(2026-10)

**定位**:不算过时,也无超前点。最像 LangGraph 状态机 + Manus 实践的合集;走的是"手工管理结构化 State"路线(Anthropic 走的是相反的"状态交由 API/模型托管"路线)。

**比课程更新的做法**(按对本仓影响排序):

1. **压缩策略已从"摘要"升级**:非破坏式压缩(Cloudflare Project Think)、确定性 fold;Manus 提出 **KV-cache 命中率才是生产第一指标**(稳定前缀 + append-only),比 Token Budget 更硬 ——[Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)、[Cloudflare](https://blog.cloudflare.com/project-think)
2. **checkpoint ≠ durable execution**:LangGraph checkpointer 只管断点续跑,趋势是 Temporal/Restate 做步级重放;已知生产坑:checkpoint 后改 state schema 会导致 resume 失败 ——[Diagrid](https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short-for-production-agent-workflows)
3. **Anthropic context editing + memory tool 已 GA**(自动清旧 tool result + 文件式记忆,官方评测 +29%/39%)——[cookbook](https://platform.claude.com/cookbook/tool-use-context-engineering-context-engineering-tools)
4. **评测口径升级为 pass^k**(全过才算过)+ trace→dataset 自动回灌 ——[philschmid](https://www.philschmid.de/agents-pass-at-k-pass-power-k)
5. **任务边界判定业界仍是开放问题**:无公认算法,大家靠模型隐式判断——课程的显式判定反而是合理自建方案
6. 学术前沿(本仓暂不追):ACE(context 当进化 playbook,防 context collapse,[arXiv 2510.04618](https://arxiv.org/abs/2510.04618))、speculative tool execution([PASTE](https://arxiv.org/html/2603.18897v1))

**课程漏掉的**(本仓需留意):多 agent 状态共享、state schema 演进/迁移、状态与租户隔离(本仓架构不变量 #1 已覆盖 business_id 归因)、压缩腐化状态(governance decay,审批挂起时需冻结压缩)。

---

## 3. 设计裁决(grilling 12 条,2026-10-24 定稿)

| # | 裁决 | 结论 |
|---|---|---|
| D1 | 产出形态 | 规划成票、分批实施;范围 = engine-py 商城链路 + d-ops 监控面 |
| D2 | 边界判定器调用形态 | **合并进 intent_triage 同一次 LLM 调用**(结构化输出加 boundary 字段);低置信 → 澄清旁路。fail 方向 = 澄清,**不是**默认重规划(那是病象) |
| D3 | task_state 与域总线 | **分层**:task_state 是任务层真源,guide/cart/order_context 保持域层总线不动;序列化时任务层在前 |
| D4 | task_state 形态 | JSONB 小节(列内演进,无 alembic 迁移):goal / constraints / entities{值+来源轮次+superseded[]};更新即覆盖;读取缺省兜底 |
| D5 | journal 恢复语义 | 同 session **下一轮入口**检测未完成 journal → 续跑剩余步;超 1 轮或实体失效 → 降级致歉;HITL/审批挂起正交不动 |
| D6 | 指标节奏 | 四指标+切换代理**先上 d-ops 只读看板**,夜评硬闸阈值等 ~2 周基线再定;线上 pass^k 视图依赖 task_state 任务分组,后置 |
| D7 | 回灌安全阀 | 高置信信号**自动起草进 shadow 集**(夜评只跑不出闸),人工一键转正进硬闸集 |
| D8 | 实体键控 | 开放键值 + **hot keys 白名单**(白名单外只记观察日志不进状态,防垃圾串) |
| D9 | KV-cache 范围 | 本轮 = context_builder **前缀稳定纪律** + 可缓存性审计;命中率监控(需网关上报缓存字段 + llm_call_logs 加列)记后续票 |
| D10 | 不引入 | Temporal/Restate(部署矩阵 A 档单机为主,运维面不匹配)、tool result 自动清理(tool result 本就不进历史块,已天然领先)、speculative、ACE |

---

## 4. 如何做(六件套实施设计)

### 4.1 P0-1 · task_state 结构化小节(地基)

**解决**:课程④(无结构化任务态)+ ③(实体无通用退休)。

- **存储**:`TaskMemoryRow.pending_intents` JSONB(`db/models.py:204-209`)内新增 `task_state` 键,**无 alembic 迁移**(列内演进);读取对缺键/旧数据缺省 `{}` 兜底——规避调研点名的"schema 演进破坏 resume"生产坑。
- **schema**:

```json
{
  "task_state": {
    "goal": "上海行程",
    "constraints": [{"text": "保留本轮限制", "turn": 3}],
    "entities": {
      "date": {"value": "周四", "turn": 5,
               "superseded": [{"value": "周三", "turn": 2}]}
    }
  }
}
```

- **写入单点** `retire_and_set(key, value, turn)`:覆盖即退休、旧值进 superseded——照搬长记忆已验证模式(`long_memory.py:40-58`)。所有实体更新点(slot 抽取/工具回填)统一走它,替代散点修补。
- **hot keys 白名单**(D8):初版 `date / time / city / address / product / order_id / guest_count`,可配;白名单外键 → logger 观察通道,不落状态(防垃圾串,compose 归一前科票同源纪律)。
- **读取**:context_builder 序列化"任务层段"(goal/约束/活跃实体)置于域总线段之前(任务层→域层),受同一预算管控。

### 4.2 P0-2 · bad case 回灌 shadow 集(飞轮最后一公里)

**解决**:课程⑩回灌的"人工 CLI 起草"断点。

- 现状:信号自动入池(`badcase/intent_signals.py:46,97`,BadcaseCandidate + 去重)→ CLI `cmd_draft` 人工起草(`badcase/cli.py:142-180`)→ 人工并入 testCases。
- 改造:高置信信号**自动**生成用例草稿 → **shadow 集**(testCases 带 `status=shadow` 或独立文件);夜评对 shadow **只跑只报告、不出闸**;CLI 增 `promote` 命令人工一键转正进硬闸集。
- 纪律(D7):自动只到 shadow 为止,人审才拦发版——防误信号锁死发版。

### 4.3 P1-1 · 任务边界判定器(最大缺口)

**解决**:课程⑦;修 `run_agent.py:814,828` "新输入一律重规划"病象。

- **调用形态**(D2):不建独立节点——扩展 intent_triage 现有 LLM 调用,结构化输出加字段:

```json
{"boundary": {"decision": "modify | new", "confidence": 0.83,
              "rationale": "用户仅修正日期,目标(上海行程)与实体(城市)未变",
              "entities_changed": ["date"]}}
```

- **modify 分支**:载回旧 plan(复用现 `System:` 前缀路径的载回逻辑,触发条件从"仅 System: 前缀"扩到判定器 modify)+ task_state 差异更新(entities_changed 走 retire_and_set),**不整体重规划**。
- **new 分支**:维持现状 DEFAULT_TASK_PLAN 重规划。
- **低置信**(< 阈值,初值 0.6,env 可配):走澄清旁路(现有 bypass_step 模式,`intent_triage_engine.py:711`),话术"是继续安排上海行程,还是新需求?"——宁可多问一句,不可丢任务。
- **评测闸**:新建 boundary 评测集 30-50 例(modify / new / 低置信澄清三段),入夜评硬闸(意图 95 闸同款机制);与意图集双护栏同域管理。验收红线:data 42/42、t1t2 25/25、意图 95 闸不回退。

### 4.4 P1-2 · 四指标 + 切换代理,d-ops 看板

**解决**:课程⑩五指标。全部从现有遥测派生,**零新采集**:

| 指标 | 口径 | 原料 |
|---|---|---|
| 任务完成率 | resolution_status 成功 / 轮(单轮口径;多轮 pass^k 视图等 task_state 任务分组后置) | resolution_status |
| 参数补全准确率 | 澄清触发 → 后续轮补全成功(无二次澄清)比例 | turn_path + pending_intents |
| Tool 调用失败率 | tool_errors / tool 调用 | session_metrics |
| 单轮 Token 成本 | job 聚合 tokens/cost | llm_call_logs(`db/models.py:359`) |
| 切换准确率(代理) | 同 session 同 intent_category 重复 + 纠正词表命中,计为边界失败信号 | turn_path + 词表(初版;标注攒够再校真值) |

- 呈现:`apps/merchant-admin/src/pages/ai-usage/` 加只读一节;口径 SQL 全部单测。
- 节奏(D6):看板先行,硬闸阈值等 ~2 周基线再定——"管道盲闸吞失败"前科纪律。

### 4.5 P2-1 · 步级 journal(第二缺口)

**解决**:课程⑧;修"执行中崩溃整体降级道歉"(`run_agent.py:330-334`)。

- **新表** `task_step_journal`(append-only,无 update):`id, thread_id, job_id, plan_id, step_index, status(pending|ok|failed), result_digest, created_at`。
- **写点**:step_execution_engine 每步完成 / 工具结果落一行(含 result_digest 供幂等重放判断)。
- **恢复**(D5):run_agent 轮入口检测同 thread 存在未完成尾巴(且非 HITL 审批挂起)→ 从最后 ok 步续跑剩余;超 1 轮未续或 task_state 相关实体已变 → 放弃,降级致歉。
- **正交性**:PendingApproval 计划级暂停不算"未完成";journal 任何异常不阻断主流程(context_builder"回退不阻断"同款纪律)。
- **不引入** Temporal/Restate(D10):A 档单机部署矩阵不匹配其运维面;步级重放由本表实现。

### 4.6 P2-2 · KV-cache 前缀稳定纪律

**事实**:全链路无缓存命中字段——`llm_call_logs` 仅 tokens_in/out + cost + latency(`db/models.py:359-374`),telemetry 只读 `input_tokens/output_tokens`(`llm/telemetry.py:126`)。

- **本轮**(D9):context_builder **可缓存性审计 + 结构纪律**——稳定前缀(system/tools/任务层)在前,history append-only,易变段(时间戳等)后置或剥离;产出装配顺序快照测试锁死顺序。
- **后续票**(不在本轮):网关上报 cached tokens → llm_call_logs 加列 → 看板命中率指标。依据 Manus:命中率是比 Token Budget 更硬的成本指标。

---

## 5. 票表

| 票 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| **P0-1** | task_state 小节 + retire_and_set + context 任务层序列化 | — | 单测(覆盖/退休/白名单外观察/旧数据缺省)+ context 快照 |
| **P0-2** | 回灌 shadow 集 + promote 命令 | — | shadow 夜评只跑不出闸;转正后进硬闸 |
| **P1-1** | 边界判定器(boundary 字段 + modify 载回 + 澄清旁路) | P0-1 | boundary 集 30 例全绿;意图 95 闸 / data 42/42 / t1t2 25/25 不回退 |
| **P1-2** | 四指标 + 切换代理 d-ops 看板 | — | 口径 SQL 单测;看板呈现;无新采集 |
| **P2-1** | 步级 journal + 下一轮续跑 | — | 崩溃注入:从最后 ok 步续跑;HITL 不误伤;异常不阻断 |
| **P2-2** | KV-cache 前缀纪律 + 装配顺序快照测试 | — | 审计清单 + 快照测试 |

顺序依据(D12/Q12):判定器修用户可感病象,journal 是韧性加固后置不加重病象。

## 6. 不做清单与重估触发器(ADR-0006 风格)

| 不做 | 理由 | 重估触发器 |
|---|---|---|
| Temporal/Restate durable execution | A 档单机部署矩阵,运维面不匹配 | 多实例/跨服务长任务成为常态 |
| Anthropic 式 tool result 清理 | tool result 本就不进历史块,已天然领先 | —(结构性免疫) |
| speculative/并行工具调用 | 延迟非当前痛点 | 延迟成为投诉点 |
| ACE 进化 playbook | 上下文策略无需热更 | 策略需频繁线上热更 |
| 线上 pass^k 视图 | 缺任务级分组真值 | task_state 分组落地后重估 |
| 判定器独立节点/独立调用 | 白费一次调用延迟 | triage 小模型判 boundary 质量不达标时 |
| 自动入硬闸集 | 误信号锁死发版 | shadow 误报率连续 <1% 时可议 |

## 7. 风险与纪律

- **schema 演进**:task_state 全程 JSONB 缺省兜底,任何读取处禁止严格 schema 断言(调研坑:checkpoint 后改 schema 致 resume 失败)。
- **垃圾串**:白名单外实体只进观察日志;观察日志本身定期评审防堆积。
- **盲闸**:所有新硬闸(边界集/指标阈值)必须先看板观察 ≥2 周再上闸(前科:管道盲闸吞失败)。
- **并行会话**:实施时 git add 必须按文件点名(前科:引擎八文件被无关提交卷入);当前工作区尚有 0026 memory_fact_subject 未提交,开工前先落它。
- **判定器误杀**:fail 方向恒为澄清;边界评测集与意图集双护栏同域演进,防两集互相顶。

## 8. 来源

- 课程:《多轮任务失效检修》12 帧(失效 01 指代丢失 / 失效 02 参数补全错误 / 冲突传导旧状态未退休 / 结构化 Task State / 执行前参数装配 / Context Editor / 任务边界判定 / Checkpoint / 三道护栏 / 健康度五指标 / 围绕同一套 State / PRODUCTION READY)
- 调研:§2 所列一手来源(Manus / Cloudflare / Diagrid / Anthropic / philschmid / arXiv),检索时点 2026-10-24
- 本仓审计:12 项对照(§1)+ file:line 证据,见各节内嵌锚点
