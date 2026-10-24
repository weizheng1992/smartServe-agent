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

- **写入单点** `retire_and_set(key, value, turn)`:覆盖即退休、旧值进 superseded——照搬长记忆已验证模式(`long_memory.py:40-58`)。**任务层实体的统一入口 = 收口缝 `advance_task_state`**(goal ← 计划、实体 ← 本轮意图槽位、约束 ← 用户输入句式);域总线回填(step_execution「有值才覆盖」)按 D3 分层裁决保持域侧不动,P1-1 边界判定器的 `entities_changed` 落地时再统一走 `retire_and_set`。
- **hot keys 白名单**(D8):初版 `date / time / city / address / product / order_id / guest_count`,env `AI_TASK_STATE_HOT_KEYS` 可扩;白名单外键 → **观察通道留痕再拒**(print 单行,同轮同名去重刷屏)——静默丢弃会让该扩的白名单无从发现(code-review 裁定,2026-10-24)。
- **约束来源**(实施细化):保守窄句式正则(不要/不用/无需/只要/尽量/务必 + 1-8 字尾串,句读截停),误收面靠窄模式+截帽(20 字)控制;同文本去重刷新轮次,超帽(3 条)丢最旧。
- **读取**:context_builder 序列化"任务层段"(goal/约束/活跃实体)置于域总线段之前(任务层→域层),**受同一预算管控**(先扣自身成本再装轮;goal 80/约束 20/实体值 40 截帽保证扣减有界——code-review 裁定),`turns` 自带单调轮次计数(short_memory 截 10 长度非单调)。

### 4.2 P0-2 · bad case 回灌 shadow 集(飞轮最后一公里)

**解决**:课程⑩回灌的"人工 CLI 起草"断点。

- 现状:信号自动入池(`badcase/intent_signals.py:46,97`,BadcaseCandidate + 去重)→ CLI `cmd_draft` 人工起草(`badcase/cli.py:142-180`)→ 人工并入 testCases。
- 改造:高置信信号**自动**生成用例草稿 → **shadow 集**(`eval/testCases/shadow/pending.json`,不被任何硬闸 yaml 引用——主配置 suites 显式列举,新目录天然不入闸);开闸面**派生自** `pool.SOURCE_PRIORS` 的 suspected_defect 族(circuit_breaker 刻意排除,「单独立案聚合不直接转 case」);夜评新增报告例 `sh01_shadow集`(advisory 恒真:失败不进退出码、不回灌坏例池,空集/promptfoo 缺位诚实记 skipped);CLI `promote` 人审一键转正(选套件+补断言+留痕 converted)。
- 纪律(D7):自动只到 shadow 为止,人审才拦发版——防误信号锁死发版。

### 4.3 P1-1 · 任务边界判定器(最大缺口)—— ✅ 已落地(2026-10-24)

**解决**:课程⑦;修 `run_agent.py:814,828` "新输入一律重规划"病象。

- **调用形态**(D2):不建独立节点——扩展 intent_triage 现有 LLM 调用,结构化输出加字段:

```json
{"boundary": {"decision": "modify | new", "confidence": 0.83,
              "rationale": "用户仅修正日期,目标(上海行程)与实体(城市)未变",
              "entities_changed": ["date"]}}
```

- **modify 分支**:planner Boundary-Preserve 保留既有计划(prior_subtasks 在场 ∧ 高置信 ∧ 非 System 轮 ∧ 无驳回上下文 ∧ 当前步不挂审批——四道门禁),零 LLM;新槽位由 step_execution 现取现用,**entitiesChanged 的实体更新由收口缝 advance_task_state 的槽位抽取覆盖**(同源同键,不重复接线——as-built 裁决)。`System:` 前缀路径与 Plan-Preservation Bypass 维持现状。非 System 轮 initial task_plan 为空的载回接线已随并行批 aa98ef3 进 HEAD(⚠️该批把 run_agent.py 连同本批 P0 接线 hunk 一并卷入提交,未署名——ebd3ffc 同型事故第三起,git add 按文件点名纪律再次强调)。
- **new 分支**:维持现状 DEFAULT_TASK_PLAN 重规划。
- **低置信**(< 0.6,env `AI_BOUNDARY_CONFIDENCE_THRESHOLD`):走澄清旁路(handle_immediate_bypass "boundary_clarify" → turn_path=clarify),话术不引用具体任务名(判定器拿不准时复述任务名只会放大错误);`AI_BOUNDARY_CLARIFY=0` 一键回退。
- **评测闸**:`evals/boundary_cases.jsonl` 30 例(modify 10/new 10/clarify 10)+ `evals/run_boundary_eval.py`(评分口径与被测行为一致:弃权=失败,严禁放水);夜评 `b01_boundary集` 例,**`AI_BOUNDARY_GATE` 默认 off(D6 看板先行纪律,先攒 2 周基线再开硬闸)**;首跑实弹 26/30=86.7%(2026-10-24,失败全在 clarify 段,其中「帮我订那个」判 modify@0.90 属语料标注可商榷)。
- 验收红线:意图 95 闸 / data 42/42 / t1t2 25/25 未触碰(本批 diff 零涉及)。

