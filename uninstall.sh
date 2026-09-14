#!/bin/sh
# 卸掉装进容器里的进度桥。
#
#   sh uninstall.sh [容器名] [宿主上的数据目录]          停掉循环（脚本目录留着）
#   sh uninstall.sh [容器名] [宿主上的数据目录] --purge  再删掉脚本目录与定时补齐记录
#
# 只停进程、删自己装进去的东西，不动书库、阅读进度与备份。

set -eu

NAME=""
DATA=""
PURGE=0

for a in "$@"; do
    case "$a" in
        --purge) PURGE=1 ;;
        --*) echo "不认识的选项：$a"; exit 1 ;;
        *) if [ -z "$NAME" ]; then NAME="$a"
           elif [ -z "$DATA" ]; then DATA="$a"; fi ;;
    esac
done

command -v docker >/dev/null 2>&1 || { echo "没有 docker"; exit 1; }

if [ -z "$NAME" ]; then
    NAME=$(docker ps --format '{{.Names}} {{.Image}}' | grep -i talebook | head -1 | cut -d' ' -f1 || true)
fi
[ -n "$NAME" ] || { echo "找不到 Talebook 容器，请把容器名传进来"; exit 1; }

if [ -z "$DATA" ]; then
    DATA=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$NAME")
fi
DST="$DATA/.reading-progress-bridge"

if docker exec "$NAME" sh -c 'test -d /etc/supervisor/conf.d' >/dev/null 2>&1; then
    docker exec "$NAME" supervisorctl stop progress-bridge >/dev/null 2>&1 && echo "停了受管程序 progress-bridge" || true
    docker exec "$NAME" rm -f /etc/supervisor/conf.d/progress-bridge.conf >/dev/null 2>&1 || true
    docker exec "$NAME" supervisorctl reread >/dev/null 2>&1 || true
    docker exec "$NAME" supervisorctl update >/dev/null 2>&1 || true
    echo "删了容器里的 /etc/supervisor/conf.d/progress-bridge.conf"
fi

docker exec "$NAME" pkill -f '\.reading-progress-bridge/run\.sh' >/dev/null 2>&1 && echo "停了后台循环" || true

# 还原 WebDAV 事件触发补丁（只还原首次备份，不动数据）
DAV=/var/www/talebook/webserver/webdav/dav_provider.py
EVENT_BACKUP=/var/tmp/reading-progress-bridge/webdav-backup/dav_provider.py
if docker exec "$NAME" sh -c "test -f '$EVENT_BACKUP' && test -f '$DAV'" >/dev/null 2>&1; then
    docker exec -u root "$NAME" cp "$EVENT_BACKUP" "$DAV"
    docker exec -u root "$NAME" rm -f /opt/reading-progress-bridge/trigger.sh
    docker exec "$NAME" supervisorctl restart tornado >/dev/null 2>&1 || true
    echo "还原了 Talebook WebDAV 文件（备份保留在 $EVENT_BACKUP）"
fi

if [ "$PURGE" = 1 ]; then
    if [ -n "$DATA" ] && [ -d "$DST" ]; then
        docker exec -u root "$NAME" rm -rf "$DST" >/dev/null 2>&1 || rm -rf "$DST"
        echo "删了 $DST"
    fi
    if [ -f /etc/cron.d/reading-progress-bridge ] && grep -q 'install.sh --rearm' /etc/cron.d/reading-progress-bridge 2>/dev/null; then
        rm -f /etc/cron.d/reading-progress-bridge && echo "删了 /etc/cron.d/reading-progress-bridge"
    fi
    echo "容器里的状态与日志还在（/var/tmp/reading-progress-bridge），容器重建即消失："
    echo "  docker exec $NAME rm -rf /var/tmp/reading-progress-bridge"
fi

echo ""
echo "已经写进去的阅读进度不动；要还原，把 reader/<用户号>/backup/bridge/ 下的备份拷回去。"
