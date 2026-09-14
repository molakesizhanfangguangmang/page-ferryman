# -*- coding: utf-8 -*-
"""txt 的坐标换算：Moeli 的 txtloc <-> legado 的 (章号, 章内偏移)。

现状（2026-09-14 实测标定）：

  * Moeli 侧：`txtloc(1:237923:0)`，第二个字段是**字节偏移**，不是字符数。
    本机标定那本：237923 字节 = 82377 字符 = 全书 17.8%，与它自报的 `readPercent=17` 吻合。
    第一个字段按现有观测固定为 1（Moeli 把整本 txt 当一章）；第三个字段为 0。
    写回时保留原来的一、三字段，只改第二个 —— 这两个字段的语义没有第二个样本可验证。
  * legado 侧：`(durChapterIndex, durChapterPos)`。章号由手机自己的切章规则
    （`txtTocRule.json`，见同目录固定副本）切出来；`durChapterPos` 从该章开头（标题行首字）
    算起。legado 还会把第一个匹配之前的那段正文单独算成第 0 章，标题「前言」——
    同一本切出 97 章 + 前言 = 手机报的 `totalChapterNum=98`，即
    **手机章号 = 规则命中序号 + 1**。

换算链路（只在跨软件时用）：

    字节 -> 字符 -> 规则命中序号 -> 手机章号(+1) + 章内偏移

选规则：手机报过总章数的（书架快照里的 `totalChapterNum`）优先拿它当准绳 ——
挑切出来正好等于「总章数」的那条，能一比一复刻手机的章号。没准绳时退回
「按 serialNumber 升序，第一条能切出 ≥2 章的规则」。legado 具体的择优逻辑没有源码可核，
所以准绳优先；准绳对不上时会在说明里写出来。

纯标准库。
"""

import bisect
import glob
import json
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(HERE, "txt-toc-rule.json")
PREFACE = "前言"          # legado 给第一个匹配之前那段正文的标题
LEAD_BYTES = 3            # 常见中文 txt 的每字字节数，仅用于说明


class TxtError(Exception):
    pass


def rules_from_backups(legado_dir):
    """从 legado 的备份 zip 里抽 txtTocRule.json —— 用使用者自己那份切章规则"""
    best = None
    for z in glob.glob(os.path.join(legado_dir, "backup*.zip")):
        m = re.search(r"backup(\d{4})-(\d{2})-(\d{2})-(.+)\.zip$", os.path.basename(z))
        if not m:
            continue
        key = (m.group(1), m.group(2), m.group(3), os.path.getmtime(z))
        if best is None or key > best[0]:
            best = (key, z)
    if best is None:
        return None, None
    with zipfile.ZipFile(best[1]) as zf:
        hit = [n for n in zf.namelist() if os.path.basename(n) == "txtTocRule.json"]
        if not hit:
            return None, None
        return json.loads(zf.read(hit[0]).decode("utf-8")), best[1]


def load_rules(path=None, legado_dir=None):
    """切章规则：指定的文件 -> 同目录固定副本 -> 从最新备份抽（抽到顺手存一份）"""
    path = path or RULES_FILE
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    elif legado_dir:
        data, _src = rules_from_backups(legado_dir)
        if data is None:
            raise TxtError("没有切章规则：既没有 %s，备份里也没有 txtTocRule.json" % path)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
    else:
        raise TxtError("没有切章规则文件：%s" % path)
    rs = [r for r in data if r.get("enable") and (r.get("rule") or "").strip()]
    if not rs:
        raise TxtError("切章规则里没有启用项：%s" % path)
    return sorted(rs, key=lambda r: r.get("serialNumber") or 0)


def decode(raw):
    for enc in ("utf-8", "gb18030", "utf-16"):
        try:
            t = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if t.encode(enc) == raw:          # 能原样编回去，字节偏移才谈得上准确
            return t, enc
    raise TxtError("解不开编码（试过 utf-8/gb18030/utf-16）")


def match_rule(text, rule):
    """跑一条规则。Python 编译不了的（legado 的变长 lookbehind）返回 None"""
    try:
        pat = re.compile(rule, re.MULTILINE)
    except re.error:
        return None
    return [(m.start(), m.group(0).strip()) for m in pat.finditer(text)]


