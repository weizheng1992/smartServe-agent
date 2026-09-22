# T4-pinned-board

## Question

结果卡「钉到看板」(存 intent+参数+chart_hint 到 localStorage)→ 新看板页按卡片重放 /ask 定时刷新(可见性暂停)→ 每卡图表/导出复用

## Resolution

已解决:钉卡存问句+上下文(localStorage,上限20);/board 页重放 /ask(60s 轮询+不可见暂停+手动刷新);结果卡组件抽为 components/ResultCard 供对话/看板同形复用;入口=助手面板「📌 看板」。浏览器实测:两卡重放出真实数据、手动刷新时间戳更新
