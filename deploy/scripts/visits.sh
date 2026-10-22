#!/usr/bin/env bash
# 访问分析一键入口(B 机 / 部署机运行,2026-10-22)—— 「谁看过我这个网站」的数据面。
#
# 数据源:smartserve-prod-web 容器双写到持久卷的 nginx access.log(combined+端口尾列(log_format analytics);
# 卷名 smartserve-prod_nginx_logs,由 deploy/docker-compose.prod.yml 定义)。
# 分析器:goaccess 官方镜像按需起、用完即焚,B 机(2C4G)无常驻开销。
#
# 用法:
#   bash visits.sh                # 终端交互报表(默认):独立访客/IP/UA/URL/时间分布
#   bash visits.sh --html         # 生成 HTML 快照 → http://<服务器>:3001/reports/report.html
#                                 #   (基本认证 admin/<密码>;首次生成随机密码并打印一次)
#   bash visits.sh --set-password # 改报表访问密码(交互输入)
#   bash visits.sh --tail [N]     # 原始日志快看(缺省 50 条;healthz 已滤)
#   bash visits.sh --raw N        # 不过滤的最后 N 条(含健康检查,排查用)
#
# 说明:
#   - 终端模式经 SSH 直接看,最常用;HTML 模式适合手机上翻(每次运行刷新快照)。
#   - 镜像源可覆写:GOACCESS_IMG 环境变量(缺省 docker.io/allinone/goaccess:1.9.3)。
#     国内网络直连 docker.io 拉不动时,先 `export GOACCESS_IMG=docker.m.daocloud.io/allinone/goaccess:1.9.3`
#     或预拉同 tag 后 `docker tag` 回缺省名(与 CI 部署步的代理预拉套路同型)。
#   - 日志无界增长由本脚本不负轮转之责:低流量(作品集级)数月无虞,若要收紧
#     可在宿主 cron 里定期 `docker run --rm -v smartserve-prod_nginx_logs:/l alpine \
#     sh -c 'tail -n 50000 /l/access.log > /l/a && mv /l/a /l/access.log'`。

set -euo pipefail

VOL="smartserve-prod_nginx_logs"
GOACCESS_IMG="${GOACCESS_IMG:-docker.io/allinone/goaccess:1.9.3}"
REPORT="report.html"
# 与 deploy/nginx.conf 的 log_format analytics 逐 token 对齐(combined + 尾列
# $server_port → %v,端口即四端区分:3000=web 3001=admin 3005=merchant 3006=merchant-admin)。
# 格式串含空格与引号 —— 经环境变量传入容器、容器内 "$LOGFMT" 整体引用,
# 严禁拼进 sh -c 命令串(词法拆碎)。必须 export:`docker run -e VAR`(裸形式)
# 只透传 docker CLI 进程环境中的变量,未 export 的 shell 变量到不了容器
# (2026-10-22 夜评实证:漏 export 时容器内格式串为空、goaccess 全量误解析)。
LOGFMT='%h %^[%d:%t %^] "%r" %s %b "%R" "%u" %v'
DATEFMT='%d/%b/%Y'
TIMEFMT='%H:%M:%S'
export LOGFMT DATEFMT TIMEFMT

say() { printf '\033[1;36m[visits]\033[0m %s\n' "$*"; }

htpasswd_exists() {
  docker run --rm -v "$VOL":/logs:ro alpine:3.20 \
    sh -c "[ -f /logs/.htpasswd ]" 2>/dev/null
}

write_htpasswd() { # $1=密码(明文,经 stdin 进 httpd 容器 —— alpine 无 openssl,
                   # 用 httpd 自带 htpasswd 工具;不进 argv/env/ps)
  printf '%s\n' "$1" | docker run --rm -i -v "$VOL":/logs httpd:2.4-alpine \
    sh -c 'htpasswd -ni admin > /logs/.htpasswd'
}

ensure_htpasswd() {
  if htpasswd_exists; then return 0; fi
  local pw
  pw="$(docker run --rm alpine:3.20 sh -c \
    'tr -dc A-Za-z0-9 </dev/urandom 2>/dev/null | head -c 12' || true)"
  [ -n "$pw" ] || { say "随机密码生成失败,改用固定缺省(请尽快 --set-password 换)"; pw="smartserve-$(date +%s)"; }
  write_htpasswd "$pw"
  say "报表密码已生成(仅此一次显示):admin / $pw"
  say "记不住就重设:bash visits.sh --set-password"
}

case "${1:-}" in
  --raw)
    n="${2:-30}"
    docker run --rm -v "$VOL":/logs:ro alpine:3.20 tail -n "$n" /logs/access.log
    ;;
  --tail)
    n="${2:-50}"
    # n 经 "$1" 传参整体引用 —— 此前拼进 sh -c 命令串,操作员参数含空格/; 即容器内注入面
    docker run --rm -v "$VOL":/logs:ro alpine:3.20 \
      sh -c 'tail -n "$1" /logs/access.log | grep -v healthz' _ "$n"
    ;;
  --set-password)
    # Ctrl-C 中断于 read 时恢复终端回显(缺省 trap 覆盖正常/异常两路退出)
    trap 'stty echo 2>/dev/null || true' EXIT
    printf '新密码: ' >&2; stty -echo; read -r pw; stty echo; printf '\n' >&2
    [ -n "$pw" ] || { say "空密码,未改"; exit 1; }
    write_htpasswd "$pw"
    say "密码已更新(报表可能被浏览器缓存旧 401,重开无痕窗验证)"
    ;;
  --html)
    ensure_htpasswd
    # goaccess 读 stdin 出静态 HTML(滤 healthz);失败则退化为整文件直读
    docker run --rm -e LOGFMT -e DATEFMT -e TIMEFMT --entrypoint /bin/sh -v "$VOL":/logs "$GOACCESS_IMG" \
      -c 'grep -hv healthz /logs/access.log | goaccess /dev/stdin \
          --log-format "$LOGFMT" --date-format "$DATEFMT" --time-format "$TIMEFMT" --no-progress -o /logs/'"$REPORT" || \
    docker run --rm -e LOGFMT -e DATEFMT -e TIMEFMT --entrypoint /bin/sh -v "$VOL":/logs "$GOACCESS_IMG" \
      -c 'goaccess /logs/access.log --log-format "$LOGFMT" --date-format "$DATEFMT" --time-format "$TIMEFMT" \
          --no-progress -o /logs/'"$REPORT"
    say "快照已生成:http://<服务器>:3001/reports/$REPORT (admin/密码;visits.sh --set-password 可改)"
    ;;
  ""|--term|*)
    docker run --rm -it -e LOGFMT -e DATEFMT -e TIMEFMT --entrypoint /bin/sh -v "$VOL":/logs:ro "$GOACCESS_IMG" \
      -c 'grep -hv healthz /logs/access.log | goaccess /dev/stdin \
          --log-format "$LOGFMT" --date-format "$DATEFMT" --time-format "$TIMEFMT"'
    ;;
esac
