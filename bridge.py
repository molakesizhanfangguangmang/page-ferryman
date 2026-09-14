#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""legado ↔ Moeli 阅读进度桥。

scan: 只读。把三边（书库文件 / 安卓 legado / iOS Moeli）按书对齐，打印各自位置，
      并算出谁更靠前、该往哪边推。不写任何东西。

对齐键
  书库目录名末尾的括号编号 = Calibre book id；安卓 legado 的 originName 前缀就是这个编号
  （'23.某本书.epub' -> 某本书 (23)）
  Moeli 的 Books.md5 是它在 reader/<用户号>/moeli_reader/book/ 下的文件名（不是内容哈希），
  那份副本与书库文件逐字节相同 -> 用副本的内容 md5 对齐书库
  安卓侧位置文件 = bookProgress/<书名>_<作者>.json，逐设备各有一份；
  云文件里的 name/author 字段就是该设备的键，用它跟书架对上（不猜文件名规则）

判定沿用 legado 自己的口径：只看位置，先比章号再比章内偏移，不比时间
  （见 LegadoTeam/legado ReadBook.syncProgress / AppWebDav.downloadAllBookProgress）
"""

import fcntl
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cfi import EpubDoc, chapter_char_total  # noqa: E402
from txt import TxtBook, TxtError, parse_txtloc, load_rules as load_txt_rules  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- 配置
# 同目录 config.json（RPB_CONFIG 可指别处）→ 环境变量，环境变量优先。
# 键名：data / reader_user / interval_seconds / threshold_chars / threshold_percent /
#       apply / state_dir / rules_file / skip_books
def _cfg():
    for p in [os.environ.get("RPB_CONFIG"), os.path.join(HERE, "config.json")]:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        for k, v in d.items():
            if k.startswith("_") or v is None:
                continue
            if isinstance(v, bool):
                v = "1" if v else "0"
            elif isinstance(v, (list, tuple)):
                v = ",".join(str(x) for x in v)
            os.environ.setdefault("RPB_" + k.upper(), str(v))
        break


def _env(name, default=None):
    v = os.environ.get("RPB_" + name)
    return default if v in (None, "") else v


def _find_reader(data):
    """数据卷里的 reader/<用户号>；优先挑带 moeli_reader 的那个"""
    want = _env("READER_USER")
    cands = [d for d in sorted(glob.glob(os.path.join(data, "reader", "*")))
             if os.path.isdir(os.path.join(d, "legado"))]
    if want and os.path.isdir(os.path.join(data, "reader", str(want))):
        return os.path.join(data, "reader", str(want))
    for d in cands:
        if os.path.isdir(os.path.join(d, "moeli_reader")):
            return d
    return cands[0] if cands else os.path.join(data, "reader", "1")


_cfg()
DATA = _env("DATA", "/data")
LIB = os.path.join(DATA, "books/library")
READER = _find_reader(DATA)
LEGADO = os.path.join(READER, "legado")
PROGRESS = os.path.join(LEGADO, "bookProgress")
MOELI = os.path.join(READER, "moeli_reader")
DB = os.path.join(MOELI, "book.db")
BACKUP = os.path.join(READER, "backup", "bridge")
RULES_FILE = _env("RULES_FILE", os.path.join(HERE, "txt-toc-rule.json"))
THRESH_PCT = float(_env("THRESHOLD_PERCENT", 0.3)) / 100.0    # 全书百分之几
THRESH_CHARS = int(_env("THRESHOLD_CHARS", 200))              # 或多少字，取大的那个当门槛
INTERVAL = int(_env("INTERVAL_SECONDS", 300))
SKIP_BOOKS = set(int(x) for x in str(_env("SKIP_BOOKS", "")).replace(",", " ").split()
                 if x.strip().isdigit())
# root 跑时把缓存与状态挪出脚本目录，免得把脚本目录里的文件属主写成 root
_STATE_DIR = _env("STATE_DIR") or (HERE if os.geteuid() != 0 else "/var/tmp/reading-progress-bridge")
if not os.path.isdir(_STATE_DIR):
    os.makedirs(_STATE_DIR, exist_ok=True)
CACHE = os.path.join(_STATE_DIR, "bridge-cache.json")
STATE = os.path.join(_STATE_DIR, "bridge-state.json")
BOOK_EXT = (".epub", ".txt", ".mobi", ".azw3", ".pdf")


# ---------------------------------------------------------------- 书库
def md5_file(path, cache):
    st = os.stat(path)
    key = "%s|%d|%d" % (path, st.st_size, int(st.st_mtime))
    if key in cache:
        return cache[key]
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    cache[key] = h.hexdigest()
    return cache[key]


def norm_title(s):
    return re.sub(r"[\s：:・·\-_]+", "", s or "").lower()


def load_library(cache):
    """{book_id: {...}}，book_id 取自目录名末尾的 (N)"""
    out = {}
    for author in sorted(os.listdir(LIB)):
        adir = os.path.join(LIB, author)
        if not os.path.isdir(adir):
            continue
        for bookdir in sorted(os.listdir(adir)):
            m = re.search(r"\((\d+)\)\s*$", bookdir)
            if not m:
                continue
            bdir = os.path.join(adir, bookdir)
            if not os.path.isdir(bdir):
                continue
            files = [f for f in os.listdir(bdir)
                     if os.path.isfile(os.path.join(bdir, f)) and not f.startswith(".")]
            books = [f for f in files if os.path.splitext(f)[1].lower() in BOOK_EXT] or files
            if not books:
                continue
            f0 = max(books, key=lambda f: os.path.getsize(os.path.join(bdir, f)))
            path = os.path.join(bdir, f0)
            out[int(m.group(1))] = {
                "id": int(m.group(1)),
                "path": path,
                "rel": os.path.relpath(path, LIB),
                "title": bookdir[:m.start()].strip(),
                "author": author,
                "ext": os.path.splitext(f0)[1].lower(),
                "size": os.path.getsize(path),
            }
    return out


# ---------------------------------------------------------------- 安卓 legado
def load_legado():
    """(每设备书架快照, 云端进度文件)"""
    newest = {}
    for z in glob.glob(os.path.join(LEGADO, "backup*.zip")):
        m = re.search(r"backup(\d{4}-\d{2}-\d{2})-(.+)\.zip$", os.path.basename(z))
        if not m:
            continue
        dev, key = m.group(2), (m.group(1), os.path.getmtime(z))
        if dev not in newest or key > newest[dev][0]:
            newest[dev] = (key, z)

    shelf = {}
    for dev, (_key, z) in sorted(newest.items()):
        with zipfile.ZipFile(z) as zf:
            data = json.loads(zf.read("bookshelf.json").decode("utf-8"))
        shelf[dev] = {
            "zip": os.path.basename(z),
            "books": [{
                "name": b.get("name"), "author": b.get("author"),
                "originName": b.get("originName"),
                "idx": b.get("durChapterIndex"), "pos": b.get("durChapterPos"),
                "time": b.get("durChapterTime"), "chapter": b.get("durChapterTitle"),
                "chapters": b.get("totalChapterNum"),
            } for b in data],
        }

    cloud = {}
    for p in sorted(glob.glob(os.path.join(PROGRESS, "*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                cloud[os.path.basename(p)] = json.load(f)
        except Exception as e:                                     # noqa: BLE001
            print("  读不了 %s: %s" % (p, e))
    return shelf, cloud


# ---------------------------------------------------------------- iOS Moeli
def load_moeli(cache):
    """Moeli 书架行 + 它在本地 book/ 下的那份副本内容 md5"""
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    cols = ["book_id", "name", "author", "lastRead", "readPercent", "lastTime", "md5"]
    rows = [dict(zip(cols, r)) for r in
            c.execute("select book_id,name,author,lastRead,readPercent,lastTime,md5 from Books")]
    c.close()
    for row in rows:
        local = None
        for f in os.listdir(os.path.join(MOELI, "book")):
            if f.startswith(row["md5"]):
                local = os.path.join(MOELI, "book", f)
                break
        row["local"] = local
        row["content_md5"] = md5_file(local, cache) if local else None
    return rows


# ---------------------------------------------------------------- 换算
def href_index(epub):
    return {href: i for i, (_t, href) in enumerate(epub.toc)}


def moeli_position(row, lib):
    """Moeli 位置 -> (章号, 章内偏移, 章标题) 或 (None, None, 说明)"""
    lr = row.get("lastRead") or ""
    if lr.startswith("epubcfi("):
        epub = get_epub(lib["path"])
        href, off = epub.cfi_to_offset(lr)
        i = href_index(epub).get(href)
        if i is None:
            return None, None, "cfi 指向的章节不在目录里: %s" % href
        return i, off, epub.chapter_title(i)
    if lr.startswith("txtloc("):
        ch, byte_off, _flag = parse_txtloc(lr)
        if lib["ext"] != ".txt":
            return None, None, "txtloc 但书不是 txt（%s）" % lib["ext"]
        try:
            tb = get_txt(lib)
        except (TxtError, OSError) as e:
            return None, None, "txt 切章失败：%s" % e
        i, p, title = tb.moeli_to_legado(byte_off)
        return i, p, "%s（Moeli 字节 %d -> 第%d章第%d字，全书 %d%%）" % (
            title, byte_off, i, p, tb.pct(i, p))
    return None, None, "认不出的坐标: %r" % lr


def key_of(o):
    return (o.get("name") or "", o.get("author") or "")


def resolve_shelf(lib, shelf):
    """设备书架条目 -> book_id。认不准的（书名互相套得住、编号也没有）留空并列出来"""
    out, amb = {}, []
    for dev, info in shelf.items():
        for bk in info["books"]:
            m = re.match(r"^0*(\d+)[.\uff0e\s]", bk.get("originName") or "")
            if m and int(m.group(1)) in lib:
                out[(dev, id(bk))] = int(m.group(1))
                continue
            nt = norm_title(bk["name"])
            if not nt:
                continue
            cands = [b["id"] for b in lib.values() if norm_title(b["title"]) == nt]
            if len(cands) == 1:
                out[(dev, id(bk))] = cands[0]
                continue
            cands = [b["id"] for b in lib.values() if nt in norm_title(b["title"])]
            if len(cands) == 1:
                out[(dev, id(bk))] = cands[0]
            else:
                amb.append((dev, bk["name"], [lib[c]["title"] for c in cands]))
    return out, amb


def align(cache):
    lib = load_library(cache)
    shelf, cloud = load_legado()
    moeli = load_moeli(cache)

    by_md5 = {}
    for b in lib.values():
        if b["ext"] in (".epub", ".txt"):          # txt 在 Moeli 那边也是逐字节的副本
            by_md5.setdefault(md5_file(b["path"], cache), []).append(b)

    smap, amb = resolve_shelf(lib, shelf)

    recs = []
    for bid in sorted(lib):
        b = lib[bid]
        rec = {"lib": b, "moeli": None, "devices": {}}

        for row in moeli:
            hit = None
            cands = by_md5.get(row["content_md5"] or "", [])
            if len(cands) == 1:
                hit = cands[0]
            if hit is None and norm_title(row["name"]) in norm_title(b["title"]) \
                    and norm_title(b["title"]) in norm_title(row["name"]):
                hit = b
            if hit is not None and hit["id"] == bid:
                rec["moeli"] = row
                break

        for dev, info in shelf.items():
            for bk in info["books"]:
                if smap.get((dev, id(bk))) != bid:
                    continue
                if bk.get("chapters"):
                    b["txt_chapters"] = max(b.get("txt_chapters") or 0, bk["chapters"])
                bk = dict(bk)
                bk["cloud"] = None
                for fname, o in cloud.items():
                    if key_of(o) == key_of(bk):
                        bk["cloud"] = (fname, o)
                        break
                # 手机上真正的位置：云端文件的写入时间比书架快照新就用云文件
                eff = (bk["idx"], bk["pos"])
                src = "书架快照(%s)" % info["zip"][:10]
                if bk["cloud"]:
                    c = bk["cloud"][1]
                    if (c.get("durChapterTime") or 0) > (bk["time"] or 0):
                        eff = (c.get("durChapterIndex"), c.get("durChapterPos"))
                        src = "云文件(%s)" % fname_tag(bk["cloud"][0])
                bk["eff"] = eff
                bk["eff_src"] = src
                rec["devices"][dev] = bk
        recs.append(rec)
    return recs, amb


def fname_tag(fname):
    return fname[:-5] if fname.endswith(".json") else fname


def fmt_ts(ms):
    if not ms:
        return "-"
    return time.strftime("%m-%d %H:%M", time.localtime(ms / 1000.0))


def report(recs):
    print("=" * 96)
    print("对齐表：书库 %d 本" % len(recs))
    print("=" * 96)
    for r in recs:
        b = r["lib"]
        if not (r["moeli"] or r["devices"]):
            continue
        idx_m = pos_m = None
        note_m = ""
        if r["moeli"]:
            idx_m, pos_m, note_m = moeli_position(r["moeli"], b)
        chs = [d["chapters"] for d in r["devices"].values() if d["chapters"]]
        print("")
        print("[%s] %s - %s  (%s, %.1fMB%s)" % (b["id"], b["title"], b["author"], b["ext"][1:],
                                               b["size"] / 1048576.0,
                                               "，%d 章" % max(chs) if chs else ""))
        if r["moeli"]:
            m = r["moeli"]
            print("   iOS     book_id=%-2s %-9s %s%%  %s  %s" %
                  (m["book_id"], "%s/%s" % (idx_m, pos_m), m["readPercent"], m["lastTime"],
                   note_m))
        else:
            print("   iOS     —")
        for dev, bk in sorted(r["devices"].items()):
            cf = bk["cloud"]
            print("   安卓 %-10s 位置 %-11s %s   ←%s" %
                  (dev, "%s/%s" % bk["eff"],
                   fmt_ts((cf[1].get("durChapterTime") if cf else bk["time"]) or 0),
                   bk["eff_src"]))
            if cf:
                print("          键名 %s.json" % fname_tag(cf[0]))
        cand = [("iOS", (idx_m, pos_m))] if idx_m is not None else []
        cand += [(dev, bk["eff"]) for dev, bk in r["devices"].items()
                 if bk["eff"][0] is not None]
        if cand:
            top = max(cand, key=lambda x: x[1])
            others = [x for x in cand if x[1] != top[1]]
            print("   -> 最靠前：%s %s/%s%s" %
                  (top[0], top[1][0], top[1][1],
                   "" if not others else
                   "；落后：%s" % "，".join("%s %s/%s" % (d, v[0], v[1]) for d, v in others)))


# ---------------------------------------------------------------- 动作计算
_EPUB_CACHE = {}
_TOTAL_CACHE = {}


_TXT_CACHE = {}


def get_txt(lib):
    """按书取 TxtBook（切章规则取固定副本，没有就从备份里抽；准绳是手机报过的总章数）"""
    key = (lib["path"], lib.get("txt_chapters"))
    t = _TXT_CACHE.get(key)
    if t is None:
        t = _TXT_CACHE[key] = TxtBook(lib["path"], rules=load_txt_rules(RULES_FILE, legado_dir=LEGADO),
                                      reported_chapters=lib.get("txt_chapters"))
    return t


def get_epub(path):
    e = _EPUB_CACHE.get(path)
    if e is None:
        e = _EPUB_CACHE[path] = EpubDoc(path)
    return e


def totals_of(path):
    t = _TOTAL_CACHE.get(path)
    if t is None:
        t = _TOTAL_CACHE[path] = book_totals(get_epub(path))
    return t


def book_totals(epub):
    return [chapter_char_total(epub, i) for i in range(len(epub.toc))]


def abs_chars(totals, idx, pos):
    """全书绝对字符位置"""
    return sum(totals[:idx]) + pos


def leader_of(sides):
    """sides: [(名字, (idx,pos))] -> 最靠前的那项"""
    ok = [s for s in sides if s[1][0] is not None]
    return max(ok, key=lambda s: s[1]) if ok else None


def plan(recs, cache):
    """算出这一轮该写什么。只在跨软件时才做坐标换算。

    安卓(legado) -> 安卓(legado)：同软件，坐标是同一套 (章号, 章内偏移)，原样搬，
                                 不解析 epub、不算字数。
    iOS(Moeli) <-> 安卓：跨软件，才做 epubcfi/txtloc <-> (章号, 章内偏移) 换算，
                        这一步必须解析 epub，省不掉。
    """
    acts, skips = [], []
    for r in recs:
        b = r["lib"]
        if b["id"] in SKIP_BOOKS:
            skips.append((b, "配置里点名跳过"))
            continue
        pos_ios = None
        if r["moeli"]:
            i, p, _note = moeli_position(r["moeli"], b)
            pos_ios = (i, p)
        devs = {n: bk for n, bk in r["devices"].items() if bk["eff"][0] is not None}
        if len(devs) + (1 if (pos_ios and pos_ios[0] is not None) else 0) < 2:
            continue

        cross = bool(pos_ios and pos_ios[0] is not None)      # 这一轮有没有 iOS 参与
        if cross and b["ext"] not in (".epub", ".txt"):
            skips.append((b, "非 epub/txt（%s），跨软件换算没做；本轮不动" % b["ext"][1:]))
            continue
        epub = totals = txtb = None
        if cross:
            if b["ext"] == ".txt":
                try:
                    txtb = get_txt(b)
                except (TxtError, OSError) as e:
                    skips.append((b, "txt 切章失败：%s" % e))
                    continue
                totals = txtb.totals()
            else:
                epub, totals = get_epub(b["path"]), totals_of(b["path"])

        sides = [(n, bk["eff"]) for n, bk in devs.items()]
        if pos_ios and pos_ios[0] is not None:
            sides.append(("iOS", pos_ios))
        lead = leader_of(sides)          # (章号, 偏移) 两侧口径一致，直接比
        lead_title = None
        if lead[0] in devs:
            src = devs[lead[0]]
            lead_title = (src["cloud"][1].get("durChapterTitle") if src["cloud"]
                          else src.get("chapter"))
        thr = max(THRESH_CHARS, int(THRESH_PCT * sum(totals))) if totals else THRESH_CHARS

        for name, pos in sides:
            if name == lead[0]:
                continue
            if totals:
                gap = abs_chars(totals, *lead[1]) - abs_chars(totals, *pos)
                if gap < thr:
                    skips.append((b, "%s 落后 %d 字（< %d），不动" % (name, gap, thr)))
                    continue
            elif lead[1][0] == pos[0] and abs(lead[1][1] - pos[1]) < THRESH_CHARS:
                skips.append((b, "%s 落后不到 %d 字（同软件，没解析正文），不动"
                              % (name, THRESH_CHARS)))
                continue

            why = "%s 领先 %s %s/%s" % (lead[0], b["title"], lead[1][0], lead[1][1])
            if name == "iOS":
                if txtb is not None:
                    c0, _b0, flag = parse_txtloc(r["moeli"]["lastRead"])
                    loc = EpubDoc.make_txtloc(c0, txtb.legado_to_moeli(*lead[1]), flag)
                    href = None
                else:
                    href = epub.chapter_href(lead[1][0])
                    loc = epub.offset_to_cfi(href, lead[1][1])
                acts.append({
                    "book": b, "side": "iOS", "kind": "db",
                    "book_id": r["moeli"]["book_id"],
                    "cfi": loc,
                    "percent": round(100.0 * abs_chars(totals, *lead[1]) / sum(totals)),
                    "why": why,
                })
            else:
                bk = devs[name]
                if not bk["cloud"]:
                    skips.append((b, "%s 在云上没有键文件，不新造" % name))
                    continue
                if lead[0] != "iOS":
                    title = lead_title or chapter_title_of(epub, txtb, lead[1][0])
                else:
                    title = chapter_title_of(epub, txtb, lead[1][0])
                acts.append({
                    "book": b, "side": name, "kind": "json",
                    "file": os.path.join(PROGRESS, bk["cloud"][0]),
                    "obj": {
                        "author": bk["author"], "durChapterIndex": lead[1][0],
                        "durChapterPos": lead[1][1], "durChapterTime": int(time.time() * 1000),
                        "durChapterTitle": title, "name": bk["name"],
                    },
                    "why": why,
                })

    # 同一本书、同一个目标文件只留一条（两台安卓可能共用同一个键）
    merged, seen = [], {}
    for a_ in acts:
        k = (a_["book"]["id"], a_["side"] if a_["kind"] == "db" else a_["file"])
        if k in seen:
            seen[k]["devices"].append(a_["side"])
            continue
        a_["devices"] = [a_["side"]]
        seen[k] = a_
        merged.append(a_)
    return merged, skips


def chapter_title_of(epub, txtb, idx):
    return txtb.title(idx) if txtb is not None else epub.chapter_title(idx)


def show_plan(acts, skips):
    print("=" * 96)
    print("这一轮的动作：%d 条（写成 / 只算）" % len(acts))
    print("=" * 96)
    for a in acts:
        print("  [%s] %s  %s" % (a["side"], a["book"]["title"], a["why"]))
        if a["kind"] == "json":
            print("        写 %s   （设备：%s）" % (a["file"], "、".join(a["devices"])))
            print("        %s" % json.dumps(a["obj"], ensure_ascii=False))
        else:
            print("        book_id=%s lastRead=%s readPercent=%s" %
                  (a["book_id"], a["cfi"], a["percent"]))
    print("")
    print("不动：%d 条" % len(skips))
    for b, why in skips:
        print("  [%s] %s" % (b["id"], why))


def do_backup(path):
    os.makedirs(BACKUP, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP, "%s.%s" % (os.path.basename(path), ts))
    with open(path, "rb") as a, open(dst, "wb") as c:
        c.write(a.read())
    return dst


def apply_plan(acts, state):
    done = []
    for a in acts:
        if a["kind"] == "json":
            st = os.stat(a["file"])
            bk = do_backup(a["file"])
            tmp = a["file"] + ".bridge-tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(a["obj"], f, ensure_ascii=False, indent=2)
            os.chown(tmp, st.st_uid, st.st_gid)
            os.chmod(tmp, st.st_mode & 0o7777)
            os.replace(tmp, a["file"])
            done.append("写了 %s（备份 %s）" % (a["file"], os.path.basename(bk)))
        else:
            bk = do_backup(DB)
            lt = time.localtime()          # Moeli 自己的写法：2026-9-14-16:32:51
            ts = "%d-%d-%d-%d:%02d:%02d" % (lt.tm_year, lt.tm_mon, lt.tm_mday,
                                            lt.tm_hour, lt.tm_min, lt.tm_sec)
            c = sqlite3.connect(DB)
            c.execute("update Books set lastRead=?, readPercent=?, lastTime=? where book_id=?",
                      (a["cfi"], a["percent"], ts, a["book_id"]))
            c.commit()
            c.close()
            done.append("写了 book.db book_id=%s（备份 %s）" % (a["book_id"], os.path.basename(bk)))
        state["last:%s:%s" % (a["book"]["id"], a["side"])] = int(time.time())
    return done


def main():
    argv = sys.argv[1:]
    cmd = argv[0] if argv and not argv[0].startswith("-") else "scan"
    apply_ = ("--apply" in argv) or _env("APPLY", "0") == "1"
    cache = {}
    if os.path.exists(CACHE):
        try:
            cache = json.load(open(CACHE))
        except Exception:                                          # noqa: BLE001
            cache = {}
    state = {}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE))
        except Exception:                                          # noqa: BLE001
            state = {}

    lock = None
    if cmd == "sync":                      # 定时任务跑，别让两轮叠在一起
        lock = open(os.path.join(_STATE_DIR, "bridge.lock"), "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("上一轮还没跑完，这一轮跳过")
            return 0

    if cmd == "scan":
        recs, amb = align(cache)
        report(recs)
        if amb:
            print("")
            print("对不准（已跳过）：")
            for dev, name, cands in amb:
                if cands:
                    print("  %s %r -> 可能：%s" % (dev, name, "、".join(cands)))
                else:
                    print("  %s %r -> 书库里没有这本" % (dev, name))
    elif cmd == "sync":
        recs, _amb = align(cache)
        acts, skips = plan(recs, cache)
        show_plan(acts, skips)
        if apply_:
            print("")
            print("执行（会写生产文件）：")
            for line in apply_plan(acts, state):
                print("  " + line)
            json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
        else:
            print("")
            print("（dry-run，没有写任何东西；要真写加 --apply，且必须以 root 在宿主上跑）")
    else:
        print(__doc__)
        return 2
    json.dump(cache, open(CACHE, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
