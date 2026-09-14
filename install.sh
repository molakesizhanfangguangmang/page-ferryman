#!/bin/sh
# 把进度桥装进 Talebook 容器。在宿主机上跑（能执行 docker 的那台机器）。
#
#   sh install.sh [容器名] [宿主上的数据目录] [选项]
#
# 选项：
#   --apply         把 config.json 的 apply 改成 true（默认 false，装完先干跑）
#   --no-start      只放文件与配置，不启动循环
#   --rearm         静默补齐：只保证容器里的循环在跑，不复制文件、不扫描（定时任务用）
#   --install-cron  写一条 /etc/cron.d 记录，每 5 分钟跑一次 --rearm（要 root）
#   --quiet         少说话
#
# 装完的样子：
#   <数据目录>/.reading-progress-bridge/   脚本与配置（在数据卷上，容器重建不掉）
#   容器里 /etc/supervisor/conf.d/progress-bridge.conf  受管程序（有 supervisord 时）
#   或容器里一个后台循环（没有 supervisord 时）
#
# 容器重建之后受管程序会丢，重跑一次本脚本即可；或者用 --install-cron 让定时任务每 5 分钟补一次。

set -eu

SRC=$(cd "$(dirname "$0")" && pwd)
NAME=""
DATA=""
START=1
REARM=0
CRON=0
QUIET=0
WANT_APPLY=""

for a in "$@"; do
    case "$a" in
        --apply) WANT_APPLY=1 ;;
        --no-start) START=0 ;;
        --rearm) REARM=1; START=1 ;;
        --install-cron) CRON=1 ;;
        --quiet) QUIET=1 ;;
        --*) echo "不认识的选项：$a"; exit 1 ;;
        *) if [ -z "$NAME" ]; then NAME="$a"
           elif [ -z "$DATA" ]; then DATA="$a"; fi ;;
    esac
done

