# -*- coding: utf-8 -*-
"""离线自测：拿书库里真实的 epub 验证 CFI <-> (章, 偏移) 互转。

只读，不碰任何生产数据。用法：python3 test/test_cfi.py
数据目录取环境变量 RPB_DATA（默认 /data）。

通用部分（往返、章长度）自动从书库里挑 epub，有书库就能跑。
定点比对要一份 `test/calibration.local.json`，里面写本机标定过的那几本与预期值；
那份文件不入库、不随包发，没有就跳过定点比对。
"""

import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from cfi import EpubDoc, chapter_char_total  # noqa: E402

DATA = os.environ.get("RPB_DATA") or "/data"
LIB = os.environ.get("RPB_LIB") or os.path.join(DATA, "books/library")
MAX_BOOKS = int(os.environ.get("RPB_TEST_EPUBS") or 3)


def load_cal():
    """本机标定值：{标签: {"path": 相对书库的路径, "cfi": {cfi: [文档片段, 下限, 上限]}}}"""
    path = os.path.join(HERE, "calibration.local.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("epub") or {}
    except Exception:                                      # noqa: BLE001
        return {}


fails = []


def check(name, ok, detail=""):
    print("  %s %s %s" % ("OK  " if ok else "FAIL", name, detail))
    if not ok:
        fails.append(name)


def find_epubs(limit):
    out = []
    for author in sorted(glob.glob(os.path.join(LIB, "*"))):
        if not os.path.isdir(author):
            continue
        for d in sorted(glob.glob(os.path.join(author, "*"))):
            if not re.search(r"\((\d+)\)\s*$", os.path.basename(d)):
                continue
            hits = sorted(glob.glob(os.path.join(d, "*.epub")))
            if hits:
                out.append((os.path.basename(d), hits[0]))
    out.sort(key=lambda t: -os.path.getsize(t[1]))
    return out[:limit]


def roundtrip(epub, label):
    for idx in range(min(len(epub.toc), 4)):
        href = epub.chapter_href(idx)
        total = chapter_char_total(epub, idx)
        if total <= 0:
            check("章%d 有正文" % idx, False, "章长 0")
            continue
        bad = []
        cap = None
        for off in [0, 1, 17] + list(range(0, total, max(1, total // 61))) + [total - 1, total]:
            try:
                cfi = epub.offset_to_cfi(href, off)
                href2, off2 = epub.cfi_to_offset(cfi)
            except Exception as e:                      # noqa: BLE001
                bad.append((off, "异常 %s" % e))
                continue
            if href2 != href or off2 != off:
                bad.append((off, "%s -> %s" % (href2.rsplit("/", 1)[-1], off2)))
            if off in (0, total // 2):
                cap = cfi
        check("%s 章%d 往返（%d 字）" % (label, idx, total), not bad, "示例 %s" % cap)
        if bad:
            print("       前 5 个不一致: %s" % bad[:5])


def main():
    samples = find_epubs(MAX_BOOKS)
    if not samples:
        print("!! 书库里找不到 epub（%s）" % LIB)
        return 1
    for label, path in samples:
        epub = EpubDoc(path)
        print("=" * 74)
        print("%s  %s" % (label, os.path.basename(path)))
        print("  spine 步长 /%d，spine %d 项，TOC %d 章"
              % (epub.spine_step, len(epub.spine), len(epub.toc)))
        for i, (t, h) in enumerate(epub.toc[:6]):
            print("    [%d] %-26s %-40s 正文字数 %d"
                  % (i, t[:26], h.rsplit("/", 1)[-1], chapter_char_total(epub, i)))
        if len(epub.toc) > 6:
            print("    ... 共 %d 章" % len(epub.toc))
        check("%s 有目录" % label, len(epub.toc) > 0)
        roundtrip(epub, label)

    cal = load_cal()
    print("=" * 74)
    if not cal:
        print("本机标定比对：没有 test/calibration.local.json，跳过")
    else:
        print("本机标定比对（这台没有那本就跳过）：")
        for label, spec in cal.items():
            path = os.path.join(LIB, spec["path"])
            if not os.path.exists(path):
                print("  跳过 %s（这台没有这本）" % label)
                continue
            epub = EpubDoc(path)
            for cfi, (want_doc, lo, hi) in spec["cfi"].items():
                href, off = epub.cfi_to_offset(cfi)
                print("  解析 %s -> %s 章内偏移 %d" % (cfi, href.rsplit("/", 1)[-1], off))
                check("%s 文档匹配" % label, want_doc in href, href)
                check("%s 偏移区间" % label, lo <= off <= hi, "[%d,%d]" % (lo, hi))

    print("=" * 74)
    print("失败项: %s" % (fails if fails else "无"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
