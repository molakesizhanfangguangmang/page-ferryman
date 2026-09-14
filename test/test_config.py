# -*- coding: utf-8 -*-
"""配置与目录发现的自测：都是临时目录里的假数据，不碰真实数据。

跑：python3 test/test_config.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.dirname(HERE)

PROBE = (
    "import json,sys;"
    "sys.path.insert(0, %r);"
    "import bridge as b;"
    "print(json.dumps({'data': b.DATA, 'lib': b.LIB, 'reader': b.READER,"
    " 'legado': b.LEGADO, 'progress': b.PROGRESS, 'moeli': b.MOELI, 'db': b.DB,"
    " 'backup': b.BACKUP, 'rules': b.RULES_FILE, 'pct': b.THRESH_PCT,"
    " 'chars': b.THRESH_CHARS, 'interval': b.INTERVAL,"
    " 'skip': sorted(b.SKIP_BOOKS), 'state': b._STATE_DIR}))" % DIST
)


def resolve(env, extra_env=None):
    e = dict(os.environ)
    for k in list(e):
        if k.startswith("RPB_"):
            del e[k]
    e.update(env or {})
    e.update(extra_env or {})
    out = subprocess.check_output([sys.executable, "-c", PROBE], env=e, stderr=subprocess.STDOUT)
    return json.loads(out.decode("utf-8").strip().splitlines()[-1])


def make_tree(root):
    for rid, with_moeli in (("3", False), ("7", True)):
        os.makedirs(os.path.join(root, "reader", rid, "legado", "bookProgress"), exist_ok=True)
        if with_moeli:
            os.makedirs(os.path.join(root, "reader", rid, "moeli_reader", "book"), exist_ok=True)
    os.makedirs(os.path.join(root, "books", "library", "作者", "某书 (12)"), exist_ok=True)
    return root


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rpb-cfg-")
        self.data = make_tree(os.path.join(self.tmp, "data"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_picks_reader_with_moeli(self):
        got = resolve({"RPB_DATA": self.data})
        self.assertEqual(got["reader"], os.path.join(self.data, "reader", "7"))
        self.assertEqual(got["legado"], os.path.join(self.data, "reader", "7", "legado"))
        self.assertEqual(got["progress"], os.path.join(self.data, "reader", "7", "legado", "bookProgress"))
        self.assertEqual(got["moeli"], os.path.join(self.data, "reader", "7", "moeli_reader"))
        self.assertEqual(got["db"], os.path.join(self.data, "reader", "7", "moeli_reader", "book.db"))
        self.assertEqual(got["backup"], os.path.join(self.data, "reader", "7", "backup", "bridge"))
        self.assertEqual(got["lib"], os.path.join(self.data, "books", "library"))

    def test_reader_user_pins_it(self):
        got = resolve({"RPB_DATA": self.data, "RPB_READER_USER": "3"})
        self.assertEqual(got["reader"], os.path.join(self.data, "reader", "3"))
        self.assertEqual(got["moeli"], os.path.join(self.data, "reader", "3", "moeli_reader"))

    def test_reader_user_missing_falls_back(self):
        got = resolve({"RPB_DATA": self.data, "RPB_READER_USER": "99"})
        self.assertEqual(got["reader"], os.path.join(self.data, "reader", "7"))

    def test_defaults(self):
        got = resolve({"RPB_DATA": self.data})
        self.assertEqual(got["pct"], 0.003)
        self.assertEqual(got["chars"], 200)
        self.assertEqual(got["interval"], 300)
        self.assertEqual(got["skip"], [])
        self.assertEqual(got["rules"], os.path.join(DIST, "txt-toc-rule.json"))

    def test_empty_data_dir_is_not_fatal(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        got = resolve({"RPB_DATA": empty})
        self.assertEqual(got["reader"], os.path.join(empty, "reader", "1"))


class TestConfigFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rpb-cfg-")
        self.data = make_tree(os.path.join(self.tmp, "data"))
        self.cfg = os.path.join(self.tmp, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"_说明": "注释键要忽略", "data": self.data, "interval_seconds": 60,
                       "threshold_chars": 50, "threshold_percent": 0.5, "apply": True,
                       "skip_books": [2, 3], "reader_user": "3", "rules_file": "x.json"},
                      f)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_config_file(self):
        got = resolve({}, {"RPB_CONFIG": self.cfg})
        self.assertEqual(got["data"], self.data)
        self.assertEqual(got["reader"], os.path.join(self.data, "reader", "3"))
        self.assertEqual(got["interval"], 60)
        self.assertEqual(got["chars"], 50)
        self.assertEqual(got["pct"], 0.005)
        self.assertEqual(got["skip"], [2, 3])
        self.assertEqual(got["rules"], "x.json")

    def test_env_beats_config_file(self):
        got = resolve({"RPB_THRESHOLD_CHARS": "999", "RPB_INTERVAL_SECONDS": "5"},
                      {"RPB_CONFIG": self.cfg})
        self.assertEqual(got["chars"], 999)
        self.assertEqual(got["interval"], 5)

    def test_broken_config_is_ignored(self):
        bad = os.path.join(self.tmp, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{ this is not json")
        got = resolve({"RPB_DATA": self.data}, {"RPB_CONFIG": bad})
        self.assertEqual(got["chars"], 200)
        self.assertEqual(got["pct"], 0.003)


if __name__ == "__main__":
    unittest.main(verbosity=2)
