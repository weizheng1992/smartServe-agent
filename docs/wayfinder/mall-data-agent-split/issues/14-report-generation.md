# 14: 报告生成与导出形态

Type: grilling
Status: resolved
Blocked by: 10

## Question

「做报表」的具体形态拍板（图谱期 Q7 决议「对话式起步、预留固化报表演化」的兑现票）：

- 即席 vs 固化：对话内富卡片汇总（即席）之外，要不要周期性报告（周报/月报：定时还是手动触发、生成去哪、推送通道）；
- 输出格式：CSV 导出 / Markdown / 含图表的 HTML 报告——参照 spring-ai-alibaba/DataAgent 的 ECharts HTML/MD 报告（map Notes），前端 React 生态 ECharts 可用，但需对齐现有卡片基建（CardSynthesizer）而非另起渲染管线；
- 报告的存储与复看：落库独立表？threads 内可回溯即可？
- 与 10 号快捷问题胶囊的关系：高频问题固化为报表的路径。

原 fog「固化报表/订阅推送形态」毕业至此。


## Answer

决议日期 2026-09-18，用户采纳推荐（回复「可以」）。

### D1 形态 = 即席卡片 + 手动生成报告

对话内随时对当前分析或指定月份「生成报告」；**定时订阅推送（周报/月报）二期**，触发条件 = 手动报告的真实使用频率，不提前建调度。

### D2 输出格式 = CSV + 单页 HTML 报告

- 表格卡片一键 CSV 导出；单页 HTML 报告（ECharts 图 + 指标表 + 结论段，沿 DataAgent 形态）；Markdown 不做（HTML 打印即纸面）。
- 渲染对齐现有卡片基建，数据同源 `MetricQueryEngine` 的 QueryResult，不另起数据管线。

### D3 生成链路与数据诚实（不变量）

**数字全部来自真实查询，LLM 只组织语言**——报告 = 四族指标批量执行（同一 MetricQueryEngine、同权限同沙箱）+ LLM 基于查出的真实数字写结论文字段（标注口径来源）；禁止 LLM 编造任何数字。

### D4 存储与复看

新表 `analytics_reports`（business_id / 生成者 / 时间窗 / 内容引用）；HTML 文件复用现有 uploads 通道；merchant-admin「数据」分组下「我的报告」列表页。

### D5 入口（两个，均为真能力）

结果卡上的「生成报告」动作按钮 + 对话指令（「给我上个月的月报」）；六胶囊保持即席不动。
