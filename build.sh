#!/bin/sh
# 打发布包。在仓库根目录跑：
#
#   sh build.sh            # 生成 tar.gz、单文件安装器、SHA256SUMS，并打印各自的 sha256
#   sh build.sh --verify   # 顺便自校验 + 跑通用自测 + 扫一遍本机字样
#
# 产物路径可以用环境变量改（Actions 里用得上）：
#   VERSION / OUT / SINGLE / RELEASE_NOTE
#
# 只打包下面 FILES 列的这些东西。缓存、状态、锁、切章规则副本、
# test/calibration.local.json（本机标定值）与真实数据一律不进包。

set -eu

VERSION=${VERSION:-1.0.2}
HERE=$(cd "$(dirname "$0")" && pwd)
FILES="README.md LICENSE .gitignore build.sh bridge.py cfi.py txt.py run.sh install.sh uninstall.sh config.example.json test/test_config.py test/test_cfi.py test/test_txt.py test/test_e2e_txt.py"
OUT=${OUT:-"$HERE/../reading-progress-bridge-v$VERSION.tar.gz"}
SINGLE=${SINGLE:-"$HERE/../install-reading-progress-bridge.sh"}
RELEASE_NOTE=${RELEASE_NOTE:-"$HERE/../RELEASE.md"}

cd "$HERE"

# 打包前清掉运行残留
rm -rf __pycache__ test/__pycache__
rm -f bridge-cache.json bridge.lock
[ -f txt-toc-rule.json ] && rm -f txt-toc-rule.json

sha256sum $FILES > SHA256SUMS

STAGE=$(mktemp -d)
mkdir -p "$STAGE/reading-progress-bridge"
tar cf - $FILES SHA256SUMS | (cd "$STAGE/reading-progress-bridge" && tar xf -)
tar czf "$OUT" -C "$STAGE" reading-progress-bridge

# ------------------------------------------------------------------ 单文件安装器
# 前面是脚本，__PAYLOAD__ 标记之后是整包的 base64（base64 字母表里没有下划线，
# 所以标记不会在载荷里出现）。
TARSHA=$(sha256sum "$OUT" | cut -d' ' -f1)

{
    cat <<EOF
#!/bin/sh
# 阅读进度桥 单文件安装器 v$VERSION
#
# 里面是 reading-progress-bridge-v$VERSION.tar.gz 的 base64。跑的时候先解开、
# 按包里的 SHA256SUMS 自校验，然后把参数原样交给包里的 install.sh。
#
# 用法（在能执行 docker 的宿主上）：
#   sudo sh install-reading-progress-bridge.sh [容器名] [数据目录] [选项]
#   sudo sh install-reading-progress-bridge.sh --install-cron        # 装完顺手写定时补齐
#   sh install-reading-progress-bridge.sh --extract-only DIR         # 只解开看看，不碰 docker
#
# 选项与默认行为见包里的 README.md。装完是干跑（apply=false）。

set -eu

VERSION=$VERSION
TAR_SHA256=$TARSHA
PAYLOAD_MARK=__PAYLOAD__

EXTRACT_ONLY=0
if [ "\${1:-}" = "--extract-only" ]; then
    EXTRACT_ONLY=1
    [ -n "\${2:-}" ] || { echo "用法：sh \$0 --extract-only DIR"; exit 1; }
    WORK=\$2
    mkdir -p "\$WORK"
else
    WORK=\$(mktemp -d)
    trap 'rm -rf "\$WORK"' EXIT INT TERM
fi

LINE=\$(grep -n "^\$PAYLOAD_MARK\$" "\$0" | head -1 | cut -d: -f1)
[ -n "\$LINE" ] || { echo "这个文件不完整：找不到内嵌载荷。重新下载一次。" >&2; exit 1; }

if ! tail -n +\$((LINE + 1)) "\$0" | base64 -d | tar xzf - -C "\$WORK"; then
    echo "载荷解不开：文件可能下载时被截断，重新下载一次。" >&2
    exit 1
fi

PKG=\$WORK/reading-progress-bridge
[ -f "\$PKG/install.sh" ] || { echo "解开的内容不对：\$PKG 里没有 install.sh" >&2; exit 1; }

if ! (cd "\$PKG" && sha256sum -c SHA256SUMS >/dev/null 2>&1); then
    echo "载荷自校验不过，别往下跑了：" >&2
    (cd "\$PKG" && sha256sum -c SHA256SUMS) >&2 || true
    exit 1
fi
echo "载荷自校验通过（v\$VERSION，sha256 \$TAR_SHA256）"

if [ "\$EXTRACT_ONLY" = "1" ]; then
    echo "解开到：\$PKG"
    exit 0
fi

exec sh "\$PKG/install.sh" "\$@"
__PAYLOAD__
EOF
    base64 "$OUT" | tr -d '\n'
    printf '\n'
} > "$SINGLE"
chmod 755 "$SINGLE" 2>/dev/null || true

