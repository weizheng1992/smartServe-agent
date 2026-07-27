# 🚀 smartServe SaaS: 接入新商户/新业务标准化 SOP 手册

本手册详尽阐述了如何在 **smartServe** 智能客服多租户平台中接入并配置一笔全新的业务租户（如新增 **“puma”** 彪马运动品牌、或非电商的 **“legal”** 法律合规业务）。

系统依靠 **SaaS 物理租户逻辑隔离**、**Contextual RAG 热加载自愈**、以及 **LLM 决策图动态热插拔**，接入新业务无需重构任何状态机节点代码。

---

## 📅 接入整体流程时序图

```
[步骤 1: 物理注册] -> [步骤 2: 知识库灌入] -> [步骤 3: 自动化测试] -> [步骤 4: 仪表盘激活]
```

---

## 1. 步骤 1：物理注册商户配置（SaaS Config Onboarding）

smartServe 在 `business_configs` 物理表中以 JSON 格式动态热载入商户特定的退款限额、专属 Prompt 以及授权调用的底层工具清单。

### 1.1 SQL 注册模板
连接至 PostgreSQL 物理数据库后，执行以下 INSERT 语句（以接入 `puma` 彪马品牌为例）：

```sql
INSERT INTO business_configs (id, business_id, config, is_active, created_at)
VALUES (
  gen_random_uuid(),
  'puma',
  '{
    "businessId": "puma",
    "systemPrompt": "您是 Puma (彪马) 官方尊享智能客服。请秉承 Puma \"Forever Faster\" 的运动精神，热忱、高效地为客户解答跑鞋、服饰等订单物流与 14天无理由退换货权益。",
    "intents": {
      "order_status": { "description": "追踪或查询 Puma 的物理物流最新状态" },
      "refund": { "description": "申请 Puma 14天无理由快速退款服务" },
      "general_query": { "description": "解答 Puma 常见尺寸、折扣或防伪标咨询" }
    },
    "tools": ["getOrderStatus", "processRefund", "listUserOrders"],
    "refundAutoApprovalLimit": 120.00,
    "confidenceThresholds": { "high": 0.85, "mid": 0.60 }
  }'::jsonb,
  true,
  NOW()
)
ON CONFLICT (business_id) DO UPDATE 
SET config = EXCLUDED.config, is_active = true;
```

---

## 2. 步骤 2：Contextual RAG 品牌专属政策灌入

为了彻底杜绝多租户之间政策混淆或 RAG 政策交叉感染（例如：Puma 会员误用 Nike 会员的 30 天超长试穿政策），我们必须为新商户独立生成 RAG 向量切片，并打上 `business_id` 物理隔离戳。

### 2.1 灌入操作代码
在后台执行 RAG 注入或运行数据同步脚本，将政策切片与 Contextual Summary、向量嵌入同步存储：

```typescript
import { getDrizzle, ragDocuments } from 'db';
import { getEmbeddingModel } from 'engine/src/llm/callLLMWithRetry';

async function onboardingPumaRAG() {
  const drizzle = getDrizzle();
  const embeddingModel = getEmbeddingModel();

  const pumaPolicies = [
    {
      businessId: 'puma',
      chunkText: 'Puma (彪马) 官方保障：支持自商品签收之日起 14 天无理由退换货。所有鞋盒退回时请使用额外纸箱包装，严禁直接在 Puma 原装鞋盒上粘贴快递单面单，否则影响二次销售将予以扣除鞋盒包装费。',
      contextualSummary: '这段切片规定了 Puma 14 天无理由退换货保障、退回时外包装保护要求以及原装鞋盒的硬性无损约束政策。'
    }
  ];

  for (const doc of pumaPolicies) {
    const combinedText = `[Context] ${doc.contextualSummary}\n\n[Content] ${doc.chunkText}`;
    const embedding = await embeddingModel.embedQuery(combinedText);

    await drizzle.insert(ragDocuments).values({
      businessId: doc.businessId,
      chunkText: doc.chunkText,
      contextualSummary: doc.contextualSummary,
      embedding: JSON.stringify(embedding),
      metadata: { category: 'refund_policy', version: '1.0' }
    });
  }
  console.log('✅ Puma 专属政策 RAG 知识库切片灌入完毕，高保真隔离隔离成功！');
}
```

---

## 3. 步骤 3：多意图分类与步骤规划 F1 回归测试

新商户上线前，必须通过 **Promptfoo 评测平台** 跑批核验，确保大语言模型在应对 Puma 的真实客服提问时，其**多意图 F1 分数 >= 80%** 且**工具调起准确率 100%**。

### 3.1 编写商户回归测试数据集
在 `eval/testCases/ecommerce/` 目录下新增专属的测试案例：

```json
[
  {
    "description": "Puma 多意图分类与规划极速回归",
    "vars": {
      "input": "我上周买的彪马跑鞋 ORD-88888 帮我退了，顺便查一下这单物流在哪里了？",
      "expectedIntents": ["order_status", "refund"],
      "expectedTools": ["getOrderStatus", "processRefund"]
    },
    "assert": [
      {
        "type": "javascript",
        "value": "file://scorers/intentF1.scorer.ts"
      },
      {
        "type": "javascript",
        "value": "file://scorers/toolAccuracy.scorer.ts"
      }
    ]
  }
]
```

### 3.2 运行评测命令
在根目录下，执行黄金指标大盘测试：
```bash
bun run test:prompt
```
控制台报告呈现 **GREEN PASS** 后，方可允许在生产环境放行激活！

---

## 4. 步骤 4：在 Web 主控制台上验证

1. 打开浏览器登录后台系统：`http://localhost:3000/`
2. **多租户隔离体验**：当有新线程挂载至 Puma 商户、且用户发送“我想申请退款”时：
   * 决策引擎会自动热加载刚才注册的 `puma` JSON 配置。
   * **免签核准拦截线**将由 Nike 的 $150 自动调整为刚才配置 of Puma **$120**，超过该额度将完美触发 **Human-in-the-Loop 实时拦截挂起**，全自适应切换！

祝您新业务接入顺畅！Forever Faster ⚡
