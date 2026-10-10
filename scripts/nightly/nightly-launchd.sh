#!/bin/bash
# 夜间 agent 评测 launchd 入口(2026-10-10 起,替代 Claude REPL durable cron——
# 后者只在「本项目会话开着且空闲」时触发,10-07/08/09 三晚静默实证不可靠;
# launchd 是系统调度器,不依赖任何 REPL 存活,无 7 天过期,无自续期链)。
#
# 触发:~/Library/LaunchAgents/com.aurora.nightly-eval.plist,每天 23:00
# 手工彩排:NIGHTLY_LAUNCHD_SMOKE=1 bash scripts/nightly/nightly-launchd.sh
#   (或 bash scripts/nightly/nightly-launchd.sh smoke;切片 5 场景约 6 次 LLM 调用)
# 日志:eval/nightly/logs/launchd.log(gitignored)
set -u

REPO=/Users/weizheng/Desktop/test/ai/agent-all
LOGDIR="$REPO/eval/nightly/logs"
mkdir -p "$LOGDIR"

# launchd 无交互 shell:nvm/bun/uv 不自加载,显式注入 PATH(node 版本升级时改首段;
# fallback 会自动找 .nvm 下最新版本)
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$HOME/.bun/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if ! command -v claude >/dev/null 2>&1; then
  NEWEST_NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort | tail -1)
  [ -n "$NEWEST_NODE_BIN" ] && export PATH="$NEWEST_NODE_BIN:$PATH"
fi
if ! command -v claude >/dev/null 2>&1; then
  echo "[$(date '+%F %T')] FATAL: claude CLI 不在 PATH(nvm node 版本变更?),夜测未跑" >> "$LOGDIR/launchd.log"
  exit 1
fi

# 简单锁:防重叠;卡死锁 6h 自动过期
LOCK=/tmp/aurora-nightly.lock
if mkdir "$LOCK" 2>/dev/null; then
  trap 'rmdir "$LOCK" 2>/dev/null' EXIT
else
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    rm -rf "$LOCK"; mkdir "$LOCK"; trap 'rmdir "$LOCK" 2>/dev/null' EXIT
  else
    echo "[$(date '+%F %T')] SKIP: 上一轮仍在跑" >> "$LOGDIR/launchd.log"
    exit 0
  fi
fi

MODE=full
if [ "${1:-}" = "smoke" ] || [ "${NIGHTLY_LAUNCHD_SMOKE:-}" = "1" ]; then
  MODE=smoke
fi
cd "$REPO"
echo "[$(date '+%F %T')] === nightly start (mode=$MODE, claude=$(command -v claude)) ===" >> "$LOGDIR/launchd.log"

if [ "$MODE" = "smoke" ]; then
  PROMPT=$(cat <<'PROMPT_EOF'
【夜间评测链路彩排(smoke)】只验证 launchd→headless→跑批器链路,严禁做评审/CHANGELOG/修复/提交:
1. 环境前置:curl -m 5 http://localhost:4000/api/health;不通则 cd /Users/weizheng/Desktop/test/ai/agent-all && bun run docker:up 后等 12s 再探;仍不通则 cd /Users/weizheng/Desktop/test/ai/agent-all/services/gateway-py 后 nohup uv run --env-file /Users/weizheng/Desktop/test/ai/agent-all/.env uvicorn gateway_py.main:app --port 4000 >/tmp/gw-nightly.log 2>&1 & 等 15s;三探仍败 → 如实记录「环境不可用」即止,不产假红。
2. 彩排跑批:cd /Users/weizheng/Desktop/test/ai/agent-all/services/gateway-py && NIGHTLY_SMOKE=1 uv run python ../../eval/nightly/run_nightly.py
3. 收尾一行摘要:严格通过 x/y、结果目录路径、环境是否自举。严禁 git commit。
PROMPT_EOF
)
else
  PROMPT=$(cat <<'PROMPT_EOF'
【夜间 agent 评测 + 代码评审 + CHANGELOG 回填(launchd 调度,每晚 23:00,58 用例)】严格按序执行:
1. 环境前置:curl -m 5 http://localhost:4000/api/health;不通则 cd /Users/weizheng/Desktop/test/ai/agent-all && bun run docker:up 后等 12s 再探;仍不通则 cd /Users/weizheng/Desktop/test/ai/agent-all/services/gateway-py 后 nohup uv run --env-file /Users/weizheng/Desktop/test/ai/agent-all/.env uvicorn gateway_py.main:app --port 4000 >/tmp/gw-nightly.log 2>&1 & 等 15s;三探仍败 → 如实记录「环境不可用」即止,不产假红、不修代码。
2. 跑评测:cd /Users/weizheng/Desktop/test/ai/agent-all/services/gateway-py && uv run python ../../eval/nightly/run_nightly.py(58 用例、130 轮上限;严禁设 NIGHTLY_SMOKE;可用 NIGHTLY_CASES=c前缀,d前缀 定向复跑)。
3. 处置评测失败(eval/nightly/results/<最新时间戳>/results.jsonl 含转录与 frame_payloads):① 评测脚本/场景自身缺陷(锚点被新措辞击穿、场景语义设计错、接口变更等)→ 修脚本并提交;② agent 行为缺陷 → 定位根因,能修则按仓库提交规范修复并提交(提交说明只写说明本身,不加任何尾注;涉及契约变化须同批改契约测试,提交前全量 pytest + ruff 双服务验证),不能定位 → 确认坏例池已入档即止,留晨审;③ 性能与优化(p95 超预算、并发失败、慢端点)→ 只列晨审优化清单,严禁夜间自动改性能代码;评测脚本自身性能缺陷(超时参数等)除外可修。
4. 代码评审:调用 Skill 工具执行 code-review,评审基点 = 昨晚评审收尾时的提交(用 git log 找最近 24h 内全部提交;当日无提交则本步跳过)。评审发现分级处置:文档/注释/测试类小问题直接修复提交;行为代码修复须全量 pytest + ruff 双服务验证后提交;设计级争议与大型重构列晨审清单,严禁夜间大改。
5. CHANGELOG 回填自检:读 /Users/weizheng/Desktop/test/ai/agent-all/CHANGELOG.md 最新条目日期;若已是今日 → 跳过;若早于今日且 git log 自该日期后日期有提交 → 按日写主题式摘要条目补齐(格式仿既有条目:`## [x.y.z] - 日期 (主题句)` + ✨/🔧/🐛/🧪 小节;版本号顺延——功能/架构日次版本 +1、小修日补丁位 +1,以文件中最新条目为基;主题聚类自当日提交主题忠实合成,不逐笔流水,含关键提交哈希锚点),插于文件最新条目之上;当日无提交则跳过;写完提交(docs(changelog): 回填 x.y.z …)。纯 reformat/文档日可并入相邻日,不空占版本号。
6. 调度说明:本任务由 macOS launchd 系统调度(com.aurora.nightly-eval,每天 23:00),无 7 天过期、无需自续期;若发现 .claude/scheduled_tasks.json 里存在同内容的旧 durable cron 任务(每日 23:00 夜间评测),一律 CronDelete 删除防双跑。
7. 收尾给一行摘要:严格通过 x/y、新失败清单、已修项、评审发现数与处置、CHANGELOG 回填情况、报告路径。
PROMPT_EOF
)
fi

claude -p "$PROMPT" --dangerously-skip-permissions >> "$LOGDIR/launchd.log" 2>&1
rc=$?
echo "[$(date '+%F %T')] === nightly exit=$rc (mode=$MODE) ===" >> "$LOGDIR/launchd.log"
exit "$rc"
