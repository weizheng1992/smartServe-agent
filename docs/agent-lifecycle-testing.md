# Agent 全生命周期迭代测试与金丝雀发布规划指南 (Agent Lifecycle Testing & Canary Deployment)

本指南旨在为本智能客服平台（smartServe）提供一套工业级、闭环的 **DevOps + LLMOps 持续集成与发布保障体系**。由于大模型 Agent 具有随机性、提示词敏感性与工具链状态漂移等特征，Agent 的上线迭代必须遵循严格的、数据驱动的渐进式发布流程。

---

## 🗺️ 架构全局纵览 (Overview)

```
[ 本地/CI 迭代开发 ] ➔ [ 1. 离线黄金集回归 (Promptfoo + Playwright) ]
                                      │ (100% 绿灯通过)
                                      ▼
                       [ 2. 线上 Shadow 暗网双跑 ] ➔ 对比 Latency/Cost/Intent
                                      │ (平稳运行 1-3 天)
                                      ▼
                       [ 3. 金丝雀渐进式灰度 ] ➔ 先 Puma ➔ 再 Nike/Adidas 按比例灰度
                                      │ (观察 session_metrics)
                                      ▼
                       [ 4. 生产观测 (Langsmith APM) ] ➔ 收集用户真实提问
                                      │
                                      ▼
                       [ 5. Bad-Case 反馈与自愈自进化 ] ➔ 追加进 E2E 黄金集
```

---

## 🛑 第一阶段：离线黄金回归测试 (Offline Regression & Golden Dataset)

在任何 Agent 提示词或工具链代码合并进 `main` 主干分支前，必须通过 **双层黄金测试集（Golden Dataset）**，证明其决策与对话质量无退化。

### 1. 语义与意图分类回归 (Promptfoo)
我们使用内置的 **Promptfoo** 作为大模型评测引擎（配置文件位于 `eval/promptfooconfig.yaml`）。
*   **评测指标**：
    *   **Triage F1 Score**：测试分类意图的精准度，确保不会将 `order_status` 与 `refund` 混淆。
    *   **Answer Quality Score (LLM-as-a-Judge)**：采用高级模型（如 Opus/Sonnet）对 Agent 总结输出（Finish Node）进行打分。
*   **执行指令**：
    ```bash
    bun run test:prompt
    ```
*   **硬性红线**：意图匹配率必须维持在 **100%**，回答语义均分不低于 **4.5 / 5.0** 分。

### 2. 物理与安全性回归 (Playwright E2E)
使用 Playwright 真机模拟用户真实的多轮交互，测试工具链的完整性与安全性防线（测试文件位于 `apps/web/e2e/`）。
*   **验证要点**：
    *   **安全拦截（Anti-IDOR）**：验证用户只能查到或修改属于自己 `userId` 归属下的订单。
    *   **审批拦截（HITL）**：验证大额退款正确被系统挂起（Status: pending）并生成审批单。
    *   **熔断器（Circuit Breaker）**：验证自旋熔断阈值（10 步/3 次错误）生效。
*   **执行指令**：
    ```bash
    bun run test:e2e
    ```

---

## 🌐 第二阶段：暗网双跑模式 (Shadow Mode / Parallel Run)

真实生产环境的用户输入具有无限可能性，因此在完全切流前，必须进行 **Shadow Mode（暗网双跑）**，验证新 Agent 在海量生产请求下的并发吞吐与稳定性。

### 1. 流量分发架构
当 Next.js API 端点（`/api/chat`）收到用户提问时，同时并发启动老 Agent 与新 Agent：
```typescript
// apps/web/app/api/chat/route.ts 伪代码技术实现
export async function POST(req: NextRequest) {
  const { threadId, userId, message } = await req.json();

  // 1. 生产环境老 Agent (同步阻塞，直接决定用户感知到的输出)
  const productionPromise = runStableAgent(threadId, userId, message);

  // 2. 灰度新 Agent (暗网双跑，异步非阻塞，隐藏其返回)
  if (isShadowModeEnabled) {
    runShadowAgent(threadId, userId, message, `shadow_${Date.now()}`)
      .then(async (shadowResult) => {
        // 静默记录 shadow 的决策流、耗时、Token 到 eval_results 进行对比分析
        await logShadowMetrics(threadId, shadowResult);
      })
      .catch(err => console.error("[Shadow Agent Error]:", err));
  }

  const result = await productionPromise;
  return NextResponse.json(result);
}
```

