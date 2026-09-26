# 📖 smartServe SaaS: 新商户接入与配置操作手册 (Merchant Onboarding Guide)

本手册详细介绍了如何在多租户智能客服与决策中台体系中接入一个全新的业务商户（如独立商城、第三方品牌旗舰店），并在 **Admin 控制平面（Port 3001）** 中进行可视化配置、实时会话监控、HITL 审批干预与业务调优。

> 架构基线（2026-09）：后端为 **Python 栈** —— FastAPI 网关（`services/gateway-py`:4000）+ LangGraph 决策引擎（`services/engine-py`）；原 NestJS `apps/server` 与 `packages/*` TS 后端已退役，行为由 `services/gateway-py/tests/` 的 pytest 契约套件钉死。

---

## 目录

- [一、核心架构与多租户机制](#一核心架构与多租户机制)
- [二、新商户接入的三种方式](#二新商户接入的三种方式)
  - [方式 1：Admin 控制台可视化一键入驻 (推荐)](#方式-1admin-控制台可视化一键入驻-推荐)
  - [方式 2：数据库 SQL / 种子脚本动态注册 (Zero Hardcode)](#方式-2数据库-sql--种子脚本动态注册-zero-hardcode)
  - [方式 3：SPI 标准合同面对接](#方式-3spi-标准合同面对接)
- [三、在 Admin 3001 控制台中的全链路查看与管理](#三在-admin-3001-控制台中的全链路查看与管理)
- [四、内置模拟商户（Aurora 极光潮品）快速实战演练](#四内置模拟商户aurora-极光潮品快速实战演练)
- [五、商户专属业务技能 (SOP Skills) 的扩展、开发与使用教程](#五商户专属业务技能-sop-skills-的扩展开发与使用教程)
  - [5.1 Tool（原子工具）与 Skill（业务技能）的本质区别](#51-tool原子工具与-skill业务技能的本质区别)
  - [5.2 Skill 执行架构与生命周期管线](#52-skill-执行架构与生命周期管线)
  - [5.3 实战示例：添加电子发票开具 SOP 技能 (`OrderInvoiceSkill`)](#53-实战示例添加电子发票开具-sop-技能-orderinvoiceskill)
  - [5.4 SPI 合同面承接与 HMAC 验签守卫](#54-spi-合同面承接与-hmac-验签守卫)
  - [5.5 在 Admin 控制台与数据库中动态配置 Skill](#55-在-admin-控制台与数据库中动态配置-skill)
  - [5.6 在商户商城前端使用与验证](#56-在商户商城前端使用与验证)
  - [5.7 编写自动化测试验证](#57-编写自动化测试验证)
- [六、常见问题排查与 FAQ](#六常见问题排查与-faq)

---

## 一、核心架构与多租户机制

平台采用**无代码硬编码（Zero Hardcode）**的多租户动态装配架构：

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        SaaS 控制平面 (apps/admin:3001)                 │
│  [商户管理]     [会话 & 接管]     [审批中心]     [技能配置]     [RAG 知识库]│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ x-tenant-id: <businessId>
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                FastAPI 网关 (services/gateway-py:4000)                 │
│        /api/admin/* │ /api/tenants │ /spi/v1/* │ /api/v1/spi/*         │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ 动态装配
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│              决策引擎 (services/engine-py - LangGraph)                 │
│  1. 租户隔离: 所有会话/订单/记忆严格绑定 businessId                      │
│  2. 双层画像: global(生理/事实) 与 tenant(品牌专属偏好) 隔离              │
│  3. 数据通道: 引擎经只读 reader 直连商户库(agent_merchant);             │
│     SPI 合同面(/spi/v1/*)承载对外集成,HMAC 验签防护                     │
│  4. 技能重载: 动态覆盖退款阈值 (approvalThresholdAmount) 与 SOP 规则    │
└────────────────────────────────────────────────────────────────────────┘
```

- **`businessId`**：租户全局唯一字符串标识（纯小写字母与连字符，如 `aurora`, `nike`, `myshop`）。
- **物理与逻辑隔离**：数据库所有表（`threads`, `messages`, `orders`, `pending_approvals`, `long_memory_facts`）均强制附带 `business_id` 过滤。
- **数据通道现状（诚实说明）**：引擎运行时经 `LocalDbSpiAdapter` 与只读 reader **直连**商户库 `agent_merchant`（与商户门户「我的订单」同源）；`tenant_configs.spi_config` 的 `remote_spi` 模式与网关 `/spi/v1/*` 合同面已就绪，远程 HTTP 适配器为 Phase 1b 演化缝。

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
   - **API Key & SPI Webhook URL**：填写该商户的后端服务根地址（写入 `tenant_configs.spi_config.spiBaseUrl`，如 `https://api.myshop.com/spi` 或本地联调 `http://localhost:3005`）。
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

> 种子脚本等效入口：`bun run db:seed`（三段式：engine 库播种 → 第三方租户播种（注册 aurora 及其 SPI 配置）→ 商户真单播种 `gateway_py.merchant_seed`）。

---

### 方式 3：SPI 标准合同面对接

平台在**网关侧**（`services/gateway-py/src/gateway_py/routers/merchant.py`）托管对外 SPI 合同面，第三方商户系统按以下契约查询/回写业务数据；本地联调时商户门户（3005）的 `/spi/*` 由 Vite proxy 转发至网关 4000。

#### 标准 SPI 接口列表（网关承接，`/spi/v1/*`）

| HTTP 方法 | 端点路径                    | 功能描述                                             |
| :-------- | :-------------------------- | :--------------------------------------------------- |
| `GET`     | `/spi/v1/products/search`   | 查询商户商品库（关键词检索、SPU/SKU 规格与实时库存） |
| `GET`     | `/spi/v1/user/info`         | 查询商户会员信息、历史默认地址列表与标签             |
| `GET`     | `/spi/v1/orders/list`       | 查询订单列表（按用户/状态过滤）                      |
| `GET`     | `/spi/v1/orders/detail`     | 查询指定订单的详情、物流与退款状态                   |
| `POST`    | `/spi/v1/orders/action`     | 订单动作回写（改地址 / 退款等，带幂等语义）          |

另有**反向通道** `/api/v1/spi/*`（`routers/spi.py`，镜像 TS `merchant-spi.controller`）：`POST /api/v1/spi/approvals/{approvalId}/resolve`（第三方核决 HITL 工单）、`POST /api/v1/spi/escalation/{threadId}/reply|close`（人工接管话术回写/关单），API-Key 约定式（`key_{tenant}` / `secret_{tenant}` 派生形，静态集由 `SPI_API_KEYS` env 配置）与 HMAC 双通道鉴权。

#### SPI 安全认证协议

- **签名头**：`x-signature` = `HMAC-SHA256(secret, METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY))`
- **防重放**：`x-timestamp`（Unix 毫秒，与服务器时差超过 **5 分钟**即拒绝）+ `x-nonce`
- **租户门禁**：请求方 business_id 必须已在 `tenants` 注册且 `status = 'active'`，否则 fail-closed 403（注册表查询失败时 503 拒绝）

**密钥配置在网关侧 `.env`**（商户门户现为 Vite SPA，不再有独立 Node 服务端）：

```bash
# services/.env（网关读取）
MERCHANT_API_SECRET=aurora_secret_key_8899   # SPI 验签密钥;缺省回落 aurora_secret_key_8899
```

---

## 三、在 Admin 3001 控制台中的全链路查看与管理

接入新商户后，启动控制台并在浏览器打开 `http://localhost:3001`：

### 1. 全局租户穿透切换 (Tenant Switcher)

- 在页面顶部 Header 中，点击 **租户选择器**。
- 可切换至 **`全平台多租户 (上帝视角)`** 查看全局大盘，或精确切换至指定商户（如 `aurora` 或新增的商户 ID）。
- 切换后，页面所有模块自动携带该商户作用域（请求头 `x-tenant-id`）。

### 2. 各核心模块查看指南

- 💬 **会话管理 & 实时人工接管 (`/conversations`)**：
  - 实时查看该商户下所有客户与 AI 的对话流。
  - 点击会话可展开 **Deep Trace 抽屉**，查看 LLM 思考链（Thought Steps）、意图分类、命中的技能与工具参数。
  - 点击 **「接入实时人工会话」** 即可一键进入 Live Desk 模式接管对话，系统经 socket.io 向客户端广播坐席名片并暂停 AI 自动回复。
- 🛡️ **人工审批工作台 (`/approvals`)**：
  - 当客户触发超过商户阈值的高额退款、发货后强行改地址等高危动作时，状态机将自动挂起为 `waiting` 状态。
  - 管理员在审批中心可查看完整的上下文 Timeline、原始 Payload，点击 **「通过」** 或 **「驳回」** 后，Transactional Outbox 机制（决议与事件同事务落盘 + 确定性 `job_resume_{approvalId}` 恢复）会自动恢复执行并通知用户。
- 🧩 **技能与工具市场 (`/skills-tools`)**：
  - 查看该商户已启用的技能状态、生效的 SOP 门禁规则以及 SPI 外部端点连通性。
- 🧠 **双层画像与记忆 (`/personas`)**：
  - 检查客户画像物理隔离效果：区分客户全局基础生理特征（`global`，如身高鞋码）与商户私域偏好（`tenant`，如在该商城的专属优惠与风格偏好）。
- 📊 **SaaS 账单与遥测大盘 (`/billing` & `/system-logs`)**：
  - 监控该商户的 API 调用量、Token 算力消耗、财务费用、平均决策延迟与 Autopilot 自动解决率。

---

## 四、内置模拟商户（Aurora 极光潮品）快速实战演练

代码库中已内置了高度拟真的独立商户系统 `apps/merchant`（极光潮品官方商城，Vite SPA:3005），你可以按照以下步骤进行端到端闭环验证：

### 1. 快速初始化数据

```bash
# 一条命令三段式播种：
# engine 库(threads/messages/pending_approvals 等) + 第三方租户(aurora + SPI 配置)
# + 商户真单库 agent_merchant(商品/订单 AURORA-ORD-2026-9081 起)
bun run db:seed
```

### 2. 启动全套服务

```bash
# 启动 FastAPI 网关 (Port 4000)
bun run dev:server

# 启动模拟商城前台 (Port 3005; /api/* 与 /spi/* 代理至网关)
bun run dev:merchant

# 启动 SaaS Admin 控制台 (Port 3001)
bun run dev:admin
```

### 3. 场景实测与验证

1. **打开模拟商城**：浏览器访问 `http://localhost:3005`，点击右下角智能客服。
2. **测试订单查询**：输入 `“帮我查一下订单 AURORA-ORD-2026-9081 的物流到哪了”`，AI 将实时拉取订单状态并呈现多模态富卡片。
3. **测试风控审批拦截**：对该订单说 `“我想把这个订单退款”`（冲锋衣 ¥499，超过退款技能默认免审阈值 ¥50），AI 会回复已为您提交人工审核。
4. **在 Admin 3001 审批**：打开 `http://localhost:3001/approvals`，找到该笔退款申请并点击 **通过**，回到商城前台即可看到退款成功并恢复后续流程。

---

## 五、商户专属业务技能 (SOP Skills) 的扩展、开发与使用教程

在本平台中，**Skill（业务技能）** 是将业务规则、参数校验、风控门禁、商户数据通道调用以及多模态卡片渲染完整闭环的高阶抽象层。

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

1. **资金防损**：若仅暴露退款执行动作，用户说“帮我退款 10 万元”，LLM 将直接调用产生严重资损；而 Skill 会根据商户动态配置进行风控阈值拦截与人工审批挂起；
2. **状态防越权**：若订单状态为已发货（`SHIPPED`），Skill 会在调用工具前直接拦截改地址请求；
3. **多租户隔离**：不同商户的免审额度和政策各不相同（A 商户 100 元免审，B 商户 500 元免审），只有 Skill 能结合 `tenant_configs` 动态做出差异化决策。

---

### 5.2 Skill 执行架构与生命周期管线

```text
[用户输入: "帮我把订单 AURORA-ORD-2026-9081 开发票"]
                        │
                        ▼
      【triage 意图分流 (engine_py/triage/intent_triage_engine.py)】
                        │ (识别 intent: 'APPLY_INVOICE')
                        ▼
      【SkillRegistry 技能注册中心 (engine_py/skills/__init__.py)】
                        │ (activeIntent 精确命中 triggerIntents → OrderInvoiceSkill)
                        ▼
      ┌──────────────────────────────────────────────────┐
      │        🧩 OrderInvoiceSkill (BaseSkill)           │
      │                                                  │
      │  1. can_handle: 命中 APPLY_INVOICE 意图           │
      │  2. 槽位前置校验: 检查 orderId 是否提供           │
      │  3. 读取商户策略: get_effective_approval_threshold│
      │  4. 风控判断: 是否超过免审上限？                   │
      │     ├─ 超过: next_action=require_approval 挂起    │
      │     └─ 未超: 调用商户数据通道执行开票              │
      │  5. 组装发票确认富卡片 (cards)                     │
      └────────────────────────┬─────────────────────────┘
                               │
                               ▼
      ┌──────────────────────────────────────────────────┐
      │      🛠️ 商户数据通道 (LocalDbSpiAdapter)          │
      │  - 直连 agent_merchant 库;对外场景走 /spi/v1/*    │
      │    合同面(网关自动校验 HMAC-SHA256 签名)          │
      └──────────────────────────────────────────────────┘
```

---

### 5.3 实战示例：添加电子发票开具 SOP 技能 (`OrderInvoiceSkill`)

下面以一个真实高频业务——**「电子发票申请与开具」** 为例，完整演示如何新增并接入自定义 Skill：

#### 步骤 1：在决策引擎中创建 Skill 类

新建 `services/engine-py/src/engine_py/skills/order_invoice_skill.py`，继承 `BaseSkill`：

```python
# services/engine-py/src/engine_py/skills/order_invoice_skill.py
import re

from .base_skill import BaseSkill
from .contract import SkillContext, SkillResult


class OrderInvoiceSkill(BaseSkill):
    metadata = {
        "id": "skill_order_invoice",
        "name": "电子发票极速开具 SOP",
        "description": "核验订单支付状态与抬头信息，自动开具电子发票并支持超额人工审核",
        "category": "after_sale",
        "triggerIntents": ["APPLY_INVOICE", "order_invoice", "request_invoice"],
        "requiredTools": ["getOrderDetail", "executeOrderAction"],
        "requiresApproval": True,
        "approvalThresholdAmount": 2000,  # 默认 2000 元以上开票需人工财务审批
        "version": "1.0.0",
    }

    # 文本兜底(仅用于未决意图的动作嗅探;已决意图由 triage 精确命中)
    _FALLBACK_RE = re.compile(r"(开发票|电子发票|开票|补开发票)", re.IGNORECASE)

    def can_handle(self, context: SkillContext) -> bool:
        if super().can_handle(context):
            return True
        return bool(self._FALLBACK_RE.search(context.input))

    async def execute(self, context: SkillContext) -> SkillResult:
        order_id = context.slots.get("orderId") or ""
        invoice_title = (
            context.slots.get("invoiceTitle") or context.slots.get("title") or "个人"
        )

        # 前置槽位校验（自愈追问）
        if not order_id:
            return SkillResult(
                success=False,
                skill_id=self.metadata["id"],
                output="申请开具发票需要提供订单编号，请补充您的订单号。",
                error="Missing required slot: orderId",
            )

        # 动态获取当前商户绑定的 SPI 客户端
        spi_client = await self.get_spi_client(context.tenant_id)

        # Step A: 查验订单履约状态
        order = await spi_client.get_order_detail(
            {"orderId": order_id, "tenantId": context.tenant_id}
        )
        if not order:
            return SkillResult(
                success=False,
                skill_id=self.metadata["id"],
                output=f"未查询到订单 [{order_id}]，请核对订单编号。",
            )
        if order.get("status") not in ("PAID", "SHIPPED", "DELIVERED"):
            return SkillResult(
                success=False,
                skill_id=self.metadata["id"],
                output=(
                    f"订单 [{order_id}] 当前状态为【{order.get('status')}】，"
                    "仅已付款或已发货的订单支持开具发票。"
                ),
            )

        total_amount = float(order.get("totalAmount") or 0)

        # Step B: HITL 风控门禁检查 (动态读取商户针对此 Skill 的自定义阈值)
        threshold = await self.get_effective_approval_threshold(context.tenant_id)
        if total_amount > threshold and not context.is_approved:
            return SkillResult(
                success=True,
                skill_id=self.metadata["id"],
                output=(
                    f"您的发票开具金额为 ¥{total_amount:.2f}"
                    f"（超过免审上限 ¥{threshold}），已为您提交至财务专员复核，请稍候。"
                ),
                next_action="require_approval",
                approval_payload={
                    "actionType": "applyInvoice",
                    "amount": total_amount,
                    "reason": f"大额开票申请: {invoice_title}",
                    "details": {
                        "orderId": order_id,
                        "invoiceTitle": invoice_title,
                        "tenantId": context.tenant_id,
                        "userId": context.user_id,
                    },
                },
            )

        # Step C: 免审或审批通过后调用商户数据通道执行开票
        await spi_client.execute_order_action(
            {
                "actionType": "APPLY_INVOICE",
                "orderId": order_id,
                "userId": context.user_id,
                "tenantId": context.tenant_id,
            }
        )

        # Step D: 组装开票凭证卡片
        cards = [
            {
                "type": "refund_confirmation",
                "data": {
                    "orderId": order_id,
                    "refundAmount": total_amount,
                    "currency": "CNY",
                    "refundReason": f"发票抬头：{invoice_title}",
                    "refundMethod": "ELECTRONIC_INVOICE_PDF",
                    "status": "issued",
                },
            }
        ]

        return SkillResult(
            success=True,
            skill_id=self.metadata["id"],
            output=(
                f"已成功为您开具订单 [{order_id}] 的电子普通发票"
                f"（抬头：{invoice_title}），发票金额：¥{total_amount:.2f}。"
            ),
            cards=cards,
            next_action="finish",
        )
```

> 契约要点：技能消费 `SkillContext`（`slots` / `is_approved` / `tenant_id` 等）、返回 `SkillResult`；`to_dict()` 是冻结的线上契约形状（`tests/test_skill_contract_golden.py` 黄金快照钉死）。风控阈值经 `BaseSkill.get_effective_approval_threshold` 读取租户 `skills_config` 覆写，缺省回落 `metadata.approvalThresholdAmount`。

---

#### 步骤 2：在技能注册中心注册该 Skill

编辑 `services/engine-py/src/engine_py/skills/__init__.py` 的静态注册块：

```python
from .order_invoice_skill import OrderInvoiceSkill

# 在 _ensure_initialized 的静态注册元组中登记
for skill in (
    OrderAddressModificationSkill(),
    OrderRefundSkill(),
    OrderInvoiceSkill(),  # ← 新增
    ProductInquirySkill(),
    ShoppingGuideSkill(),
    PromotionQuerySkill(),
    CartManageSkill(),
):
    cls.register(skill)
```

---

### 5.4 SPI 合同面承接与 HMAC 验签守卫

对外 SPI 合同面由**网关承接**（`services/gateway-py/src/gateway_py/routers/merchant.py`），`/spi/v1/orders/action` 等端点在进入业务逻辑前先过验签守卫：

```python
# services/gateway-py/src/gateway_py/routers/merchant.py — /spi/v1/orders/action（节选）
signature = request.headers.get("x-signature") or ""
timestamp = request.headers.get("x-timestamp") or ""
nonce = request.headers.get("x-nonce") or ""
body = (await request.body()).decode(errors="replace")

# 1. 严格校验 HMAC-SHA256 签名与 5 分钟时间戳时效窗口(+ 租户 fail-closed 门禁)
ok, err = await verify_spi_request(
    request.method, request.url.path, body,
    signature, timestamp, nonce, require_signature=True,
)
if not ok:
    return JSONResponse(status_code=401, content={"success": False, "error": err})

# 2. 执行商户域业务逻辑
result = await handle_order_action(payload)
```

验签实现 `verify_spi_request`：签名不符返回 `Invalid HMAC-SHA256 signature`；时间戳缺失/超窗返回 `Request timestamp expired (> 5 minutes window)`；密钥来自 env `MERCHANT_API_SECRET`（或 `API_SECRET`）。

---

### 5.5 在 Admin 控制台与数据库中动态配置 Skill

商户入驻后，可在 **Admin 控制台（`http://localhost:3001/skills-tools`）** 对技能进行个性化配置：

- **可视化开启/关闭**：在技能列表勾选 `skill_order_invoice`；
- **配置免审额度**：将该商户的开票免审阈值调整为 `¥3000.00`；
- **自定义 Prompt 规则**：如 `“开票抬头包含‘分公司’时请提示用户补充统一社会信用代码”`。

也可以通过 SQL 批量配置（`enabled_skills` 为 JSONB 数组）：

```sql
UPDATE tenant_configs
SET enabled_skills = COALESCE(enabled_skills, '[]'::jsonb) || '["skill_order_invoice"]'::jsonb,
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
   - 订单金额未超过设定的 `¥3000.00` 阈值，直接调用商户数据通道成功开票；
   - 聊天界面输出结构化卡片与成功通知。

---

### 5.7 编写自动化测试验证

在 `services/engine-py/tests/` 中编写针对该 Skill 的 pytest 用例（直接构造类型化契约，不手拼 dict）：

```python
# services/engine-py/tests/test_order_invoice_skill.py
import pytest

from engine_py.skills import SkillRegistry
from engine_py.skills.contract import SkillContext
from engine_py.skills.order_invoice_skill import OrderInvoiceSkill


@pytest.mark.asyncio
async def test_invoice_intent_matches_skill():
    skill = SkillRegistry.find_matching_skill(
        SkillContext(
            tenant_id="aurora",
            input="帮我开发票",
            slots={"activeIntent": "APPLY_INVOICE"},
        )
    )
    assert skill is not None
    assert skill.metadata["id"] == "skill_order_invoice"


@pytest.mark.asyncio
async def test_invoice_missing_slot_self_heals():
    result = await OrderInvoiceSkill().execute(
        SkillContext(
            tenant_id="aurora",
            input="帮我开票",
            slots={"activeIntent": "APPLY_INVOICE"},
        )
    )
    assert result.success is False
    assert "请补充您的订单号" in result.output
```

运行测试：

```bash
cd services/engine-py && uv run pytest tests/test_order_invoice_skill.py

# 网关契约面(SPI 路由/审批链路)回归:
cd services/gateway-py && uv run pytest tests/
```

---

## 六、常见问题排查与 FAQ

### Q1: 在 Admin 控制台添加了新商户，为什么顶部租户下拉菜单里没有出现？

- **解答**：Admin 页面的全局下拉列表定义在 `apps/admin/src/store/tenantStore.ts` 的 `SUPPORTED_TENANTS` 常量中。在界面上通过 `/tenants` 动态创建的商户已经写入数据库并在所有数据表格和 API 请求中完全生效；如需在快捷切换器常驻该商户快捷项，可在 `SUPPORTED_TENANTS` 中添加对应对象。

### Q2: 为什么调用商户 SPI 接口返回 401 签名错误？

- **解答**：请检查请求方签名密钥与网关侧 env `MERCHANT_API_SECRET` 是否一致（验签密钥以网关 env 为准，而非逐租户 `spi_config.apiSecret`）。系统使用标准 `HMAC-SHA256(secret, METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY))` 计算签名，`x-timestamp` 与服务器时差超过 5 分钟、缺失 `x-nonce` 均会拒绝。另请确认该商户已在 `tenants` 注册且状态为 `active`（fail-closed 门禁返回 403）。

### Q3: 如何为商户添加独有的定制提示词（System Prompt）？

- **解答**：在 `apps/admin` 的 **技能与工具** 或通过 SQL 更新 `tenant_configs` 表中对应 `business_id` 的 `system_prompt` 字段，决策引擎在每次会话装配时均会实时热加载生效。
