# 📷 多模态视觉感知、智能破损定责与富交互卡片系统架构

本文档深度阐述 smartServe-agent 中的**多模态视觉感知流水线**、**快递面单 OCR 实体提取**、**商品破损智能定责评级**以及**结构化 JSON Blocks 富交互卡片协议与渲染中台**。

---

## 1. 架构总览 (System Architecture)

```
                       ┌─────────────────────────────────────────────────────────────┐
                       │                     用户前端 (apps/web)                       │
                       │   - [📎 图片上传/多图预览] ──(POST)──> /api/chat/upload      │
                       │   - [RichCardRenderer 统一渲染容器]                           │
                       │     ├─ 📦 订单/商品卡片 (`OrderCard`)                         │
                       │     ├─ 🚚 实时物流轨迹时间轴 (`TrackingTimeline`)            │
                       │     ├─ 🧾 退款核签与赔付凭证卡 (`RefundConfirmationCard`)     │
                       │     ├─ 📷 AI 视觉成色与破损定责卡 (`DamageAssessmentCard`)   │
                       │     └─ 💊 快捷回复与操作胶囊 (`QuickReplies`)                │
                       └──────────────────────────────┬──────────────────────────────┘
                                                      │ POST /api/chat { message, imageUrls }
                                                      ▼
                       ┌─────────────────────────────────────────────────────────────┐
                       │           LangGraph 智能多模态状态机 (packages/engine)       │
                       │                                                             │
                       │  1. [Triage 多模态视觉感知首层 (`VisionAnalyzerService`)]     │
                       │     ├─ 视觉大模型 (Vision LLM) 与启发式规则双通道并发精判     │
                       │     ├─ 快递面单/包装条形码 OCR 实体提取 (`ORD-XXXXX`, `SFXXX`)│
                       │     ├─ 商品破损/瑕疵智能评级 (`negligible`/`minor`/`severe`) │
                       │     ├─ PII 隐私数据脱敏过滤器 (手机/身份证/银行卡号物理掩码) │
                       │     └─ 1500ms Promise.race 超时快速降级容灾熔断               │
                       │                                                             │
                       │  2. [任务规划与执行引擎 (`StepExecutionEngine`)]            │
                       │     └─ 承接 OCR 提取实体，快速组装工具链入参                  │
                       │                                                             │
                       │  3. [富交互卡片自动合成引擎 (`CardSynthesizer`)]             │
                       │     └─ 提炼工具执行结果与定责分析，输出标准 JSON Blocks      │
                       │                                                             │
                       │  4. [SSE 结构化管道与持久化]                                │
                       │     └─ 通过 EventSource 将 cards 挂载至 StreamResultEvent   │
                       └─────────────────────────────────────────────────────────────┘
```

---

## 2. 多模态视觉感知流水线 (`VisionAnalyzerService`)

- **源码路径**: `packages/engine/src/vision/visionAnalyzerService.ts`
- **核心职能**: 在用户发送图片或图文混合消息时，优先于文本分流执行视觉感知。

### 2.1 双轨感知与 1500ms 超时熔断降级

为避免多模态大模型在高延迟、离线测试或模型限流时阻塞主聊天链路，系统设计了 **1500ms 竞争超时降级机制**：

```typescript
const timeoutPromise = new Promise<VisionAnalysisResult>((resolve) => {
  setTimeout(() => {
    resolve({
      detectedEntities: fallbackEntities,
      damageAssessment: fallbackDamage,
      summary: "视觉分析服务响应超时，已平滑降级至本地规则提取",
    });
  }, 1500);
});

return await Promise.race([visionPromise, timeoutPromise]);
```

### 2.2 OCR 实体提取与标准化

- **订单号识别**: 自动提取 `ORD-[A-Za-z0-9]+` 模式，并自动归一化为大写字符串（如 `ORD-77889`）。
- **快递单号识别**: 自动匹配主流承运商单号规则（如顺丰 `SF1234567890`、圆通 `YTO...`、中通 `ZTO...`、邮政 `EMS...`、通用 `TRACK...`）。
- **提取实体自动注入上下文**: 提取出的订单号直接传递至后续 `triage` 意图分流与 `planner` 任务规划，实现“发一张面单截图即可秒级查单”。

### 2.3 PII 敏感隐私数据脱敏切面 (PII Redaction)

在面单图像 OCR 提取与文本摘要生成过程中，内置正则表达式安全切面，自动执行敏感信息脱敏：

