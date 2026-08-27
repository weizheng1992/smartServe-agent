# 📖 smartServe SaaS: 新商户接入与配置配置操作手册 (Merchant Onboarding Guide)

本手册详细介绍了如何在 **smartServe-agent (v2 Architecture)** 多租户智能客服与决策中台体系中接入一个全新的业务商户（如独立商城、第三方品牌旗舰店），并在 **Admin 控制平面（Port 3001）** 中进行可视化配置、实时会话监控、HITL 审批干预与业务调优。

---

## 目录

- [一、核心架构与多租户机制](#一核心架构与多租户机制)
- [二、新商户接入的三种方式](#二新商户接入的三种方式)
  - [方式 1：Admin 控制台可视化一键入驻 (推荐)](#方式-1admin-控制台可视化一键入驻-推荐)
  - [方式 2：数据库 SQL / 种子脚本动态注册 (Zero Hardcode)](#方式-2数据库-sql--种子脚本动态注册-zero-hardcode)
  - [方式 3：第三方独立商户系统 SPI 标准对接](#方式-3第三方独立商户系统-spi-标准对接)
- [三、在 Admin 3001 控制台中的全链路查看与管理](#三在-admin-3001-控制台中的全链路查看与管理)
- [四、内置模拟商户（Aurora 极光潮品）快速实战演练](#四内置模拟商户aurora-极光潮品快速实战演练)
- [五、商户专属业务技能 (SOP Skills) 的扩展、开发与使用教程](#五商户专属业务技能-sop-skills-的扩展开发与使用教程)
  - [5.1 Tool（原子工具）与 Skill（业务技能）的本质区别](#51-tool原子工具与-skill业务技能的本质区别)
  - [5.2 Skill 执行架构与生命周期管线](#52-skill-执行架构与生命周期管线)
  - [5.3 实战示例：添加电子发票开具 SOP 技能 (`OrderInvoiceSkill`)](#53-实战示例添加电子发票开具-sop-技能-orderinvoiceskill)
  - [5.4 商户端 SPI 接口对接与 HMAC 验签守卫](#54-商户端-spi-接口对接与-hmac-验签守卫)
  - [5.5 在 Admin 控制台与数据库中动态配置 Skill](#55-在-admin-控制台与数据库中动态配置-skill)
  - [5.6 在商户商城前端使用与验证](#56-在商户商城前端使用与验证)
  - [5.7 编写自动化测试验证](#57-编写自动化测试验证)
- [六、常见问题排查与 FAQ](#六常见问题排查与-faq)

---

## 一、核心架构与多租户机制

smartServe 采用**无代码硬编码（Zero Hardcode）**的多租户动态装配架构：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        SaaS 控制平面 (apps/admin:3001)                 │
│  [商户管理]     [会话 & 接管]     [审批中心]     [技能配置]     [RAG 知识库]│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ X-Tenant-Id: <businessId>
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      NestJS 微服务网关 (apps/server:3000)               │
│               /api/skills/config │ /api/tenants │ /spi/v1/*            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 动态装配
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     决策引擎 (packages/engine - LangGraph)             │
│  1. 租户隔离: 所有会话/订单/记忆严格绑定 businessId                      │
│  2. 双层画像: global(生理/事实) 与 tenant(品牌专属偏好) 隔离              │
│  3. 动态 SPI: 根据 tenant_configs.spi_config 路由至商户私有系统          │
│  4. 技能重载: 动态覆盖退款阈值 (refundLimit) 与 SOP 规则               │
└────────────────────────────────────────────────────────────────────────┘
```

- **`businessId`**：租户全局唯一字符串标识（纯小写字母与连字符，如 `aurora`, `nike`, `myshop`）。
- **物理与逻辑隔离**：数据库所有表（`threads`, `messages`, `orders`, `pending_approvals`, `long_memory_facts`）均强制附带 `business_id` 过滤。
- **动态 SPI 适配器**：支持本地数据库直连模式（`local_db`）与远程 HMAC 加密签名 Webhook 模式（`remote_spi`）。

---

## 二、新商户接入的三种方式

### 方式 1：Admin 控制台可视化一键入驻 (推荐)

无需编写代码或重启后端服务，直接在 Admin 控制台中配置：

1. **进入商户管理页**：
   - 访问 `http://localhost:3001/tenants`（左侧菜单栏 **商户租户管理**）。
2. **创建商户基本档案**：
   - 点击右上角 **「新增商户入驻」** 按钮。
   - **商户 ID (`businessId`)**：输入全局唯一代号，例如 `zara`、`anker` 或 `myshop`。
   - **商户名称**：例如 `ZARA 官方旗舰店`。
   - **所属行业 / 渠道**：如 `快时尚服饰` / `Web Widget + 微信小程序`。
   - **API Key & SPI Webhook URL**：填写该商户的后端服务根地址（如 `https://api.myshop.com/spi` 或本地联调 `http://localhost:3005`）。
   - **风控阈值 (退款)**：设置无需人工审核的最大退款上限（例如 `¥300`，超过此金额将触发 HITL 人工审批）。
   - 点击 **保存**。
3. **配置启用的业务技能 (Skills)**：
   - 进入 `http://localhost:3001/skills-tools`（**技能与工具市场**）。
   - 针对该商户启用对应的 SOP 技能（如 `skill_order_refund` 订单退款、`skill_order_address_modification` 改地址、`skill_product_inquiry` 商品查询）。
   - 可在右侧抽屉自定义该商户专属的 Prompt 提示词与单项技能限额。
4. **导入商户专属知识库 (RAG)**：
   - 进入 `http://localhost:3001/rag-studio`（**Contextual RAG 知识库**）。
   - 选择该商户，上传其退换货政策、保修条款、尺码指南等切片文档，系统将自动进行上下文增益（Contextual Summary）并打上该租户标签。

---

### 方式 2：数据库 SQL / 种子脚本动态注册 (Zero Hardcode)

对于批量接入或自动化 CI/CD 环境，可直接通过 SQL 向平台 PostgreSQL 物理表注入租户数据：

```sql
-- 1. 注册租户基本主体
INSERT INTO tenants (id, business_id, name, plan_tier, status)
VALUES (
  gen_random_uuid(),
  'myshop',
  'My Shop 官方精品店',
  'enterprise',
  'active'
)
ON CONFLICT (business_id) DO UPDATE SET
  name = EXCLUDED.name,
  status = EXCLUDED.status;

-- 2. 配置专属 System Prompt、SPI 远程路由与技能清单
INSERT INTO tenant_configs (
  id,
  business_id,
  system_prompt,
  welcome_message,
  status,
  version,
  spi_config,
  enabled_skills,
  skills_config
)
VALUES (
  gen_random_uuid(),
  'myshop',
  '你是 My Shop 官方尊享智能客服。热忱、高效解答用户关于发货时效、商品尺码及退换货诉求。',
  '您好！欢迎来到 My Shop 官方旗舰店，请问有什么可以帮您？',
  'published',
  1,
  '{
    "mode": "remote_spi",
    "spiBaseUrl": "http://localhost:3005",
    "apiSecret": "myshop_sec_key_9988",
    "timeoutMs": 5000
  }'::jsonb,
  '["skill_order_address_modification", "skill_order_refund", "skill_product_inquiry"]'::jsonb,
  '{
    "skill_order_refund": {
      "enabled": true,
      "approvalThresholdAmount": 300,
      "customPolicyPrompt": "仅支持签收后7天内的未拆封商品申请退款"
    }
  }'::jsonb
);
```

---

### 方式 3：第三方独立商户系统 SPI 标准对接

如果商户拥有自己的 ERP/OMS 独立订单系统，只需实现标准 **RESTful SPI 规范**，smartServe 决策引擎即可自动通过安全的 HMAC 签名协议进行远程调用：

#### 标准 SPI 接口列表

| HTTP 方法 | 端点路径                                   | 功能描述                                             |
| :-------- | :----------------------------------------- | :--------------------------------------------------- |
| `GET`     | `/spi/v1/orders/:orderId`                  | 查询指定订单的详情、物流、是否允许修改地址与退款状态 |
| `POST`    | `/spi/v1/orders/:orderId/shipping-address` | 申请修改订单收货地址（校验未发货状态）               |
| `POST`    | `/spi/v1/orders/:orderId/refund`           | 提交订单退款申请（支持退款金额、原因及幂等标识）     |
| `GET`     | `/spi/v1/products`                         | 查询商户商品库列表、SPU/SKU 规格参数与实时库存       |
| `GET`     | `/spi/v1/user`                             | 查询商户会员等级、历史默认地址列表与标签             |

#### SPI 安全认证协议与商户端环境变量 (.env)

- **签名头信息**：`X-Spi-Signature: sha256=<HMAC-SHA256(timestamp + "." + body, apiSecret)>`
- **防重放机制**：`X-Spi-Timestamp: <Unix Epoch 毫秒>`（超过 300 秒自动拒绝）
- **幂等防护**：`X-Idempotency-Key: <UUID>`

**在商户端 `apps/merchant/.env` 中配置对应密钥**：

```bash
# apps/merchant/.env
MERCHANT_ID=aurora                     # 商户全局唯一 ID
MERCHANT_API_SECRET=aurora_secret_key_8899  # 与平台 Admin/tenant_configs 中配置的 API Key 严格一致
PORT=3005                              # 商户端服务端口
```

---

## 三、在 Admin 3001 控制台中的全链路查看与管理

接入新商户后，启动控制台并在浏览器打开 `http://localhost:3001`：

### 1. 全局租户穿透切换 (Tenant Switcher)

- 在页面顶部 Header 中，点击 **租户选择器**。
- 可切换至 **`全平台多租户 (上帝视角)`** 查看全局大盘，或精确切换至指定商户（如 `aurora` 或新增的商户 ID）。
- 切换后，页面所有模块自动携带该商户作用域。

### 2. 各核心模块查看指南

- 💬 **会话管理 & 实时人工接管 (`/conversations`)**：
  - 实时查看该商户下所有客户与 AI 的对话流。
  - 点击会话可展开 **Deep Trace 抽屉**，查看 LLM 思考链（Thought Steps）、意图分类、命中的技能与工具参数。
  - 点击 **「接入实时人工会话」** 即可一键进入 Live Desk 模式接管对话，系统实时向客户端广播坐席名片并暂停 AI 自动回复。
- 🛡️ **人工审批工作台 (`/approvals`)**：
  - 当客户触发超过商户阈值的高额退款、发货后强行改地址等高危动作时，状态机将自动挂起为 `waiting` 状态。
  - 管理员在审批中心可查看完整的上下文 Timeline、原始 Payload，点击 **「通过」** 或 **「驳回」** 后，Transactional Outbox 机制会自动恢复执行并通知用户。
- 🧩 **技能与工具市场 (`/skills-tools`)**：
  - 查看该商户已启用的技能状态、生效的 SOP 门禁规则以及 SPI 外部端点连通性。
- 🧠 **双层画像与记忆 (`/personas`)**：
  - 检查客户画像物理隔离效果：区分客户全局基础生理特征（`global`，如身高鞋码）与商户私域偏好（`tenant`，如在该商城的专属优惠与风格偏好）。
- 📊 **SaaS 账单与遥测大盘 (`/billing` & `/system-logs`)**：
  - 监控该商户的 API 调用量、Token 算力消耗、财务费用（USD）、平均决策延迟与 Autopilot 自动解决率。

---

## 四、内置模拟商户（Aurora 极光潮品）快速实战演练

代码库中已内置了高度拟真的独立商户系统 `apps/merchant`（极光潮品官方商城），你可以按照以下步骤进行端到端闭环验证：

### 1. 快速初始化数据

```bash
# 初始化商户专属物理数据库表与商品/订单数据
bun apps/merchant/src/db/seed.ts

# 在平台 SaaS 表中动态注册 aurora 商户及其 SPI 配置
bun packages/db/src/seedThirdPartyMerchant.ts
```

### 2. 启动全套服务

```bash
# 启动 NestJS API 网关 (Port 3000)
bun run dev:server

# 启动模拟商城前台 (Port 3005)
bun run dev:merchant

# 启动 SaaS Admin 控制台 (Port 3001)
bun run dev:admin
```

### 3. 场景实测与验证

1. **打开模拟商城**：浏览器访问 `http://localhost:3005`，点击右下角智能客服。
2. **测试订单查询**：输入 `“帮我查一下订单 AURORA-ORD-2026-9081 的物流到哪了”`，AI 将通过 SPI 实时拉取订单状态并呈现多模态富卡片。
3. **测试风控审批拦截**：输入 `“我想把这个订单退款”`（金额 ¥499 超过预设的 ¥300 上限），AI 会回复已为您提交人工审核。
4. **在 Admin 3001 审批**：打开 `http://localhost:3001/approvals`，找到该笔退款申请并点击 **通过**，回到商城前台即可看到退款成功并恢复后续流程。

---

## 五、商户专属业务技能 (SOP Skills) 的扩展、开发与使用教程

在 smartServe 平台中，**Skill（业务技能）** 是将业务规则、参数校验、风控门禁、第三方 SPI 接口调用以及多模态卡片渲染完整闭环的高阶抽象层。

---

### 5.1 Tool（原子工具）与 Skill（业务技能）的本质区别

> **一句话总结**：**Tool 是“手和脚”（负责单纯的技术操作），Skill 是“业务 SOP 大脑”（负责端到端的业务流程控制与风控合规）。**

| 核心维度       | 🛠️ 原子工具 (Tool)                                   | 🧩 业务技能 (Skill / SOP)                                  |
| :------------- | :--------------------------------------------------- | :--------------------------------------------------------- |
| **功能定位**   | **纯技术操作**（只负责发起 HTTP 请求或查询数据库表） | **面向业务闭环的标准作业程序**（SOP 状态机与业务生命周期） |
| **业务规则**   | ❌ **无**（给什么参数就执行什么，不校验业务合理性）  | ✅ **内聚全套 SOP**（发货状态拦截、时效校验、合规判断）    |
| **风控与审批** | ❌ **无**（无法自主决定是否需要人工审核）            | ✅ **HITL 门禁**（动态根据商户免审阈值自动挂起审批）       |
| **参数缺失**   | ❌ 报错崩溃或由 LLM 盲目猜测                         | ✅ **自愈追问**（精准拦截缺失槽位，引导用户补充）          |
| **多租户策略** | ❌ 静态固定                                          | ✅ **动态重载**（不同商户可自由重载免审额度与提示词）      |
| **输出形式**   | 原始 JSON / 字符串数据                               | 业务友好话术 + **多模态交互富卡片 (Rich Cards)**           |

#### 为什么不能只有 Tool？

1. **资金防损**：若仅暴露 `executeOrderAction` 工具，用户说“帮我退款 10 万元”，LLM 将直接调用接口产生严重资损；而 Skill 会根据商户动态配置进行风控阈值拦截与人工审批挂起；
2. **状态防越权**：若订单状态为已发货（`SHIPPED`），Skill 会在调用工具前直接拦截改地址请求；
3. **多租户隔离**：不同商户的免审额度和政策各不相同（A 商户 100 元免审，B 商户 500 元免审），只有 Skill 能结合 `tenant_configs` 动态做出差异化决策。

---

### 5.2 Skill 执行架构与生命周期管线

```text
[用户输入: "帮我把订单 AURORA-ORD-2026-9081 开发票"]
                        │
                        ▼
            【IntentTriageEngine 意图分流】
                        │ (识别 intent: 'APPLY_INVOICE')
                        ▼
            【SkillRegistry 技能注册中心】
                        │ (匹配到 OrderInvoiceSkill)
                        ▼
      ┌──────────────────────────────────────────────────┐
      │          🧩 OrderInvoiceSkill (BaseSkill)         │
      │                                                  │
      │  1. canHandle: 命中 APPLY_INVOICE 意图            │
      │  2. 槽位前置校验: 检查 orderId 是否提供           │
      │  3. 读取商户策略: 获取当前商户开票免审阈值        │
      │  4. 风控判断: 是否超过免审上限？                   │
      │     ├─ 超过: 挂起 require_approval 写入 Outbox    │
      │     └─ 未超: 调用底层 SPI 执行开票                │
      │  5. 组装发票确认富卡片 (RichCardBlock)            │
      └────────────────────────┬─────────────────────────┘
                               │
                               ▼
      ┌──────────────────────────────────────────────────┐
      │         🛠️ ThirdPartySpiTool (原子工具层)         │
      │  - 自动计算 HMAC-SHA256 签名与时间戳              │
      │  - POST http://localhost:3005/spi/v1/orders/action│
      └──────────────────────────────────────────────────┘
```

---

### 5.3 实战示例：添加电子发票开具 SOP 技能 (`OrderInvoiceSkill`)

下面以一个真实高频业务——**「电子发票申请与开具」** 为例，完整演示如何新增并接入自定义 Skill：

#### 步骤 1：在决策引擎中创建 Skill 类

新建 `packages/engine/src/skills/orderInvoiceSkill.ts`，继承 `BaseSkill`：

```typescript
// packages/engine/src/skills/orderInvoiceSkill.ts
import crypto from "node:crypto";
import { BaseSkill } from "./baseSkill";
import type {
  SkillMetadata,
  SkillExecutionContext,
  SkillExecutionResult,
  RichCardBlock,
} from "types";

export class OrderInvoiceSkill extends BaseSkill {
  // 1. 定义技能元数据与触发规则
  public metadata: SkillMetadata = {
    id: "skill_order_invoice",
    name: "电子发票极速开具 SOP",
    description:
      "核验订单支付状态与税号信息，自动开具电子发票并支持超额人工审核",
    category: "after_sale",
    triggerIntents: ["APPLY_INVOICE", "order_invoice", "request_invoice"],
    requiredTools: ["getOrderDetail", "executeOrderAction"],
    requiresApproval: true,
    approvalThresholdAmount: 2000, // 默认 2000 元以上开票需人工财务审批
    version: "1.0.0",
  };

  // 2. 意图与前置承接判定
  public canHandle(context: SkillExecutionContext): boolean {
    const intent =
      (context.slots?.activeIntent as string) ||
      (context.extra?.intent as string) ||
      "";
    if (this.metadata.triggerIntents.includes(intent)) return true;
    return /开发票|电子发票|开票|补开发票/i.test(context.input || "");
  }

  // 3. 核心业务 SOP 执行
  public async execute(
    context: SkillExecutionContext,
  ): Promise<SkillExecutionResult> {
    const orderId = (context.slots?.orderId as string) || "";
    const invoiceTitle =
      (context.slots?.invoiceTitle as string) ||
      (context.slots?.title as string) ||
      "个人";

    // 前置槽位校验
    if (!orderId) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: "申请开具发票需要提供订单编号，请补充您的订单号。",
        error: "Missing required slot: orderId",
      };
    }

    // 动态获取当前商户绑定的 SPI 客户端 (自动组装 HMAC-SHA256 签名)
    const spiClient = await this.getSpiClient(context.tenantId);

    // Step A: 查验订单履约状态
    const order = await spiClient.getOrderDetail({
      orderId,
      tenantId: context.tenantId,
    });

    if (!order) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `未查询到订单 [${orderId}]，请核对订单编号。`,
      };
    }

    if (
      order.status !== "PAID" &&
      order.status !== "SHIPPED" &&
      order.status !== "DELIVERED"
    ) {
      return {
        success: false,
        skillId: this.metadata.id,
        output: `订单 [${orderId}] 当前状态为【${order.status}】，仅已付款或已发货的订单支持开具发票。`,
      };
    }

    const totalAmount = Number(order.totalAmount) || 0;

    // Step B: HITL 风控门禁检查 (动态读取商户针对此 Skill 的自定义阈值)
    const threshold = await this.getEffectiveApprovalThreshold(
      context.tenantId,
    );
    const isApproved = Boolean(context.extra?.isApproved);

    if (totalAmount > threshold && !isApproved) {
      return {
        success: true,
        skillId: this.metadata.id,
        output: `您的发票开具金额为 ¥${totalAmount.toFixed(2)}（超过免审上限 ¥${threshold}），已为您提交至财务专员复核，请稍候。`,
        nextAction: "require_approval",
        approvalPayload: {
          actionType: "applyInvoice",
          amount: totalAmount,
          reason: `大额开票申请: ${invoiceTitle}`,
          details: {
            orderId,
            invoiceTitle,
            tenantId: context.tenantId,
            userId: context.userId,
          },
        },
      };
    }

    // Step C: 免审或审批通过后调用商户 SPI 执行开票
    const idempotencyKey = crypto.randomUUID();
    await spiClient.executeOrderAction({
      actionType: "APPLY_INVOICE" as any,
      orderId,
      userId: context.userId,
      idempotencyKey,
      tenantId: context.tenantId,
    });

    // Step D: 组装开票凭证卡片
    const cards: RichCardBlock[] = [
      {
        type: "refund_confirmation",
        data: {
          orderId,
          refundAmount: totalAmount,
          currency: "CNY",
          refundReason: `发票抬头：${invoiceTitle}`,
          refundMethod: "ELECTRONIC_INVOICE_PDF",
          status: "issued",
        },
      },
    ];

    return {
      success: true,
      skillId: this.metadata.id,
      output: `已成功为您开具订单 [${orderId}] 的电子普通发票（抬头：${invoiceTitle}），发票金额：¥${totalAmount.toFixed(2)}。`,
      cards,
      nextAction: "finish",
    };
  }
}
```

---

#### 步骤 2：在技能注册中心注册该 Skill

编辑 `packages/engine/src/skills/skillRegistry.ts`：

```typescript
import { OrderInvoiceSkill } from "./orderInvoiceSkill";

// 在静态注册块中注册
SkillRegistry.register(new OrderInvoiceSkill());
```

---

### 5.4 商户端 SPI 接口对接与 HMAC 验签守卫

商户端（`apps/merchant`）在 `/spi/v1/orders/action` 接收来自平台的调用，并校验数字签名：

```typescript
// apps/merchant/app/spi/v1/orders/action/route.ts
import { NextRequest, NextResponse } from "next/server";
import { verifySpiRequest } from "@/services/spiAuthGuard";
import { MerchantDomainService } from "@/services/merchantDomainService";

export async function POST(req: NextRequest) {
  const bodyText = await req.text();

  // 1. 严格校验 HMAC-SHA256 签名与 5 分钟时间戳时效窗口
  const auth = await verifySpiRequest(req, bodyText, {
    requireSignature: true,
  });
  if (!auth.isValid) {
    return NextResponse.json(
      { success: false, error: auth.error },
      { status: 401 },
    );
  }

  const payload = JSON.parse(bodyText);
  const signature = req.headers.get("x-signature") || "";

  // 2. 执行商户端业务逻辑 (带幂等防重)
  const result = await MerchantDomainService.executeOrderAction(
    payload,
    signature,
  );
  return NextResponse.json({ success: result.success, data: result });
}
```

---

### 5.5 在 Admin 控制台与数据库中动态配置 Skill

商户入驻后，可在 **Admin 控制台（`http://localhost:3001/skills-tools`）** 对技能进行个性化配置：

- **可视化开启/关闭**：在技能列表勾选 `skill_order_invoice`；
- **配置免审额度**：将该商户的开票免审阈值调整为 `¥3000.00`；
- **自定义 Prompt 规则**：如 `“开票抬头包含‘分公司’时请提示用户补充统一社会信用代码”`。

也可以通过 SQL 批量配置：

```sql
UPDATE tenant_configs
SET enabled_skills = array_append(enabled_skills, 'skill_order_invoice'),
    skills_config = jsonb_set(
      COALESCE(skills_config, '{}'::jsonb),
      '{skill_order_invoice}',
      '{"enabled": true, "approvalThresholdAmount": 3000}'
    )
WHERE business_id = 'aurora';
```

---

### 5.6 在商户商城前端使用与验证

1. **启动所有服务**：`bun run dev:all`；
2. **打开商城前端**：浏览器访问 `http://localhost:3005`；
3. **发起提问**：点击右下角极光智能客服悬浮窗，发送：
   > _“帮我把订单 AURORA-ORD-2026-9081 开一张电子发票，抬头写【极光科技】”_
4. **验证响应**：
   - AI 自动识别开票诉求并命中 `OrderInvoiceSkill`；
   - 订单金额 `¥1299.00` 未超过设定的 `¥3000.00` 阈值，直接调用商户 SPI 成功开票；
   - 聊天界面输出结构化卡片与成功通知。

---

### 5.7 编写自动化测试验证

在 `packages/engine/tests/` 中编写针对该 Skill 的测试用例：

```typescript
import { describe, expect, it } from "bun:test";
import { SkillRegistry } from "../src/skills";
import { OrderInvoiceSkill } from "../src/skills/orderInvoiceSkill";

describe("OrderInvoiceSkill Test Suite", () => {
  it("should find matching skill for invoice intent", () => {
    const skill = SkillRegistry.findMatchingSkill({
      threadId: "t_test",
      tenantId: "aurora",
      input: "帮我开发票",
      slots: { activeIntent: "APPLY_INVOICE" },
    });
    expect(skill?.metadata.id).toBe("skill_order_invoice");
  });

  it("should intercept missing slots in OrderInvoiceSkill", async () => {
    const skill = new OrderInvoiceSkill();
    const result = await skill.execute({
      threadId: "t_test",
      tenantId: "aurora",
      input: "帮我开票",
      slots: { activeIntent: "APPLY_INVOICE" },
    });
    expect(result.success).toBe(false);
    expect(result.output).toContain("请补充您的订单号");
  });
});
```

运行测试：

```bash
bun test packages/engine/tests/skillsRegistry.test.ts
bun test packages/engine/tests/openSpiMerchant.test.ts
```

---

## 六、常见问题排查与 FAQ

### Q1: 在 Admin 控制台添加了新商户，为什么顶部租户下拉菜单里没有出现？

- **解答**：Admin 页面的全局下拉列表定义在 `apps/admin/src/store/tenantStore.ts` 的 `SUPPORTED_TENANTS` 常量中。在界面上通过 `/tenants` 动态创建的商户已经写入数据库并在所有数据表格和 API 请求中完全生效；如需在快捷切换器常驻该商户快捷项，可在 `SUPPORTED_TENANTS` 中添加对应对象。

### Q2: 为什么调用商户 SPI 接口返回 401 签名错误？

- **解答**：请检查 `tenant_configs.spi_config.apiSecret` 与商户服务中配置的密钥是否一致。系统使用标准 `HMAC-SHA256` 算法计算签名并附加时间戳防重放。

### Q3: 如何为商户添加独有的定制提示词（System Prompt）？

- **解答**：在 `apps/admin` 的 **技能与工具** 或通过 SQL 更新 `tenant_configs` 表中对应 `business_id` 的 `system_prompt` 字段，决策引擎在每次会话装配时均会实时热加载生效。
