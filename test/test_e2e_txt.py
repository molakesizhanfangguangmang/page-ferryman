# -*- coding: utf-8 -*-
"""端到端自测：在临时目录里造一份假数据，真跑一遍 sync 的写入路径。

不碰任何真实数据 —— 书库、book.db、bookProgress 全是临时目录里的副本。

跑：python3 test/test_e2e_txt.py
样本与切章规则取自真实数据目录（RPB_DATA，默认 /data）：抽一本 txt 当样本，
规则从 legado 备份里抽。取不到就跳过。

验证的是：
  1) 安卓领先 -> 写 Moeli 的 book.db，写进去的字节偏移落在字符边界上、
     反过来解析回来等于原来的 (章号, 章内偏移)
  2) Moeli 领先 -> 写安卓的云端进度文件，章号/偏移/标题与换算结果一致
  3) 两边写前都留了备份
  4) 再跑一轮不重复写（幂等）
"""

import glob
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.dirname(HERE)
sys.path.insert(0, DIST)
import txt as T  # noqa: E402

SRC_DATA = os.environ.get("RPB_DATA") or "/data"
BOOK_ID = 9001
DEVICE = "TESTDEV"
BOOK_TITLE = "样例书"
BOOK_AUTHOR = "测试作者"

FALLBACK_SCHEMA = """CREATE TABLE Books (
    book_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, author TEXT NOT NULL, describe TEXT NOT NULL DEFAULT '',
    lastRead TEXT NOT NULL DEFAULT 'null', readPercent INTEGER DEFAULT 0,
    joinTime TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'null',
    lastTime TEXT NOT NULL DEFAULT '000000', seriesId TEXT NOT NULL DEFAULT 'null',
    state TEXT NOT NULL DEFAULT 'default', themeColor TEXT NOT NULL DEFAULT 'null',
    md5 TEXT NOT NULL DEFAULT 'null', setCover TEXT NOT NULL DEFAULT 'false',
    readStatus TEXT NOT NULL DEFAULT 'unread', finishedDate TEXT NOT NULL DEFAULT '',
    readTime INTEGER NOT NULL DEFAULT 0, seriesLevel INTEGER NOT NULL DEFAULT 0,
    syncStatus TEXT NOT NULL DEFAULT 'local', isPrivate INTEGER NOT NULL DEFAULT 0,
    bookStyle TEXT, filePassword TEXT NOT NULL DEFAULT '',
    rating REAL NOT NULL DEFAULT 0, review TEXT NOT NULL DEFAULT '')"""


def find_sample(rules):
    """真实数据里第一本切得出章来的 txt"""
    for f in sorted(glob.glob(os.path.join(SRC_DATA, "books", "library", "*", "*", "*.txt"))):
        if os.path.getsize(f) <= 4096:
            continue
        try:
            if len(T.TxtBook(f, rules=rules).chapters) >= 4:
                return f
        except (T.TxtError, OSError):
            continue
    return None


def find_real_legado():
    want = os.environ.get("RPB_READER_USER")
    if want and os.path.isdir(os.path.join(SRC_DATA, "reader", want)):
        return os.path.join(SRC_DATA, "reader", want, "legado")
    hits = [d for d in sorted(glob.glob(os.path.join(SRC_DATA, "reader", "*", "legado")))
            if os.path.isdir(os.path.join(d, "..", "moeli_reader"))]
    return hits[0] if hits else os.path.join(SRC_DATA, "reader", "1", "legado")


def real_schema():
    p = os.path.join(SRC_DATA, "reader", "1", "moeli_reader", "book.db")
    if not os.path.isfile(p):
        return None
    c = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    try:
        row = c.execute("select sql from sqlite_master where name='Books'").fetchone()
        return row[0] if row else None
    finally:
        c.close()


class Sandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp(prefix="rpb-e2e-")
        cls.data = os.path.join(cls.root, "data")
        cls.state = os.path.join(cls.root, "state")

        # 切章规则：优先从真实数据的备份里抽，抽不到就用真实数据里的规则文件
        legado_real = find_real_legado()
        try:
            rules = T.load_rules(None, legado_dir=legado_real)
        except T.TxtError:
            src = os.path.join(legado_real, "txt-toc-rule.json")
            if not os.path.isfile(src):
                raise unittest.SkipTest("拿不到切章规则（%s）" % src)
            rules = T.load_rules(src)
        sample = find_sample(rules)
        if not sample:
            raise unittest.SkipTest("真实数据里找不到切得出章的 txt（%s）" % SRC_DATA)

        legado = os.path.join(cls.data, "reader", "1", "legado")
        moeli = os.path.join(cls.data, "reader", "1", "moeli_reader")
        os.makedirs(os.path.join(legado, "bookProgress"))
        os.makedirs(os.path.join(moeli, "book"))
        bdir = os.path.join(cls.data, "books", "library", BOOK_AUTHOR,
                            "%s (%d)" % (BOOK_TITLE, BOOK_ID))
        os.makedirs(bdir)
        cls.book = os.path.join(bdir, BOOK_TITLE + ".txt")
        shutil.copyfile(sample, cls.book)

        cls.rules_file = os.path.join(legado, "txt-toc-rule.json")
        with open(cls.rules_file, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=1)
        cls.tb = T.TxtBook(cls.book, rules=T.load_rules(cls.rules_file))
        if len(cls.tb.chapters) < 4:
            raise unittest.SkipTest("样本切不出足够的章")

        # Moeli 侧：book.db（有真库就复制真库的 schema，再去掉行）
        cls.db = os.path.join(moeli, "book.db")
        src_db = os.path.join(SRC_DATA, "reader", "1", "moeli_reader", "book.db")
        if os.path.isfile(src_db):
            shutil.copyfile(src_db, cls.db)
            c = sqlite3.connect(cls.db)
            c.execute("delete from Books")
            c.commit()
            c.close()
        else:
            c = sqlite3.connect(cls.db)
            c.execute(real_schema() or FALLBACK_SCHEMA)
            c.commit()
            c.close()

        cls.dev = os.path.join(legado, "bookProgress", "%d.%s_.json" % (BOOK_ID, BOOK_TITLE))
        cls.copies = os.path.join(moeli, "book")

        # 安卓侧的书架快照：设备靠备份 zip 里的 bookshelf.json 出现，
        # 快照里的 totalChapterNum 还会被当成切章的准绳
        cls.shelf_idx, cls.shelf_pos = min(5, len(cls.tb.chapters) - 1), 7
        shelf = [{
            "name": "%d.%s" % (BOOK_ID, BOOK_TITLE), "author": BOOK_AUTHOR,
            "originName": "%d.%s.txt" % (BOOK_ID, BOOK_TITLE),
            "durChapterIndex": cls.shelf_idx, "durChapterPos": cls.shelf_pos,
            "durChapterTime": int((time.time() - 86400) * 1000),
            "durChapterTitle": cls.tb.title(cls.shelf_idx),
            "totalChapterNum": len(cls.tb.chapters),
        }]
        with zipfile.ZipFile(os.path.join(legado, "backup2026-01-01-%s.zip" % DEVICE), "w") as zf:
            zf.writestr("bookshelf.json", json.dumps(shelf, ensure_ascii=False))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    # ---------------- 造数据
    def seed_moeli(self, byte_off, percent=1, chapter_field=1):
        """Moeli 侧一行：md5 字段存的是本地副本的文件名（前缀就是内容 md5）"""
        h = hashlib.md5()
        with open(self.book, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        name = "%s-%d.txt" % (h.hexdigest(), int(time.time() * 1000))
        shutil.copyfile(self.book, os.path.join(self.copies, name))
        c = sqlite3.connect(self.db)
        c.execute("delete from Books")
        c.execute("insert into Books (name, author, lastRead, readPercent, joinTime,"
                  " lastTime, md5) values (?,?,?,?,?,?,?)",
                  (BOOK_TITLE, BOOK_AUTHOR, "txtloc(%d:%d:0)" % (chapter_field, byte_off),
                   percent, "2026-01-01", "2026-01-01-0:0:0", name))
        c.commit()
        c.close()
        return name

    def seed_phone(self, idx, pos, title=None, when=None):
        obj = {"author": BOOK_AUTHOR, "durChapterIndex": idx, "durChapterPos": pos,
               "durChapterTime": when if when is not None else int(time.time() * 1000),
               "durChapterTitle": title if title is not None else self.tb.title(idx),
               "name": "%d.%s" % (BOOK_ID, BOOK_TITLE)}
        with open(self.dev, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        return obj

    def run_sync(self):
        env = dict(os.environ)
        env.update({"RPB_DATA": self.data, "RPB_RULES_FILE": self.rules_file,
                    "RPB_STATE_DIR": self.state, "RPB_APPLY": "1"})
        p = subprocess.run([sys.executable, os.path.join(DIST, "bridge.py"), "sync"],
                           env=env, capture_output=True, timeout=300)
        out = p.stdout.decode("utf-8", "replace") + p.stderr.decode("utf-8", "replace")
        return p.returncode, out

    def db_row(self):
        c = sqlite3.connect(self.db)
        try:
            r = c.execute("select lastRead, readPercent, lastTime from Books where name=?",
                          (BOOK_TITLE,)).fetchone()
        finally:
            c.close()
        return r

    def backups(self, sub="bridge"):
        return sorted(glob.glob(os.path.join(self.data, "reader", "1", "backup", sub, "*")))

    # ---------------- 用例
    def test_01_android_leads_writes_moeli(self):
        idx, pos = self.shelf_idx, self.shelf_pos
        self.seed_moeli(0, percent=1)
        self.seed_phone(idx, pos)
        rc, out = self.run_sync()
        self.assertEqual(rc, 0, out)
        self.assertIn("写了 book.db", out, out)

        lr, pct, when = self.db_row()
        self.assertTrue(lr.startswith("txtloc(1:"), lr)
        byte_off = T.parse_txtloc(lr)[1]
        with open(self.book, "rb") as f:
            data = f.read()
        self.assertLessEqual(byte_off, len(data))
        data[:byte_off].decode(self.tb.enc)                  # 不能落在字中间
        self.assertEqual(self.tb.moeli_to_legado(byte_off)[:2], (idx, pos))
        self.assertEqual(pct, self.tb.pct(idx, pos))
        self.assertRegex(when, r"^\d{4}-\d{1,2}-\d{1,2}-\d{1,2}:\d{2}:\d{2}$")   # 别写成 %-H
        self.assertTrue(self.backups(), "写 book.db 前应该留备份")

    def test_02_idempotent(self):
        rc, out = self.run_sync()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("写了 book.db", out, out)
        self.assertIn("这一轮的动作：0 条", out, out)

    def test_03_ios_leads_writes_phone_json(self):
        far = int(self.tb.byte_len * 0.9)
        self.seed_moeli(far, percent=90)
        self.seed_phone(0, 0, when=1)                        # 手机停在开头
        rc, out = self.run_sync()
        self.assertEqual(rc, 0, out)
        self.assertIn("写了 %s" % self.dev, out)
        with open(self.dev, encoding="utf-8") as f:
            got = json.load(f)
        want_idx, want_pos, _title = self.tb.moeli_to_legado(far)
        self.assertEqual((got["durChapterIndex"], got["durChapterPos"]), (want_idx, want_pos))
        self.assertEqual(got["durChapterTitle"], self.tb.title(want_idx))
        self.assertEqual(got["name"], "%d.%s" % (BOOK_ID, BOOK_TITLE))
        self.assertTrue(self.backups(), "写进度文件前应该留备份")

    def test_04_skip_list(self):
        env = dict(os.environ)
        env.update({"RPB_DATA": self.data, "RPB_RULES_FILE": self.rules_file,
                    "RPB_STATE_DIR": self.state, "RPB_APPLY": "1",
                    "RPB_SKIP_BOOKS": str(BOOK_ID)})
        self.seed_moeli(0)
        self.seed_phone(self.shelf_idx, self.shelf_pos)
        p = subprocess.run([sys.executable, os.path.join(DIST, "bridge.py"), "sync"],
                           env=env, capture_output=True, timeout=300)
        out = p.stdout.decode("utf-8", "replace")
        self.assertIn("这一轮的动作：0 条", out, out)
        self.assertIn("配置里点名跳过", out, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