### 4.4 P1-2 · 四指标 + 切换代理,d-ops 看板 —— ✅ 已落地(2026-10-24)

**解决**:课程⑩五指标。全部从现有遥测派生,**零新采集**:

| 指标 | 口径(实际落位) | 原料 |
|---|---|---|
| 任务完成率 | resolution_status='resolved_auto' / 轮(单轮口径;多轮 pass^k 视图等 task_state 任务分组后置) | session_metrics FILTER 聚合 |
| 参数补全准确率 | 澄清轮 → 同会话 30 分钟内下一轮不再澄清(与 labeling.backfill_clarify_outcome 资格窗同口径);无后继不计分母 | session_metrics lead() 窗口函数 |
| Tool 错误轮占比(v1 代理) | tool_errors_count≥1 的轮占比;**真失败率(tool_errors/调用)待 tool_calls_count 落库列**(随 run_agent 接线小票) | session_metrics |
| 单轮 Token | AVG(total_tokens)(session_metrics.total_tokens 即当轮 llm_call_logs 聚合产物,同源;cost 维度随真失败率票补) | session_metrics |
| 切换准确率(代理,v1) | duplicate_bypass 轮占比(最强重复信号,已落库);**同 intent 重复 + 纠正词表待标注攒批后与真值同批实现**(spec 收窄,as-built 裁决) | session_metrics.turn_path |

- 呈现:`apps/merchant-admin/src/pages/ai-usage/` 「多轮任务健康度」五卡节;网关 summary `taskHealth` 键(含分子分母绝对数,比率可自洽验证);口径 SQL 有 delta 单测。
- 节奏(D6):看板先行,硬闸阈值等 ~2 周基线再定——"管道盲闸吞失败"前科纪律。

### 4.5 P2-1 · 步级 journal(第二缺口)—— ✅ 已落地(2026-10-24)

**解决**:课程⑧;修"执行中崩溃整体降级道歉 + 降级桩空 task_plan 覆写在途计划"(`run_agent.py` 崩溃臂)。

- **新表** `task_step_journal`(0028 迁移,幂等守卫沿 0027 先例;append-only 无 update):`id, thread_id, job_id, step_index, status(completed|failed), result_digest, created_at`。状态词汇与子任务本词汇一致(不做 ok 翻译)。
- **写点**:executor_node 对进出 task_plan 做 **diff** —— 单缝覆盖全部 return 路径,只记状态变化行,completed 步带结果 sha256 指纹(16 位,审计留痕);旁路自吞 print,绝不阻断执行。
- **恢复**(D5):run_agent 轮入口 `detect_crash_tail` —— 同会话最新一轮 session_metrics 落崩溃态(graph_error_degraded / llm_circuit_breaker)∧ 该 job 有步级行 → 非 System 轮也载回 task_memory 在途计划,`rebuild_plan_from_journal` 按 journal 真值修补(completed 保留/failed 显式标 failed 由执行器重试),planner **Journal-Resume** 保留计划续跑(门禁:System 轮不抢/当前步挂审批不抢)。「超 1 轮未续」由构造自然成立:任何更新一轮都让 latest 不再是那个崩溃 job。interrupted(S2c)部分态自带计划、llm_quota 需人工干预,均不入恢复面。
- **code-review as-built 裁决(2026-10-24)**:①currentStepIndex = **首个未完成步**(并行分支下 failed 先于 completed 共存时,取 max(completed)+1 会把失败步跳过);②detect 排序契约 = (step_index, created_at) 后写 last-wins,latest 轮以 id 作同秒 tiebreak;③已知窗口:validator 在 executor 节点返回之后把 completed 降级 failed 的转变不落 journal(v1 接受,后续票把 diff 上移 settle 层)。
- **崩溃臂计划保真**:settle 落库策略 `plan_to_persist_on_crash` —— 降级桩的空 task_plan 严禁覆写 task_memory 在途计划(恢复面依赖它存续);此前崩溃=计划蒸发是恢复面无从谈起的根因。
- **正交性**:PendingApproval 计划级暂停不产生 journal 行(步未完成),两套恢复互不越界;journal 任何异常不阻断主流程。

