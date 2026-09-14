#!/bin/sh
# 在容器里循环跑同步。
#
#   sh run.sh          一直跑（每 interval_seconds 一轮）
#   sh run.sh --once   只跑一轮
#
# 是否真写数据由 config.json 的 apply 决定；apply 为 false 时只算不写。
# 日志默认落在 state_dir/run.log，超过 5MB 轮转一份 .1。

set -u

HERE=$(cd "$(dirname "$0")" && pwd)
PY=${RPB_PYTHON:-python3}
STATE=${RPB_STATE_DIR:-/var/tmp/reading-progress-bridge}
LOG=${RPB_LOG:-$STATE/run.log}

mkdir -p "$STATE" 2>/dev/null || true

rotate() {
    if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 5242880 ]; then
        mv "$LOG" "$LOG.1"
    fi
}

if [ "${1:-}" = "--once" ]; then
    "$PY" "$HERE/bridge.py" sync
    exit $?
fi

INTERVAL=$("$PY" -c "import sys; sys.path.insert(0, '$HERE'); import bridge; print(bridge.INTERVAL)" 2>/dev/null)
case "$INTERVAL" in
    ''|*[!0-9]*) INTERVAL=300 ;;
esac

echo "进度桥：每 $INTERVAL 秒一轮，数据目录 $(cd "$HERE/.." && pwd)，日志 $LOG"
while :; do
    rotate
    "$PY" "$HERE/bridge.py" sync >>"$LOG" 2>&1
    sleep "$INTERVAL"
done
