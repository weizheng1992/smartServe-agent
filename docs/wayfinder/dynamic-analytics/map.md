# Wayfinder 地图:data agent 从单轮问答到动态统计分析

## Destination

对话式数据 agent 具备:按客户的消费趋势折线、用户图表类型指令、多轮上下文(指代/省略/「换成柱状」)、可钉卡自动刷新的常驻看板。到站标志 = 四者全部上线并浏览器实弹验收。

## Notes

- 本图携带执行(Notes 覆盖 wayfinder 默认):票据即施工项,逐张做完即合入。
- 领域铁律不变:08-D1 LLM 永不写 SQL;08-P1 响亮失败;用户输入永不进 SQL 文本。
- 每张票完成:双端回归全绿 + 浏览器实弹 + git 提交,提交号回填本图 Decisions。
- 技能:grilling(决策拷问);domain-modeling/prototype 本机未装,由 grilling 承担。

## Decisions so far

- [T1 客户消费趋势折线](tickets/T1-customer-spend-trend.md):已上线,折线图浏览器实测(d8dad09)
- [T2 图表类型指令槽位](tickets/T2-chart-hint.md):chart_hint 全链路,折线/柱状/表格指令生效(d8dad09)

- Q1 终态 = b(对话 + 常驻看板);订阅/告警/大屏进雾区
- Q2 客户消费趋势 = 趋势族第四元 customer_spend_trend(客户实体 × 日/月)
- Q3 图表指令 = intent.chart_hint 槽位(L0 词面 + L3 字段 + 前端尊重,缺省自动)
- Q4 多轮 = **b 完整会话态**:Redis 按 session_id 存上下文,LLM 前置改写追问为独立问句,管线保持无状态;追问才触发改写(glm-4-flash 免费,1-2s)
- Q5 看板刷新 = 重放意图(存 intent+参数,定时调 /ask;不存 SQL,不绕语义层)
- Q6 会话态 = 服务端 Redis(session_id 键,TTL 24h);钉卡配置 localStorage

## 票据

- [T1 客户消费趋势折线](tickets/T1-customer-spend-trend.md) — ready
- [T2 图表类型指令槽位](tickets/T2-chart-hint.md) — ready
- [T3 多轮会话态(Redis + LLM 改写)](tickets/T3-multi-turn-session.md) — blocked by T2
- [T4 常驻看板(钉卡 + 重放刷新)](tickets/T4-pinned-board.md) — ready(软依赖 T2)

## Not yet specified

- 订阅推送/告警(概览每日推送到哪、什么触发)
- 大屏模式(看板只读放大)
- 归因族意图(「为什么退货变多」×8 积压,回捞清单首位)
- LangGraph 全面会话化(T3 轻实现之上是否再加话题切换/回指链)

## Out of scope

- 后端物化 SQL 看板:钉卡存 SQL 直查绕过语义层,违反 08-D1 精神,永不出场