### 4.6 P2-2 · KV-cache 前缀稳定纪律 —— ✅ 已落地(2026-10-24,审计清单形态)

**事实**:全链路无缓存命中字段(`llm_call_logs` 仅 tokens_in/out+cost+latency)。

- **本轮交付**:①快照测试钉死 context_builder 两条可缓存性性质——**预算内 append-only**(上一轮装配产物必须是本轮严格前缀)+ **确定性**(同输入同产物,无时钟/随机注入);②可缓存性审计清单(下)。
- **审计结论(2026-10-24)**:
  - ✅ 历史块本身:预算内严格 append-only,轮行格式稳定(`[T{n} ts] Role: "..."`),摘要段截 600 防膨胀 —— 块内性质合格;
  - ⚠️ **任务层段(P0-1)置于块首且逐轮演进**:与 KV-cache 前缀稳定相抵。裁决:保持前置 —— 会话内 provider prefix cache 本就逐轮失效,命中主要吃 system/tools 段;任务层前置是提示词注意力效能选择,重排记观察池(触发器:provider 缓存计费成为成本大头);
  - ⚠️ planner 深规划 prompt 的 RAG 注入逐轮变化且位于历史块之前:易变段居中会截断后续 append 段的命中;重排(易变段后置)涉及提示词语义,记后续票(与网关缓存字段上报同批);
  - ❌ 命中率监控:需网关上报 cached tokens + `llm_call_logs` 加列,记后续票(Manus:命中率是比 Token Budget 更硬的成本指标)。
- **后续票捆绑建议**:tool_calls_count 落库列(P1-2 真失败率分母)+ cached_tokens 上报与加列 + RAG 段重排,三件都是"网关↔引擎遥测面"工程,一批做掉。

---

## 5. 票表

| 票 | 内容 | 依赖 | 验收 |
|---|---|---|---|
| **P0-1** ✅(2026-10-24) | task_state 小节 + retire_and_set + context 任务层序列化 | — | `test_task_state.py`(29 断言级:退休/白名单观察/缺省兜底/截帽/预算管控)+ `test_context_builder.py` 任务层段断言;run_agent 收口链路回归绿 |
| **P0-2** ✅(2026-10-24) | 回灌 shadow 集 + promote 命令 | — | `test_badcase_shadow.py`(端到端:起草→promote→硬闸套件落例→converted);夜评 `sh01_shadow集` 报告例 advisory 不出闸 |
| **P1-1** ✅(2026-10-24) | 边界判定器(boundary 字段 + modify 保留 + 低置信澄清) | P0-1 | parse/漂移/纯谓词/planner 门禁 17 例全绿;实弹首跑 26/30;意图 95 闸/data 42/42/t1t2 25/25 零涉及;夜评闸 AI_BOUNDARY_GATE=off 攒基线 |
| **P1-2** ✅(2026-10-24) | 四指标 + 切换代理 d-ops 看板 | — | 网关 delta 单测 + 页面 5 例;口径自洽断言;无新采集 |
| **P2-1** ✅(2026-10-24) | 步级 journal + 崩溃恢复载回 | — | 纯函数/PG 集成/planner 门禁 19 例全绿;0028 迁移幂等守卫;崩溃臂计划保真 |
| **P2-2** ✅(2026-10-24) | KV-cache 前缀纪律 + 装配快照测试 | — | append-only 前缀稳定性+确定性两性质钉死;审计清单入档(任务层前置/RAG 居中两处相抵已记录裁决) |

P0 批次落地文件(P0-1:`memory/task_state.py`、`memory/context_builder.py`、`config.py` 热键;P0-2:`badcase/shadow.py`、`badcase/cli.py`(shadow/promote)、`badcase/digest.py`(6h 挂钩)、`eval/promptfoo.shadow.yaml`、`eval/testCases/shadow/pending.json`、夜评报告例、`package.json` `test:prompt:shadow`)。

> **⚠️ run_agent 三缝接线暂缓提交(2026-10-24)**:run_agent.py 被并行会话(memory-sota 升级批,0027_profile_slots)共写 —— 其 `thread_id 透传`(op 裁决)长泳道 hunk 依赖同批未提交的 `long_memory.py` 签名,此刻提交 run_agent 会把 HEAD 落成运行时即炸态。按「并行写入不混提交」纪律,任务态接线(载入 prev_task_state/装配 task_state_line/收口 advance+落库)留在工作区,作为并行批落地后的后续小票单独提交;`test_settle_turn_seam` 3 例红同为并行批桩签名未同步所致,非本批引入。

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
