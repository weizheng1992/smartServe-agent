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
- [五、常见问题排查与 FAQ](#五常见问题排查与-faq)

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

## 五、常见问题排查与 FAQ

### Q1: 在 Admin 控制台添加了新商户，为什么顶部租户下拉菜单里没有出现？

- **解答**：Admin 页面的全局下拉列表定义在 `apps/admin/src/store/tenantStore.ts` 的 `SUPPORTED_TENANTS` 常量中。在界面上通过 `/tenants` 动态创建的商户已经写入数据库并在所有数据表格和 API 请求中完全生效；如需在快捷切换器常驻该商户快捷项，可在 `SUPPORTED_TENANTS` 中添加对应对象。

### Q2: 为什么调用商户 SPI 接口返回 401 签名错误？

- **解答**：请检查 `tenant_configs.spi_config.apiSecret` 与商户服务中配置的密钥是否一致。系统使用标准 `HMAC-SHA256` 算法计算签名并附加时间戳防重放。

### Q3: 如何为商户添加独有的定制提示词（System Prompt）？

- **解答**：在 `apps/admin` 的 **技能与工具** 或通过 SQL 更新 `tenant_configs` 表中对应 `business_id` 的 `system_prompt` 字段，决策引擎在每次会话装配时均会实时热加载生效。
