#!/bin/bash
# health_watch.sh —— B 机自监控 + 微信告警(Server酱 / 企业微信机器人二选一)
#
# 设计(2026-10-25):2C2G 小机零常驻,cron 每 5 分钟巡检;告警按 key 冷却
# (默认 30 分钟,CRITICAL 与恢复通知不受冷却压制首次);状态落
# deploy/.watch/ 目录。磁盘检查是第一公民 —— 2026-10-24 网关镜像(19.8GB)
# 拉取曾把 50G 盘写爆(failed commit on ref),此类事故提前 85% 阈值预警。
#
# 用法:
#   health_watch.sh            # 巡检 + 按需告警(cron 调用形态)
#   health_watch.sh --dry-run  # 只打印判定,不发不写状态(部署验收用)
#   health_watch.sh --test     # 发送一条测试消息(验证微信通道)
#
# 凭据(服务器侧 .env.prod 追加,不入库;两者都配则企业微信优先):
#   WATCH_SENDKEY=SCTxxxx                                # Server酱·个人微信
#   WATCH_WECOM_WEBHOOK=https://qyapi.weixin.qq.com/...  # 企业微信群机器人
# 阈值/目标可覆写(同文件):WATCH_DISK_PCT(85) WATCH_DISK_MIN_GB(8)
#   WATCH_MEM_PCT(92) WATCH_LOAD1(6) WATCH_COOLDOWN(1800) WATCH_PG_ADDR(10.10.0.1:5433)
# 注:Server酱免费额度 5 条/天,重度告警场景建议企业微信机器人(近无限额)。

set -u

DRY_RUN=0; TEST_MODE=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY_RUN=1 ;;
    --test) TEST_MODE=1 ;;
  esac
done

ENV_FILE="${ENV_FILE:-$HOME/agent-all/deploy/.env.prod}"
# 只提取 WATCH_* 行(.env.prod 其余值可能含特殊字符,不整文件 source)
if [ -f "$ENV_FILE" ]; then
  while IFS='=' read -r k v; do
    [ -n "${!k:-}" ] || export "$k=$v"
  done < <(grep -E '^WATCH_[A-Z0-9_]+=' "$ENV_FILE" 2>/dev/null)
fi

DISK_PCT="${WATCH_DISK_PCT:-85}"
DISK_MIN_GB="${WATCH_DISK_MIN_GB:-8}"
MEM_PCT="${WATCH_MEM_PCT:-92}"
LOAD1_MAX="${WATCH_LOAD1:-6}"
COOLDOWN="${WATCH_COOLDOWN:-1800}"
PG_ADDR="${WATCH_PG_ADDR:-10.10.0.1:5433}"

BASE_DIR="$HOME/agent-all/deploy"
STATE_DIR="$BASE_DIR/.watch"
mkdir -p "$STATE_DIR"
# cron.log 自截断(>1MB 清零;2C2G 小盘不留无界日志)
WATCH_LOG="$STATE_DIR/cron.log"
[ -f "$WATCH_LOG" ] && [ "$(stat -c%s "$WATCH_LOG" 2>/dev/null || echo 0)" -gt 1048576 ] && : > "$WATCH_LOG"
NOW=$(date +%s)

# ---------------------------------------------------------------- 通知通道
send_wechat() {
  local title="$1" body="$2"
  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] $title"
    echo "$body" | sed 's/^/  | /'
    return 0
  fi
  if [ -n "${WATCH_WECOM_WEBHOOK:-}" ]; then
    local payload
    payload=$(python3 - "$title" "$body" <<'PY'
import json, sys
print(json.dumps({"msgtype": "text", "text": {"content": sys.argv[1] + "\n" + sys.argv[2]}}, ensure_ascii=False))
PY
)
    curl -s -m 10 -H 'Content-Type: application/json' -d "$payload" "$WATCH_WECOM_WEBHOOK" >/dev/null
  elif [ -n "${WATCH_SENDKEY:-}" ]; then
    curl -s -m 10 -G "https://sctapi.ftqq.com/${WATCH_SENDKEY}.send" \
      --data-urlencode "title=$title" --data-urlencode "desp=$body" >/dev/null
  else
    echo "[watch] 未配置 WATCH_SENDKEY / WATCH_WECOM_WEBHOOK,告警只落日志"
  fi
}

# ------------------------------------------------------- 巡检项(追加即扩展)
# 输出行: KEY|LEVEL|detail   LEVEL ∈ CRITICAL|WARN
FAIL_LINES=""

check() {  # check KEY LEVEL detail
  FAIL_LINES="${FAIL_LINES}$1|$2|$3
"
}

# ① 磁盘(第一公民:10-24 实弹事故)
read -r DISK_USED DISK_GB <<<"$(df -Pm / | awk 'NR==2{print $5, $4/1024}')"
DISK_USED=${DISK_USED%\%}
if [ "${DISK_USED:-0}" -ge "$DISK_PCT" ]; then
  check disk_root CRITICAL "根分区 ${DISK_USED}%(阈值 ${DISK_PCT}%),剩 ${DISK_GB%.*}GB —— 大镜像拉取前先清理"
elif [ "${DISK_GB%.*}" -le "$DISK_MIN_GB" ]; then
  check disk_root CRITICAL "根分区仅剩 ${DISK_GB%.*}GB(下限 ${DISK_MIN_GB}GB)"
