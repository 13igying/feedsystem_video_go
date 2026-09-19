#!/usr/bin/env bash
# 内网穿透管理脚本：把 8081(运行器)/5173(前端)/8080(后端) 暴露到公网
# 用法:
#   ./tunnel.sh start   启动 3 条 Cloudflare 隧道（后台）
#   ./tunnel.sh stop    停止全部隧道
#   ./tunnel.sh status  查看当前公网地址
set -u
cd "$(dirname "$0")/.."   # 项目根目录

LOGDIR=/tmp
declare -A MAP=( [8081]=cf_8081 [5173]=cf_5173 [8080]=cf_8080 )

start() {
  for port in 8081 5173 8080; do
    if pgrep -f "cloudflared tunnel --url http://localhost:$port" >/dev/null; then
      echo "[$port] 隧道已在运行"
    else
      nohup cloudflared tunnel --url "http://localhost:$port" \
        > "$LOGDIR/${MAP[$port]}.log" 2>&1 &
      echo "[$port] 隧道启动中…"
    fi
  done
  sleep 12
  status
}

stop() {
  pkill -f "cloudflared tunnel" && echo "已停止全部隧道" || echo "没有运行中的隧道"
}

status() {
  for port in 8081 5173 8080; do
    url=$(grep -o "https://[a-z0-9-]*\.trycloudflare\.com" "$LOGDIR/${MAP[$port]}.log" 2>/dev/null | head -1)
    if [ -n "$url" ]; then
      case $port in
        8081) desc="Web 测试运行器";;
        5173) desc="前端页面";;
        8080) desc="后端 API";;
      esac
      printf "%-10s %-10s %s\n" "$desc" "端口$port" "$url"
    else
      echo "端口 $port：隧道未运行"
    fi
  done
}

case "${1:-status}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) echo "用法: $0 {start|stop|status}"; exit 1 ;;
esac