# T5 选择上下文翻新

## Question

勾选上下文从「localStorage 无类型数组」翻新为「内存广播 + 实体类型标记」:
订单/商品/客户三类勾选各归各(订单只进订单对比、商品只进标准族过滤、
客户只进客户族),面板实时显示勾选构成;「向 AI 提问」就地唤起不跳页;
勾选能力推广到商品/客户列表页。

## Resolution

已解决。page-context.ts 内存广播库(setSelectionKind/toggleKindId/clear/
subscribe);FloatingAgent 实时订阅(按类型显示「已勾选 订单 2 · 客户 1 ✕」)
+ 上行类型化 selection + 监听 open-agent 事件就地自动提问;orders-tab 向 AI
提问按钮改就地唤起;customer-drawer/订单页/商品列表/客户列表全部接入。
后端 graph 类型化分发:order→仅 order_overview;spu→标准族;customer→
客户族;旧数组形态向后兼容(订单对比+标准族双吃)。残留污染类 bug 结构性消灭。
