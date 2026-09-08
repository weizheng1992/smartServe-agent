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
                       │        LangGraph 智能多模态状态机 (services/engine-py)       │
                       │                                                             │
                       │  1. [Triage 多模态视觉感知首层 (`vision/analyzer.py`)]      │
                       │     ├─ 视觉大模型精判 + 启发式规则降级兜底(双通道容灾)      │
                       │     ├─ 快递面单/包装条形码 OCR 实体提取 (`ORD-XXXXX`, `SFXXX`)│
                       │     ├─ 商品破损/瑕疵智能评级 (`negligible`/`minor`/`severe`) │
                       │     ├─ PII 隐私数据脱敏过滤器 (手机/身份证/银行卡号物理掩码) │
                       │     └─ 模型级超时可配(默认 30s)+ 入图限额治理(≤3 图/条)    │
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

## 2. 多模态视觉感知流水线 (`vision/analyzer.py`)

- **源码路径**: `services/engine-py/src/engine_py/vision/analyzer.py`（2026-09 移植自 TS `visionAnalyzerService.ts`，原 TS 后端已退役）
- **核心职能**: 在用户发送图片或图文混合消息时，优先于文本分流执行视觉感知。
- **模型接入**: `llm/chat.py` 的 `get_vision_model()` 统一工厂（`AI_VISION_MODEL`，默认 `glm-4.6v`；结构化输出走 `with_structured_output(method="function_calling")` —— 视觉模型不支持 `response_format`）。

### 2.1 双轨感知与可配超时降级

为避免多模态大模型在高延迟、离线测试或模型限流时阻塞主聊天链路，视觉调用挂在**模型级 `request_timeout`（`AI_VISION_TIMEOUT_SECONDS` 可调，默认 30s——E2E 实测 GLM-4.6V 真实请求可超 15s）+ `max_retries=0`** 上，失败即刻降级：

```python
# 失败即降级 —— 启发式正则兜底(纯函数),绝不炸主链路
try:
    parsed = await structured.ainvoke([HumanMessage(content=content)])
except Exception:
    return _fallback_result(order_id, tracking_no, user_prompt, primary_url)
```

TS 时代的 1500ms `Promise.race` 硬超时已废弃（真实多模态请求 1.5s 内几乎必超时，等于永久降级）；本地图（`/api/uploads/` 引用）经 **base64 Data URL 直传**（bigmodel 拉不到 localhost，亦免本地文件服务出网暴露）。

### 2.2 入图归一化与限额治理

TS 时代入图零防护；Python 侧在 `run_agent` 构建初始状态时经 `normalize_image_urls` 统一收口（剔除非字符串/空白项、去重保序、截断至 **≤3 图/条**）。网关上传端点另钳制单张 ≤10MB，两侧限额对齐；垃圾输入最多变少图，绝不抛错 —— 治理目标是"少看图"，不是"失败会话"。

### 2.3 OCR 实体提取与标准化

- **订单号识别**: 自动提取 `ORD-[A-Za-z0-9]+` 模式，并自动归一化为大写字符串（如 `ORD-77889`）。
- **快递单号识别**: 自动匹配主流承运商单号规则（如顺丰 `SF1234567890`、圆通 `YTO...`、中通 `ZTO...`、邮政 `EMS...`、通用 `TRACK...`）。
- **提取实体自动注入上下文**: 提取出的订单号直接传递至后续 `triage` 意图分流与 `planner` 任务规划，实现“发一张面单截图即可秒级查单”。

### 2.4 PII 敏感隐私数据脱敏切面 (PII Redaction)

在面单图像 OCR 提取与文本摘要生成过程中，内置正则表达式安全切面，自动执行敏感信息脱敏：

- **手机号**: 掩码为 `138****5678` 格式。
- **身份证号**: 统一替换为 `[ID_CARD_REDACTED]`。
- **银行卡号**: 统一替换为 `[BANK_CARD_REDACTED]`。

### 2.5 商品破损瑕疵智能定责评级

根据多模态模型对用户上传商品实物图的视觉判定，输出 3 级定责评级及建议处置策略：

- **`negligible` (无明显瑕疵/完好)**: 建议正常走通用退换货流程。
- **`minor` (轻微划痕/外包装微损)**: 置信度较高时建议发放代金券或补偿小额退款。
- **`severe` (严重破损/碎裂/不可逆损坏)**: 触发秒级极速赔付，或由 `ApprovalPolicyEngine` 路由至人工客服审核。

---

## 3. 结构化富交互卡片协议与合成引擎

- **协议定义**: `packages/types/src/card.ts`（冻结的前端契约，TS 退役后保留）
- **合成引擎**: `services/engine-py/src/engine_py/cards/card_synthesizer.py`

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

`finish` 节点在合成最终文本答复的同时调用 `CardSynthesizer.synthesize_cards({ taskPlan, damageAssessment, ... })`：

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

- **源码路径**: `services/gateway-py/src/gateway_py/routers/chat.py`（FastAPI 网关；2026-09 自 TS 路由 `apps/web/app/api/chat/upload/route.ts` 移植）

### 5.1 安全防线

1. **MIME Type 白名单拦截**: 仅允许 `image/jpeg`、`image/png`、`image/webp`、`image/gif`，硬拦截非图片文件与潜在恶意可执行脚本。
2. **物理大小边界**: 流式读取实测累计，严格限制最大 10MB，超出立即删除半成品文件并返回 HTTP 413。
3. **安全落盘与 URL 派发**: 持久化落盘至 `public/uploads/`（`UPLOADS_DIR` 可覆写），生成带随机 UUID 的唯一文件名，避免文件名覆盖与目录遍历攻击；经网关 StaticFiles 以 `/api/uploads/` 回读（搭 Vite `/api` 代理便车，web 与引擎同源可达）。
4. **引用持久化**: 用户消息的 `imageUrls` 引用以 JSONB 落 `messages.image_urls`（Alembic 0006），会话刷新按引用还原缩略图与卡片。**网关是用户行的唯一写入方**（dispatch/SPI 入口；引擎 `run_agent`/Temporal activity 零写用户行——双插会使时间线出现一行带图一行不带的重复 user 气泡,multimodal 005 治理）。
