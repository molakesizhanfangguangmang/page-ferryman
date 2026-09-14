# -*- coding: utf-8 -*-
"""txt 换算的离线自测（只读，不动任何数据）。

跑：python3 test/test_txt.py
数据目录取环境变量 RPB_DATA（默认 /data）。

分两层：

- 通用层不挑书：切章规则从使用者自己的 legado 备份里抽，字节↔字符换算在任何一本
  txt 上都该自洽。有数据就跑。
- 标定层是本机那本书的具体数字（字节数、章标题、两端位置）。这些放在
  `test/calibration.local.json` 里，那份文件是本机自己用的，不入库、不随包发；
  没有就跳过标定几条，通用层照跑。
"""

import glob
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import txt as T  # noqa: E402


def _data():
    return os.environ.get("RPB_DATA") or os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "sample-data")


def _reader(data):
    want = os.environ.get("RPB_READER_USER")
    if want and os.path.isdir(os.path.join(data, "reader", want)):
        return os.path.join(data, "reader", want)
    cands = [d for d in sorted(glob.glob(os.path.join(data, "reader", "*")))
             if os.path.isdir(os.path.join(d, "moeli_reader"))]
    return cands[0] if cands else os.path.join(data, "reader", "1")


def _load_cal():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.local.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("txt") or {}
    except Exception:                                      # noqa: BLE001
        return {}


DATA = _data()
READER = _reader(DATA)
LIB = os.path.join(DATA, "books/library")
LEGADO = os.path.join(READER, "legado")

CAL = _load_cal()
NO_CAL = not CAL
BOOKID = int(os.environ.get("RPB_TEST_BOOKID") or CAL.get("book_id") or 0)
SKIP_CAL = "没有 test/calibration.local.json（本机标定值），跳过这一条"


def book_path(bid=None):
    """bid=None：有标定就用标定那本，没有就随便捡一本 txt（通用检查不挑书）"""
    if not os.path.isdir(LIB):
        raise unittest.SkipTest("没有书库目录：%s" % LIB)
    want = BOOKID if bid is None else bid
    fallback = None
    for a in sorted(os.listdir(LIB)):
        adir = os.path.join(LIB, a)
        if not os.path.isdir(adir):
            continue
        for d in sorted(os.listdir(adir)):
            m = re.search(r"\((\d+)\)\s*$", d)
            if not m:
                continue
            txts = [f for f in sorted(os.listdir(os.path.join(adir, d)))
                    if f.lower().endswith(".txt")]
            if not txts:
                continue
            if want and int(m.group(1)) == int(want):
                return os.path.join(adir, d, txts[0])
            if fallback is None:
                fallback = os.path.join(adir, d, txts[0])
    if fallback and not want:
        return fallback
    raise unittest.SkipTest("书库里没有编号 %s 的 txt" % want)


def all_txt_paths():
    """书库里所有 txt 的路径（按编号顺序）"""
    out = []
    if not os.path.isdir(LIB):
        return out
    for a in sorted(os.listdir(LIB)):
        adir = os.path.join(LIB, a)
        if not os.path.isdir(adir):
            continue
        for d in sorted(os.listdir(adir)):
            if not re.search(r"\((\d+)\)\s*$", d):
                continue
            for f in sorted(os.listdir(os.path.join(adir, d))):
                if f.lower().endswith(".txt"):
                    out.append(os.path.join(adir, d, f))
    return out


def pick_cuttable(paths, rules):
    """这些规则能切动的第一本；都切不动就返回 None"""
    for p in paths:
        try:
            return T.TxtBook(p, rules=rules)
        except T.TxtError:
            continue
    return None


def newest_backups():
    """{设备标识: zip 路径}，legado 备份按文件名里的设备标识分组取最新"""
    newest = {}
    for z in glob.glob(os.path.join(LEGADO, "backup*.zip")):
        m = re.search(r"backup(\d{4}-\d{2}-\d{2})-(.+)\.zip$", os.path.basename(z))
        if not m:
            continue
        d, key = m.group(2), (m.group(1), os.path.getmtime(z))
        if d not in newest or key > newest[d][0]:
            newest[d] = (key, z)
    return {d: v[1] for d, v in newest.items()}