### 2. 对比审计指标 (Shadow Auditing Metrics)
*   **耗时（Latency）**：对比新老 Agent 全图决策平均耗时，验证其是否发生明显卡顿。
*   **财务成本（Cost）**：由于提示词改变、RAG 数量微调，必须在 APM 中对比两者的 Token 消耗量。
*   **工具调起差异率**：审计新 Agent 规划的 Tools 与老 Agent 调用工具的重合度，防止误调无关高危接口。

---

## 🚦 第三阶段：金丝雀渐进式灰度发布 (Canary & Ring Deployment)

当 Shadow 模式下连续 48 小时指标正常，开始通过渐进灰度将新 Agent 真实投产。

### 1. 按租户商户灰度 (Ring 1)
智能客服平台为多商户（Nike、Adidas、Puma、主站）提供多租户隔离服务。
*   **策略**：选择一两家咨询体量小、业务容错度高、合作紧密的种子商户（例如 Puma）作为灰度第一环（Ring 1）。
*   **实施**：通过修改配置库中 Puma 商户的 `is_active_new_agent` 参数，Puma 会话自动由新 Agent 接管，其他主站商户保持不变。

### 2. 按流量比例灰度 (Ring 2)
在第一环运行平稳后，针对 Nike / Adidas 等大体量商户开启流量灰度比例划分。
*   **金丝雀发布梯度（Canary Gradients）**：
    $$5\% \longrightarrow 10\% \longrightarrow 30\% \longrightarrow 50\% \longrightarrow 100\%$$
*   **指标观察哨（Drizzle `session_metrics` 实时 BI 看板）**：
    *   **Autopilot Success Ratio（自主解决率）**：如果自主解决率突降，证明新 Agent 的提示词可能导致工具无法合理匹配。
    *   **Resolution Ratio（人工核签拦截比）**：若 Pending 比例超限，说明新 Agent 的退款金额格式判断或敏感度变高。
    *   **Circuit Breaker Fuses（硬熔断次数）**：查看是否频繁触发了 10步/3错 自旋物理断路。

---

## 📊 第四阶段：生产环境深度可观测性 (Production Observability)

Agent 发布完成后，必须进行端到端的**分布式链路追踪（Distributed Tracing）**，用真实数据进行系统性能度量。

1.  **链路追踪（Trace View）**：
    使用已集成的 **Langfuse / LangSmith APM**。通过 SDK 记录并展现每一次对话中，Triage Node 意图识别、Planner Node 任务规划、Executor Node 的 Tool 调用参数以及 Validator Node 的数据核验状态。
2.  **财务审计（Billing Analytics）**：
    监控租户端 `session_metrics` 表中的 `calculated_cost_usd` 字段，发现异常超额消耗时及时进行多租户 TPM/RPM 的 Redis 滑动窗口动态限流。

---

## 🔄 第五阶段：Bad-Case 自动收集与自愈自进化 (Self-Healing Loop)

大模型 Agent 系统持续进化的关键，在于将线上的失败（Bad-cases）无缝转为下一次迭代测试的燃料。

1.  **一键标差（User Feedback Webhook）**：
    当买家在界面点击“踩（Dislike）”、申请转人工，或者客服主管在 Admin 后台对 Agent 的回答进行“删除偏好事实”或“驳回退款”操作时，自动通过 APM SDK 标注该 Trace 的 `score = 0.0`。
2.  **提取线上坏例（Badcase Extraction）**：
    后台每周定时拉取 `score = 0.0` 或触发了 `Circuit Breaker`（硬熔断降级）的生产会话。
3.  **自动补签回归测试（Auto-Seeding E2E Cases）**：
    清洗这些会话上下文，过滤掉 PII 隐私信息（地址、姓名等），将其转换为标准的 Playwright 单元测试用例或 Promptfoo 回归测试集：
    ```yaml
    # 新加入 eval/testCases/security.json 的自愈回归 Case 示意
    - vars:
        query: "刚才我们讨论过尺码，现在告诉我为什么我的 Nike 订单被拦截了？"
      assert:
        - type: select-tool
          value: "getOrderStatus"
        - type: is-not-hallucinated
    ```
4.  **以此用例在 CI/CD 中修复、回归，直至完全通过。** 这种自愈测试环能够帮助 smartServe 持续进化，形成一套坚不可摧、银行级稳健的 AGI 生产客服系统！