- **手机号**: 掩码为 `138****5678` 格式。
- **身份证号**: 统一替换为 `[ID_CARD_REDACTED]`。
- **银行卡号**: 统一替换为 `[BANK_CARD_REDACTED]`。

### 2.4 商品破损瑕疵智能定责评级

根据多模态模型对用户上传商品实物图的视觉判定，输出 3 级定责评级及建议处置策略：

- **`negligible` (无明显瑕疵/完好)**: 建议正常走通用退换货流程。
- **`minor` (轻微划痕/外包装微损)**: 置信度较高时建议发放代金券或补偿小额退款。
- **`severe` (严重破损/碎裂/不可逆损坏)**: 触发秒级极速赔付，或由 `ApprovalPolicyEngine` 路由至人工客服审核。

---

## 3. 结构化富交互卡片协议与合成引擎

- **协议定义**: `packages/types/src/card.ts`
- **合成引擎**: `packages/engine/src/cards/cardSynthesizer.ts`

### 3.1 核心卡片类型规范 (JSON Blocks Schema)

系统支持 5 种高保真交互卡片：

| 卡片类型 (`type`)     | 适用场景                   | 核心承载数据                                                                         |
| --------------------- | -------------------------- | ------------------------------------------------------------------------------------ |
| `order_card`          | 订单详情查询、订单列表展示 | 订单 ID、状态（已发货/派送中/已签收）、实付金额、币种、快捷 Action 按钮              |
| `tracking_timeline`   | 物流轨迹追踪               | 承运商名称、运单号、当前最新状态、节点时间轴数组 (`time`, `location`, `description`) |
| `refund_confirmation` | 退款成功/审批通过核签凭证  | 订单号、退款金额、退款状态、退回渠道（原路退回）、预估到账时效、审核提示             |
| `damage_assessment`   | AI 视觉定损评级            | 破损级别 (`negligible`/`minor`/`severe`)、综合诊断描述、置信度、处置建议             |
| `quick_replies`       | 动态快捷操作胶囊           | 交互胶囊列表（文本发送、订单查询、物流追踪、申请退款、唤起上传图片）                 |

### 3.2 动态卡片合成逻辑 (`CardSynthesizer`)

`finish.node.ts` 在合成最终文本答复的同时调用 `CardSynthesizer.synthesize({ taskPlan, intentResult, visionResult, message })`：

1. 若执行计划中包含 `getOrderStatus`，自动解析输出 payload 并构建 `OrderCard` 与 `TrackingTimeline`；
2. 若执行计划中包含 `processRefund`，自动解析退款金额与流水构建 `RefundConfirmationCard`；
3. 若存在多模态视觉定损分析，自动生成 `DamageAssessmentCard`；
4. 依据当前上下文动态附带 `QuickReplies` 快捷操作胶囊，实现连续闭环体验。

---

## 4. 前端组件库与零依赖渲染架构 (`packages/ui`)

- **组件路径**: `packages/ui/src/components/chat/cards/`
- **设计原则**: **零外部重量级图标库依赖**。全部图标基于 `packages/ui/src/components/icons.tsx` 原生封装可缩放 SVG 组件，保障极致打包体积与高保真深色模式质感。

### 4.1 组件家族

1. `OrderCard.tsx`: 包含商品金额高亮、状态徽标、物流编号复制与快捷按钮交互。
2. `TrackingTimeline.tsx`: 垂直时间轴，首个最新物流节点发光徽章与历史轨迹连续竖线。
3. `RefundConfirmationCard.tsx`: 绿色发光防伪徽标、退款流水核签详情与银行渠道说明。
4. `DamageAssessmentCard.tsx`: 根据破损级别展示黄/红/绿三色警示徽章与处置建议。
5. `QuickReplies.tsx`: 底部流式胶囊气泡，支持点击直接回填输入框或直接提交新会话。
6. `RichCardRenderer.tsx`: 卡片组统一渲染路由器，兼容批量卡片网格与自适应移动端布局。

---

## 5. 安全图片上传流水线 (`/api/chat/upload`)

- **源码路径**: `apps/web/app/api/chat/upload/route.ts`

### 5.1 安全防线

1. **MIME Type 白名单拦截**: 仅允许 `image/jpeg`、`image/png`、`image/webp`、`image/gif`，硬拦截非图片文件与潜在恶意可执行脚本。
2. **物理大小边界**: 严格限制最大 10MB，超出立即返回 HTTP 413。
3. **安全落盘与 URL 派发**: 自动持久化落盘至 `apps/web/public/uploads/`，生成带随机 UUID 的唯一文件名，避免文件名覆盖与目录遍历攻击。
