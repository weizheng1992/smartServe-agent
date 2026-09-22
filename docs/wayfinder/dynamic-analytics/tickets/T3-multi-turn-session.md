# T3-multi-turn-session

## Question

前端 session_id(localStorage)随 ask 上行;服务端 Redis 存最近意图/实体/图表偏好(TTL 24h);追问检测 → LLM 改写为独立问句(glm-4-flash)→ 走现有管线;「他呢/换成柱状/那优惠券呢」实测

## Resolution

已解决(见 Decisions):前端稳定 session_id 随 ask 上行;session_store.py Redis 优先/内存回落(TTL 24h);graph 三层——纯图表切换确定性快捷路、L0/L2 未命中后 LLM 改写追问为独立问句再走管线、改写问句贯穿实体绑定/行内扫描/落存(初版漏传导致 clarify 的 bug 实弹修)。浏览器实测:品类GMV排行→换成折线图,同一指标免主语重出折线