# ------------------------------------------------------------------ 产物
{
    echo "产物 sha256（下完自己核一遍）："
    echo ""
    echo '```'
    sha256sum "$OUT" | sed "s|$HERE/../||"
    sha256sum "$SINGLE" | sed "s|$HERE/../||"
    echo '```'
    echo ""
    echo "装（单文件，最简单）："
    echo ""
    echo '```sh'
    echo "sudo sh install-reading-progress-bridge.sh"
    echo '```'
    echo ""
    echo "装（仓库源码）："
    echo ""
    echo '```sh'
    echo "sudo sh install.sh"
    echo '```'
    echo ""
    echo "包里的 SHA256SUMS 是包内各文件的校验和，解开后 \`sha256sum -c SHA256SUMS\` 用。"
} > "$RELEASE_NOTE"

echo "包：$OUT"
sha256sum "$OUT"
echo "单文件安装器：$SINGLE"
sha256sum "$SINGLE"

if [ "${1:-}" = "--verify" ]; then
    VDIR=$(mktemp -d)
    tar xzf "$OUT" -C "$VDIR"
    PKG="$VDIR/reading-progress-bridge"
    echo "--- 包内自校验 ---"
    (cd "$PKG" && sha256sum -c SHA256SUMS)

    echo "--- 单文件安装器：解开自校验 ---"
    XDIR=$(mktemp -d)
    sh "$SINGLE" --extract-only "$XDIR"
    diff -r "$PKG" "$XDIR/reading-progress-bridge" >/dev/null && echo "解开的内容与 tar 一致" \
        || { echo "！解开的内容与 tar 不一致"; exit 1; }
    rm -rf "$XDIR"

    echo "--- 通用自测（数据目录：${RPB_DATA:-/data}） ---"
    for t in test_config test_cfi test_txt test_e2e_txt; do
        if (cd "$PKG" && python3 "test/$t.py") > "$PKG/.test-$t.log" 2>&1; then
            tail -2 "$PKG/.test-$t.log"
        else
            echo "！$t 没通过："
            cat "$PKG/.test-$t.log"
            exit 1
        fi
        rm -f "$PKG/.test-$t.log"
    done

    echo "--- 包内不该有本机字样 ---"
    RPB_CAL="$HERE/test/calibration.local.json" python3 - "$PKG" <<'PY'
import json
import os
import sys

pkg = sys.argv[1]
needles = [n for n in os.environ.get("RPB_LEAK", "").split(",") if n]
cal = os.environ.get("RPB_CAL") or ""
if os.path.isfile(cal):
    with open(cal, encoding="utf-8") as f:
        data = json.load(f)

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                yield from walk(v)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v)
        elif isinstance(x, str):
            yield x

    needles += [s for s in walk(data) if len(s) >= 4 and not s.startswith("_")]

hits = []
for root, dirs, files in os.walk(pkg):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    files = [f for f in files if f != "build.sh"]        # 本文件自己就写着这些字样
    for name in files:
        p = os.path.join(root, name)
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        for n in needles:
            if n and n in text:
                hits.append((os.path.relpath(p, pkg), n))
if hits:
    print("！以下文件里有本机路径、书名或标定值，别发布：")
    for p, n in hits:
        print("   %s  <- %s" % (p, n))
    sys.exit(1)
print("干净")
PY
    rm -rf "$VDIR"
fi

rm -rf "$STAGE"