say() { [ "$QUIET" = 1 ] || echo "$@"; }
die() { echo "$@" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "没有 docker，这个脚本要在能跑 docker 的机器上执行"
docker ps >/dev/null 2>&1 || die "docker 用不了（会跑 docker 的话请用 root 或加进 docker 组）"

# ---------------------------------------------------------------- 找到容器
if [ -z "$NAME" ]; then
    NAME=$(docker ps --format '{{.Names}} {{.Image}}' | grep -i talebook | head -1 | cut -d' ' -f1 || true)
fi
[ -n "$NAME" ] || { echo "找不到 Talebook 容器，请把容器名当第一个参数传进来："; docker ps --format '  {{.Names}}  ({{.Image}})'; exit 1; }
docker ps --format '{{.Names}}' | grep -qx "$NAME" || die "容器 $NAME 没在跑"

# ---------------------------------------------------------------- 数据目录
if [ -z "$DATA" ]; then
    DATA=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' "$NAME")
fi
[ -n "$DATA" ] || die "容器 $NAME 没有挂到 /data 的卷，把宿主上的数据目录当第二个参数传进来"
[ -d "$DATA" ] || die "数据目录不存在：$DATA"

MOUNT=$(docker inspect -f "{{range .Mounts}}{{if eq .Source \"$DATA\"}}{{.Destination}}{{end}}{{end}}" "$NAME" 2>/dev/null || true)
[ -n "$MOUNT" ] || MOUNT="/data"

DST="$DATA/.reading-progress-bridge"
INNER="$MOUNT/.reading-progress-bridge"

# ---------------------------------------------------------------- 进度是谁的：拿属主当跑的身份
OWNER=$(docker exec "$NAME" python3 -c "
import glob, os
for p in sorted(glob.glob('/data/reader/*/*')) + sorted(glob.glob('/data/reader/*')) + ['/data']:
    try:
        st = os.stat(p)
    except OSError:
        continue
    print('%d:%d' % (st.st_uid, st.st_gid))
    break
" 2>/dev/null || true)
[ -n "$OWNER" ] || OWNER="0:0"
UID_PART=${OWNER%%:*}
GID_PART=${OWNER##*:}

# supervisord 认用户名，这里把 uid 翻成名字（翻不到就用 uid 本身）
USER_NAME=$(docker exec "$NAME" python3 -c "
import pwd
try:
    print(pwd.getpwuid($UID_PART).pw_name)
except KeyError:
    print('$UID_PART')
" 2>/dev/null || echo "$UID_PART")

HAVE_SUPERVISOR=0
if docker exec "$NAME" sh -c 'test -d /etc/supervisor/conf.d && test -x /usr/bin/supervisorctl' >/dev/null 2>&1; then
    HAVE_SUPERVISOR=1
fi

supp_status() {
    docker exec "$NAME" supervisorctl status progress-bridge 2>/dev/null | awk '{print $2}' || true
}

alive_in_proc() {
    docker exec "$NAME" sh -c 'for f in /proc/[0-9]*/cmdline; do tr "\000" "\n" < "$f" 2>/dev/null | grep -q "reading-progress-bridge/run.sh" && exit 0; done; exit 1' >/dev/null 2>&1
}

rearm() {
    if [ "$HAVE_SUPERVISOR" = 1 ]; then
        if ! docker exec "$NAME" sh -c 'test -f /etc/supervisor/conf.d/progress-bridge.conf' >/dev/null 2>&1; then
            [ -f "$DST/run.sh" ] || { say "没装过，先跑一次不带 --rearm 的 install.sh"; return 1; }
            write_conf
        fi
        if [ "$(supp_status)" != "RUNNING" ]; then
            docker exec "$NAME" supervisorctl reread >/dev/null 2>&1 || true
            docker exec "$NAME" supervisorctl update >/dev/null 2>&1 || true
            docker exec "$NAME" supervisorctl start progress-bridge >/dev/null 2>&1 || true
            say "$(date '+%F %T') 容器 $NAME 里的循环没在跑，已拉起"
        fi
        return 0
    fi
    if ! alive_in_proc; then
        docker exec -d -u "$OWNER" "$NAME" sh "$INNER/run.sh" 2>/dev/null \
            || docker exec -d "$NAME" sh "$INNER/run.sh" \
            || { say "拉不起来"; return 1; }
        say "$(date '+%F %T') 容器 $NAME 里的循环没在跑，已拉起"
    fi
    return 0
}

write_conf() {
    TMP=$(mktemp)
    cat > "$TMP" <<EOF
; 阅读进度桥：每轮把三边进度对齐。由 install.sh 写入，删掉这个文件再 supervisorctl update 即可卸载。
[program:progress-bridge]
command=sh $INNER/run.sh
directory=$INNER
user=$USER_NAME
autostart=true
autorestart=true
startsecs=3
stopasgroup=true
killasgroup=true
redirect_stderr=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
EOF
    docker cp "$TMP" "$NAME:/etc/supervisor/conf.d/progress-bridge.conf" >/dev/null
    rm -f "$TMP"
}

# ---------------------------------------------------------------- --rearm：只保证在跑
if [ "$REARM" = 1 ]; then
    rearm
    exit $?
fi

# ---------------------------------------------------------------- 放文件
say "容器      $NAME"
say "数据目录  $DATA（容器里 $MOUNT）"
say "跑的身份  $OWNER（$USER_NAME）"
say "装到      $DST"

mkdir -p "$DST" 2>/dev/null || true
[ -d "$DST" ] || die "写不进 $DATA，用 root 或 sudo 跑：sudo sh $0 $NAME $DATA"
[ -w "$DST" ] || die "写不进 $DST，用 root 或 sudo 跑：sudo sh $0 $NAME $DATA"

for f in bridge.py cfi.py txt.py run.sh README.md config.example.json install.sh uninstall.sh LICENSE; do
    [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DST/$f"
done
chmod +x "$DST/run.sh" 2>/dev/null || true

if [ ! -f "$DST/config.json" ]; then
    cat > "$DST/config.json" <<'JSON'
{
  "_说明": "apply 改成 true 才会真写数据；interval_seconds 是每轮间隔；skip_books 里写要跳过的书库编号；改完重跑 install.sh 生效。",
  "data": "/data",
  "reader_user": "",
  "interval_seconds": 300,
  "threshold_chars": 200,
  "threshold_percent": 0.3,
  "apply": false,
  "state_dir": "/var/tmp/reading-progress-bridge",
  "rules_file": "",
  "skip_books": []
}
JSON
    say "配置      $DST/config.json（apply=false，先干跑）"
fi

if [ -n "$WANT_APPLY" ]; then
    sed -i.bak 's/"apply": *false/"apply": true/' "$DST/config.json" && rm -f "$DST/config.json.bak"
    say "配置      apply 已改成 true"
fi

# 进度文件是那个 uid 的，脚本目录也给它，免得它写不动规则副本与状态
docker exec -u root "$NAME" chown -R "$OWNER" "$INNER" 2>/dev/null || true

# ---------------------------------------------------------------- 起循环
if [ "$START" = 1 ]; then
    if [ "$HAVE_SUPERVISOR" = 1 ]; then
        write_conf
        docker exec "$NAME" supervisorctl reread >/dev/null 2>&1 || true
        docker exec "$NAME" supervisorctl update >/dev/null 2>&1 || true
        docker exec "$NAME" supervisorctl start progress-bridge >/dev/null 2>&1 || true
        say "受管程序  /etc/supervisor/conf.d/progress-bridge.conf（$(supp_status)）"
    else
        docker exec -d -u "$OWNER" "$NAME" sh "$INNER/run.sh" 2>/dev/null \
            || docker exec -d "$NAME" sh "$INNER/run.sh" \
            || die "起循环失败"
        say "后台循环  已起（容器重建后要重跑本脚本）"
    fi
fi

# ---------------------------------------------------------------- 干跑一遍
say ""
say "干跑一遍看对齐结果："
docker exec -u "$OWNER" "$NAME" python3 "$INNER/bridge.py" sync || true

# ---------------------------------------------------------------- 定时补齐
if [ "$CRON" = 1 ]; then
    LINE="*/5 * * * * root sh $DST/install.sh --rearm --quiet >> /var/log/reading-progress-bridge-cron.log 2>&1"
    if [ "$(id -u)" = "0" ]; then
        printf '# 阅读进度桥：容器重建/重启后把容器里的循环补起来\n%s\n' "$LINE" > /etc/cron.d/reading-progress-bridge
        chmod 644 /etc/cron.d/reading-progress-bridge
        say ""
        say "定时补齐  /etc/cron.d/reading-progress-bridge（每 5 分钟一次）"
    else
        say ""
        say "要它开机、容器重建后自己回来，用 root 把这个文件写好："
        say ""
        say "    # /etc/cron.d/reading-progress-bridge"
        say "    $LINE"
    fi
fi

say ""
say "日志（容器里）：docker exec $NAME tail -f /var/tmp/reading-progress-bridge/run.log"
if grep -q '"apply": *true' "$DST/config.json" 2>/dev/null; then
    say "现在是真写（apply=true）。要改回只算：把 $DST/config.json 的 apply 改成 false，再跑一次本脚本"
else
    say "想真写数据：把 $DST/config.json 的 apply 改成 true，再跑一次本脚本"
fi
