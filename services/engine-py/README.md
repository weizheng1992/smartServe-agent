# engine-py — Agent 决策引擎 Python 重写(Phase 1b)

`packages/engine`(TS,约 10.6k LOC)的参考式重写。TS 代码是行为规格说明书,
三套 promptfoo 基线(`eval/baselines/`)是等价性验收门禁。

## 与 TS 侧的互操作契约

- **事件总线线格式**(必须与 `packages/tools/src/eventBus.ts` 逐字节兼容):
  - stream key:`job:events:{jobId}`,seq key:`job:seq:{jobId}`
  - entry fields:`seq`(十进制字符串)、`type`、`data`(JSON 字符串)
  - `XADD MAXLEN ~ 200`,两个 key 均带 600s TTL
  - `result` 携带 cards 时先发 `cards` 再发 `result`(两个独立 seq)
- **SSE 消费方**(`apps/server` ChatService.pipeSSEFromStream)已在 Phase 1a
  直连该流,engine-py 发布的事件对现有 TS 网关零改动可见。
- **DB**:Drizzle 仍是 schema 唯一所有者;本包的 SQLAlchemy 模型是从
  `packages/db/src/schema.ts` 派生的投影(Phase 2 落地,先只读)。

## 结构(与 TS engine 模块一一对应)

| Python | TS 参考 |
|---|---|
| `graph/build_graph.py` | `graph/buildGraph.ts`(六节点 DAG + 条件边) |
| `graph/nodes/triage.py` | `nodes/triage/`(intentTriageEngine 等 7 文件) |
| `graph/nodes/planner.py` | `nodes/planner.node.ts`(470 LOC) |
| `graph/nodes/executor.py` | `nodes/stepExecutionEngine.ts` + `executorFastPath.ts` |
| `graph/nodes/validator.py` | `nodes/validator.node.ts` |
| `graph/nodes/finish.py` | `nodes/finish.node.ts` + `cards/cardSynthesizer.ts` |
| `event_bus.py` | `tools/src/eventBus.ts`(镜像发布) |
| `llm/chat.py` | `llm/callLLMWithRetry.ts`(统一入口 + 重试/熔断) |

`TODO(Phase 1b)` 标记 = 尚未移植的 TS 行为,均附 TS 源文件引用。

## 尚未移植的 runAgent 隐性行为(移植清单)

见 `run_agent.py` 顶部注释:欢迎语快路径、租户配置热加载、三路记忆/RAG
并取、session_metrics 埋点、LangSmith 回传。

## 影子双跑

```bash
# 1. 安装(uv):uv sync --extra worker
# 2. 把 DATABASE_URL 指向影子库(生产副本/容器),避免回放写库污染
# 3. Python 侧回放:
python -m engine_py.shadow.replay --limit 50 --out py_results.jsonl
# 4. TS 侧等价回放(产出同格式 ts_results.jsonl,eval/ 批次补齐)
# 5. 对比:
python -m engine_py.shadow.diff --ts ts_results.jsonl --py py_results.jsonl
```

门禁 = promptfoo 三套基线无回归(`bun run test:prompt:compare`)+
影子差异清零(intentMatchRate / toolMatchRate = 100%,错误清零)。

## Temporal Worker

```bash
# 影子期独立队列 agent-tasks-py(与 TS 的 agent-tasks 物理隔离)
python -m engine_py.temporal.worker
```