fi

# ② 内存(2G 小机)
MEM_USED_PCT=$(free -m | awk '/^Mem:/{printf "%.0f", $3/$2*100}')
if [ "${MEM_USED_PCT:-0}" -ge "$MEM_PCT" ]; then
  check mem WARN "内存 ${MEM_USED_PCT}%(阈值 ${MEM_PCT}%)"
fi

# ③ 负载(2C)
LOAD1=$(cut -d' ' -f1 /proc/loadavg)
LOAD_HIT=$(awk -v l="$LOAD1" -v m="$LOAD1_MAX" 'BEGIN{print (l>=m)?1:0}')
if [ "$LOAD_HIT" = 1 ]; then
  check load WARN "load1=${LOAD1}(阈值 ${LOAD1_MAX})"
fi

# ④ 三容器运行+健康 + 重启计数增量
for c in web gateway redis; do
  CS=$(docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "smartserve-prod-$c-1" 2>/dev/null || echo missing)
  if [ "$CS" != "running/healthy" ]; then
    check "container_$c" CRITICAL "容器状态 ${CS}(期望 running/healthy)"
  fi
  RC=$(docker inspect -f '{{.RestartCount}}' "smartserve-prod-$c-1" 2>/dev/null || echo 0)
  RC_FILE="$STATE_DIR/restart_$c"
  RC_PREV=$(cat "$RC_FILE" 2>/dev/null || echo "$RC")
  if [ "$RC" -gt "$RC_PREV" ]; then
    check "container_$c" WARN "重启计数 ${RC_PREV}→${RC}(崩溃循环嫌疑)"
  fi
  [ "$DRY_RUN" = 0 ] && echo "$RC" > "$RC_FILE"
done

# ⑤ gateway 健康(回环;4000 已绑 127.0.0.1)
if ! curl -sf -m 5 http://127.0.0.1:4000/api/health >/dev/null 2>&1; then
  check gateway_http CRITICAL "127.0.0.1:4000/api/health 不可达"
fi

# ⑥ 四前端 /healthz
for p in 3000 3001 3005 3006; do
  if ! curl -sf -m 5 "http://127.0.0.1:$p/healthz" >/dev/null 2>&1; then
    check "frontend_$p" CRITICAL "前端 :$p/healthz 不可达"
  fi
done

# ⑦ A 机 PG 连通(TCP 层)
PG_HOST=${PG_ADDR%%:*}; PG_PORT=${PG_ADDR##*:}
if ! timeout 3 bash -c "</dev/tcp/$PG_HOST/$PG_PORT" 2>/dev/null; then
  check pg_reach CRITICAL "PG ${PG_ADDR} TCP 不通(全站数据库失联)"
fi

# ------------------------------------------------- 冷却/恢复/发送(逐 key)
HOST_TAG="B机 $(hostname) $(date '+%m-%d %H:%M')"

if [ "$TEST_MODE" = 1 ]; then
  send_wechat "✅ health_watch 通道测试" "$HOST_TAG

巡检 ${#FAIL_LINES}+ 项通道连通性验证消息。收到即链路可用。"
  echo "test 消息已触发(配置正确则微信可见)"
  exit 0
fi

SENT_NEW=(); SENT_RECOVER=(); STILL_FAIL=()
while IFS='|' read -r key level detail; do
  [ -z "$key" ] && continue
  last_file="$STATE_DIR/${key}.last"; state_file="$STATE_DIR/${key}.state"
  last_sent=$(cat "$last_file" 2>/dev/null || echo 0)
  prev_state=$(cat "$state_file" 2>/dev/null || echo OK)

  if [ $((NOW - last_sent)) -ge "$COOLDOWN" ]; then
    send_wechat "⚠️ ${level}: ${key}" "$HOST_TAG

${detail}

(冷却 ${COOLDOWN}s 内不重发同 key)"
    if [ "$DRY_RUN" = 0 ]; then echo "$NOW" > "$last_file"; echo FAIL > "$state_file"; fi
    SENT_NEW+=("$key")
  else
    [ "$DRY_RUN" = 0 ] && echo FAIL > "$state_file"
    STILL_FAIL+=("$key")
  fi
done <<< "$FAIL_LINES"

# 恢复通知:上一轮 FAIL 且本轮不在失败清单 → 发恢复 + 清状态
for state_file in "$STATE_DIR"/*.state; do
  [ -e "$state_file" ] || continue
  key=$(basename "$state_file" .state)
  grep -q "^$key|" <<< "$FAIL_LINES" && continue
  [ "$(cat "$state_file")" = "FAIL" ] || continue
  send_wechat "✅ 恢复: ${key}" "$HOST_TAG"
  if [ "$DRY_RUN" = 0 ]; then echo OK > "$state_file"; rm -f "$STATE_DIR/${key}.last"; fi
  SENT_RECOVER+=("$key")
done

if [ "$DRY_RUN" = 1 ]; then
  echo "[dry-run] 失败项 ${#SENT_NEW[@]} 新发 / ${#STILL_FAIL[@]} 冷却中 / ${#SENT_RECOVER[@]} 恢复"
else
  echo "$(date '+%F %T') new=${#SENT_NEW[@]} cooling=${#STILL_FAIL[@]} recovered=${#SENT_RECOVER[@]}"
fi