class TxtBase(unittest.TestCase):
    """标定层：只在本机那份 txt 对得上时跑"""

    @classmethod
    def setUpClass(cls):
        if NO_CAL:
            raise unittest.SkipTest(SKIP_CAL)
        cls.path = book_path()
        rules = T.load_rules(T.RULES_FILE, legado_dir=LEGADO)     # 没有固定副本就从备份抽
        cls.book = T.TxtBook(cls.path, rules=rules, reported_chapters=CAL["reported_chapters"])

    def setUp(self):
        if self.book.byte_len != CAL["bytes_total"]:
            raise unittest.SkipTest("这台的样本不是标定那本（%d 字节），跳过标定值断言"
                                    % self.book.byte_len)


class TestRulesFromBackup(unittest.TestCase):
    """切章规则从使用者自己的备份里抽，不随包发死数据"""

    def test_extract_matches_newest_backup(self):
        zips = newest_backups()
        if not zips:
            raise unittest.SkipTest("没有 legado 备份可抽：%s" % LEGADO)
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, "txt-toc-rule.json")
            rs = T.load_rules(dst, legado_dir=LEGADO)
            self.assertTrue(os.path.isfile(dst), "抽到的规则没有落盘")
            self.assertTrue(rs, "抽到的规则里没有启用项")
            with open(dst, encoding="utf-8") as f:
                got = json.load(f)
            with zipfile.ZipFile(sorted(zips.values())[-1]) as zf:
                want = json.loads(zf.read("txtTocRule.json").decode("utf-8"))
            key = lambda rs_: {r["serialNumber"]: (r.get("rule"), r.get("enable"), r.get("name"))
                               for r in rs_}                          # noqa: E731
            self.assertEqual(key(got), key(want))

    def test_rule_bodies_agree_across_devices(self):
        """多台设备的备份里，规则本体应该一致（只比本体，不比多出来的空字段）"""
        zips = newest_backups()
        if len(zips) < 2:
            raise unittest.SkipTest("本机只有一台设备的备份，跳过")
        bodies = {}
        for dev, z in zips.items():
            with zipfile.ZipFile(z) as zf:
                pj = json.loads(zf.read("txtTocRule.json").decode("utf-8"))
            bodies[dev] = {r["serialNumber"]: (r.get("rule"), r.get("enable"), r.get("name"))
                           for r in pj}
        vals = list(bodies.values())
        for v in vals[1:]:
            self.assertEqual(vals[0], v)

    def test_missing_rules_raises(self):
        with self.assertRaises(T.TxtError):
            T.load_rules("/nonexistent/txt-toc-rule.json")


class TestChapterize(TxtBase):
    def test_counts(self):
        self.assertEqual(self.book.byte_len, CAL["bytes_total"])
        self.assertEqual(len(self.book.text), CAL["chars_total"])
        self.assertEqual(self.book.enc, "utf-8")

    def test_chapter_total_matches_phone(self):
        """规则切出来的章 + 开头「前言」= 手机报的总章数"""
        want = CAL["expect"]
        self.assertEqual(len(self.book.matches), want["matches"])
        self.assertEqual(len(self.book.chapters), CAL["reported_chapters"])
        self.assertEqual(self.book.chapters[0][1], T.PREFACE)
        self.assertEqual(self.book.chapters[1][1], want["first_chapter_title"])
        self.assertEqual(self.book.chapters[-1][1], want["last_chapter_title"])
        self.assertIn(self.book.rule["serialNumber"], (0, 1))

    def test_phone_chapter_numbering(self):
        """手机报的章标题，与规则算出来的同一号章逐字一致"""
        idx = CAL["phone_idx"]
        self.assertEqual(self.book.title(idx), CAL["phone_title"])
        self.assertEqual(self.book.chapters[idx], self.book.matches[idx - 1])


