# project_brief —— 产品一句话与边界

## 一句话

多租户 AI 客服与运营 agent 平台:客户端智能对话(含人工接管)、商户自助数据分析、坐席工作台、平台管控台,四个前端共用一个 Python 网关与决策引擎。

## 用户与界面

- **消费者**(apps/web,3000):SSE 聊天、富卡片渲染、多模态上传、人工接管切换。
- **顾客/商户门户**(apps/merchant,3005):陈列/购物车/下单/订单/自助身份 + 悬浮 AI 客服;U2 游客律(匿名访客 guest-\* 与真客 CUST-\* 隔断)。
- **商户员工**(apps/merchant-admin,3006):数据分析 Agent(悬浮助手 + ask SSE)、坐席工作台 /agent-desk、RBAC 动态菜单、订单/商品/客户 CRUD。
- **平台运营**(apps/admin,3001):11 大模块 CRUD、HITL 审批抽屉、技能管理、观测。

## 核心能力

1. 对话回合管线:triage → planner → 技能执行 → 校验循环(LangGraph DAG,exec ⇄ val 循环)。
2. HITL:敏感动作挂起等审批,事务发件箱保证审批与事件原子性,恢复确定性可追溯。
3. 数据分析 Agent:自然语言 → 闭集指标模板 → AST 守卫 → 只读执行 → 卡片;41 指标语义注册表;LLM 永不写 SQL。
4. 记忆:四象限(Short/Long/Episodic/Task)+ 双层画像(global/tenant)+ Contextual RAG(租户过滤检索)。
5. 本体知识层:闭集词汇 + 四域实体声明,pydantic v2 加载即校验,运行时消费零依赖生成物。

## 多租户与数据

每条查询与工具执行携带 tenantId/businessId;数据库双库:`agent_platform`(引擎侧)与 `agent_merchant`(商户真单),引擎跨库走 `_merchant_reader_engine` 只读。

## 明确不在范围内

- 多实例部署(单实例假设,scheduler/ socket.io 跨实例方案仅存在于指南文档)。
- Temporal 等外置编排(ADR-0007 已退役,重引入须新立 ADR)。
- 自由 SQL 入口(一切查询必须过守卫,ADR-0010 分层信任)。
