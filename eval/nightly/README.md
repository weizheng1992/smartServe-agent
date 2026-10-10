# 夜间 agent 评测(每晚 23:00)

真实 LLM 会话评测两类 agent,由 **macOS launchd + headless Claude** 驱动(2026-10-10 起,
每天 23:00;评测收尾后追加一轮 code-review:基点 = 昨晚评审收尾提交,当日无提交跳过,
小问题直接修、行为代码改动须全量 pytest+ruff 验证、设计级争议列晨审):

- **商城客服 agent**:`POST /api/store/chat`(33 场景:多场景/全链购物[导购→序数加购→地址簿建档→结算真单]/多模态/多意图复合/模糊意图/多轮指代改口/边界对抗[XSS·超长·空消息·注入]/HITL 正确性·转人工排队/会话隔离)
- **Data Agent**:`POST /api/admin/analytics/ask`(21 问:指标族扩面[评价/促销/会话/客户]/场景包/多轮追问改写[pageContext.sessionId]/诚实性[乱语·不存在指标·编造指令·写操作]/**权限面**——运营问毛利、仓储问 GMV 必须被拦,老板放行)
- **商户端菜单/按钮矩阵**:`GET /api/admin/analytics/menus` 分角色断言(老板全量基线,管理员/运营/仓储 ⊆ 且严格更小,运营≠仓储)

判分:场景锚点(**词干级**——LLM 措辞每晚都变,严禁整句锚)+ 语义反面断言(不得宣称退款成功)
+ 全局编造检查(商户单号 ∈ 种子集∪本夜新建∪**本顾客真实订单**——聊天结算当轮生成的单号查客户新鲜订单豁免;用户自报单号的诚实回显豁免)
+ HITL 观察(waiting 审批单按线程计数差)+ 转人工观察(threads.status 真源)+ 延迟记录(p50/p95/max 入报告,预算 advisory 基线学习期)。advisory 场景只记录不断言。

**优化维度**:5 路并发真实会话(不 500 不串话+并发延迟)、SSE 桥存活(订阅先于建线程会被属主闸 404 掐流——先建线程再开流)、隔离确定性断言。夜间只记录优化数据,**严禁自动改性能代码**,慢点列晨审清单。

运行::

    cd services/gateway-py && uv run python ../../eval/nightly/run_nightly.py
    NIGHTLY_SMOKE=1 …   # 彩排切片(2 客服 + 1 数据 + 2 菜单,约 6 次 LLM 调用)

前置:docker(PG/Redis)+ 网关 4000(--env-file 仓库根 .env)+ 种子在库。
栈不可用退出码 2,不产假红。

产出:`results/<时间戳>/{report.html, results.jsonl}`(gitignore);失败自动入坏例池
(`nightly_agent_eval` 信号源),Data Agent 未命中由管线落 `agent_unanswered` —— 夜测喂飞轮。

护栏:总轮次 ≤90(LLM 成本),每轮超时 90s,失败不重试;`NIGHTLY_%` 前缀数据隔离,
收尾删单+回补库存+删线程(审计记录按仓库约定保留)。

**调度 = launchd(2026-10-10 起)**:此前的 Claude durable cron 只在「本项目 REPL 会话开着
且空闲」时触发(10-07/08/09 三晚静默停跑实证),且有 7 天过期+自续期链第二脆弱点,已退役。
现役链路:`scripts/nightly/com.aurora.nightly-eval.plist`(模板,装于
`~/Library/LaunchAgents/`,每天 23:00)→ `scripts/nightly/nightly-launchd.sh`(显式注入
nvm/bun/uv PATH、6h 过期防重叠锁)→ `claude -p <完整 prompt> --dangerously-skip-permissions`
(headless,含环境自举/评测/失败处置/code-review/CHANGELOG 回填全流程)。

    # 安装/重装
    cp scripts/nightly/com.aurora.nightly-eval.plist ~/Library/LaunchAgents/
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.aurora.nightly-eval.plist
    # 状态 / 手动触发真跑
    launchctl print gui/$(id -u)/com.aurora.nightly-eval
    launchctl kickstart gui/$(id -u)/com.aurora.nightly-eval
    # 链路彩排(smoke 切片,不评审不提交)
    NIGHTLY_LAUNCHD_SMOKE=1 bash scripts/nightly/nightly-launchd.sh

日志:`eval/nightly/logs/launchd.log`(含 headless 摘要与 exit 码)。仍有依赖:23:00 时
Mac 须开机(可 `pmset repeat wakeorpoweron MTWRFSU 22:55:00` 定时唤醒);prompt 第 1 步
自举 docker+网关,栈不可用如实记录不产假红。