class TestByteChar(TxtBase):
    def test_byte_to_char(self):
        self.assertEqual(self.book.byte_to_char(CAL["moeli_bytes"]), CAL["moeli_chars"])
        self.assertEqual(self.book.byte_to_char(0), 0)
        self.assertEqual(self.book.byte_to_char(self.book.byte_len), CAL["chars_total"])

    def test_char_to_byte_roundtrip(self):
        # 都落在字符边界上：文件头、第一个字的末尾、Moeli 报的偏移、文件末尾
        first = len(self.book.text[0].encode(self.book.enc))
        for b in (0, first, CAL["moeli_bytes"], CAL["bytes_total"]):
            self.assertEqual(self.book.char_to_byte(self.book.byte_to_char(b)), b)

    def test_mid_char_byte_clamps_to_that_char(self):
        """落在字中间的字节偏移，归到该字的起点，不会算成下一个字"""
        last = CAL["chars_total"] - 1
        self.assertEqual(self.book.byte_to_char(CAL["bytes_total"] - 1), last)
        self.assertEqual(self.book.char_to_byte(last),
                         CAL["bytes_total"] - len(self.book.text[-1].encode(self.book.enc)))

    def test_char_to_byte(self):
        self.assertEqual(self.book.char_to_byte(CAL["moeli_chars"]), CAL["moeli_bytes"])


class TestConvert(TxtBase):
    def test_moeli_to_legado(self):
        """Moeli 的字节偏移 -> 手机口径的 (章号, 章内偏移)"""
        want = CAL["expect"]["moeli_to_legado"]
        idx, pos, title = self.book.moeli_to_legado(CAL["moeli_bytes"])
        self.assertEqual((idx, pos, title), tuple(want))
        self.assertEqual(self.book.pct(idx, pos), CAL["expect"]["moeli_pct"])

    def test_legado_to_moeli_roundtrip(self):
        idx, pos, _ = CAL["expect"]["moeli_to_legado"]
        self.assertEqual(self.book.legado_to_moeli(idx, pos), CAL["moeli_bytes"])

    def test_phone_position_roundtrip(self):
        """手机报的位置转成字节再转回来，必须一模一样"""
        b = self.book.legado_to_moeli(CAL["phone_idx"], CAL["phone_pos"])
        self.assertEqual(self.book.moeli_to_legado(b)[:2], (CAL["phone_idx"], CAL["phone_pos"]))
        lo, hi = CAL["expect"]["phone_pct"]
        self.assertTrue(lo <= self.book.pct(CAL["phone_idx"], CAL["phone_pos"]) <= hi)

    def test_gap_between_two_sides(self):
        """两个真位置差多少（用来判断该往哪边推）"""
        a = self.book._starts[CAL["phone_idx"]] + CAL["phone_pos"]
        b = self.book.byte_to_char(CAL["moeli_bytes"])
        self.assertGreater(a - b, CAL["expect"]["min_gap_chars"])

    def test_out_of_range(self):
        with self.assertRaises(T.TxtError):
            self.book.legado_to_moeli(999, 0)


class TestByteCharGeneric(unittest.TestCase):
    """不挑书：字节↔字符换算在任何一本 txt 上都该自洽"""

    @classmethod
    def setUpClass(cls):
        paths = all_txt_paths() or [book_path()]
        try:
            rules = T.load_rules(T.RULES_FILE, legado_dir=LEGADO)
        except T.TxtError:
            rules = []
        book = pick_cuttable(paths, rules)
        if book is None:
            # 库里这些 txt 都被规则切不动，退回按字数等分，字节换算照样查
            book = T.TxtBook(paths[0], rules=[])
        cls.book = book
        print("\n（通用换算检查用：%s）" % os.path.basename(book.path))

    def test_boundaries(self):
        b = self.book
        self.assertEqual(b.byte_to_char(0), 0)
        self.assertEqual(b.char_to_byte(0), 0)
        self.assertEqual(b.char_to_byte(b.byte_to_char(b.byte_len)), b.byte_len)
        self.assertLessEqual(b.byte_to_char(b.byte_len), len(b.text))

    def test_monotonic(self):
        b = self.book
        step = max(1, b.byte_len // 500)
        last_c = -1
        for x in range(0, b.byte_len + 1, step):
            c, by = b.byte_to_char(x), b.char_to_byte(b.byte_to_char(x))
            self.assertGreaterEqual(c, last_c)
            self.assertLessEqual(by, x)
            last_c = c

    def test_chapters_cover_whole_file(self):
        b = self.book
        self.assertTrue(b.chapters)
        self.assertEqual(b.chapters[0][0], 0)
        starts = [c[0] for c in b.chapters] + [len(b.text)]
        self.assertEqual(starts, sorted(starts))
        self.assertLessEqual(starts[-2], len(b.text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
