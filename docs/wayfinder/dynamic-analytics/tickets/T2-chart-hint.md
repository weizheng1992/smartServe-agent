# T2-chart-hint

## Question

StructuredQueryIntent.chart_hint(line/bar/table)+ L0 词面(折线/柱状/表格)+ L3 schema 字段 + PageContext/场景包透传 + 前端 ResultCard 尊重 hint(单行数据强要折线 → LineChart 诚实点不足提示)

## Resolution

已解决(d8dad09):已施工:chart_hint 全链路(L0 词面/L3 字段/graph 透传/前端尊重),柱状与表格指令实测生效,非排行形强制 bar 诚实降级