class TxtBook(object):
    def __init__(self, path, rules=None, reported_chapters=None):
        self.path = path
        self.rules = rules if rules is not None else load_rules()
        with open(path, "rb") as f:
            raw = f.read()
        self.byte_len = len(raw)
        self.text, self.enc = decode(raw)

        offs = [0] * (len(self.text) + 1)
        acc = 0
        for i, ch in enumerate(self.text):
            acc += len(ch.encode(self.enc))
            offs[i + 1] = acc
        self._byte_at = offs                     # 字符下标 -> 起始字节

        self.rule, self.matches, self.rule_note = pick_rule(
            self.text, self.rules, reported_chapters)
        if not self.matches:
            raise TxtError("没有一条规则能切章：%s" % self.path)

        self.chapters = []                       # [(起始字符下标, 标题)]
        if self.matches[0][0] > 0:               # 开头那段被 legado 当成第 0 章
            self.chapters.append((0, PREFACE))
        self.chapters.extend(self.matches)
        self._starts = [c[0] for c in self.chapters]

    # ---------- 基本 ----------
    def totals(self):
        """每章字符数（跟 epub 那套接口一致，给桥的门槛计算用）"""
        n = len(self.chapters)
        return [(self._starts[i + 1] if i + 1 < n else len(self.text)) - self._starts[i]
                for i in range(n)]

    def pct(self, idx, pos):
        c = min(self._starts[idx] + max(0, pos), len(self.text))
        return round(100.0 * c / len(self.text))

    # ---------- 字节 <-> 字符 ----------
    def byte_to_char(self, b):
        if b <= 0:
            return 0
        if b >= self.byte_len:
            return len(self.text)
        i = bisect.bisect_right(self._byte_at, b) - 1
        return max(0, min(i, len(self.text)))

    def char_to_byte(self, c):
        return self._byte_at[max(0, min(c, len(self.text)))]

    # ---------- 两套坐标互转 ----------
    def moeli_to_legado(self, byte_off):
        """Moeli 的字节偏移 -> (章号, 章内偏移, 章标题)"""
        c = self.byte_to_char(byte_off)
        i = max(0, bisect.bisect_right(self._starts, c) - 1)
        return i, c - self._starts[i], self.chapters[i][1]

    def legado_to_moeli(self, idx, pos):
        """(章号, 章内偏移) -> Moeli 的字节偏移"""
        if idx < 0 or idx >= len(self.chapters):
            raise TxtError("章号越界：%s（共 %d 章）" % (idx, len(self.chapters)))
        nxt = self._starts[idx + 1] if idx + 1 < len(self.chapters) else len(self.text)
        c = max(self._starts[idx], min(self._starts[idx] + max(0, pos), nxt - 1))
        return self.char_to_byte(c)

    def title(self, idx):
        return self.chapters[idx][1] if 0 <= idx < len(self.chapters) else None

    def describe(self):
        return "%d 章（含「%s」%s），编码 %s，%d 字节 / %d 字符，规则 [%s]%s" % (
            len(self.chapters), self.chapters[0][1],
            "有" if self.chapters[0][1] == PREFACE else "无",
            self.enc, self.byte_len, len(self.text),
            self.rule.get("serialNumber") if self.rule else "?",
            ("：" + self.rule_note) if self.rule_note else "")


def pick_rule(text, rules, reported=None):
    """挑切章规则 -> (规则, 命中列表, 说明)

    reported = 手机快照里的 totalChapterNum，有它就以它为准绳（能复刻手机的章号）。
    """
    cands = []
    unusable = []
    for r in rules:
        m = match_rule(text, r["rule"])
        if m is None:
            unusable.append(r.get("serialNumber"))
            continue
        cands.append((r, m))

    note = ""
    if reported:
        for r, m in cands:
            n = len(m) + (1 if m and m[0][0] > 0 else 0)
            if n == reported:
                return r, m, "与手机报的总章数 %d 一致" % reported
        note = "手机报 %d 章，没有规则切得正好；" % reported

    for r, m in cands:
        if len(m) >= 2:
            return r, m, note + "按 serialNumber 取第一条能切出多章的规则"
    if cands:
        return cands[0][0], cands[0][1], note + "只有一条规则有命中"
    raise TxtError("所有规则都没命中；编译不了的规则序号：%s" % unusable)


def parse_txtloc(s):
    """txtloc(章:字节:标记) -> (章, 字节, 标记)"""
    m = re.match(r"^txtloc\((\d+):(\d+):(\d+)\)$", (s or "").strip())
    if not m:
        raise TxtError("不是 txtloc: %r" % s)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))
