#!/bin/sh
# WebDAV 写完阅读进度文件后调用。由 install.sh 注入 Talebook 容器。
set -eu
DATA=/data/.reading-progress-bridge
LOCK=/var/tmp/reading-progress-bridge/event-trigger.lock
LOG=/var/tmp/reading-progress-bridge/run.log
mkdir -p "$(dirname "$LOCK")"
sleep "${RPB_EVENT_DEBOUNCE:-5}"
if ! mkdir "$LOCK" 2>/dev/null; then
    printf '%s event trigger skipped: another run is active\n' "$(date '+%F %T')" >>"$LOG"
    exit 0
fi
cleanup() { rmdir "$LOCK" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
printf '%s event trigger started\n' "$(date '+%F %T')" >>"$LOG"
set +e
python3 "$DATA/bridge.py" sync >>"$LOG" 2>&1
status=$?
set -e
printf '%s event trigger finished status=%s\n' "$(date '+%F %T')" "$status" >>"$LOG"
exit "$status"
