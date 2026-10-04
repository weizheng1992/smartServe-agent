# 夜间 agent 评测(每晚 23:00)

真实 LLM 会话评测两类 agent,由 Claude durable cron 驱动(23:00 档):

- **商城客服 agent**:`POST /api/store/chat`(20 场景:多场景/多意图复合/模糊意图/多轮指代改口/边界对抗/HITL 正确性)
- **Data Agent**:`POST /api/admin/analytics/ask`(13 问:指标口径/复合/诚实性/**权限面**——运营问毛利、仓储问 GMV 必须被拦,老板放行)
- **商户端菜单/按钮矩阵**:`GET /api/admin/analytics/menus` 分角色断言(老板全量基线,管理员/运营/仓储 ⊆ 且严格更小,运营≠仓储)

判分:场景锚点(**词干级**——LLM 措辞每晚都变,严禁整句锚)+ 语义反面断言(不得宣称退款成功)
+ 全局编造检查(商户单号必须 ∈ 种子集∪本夜新建;用户自报单号的诚实回显豁免)
+ HITL 观察(waiting 审批单按线程计数差)+ 延迟记录。advisory 场景只记录不断言。

运行::

    cd services/gateway-py && uv run python ../../eval/nightly/run_nightly.py
    NIGHTLY_SMOKE=1 …   # 彩排切片(2 客服 + 1 数据 + 2 菜单,约 6 次 LLM 调用)

前置:docker(PG/Redis)+ 网关 4000(--env-file 仓库根 .env)+ 种子在库。
栈不可用退出码 2,不产假红。

产出:`results/<时间戳>/{report.html, results.jsonl}`(gitignore);失败自动入坏例池
(`nightly_agent_eval` 信号源),Data Agent 未命中由管线落 `agent_unanswered` —— 夜测喂飞轮。

护栏:总轮次 ≤90(LLM 成本),每轮超时 90s,失败不重试;`NIGHTLY_%` 前缀数据隔离,
收尾删单+回补库存+删线程(审计记录按仓库约定保留)。

cron 自续期:Claude 循环任务 7 天自动过期,每晚触发的 prompt 末尾带「重建同任务并删旧任务」
自续期指令;链断则用本 README + `scripts` 说明手工重建(任务 #8 的 cron 定义即模板)。
