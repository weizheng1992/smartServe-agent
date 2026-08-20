# TICKET-05: 提示词沙箱（Prompt Playground）与品牌心智配置交互设计

**Label:** `wayfinder:prototype` (HITL)  
**Parent Map:** [Wayfinder Map](../map.md)  
**Assignee:** zwei24  
**Status:** Closed

---

## Question

商户管理员在控制台（`apps/admin`）中如何直观地定义商户专属的 AI 客服人设、语气风格、System Prompt 模板，并即时在沙箱中进行多轮对话测试与效果评估？

---

## Resolution Prototype & Decisions

### 1. 左右双分栏工作台交互架构 (Split-Pane Workbench)

```text
+------------------------------------------+------------------------------------------+
|  左侧：商户大脑与提示词配置面板           |  右侧：实时提示词调试沙箱 (Playground)     |
|                                          |                                          |
|  [基础人设]                               |  [会话视窗]                               |
|  - 品牌名称: "Nike Official Store"       |  User: "帮我查下 ORD-1002 的发货状态"     |
|  - 语气风格: 热情/专业/电商专属           |  Assistant: "已为您查到顺丰单号 SF998..."  |
|                                          |                                          |
|  [System Prompt 模板编辑器]              |  [决策透视大盘 (Inspector)]               |
|  - 自定义业务规范 / 退换货 SOP 引导词    |  - 🎯 意图命中: order_status (置信度 0.98)|
|                                          |  - 📚 RAG 匹配: 《七天无理由退货政策》     |
|  [模型与工具参数挂载]                    |  - 🛠️ 工具调用: getOrderStatus (耗时 120ms)|
|  - Temperature (0.0 ~ 1.0 动态滑块)      |  - ⚡ 算力消耗: 312 Tokens | TTFT: 180ms  |
|  - 勾选启用已注册的 OpenAPI 动态工具     |                                          |
|                                          |  [输入框: "在此输入测试话术..."] [发送]   |
|  [保存草稿 (Save Draft)]  [一键发布到生产]|                                          |
+------------------------------------------+------------------------------------------+
```

### 2. 双状态发布生命周期 (Draft -> Publish Lifecycle)

1. **草稿模式 (Draft Sandbox)**:
   - 管理员在左侧调整人设、提示词或工具开关时，变动即时保存在 `tenant_configs (status = 'draft')`。
   - 右侧 Playground 调试视窗直接使用 Draft 配置执行 LangGraph 图推理，不影响任何线上真实用户。
2. **一键发布 (Atomic Publish)**:
   - 管理员确认沙箱效果完美后，点击【一键发布到生产 (Publish to Live)】；
   - 系统原子更新 `tenant_configs (status = 'published', version = version + 1)`，并刷新缓存，线上智能客服在下一轮会话时秒级加载最新人设与工具规则。
