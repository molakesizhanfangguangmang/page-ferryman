# -*- coding: utf-8 -*-
"""epub CFI <-> (章, 章内字符偏移) 互转。

用途：阅读进度桥接。Android legado 用 (durChapterIndex, durChapterPos) 表示位置，
iOS Moeli 用 epubcfi(/6/N!/...) / txtloc(...) 表示位置。两者要互通必须能做坐标换算。

约定（两个方向共用，保证自洽）：
  * "章" = epub TOC（ncx/nav）里的第 N 项，N 从 0 起 —— 实测 legado 的
    durChapterIndex 就是这个下标（本机标定那本：TOC 3 项，两端都报 idx=1 = 正文）。
  * "章内偏移" = 该章 xhtml 文档中，按文档顺序累计的正文字符数（默认折叠空白）。

纯标准库，无外部依赖。
"""

import re
import zipfile
import xml.etree.ElementTree as ET

_WS = re.compile(r"\s+")


def _tag(e):
    return e.tag.split("}")[-1]


class EpubDoc(object):
    def __init__(self, path):
        self.path = path
        self.z = zipfile.ZipFile(path)
        self.opf_path = self._find_opf()
        self._opf_root = ET.fromstring(self.z.read(self.opf_path))
        self.manifest, self.spine, self.spine_step = self._manifest_spine()
        self.toc = self._toc()
        self._len_cache = {}
        self._tree_cache = {}

    # ---------- 包结构 ----------
    def _find_opf(self):
        c = ET.fromstring(self.z.read("META-INF/container.xml"))
        for e in c.iter():
            if _tag(e) == "rootfile":
                return e.get("full-path")
        raise ValueError("container.xml 里没有 rootfile")

    def _manifest_spine(self):
        base = self.opf_path.rsplit("/", 1)[0] if "/" in self.opf_path else ""
        fix = (lambda h: base + "/" + h) if base else (lambda h: h)
        manifest, idrefs, spine_el = {}, [], None
        for e in self._opf_root:
            if _tag(e) == "manifest":
                for it in e:
                    if _tag(it) == "item":
                        href = fix(it.get("href"))
                        manifest[it.get("id")] = {
                            "href": href,
                            "type": it.get("media-type") or "",
                            "props": it.get("properties") or "",
                        }
            elif _tag(e) == "spine":
                spine_el = e
                for it in e:
                    if _tag(it) == "itemref":
                        idrefs.append(it.get("idref"))
        # spine 元素在 package 元素子节点中的序号（CFI 步长 = 2*序号）
        spine_step = None
        for i, e in enumerate(list(self._opf_root), 1):
            if _tag(e) == "spine":
                spine_step = 2 * i
                break
        if spine_el is None:
            raise ValueError("opf 里没有 spine")
        spine = [manifest[i]["href"] for i in idrefs if i in manifest]
        return manifest, spine, spine_step

    def _toc(self):
        """返回 [(title, href)]，按阅读顺序。优先 ncx，其次 nav，都没有就用 spine。"""
        ncx = None
        nav = None
        for it in self.manifest.values():
            if "dtbncx" in it["type"]:
                ncx = it["href"]
            elif "nav" in it["props"].split():
                nav = it["href"]
        out = []
        sub = (lambda d: (lambda h: d + "/" + h))(ncx.rsplit("/", 1)[0]) if ncx and "/" in ncx else (lambda h: h)
        subn = (lambda d: (lambda h: d + "/" + h))(nav.rsplit("/", 1)[0]) if nav and "/" in nav else (lambda h: h)
        if ncx:
            root = ET.fromstring(self.z.read(ncx))
            for np in root.iter():
                if _tag(np) != "navPoint":
                    continue
                label, src = "", ""
                for c in np:
                    if _tag(c) == "navLabel":
                        for t in c.iter():
                            if _tag(t) == "text":
                                label = (t.text or "").strip()
                    elif _tag(c) == "content":
                        src = c.get("src") or ""
                if src:
                    out.append((label, sub(src.split("#")[0])))
        elif nav:
            root = ET.fromstring(self.z.read(nav))
            for a in root.iter():
                if _tag(a) == "a":
                    href = a.get("href") or ""
                    if href and not href.startswith(("http", "mailto")):
                        out.append(((a.text or "").strip(), subn(href.split("#")[0])))
        else:
            out = [("", h) for h in self.spine]
        return out

    def chapter_href(self, idx):
        """legado 的 durChapterIndex -> 该章的 xhtml 路径"""
        if idx < 0 or idx >= len(self.toc):
            raise IndexError("章号越界: %s（本书共 %d 章）" % (idx, len(self.toc)))
        return self.toc[idx][1]

    def chapter_title(self, idx):
        return self.toc[idx][0]

    def spine_index(self, href):
        """spine 中的 1 起序号"""
        if href in self.spine:
            return self.spine.index(href) + 1
        # 退一步：按文件名匹配
        for i, h in enumerate(self.spine, 1):
            if h.rsplit("/", 1)[-1] == href.rsplit("/", 1)[-1]:
                return i
        raise ValueError("不在 spine 里: %s" % href)

    # ---------- DOM ----------
    def tree(self, href):
        if href not in self._tree_cache:
            raw = self.z.read(href).decode("utf-8")
            raw = re.sub(r"^\s*<\?xml[^>]*\?>", "", raw)
            self._tree_cache[href] = ET.fromstring(raw)
        return self._tree_cache[href]

    @staticmethod
    def _norm(text, collapse=True):
        return _WS.sub(" ", text) if collapse else text

    def _tlen(self, e, collapse=True):
        """子树正文字符数"""
        key = (id(e), collapse)
        if key in self._len_cache:
            return self._len_cache[key]
        n = len(self._norm(e.text or "", collapse))
        for c in e:
            n += self._tlen(c, collapse) + len(self._norm(c.tail or "", collapse))
        self._len_cache[key] = n
        return n

    @staticmethod
    def _nodes(e):
        """元素的孩子按文档顺序展开成 CFI 的“节点序号”：
        1 = 元素自身文本, 2 = 第1个子元素, 3 = 第1个子元素之后的文本, 4 = 第2个子元素 ...
        """
        seq = [(1, e.text or "", None)]
        for i, c in enumerate(list(e), 1):
            seq.append((2 * i, None, c))
            seq.append((2 * i + 1, c.tail or "", None))
        return seq

    # ---------- offset -> CFI ----------
    def offset_to_cfi(self, href, offset, collapse=True):
        """章内字符偏移 -> epubcfi(...)"""
        s_idx = self.spine_index(href)
        root = self.tree(href)
        steps = self._emit(root, offset, collapse)
        return "epubcfi(/%d/%d!%s)" % (
            self.spine_step,
            2 * s_idx,
            "".join("/" + s for s in steps),
        )

    def _emit(self, e, off, collapse):
        for k, text, child in self._nodes(e):
            if child is None:                       # 文本节点：元素自身文本 / 前面子元素的 tail
                n = len(self._norm(text, collapse))
                if off <= n:
                    return ["%d:%d" % (k, off)]
                off -= n
            else:                                   # 子元素：整体跳过或下钻
                n = self._tlen(child, collapse)
                if off < n:
                    return [str(k)] + self._emit(child, off, collapse)
                off -= n
        raise ValueError("偏移超出该章长度")

    # ---------- CFI -> offset ----------
    def cfi_to_offset(self, cfi, collapse=True):
        """epubcfi(...) -> (href, 章内偏移)"""
        m = re.match(r"^epubcfi\((.+)\)$", cfi.strip())
        if not m:
            raise ValueError("不是 epubcfi: %s" % cfi)
        body = m.group(1)
        if "!" not in body:
            raise ValueError("缺少间接步（!）: %s" % cfi)
        pre, post = body.split("!", 1)
        parts = [p for p in pre.split("/") if p]
        # 前半段：/spine_step/spine_num
        if len(parts) < 2:
            raise ValueError("前缀不完整: %s" % pre)
        spine_step = int(re.match(r"\d+", parts[0]).group(0))
        spine_num = int(re.match(r"\d+", parts[1]).group(0)) // 2
        if spine_step != self.spine_step:
            raise ValueError("spine 步长不符（文件=%s 期望=%s）" % (spine_step, self.spine_step))
        href = self.spine[spine_num - 1]
        steps = [p for p in post.split("/") if p]
        return href, self._walk(self.tree(href), steps, 0, collapse)

    def _walk(self, e, steps, acc, collapse):
        if not steps:
            return acc
        m = re.fullmatch(r"(\d+)(?:\[[^\]]*\])?(?::(\d+))?", steps[0])
        if not m:
            raise ValueError("无法解析的步: %s" % steps[0])
        idx = int(m.group(1))
        char = m.group(2)
        for k, text, child in self._nodes(e):
            if k == idx:
                if char is not None:
                    if child is not None:
                        raise ValueError("元素步上不该有字符偏移")
                    return acc + int(char)
                if child is None:
                    raise ValueError("文本节点上不该有元素步")
                return self._walk(child, steps[1:], acc, collapse)
            if k > idx:
                break
            if child is not None:
                acc += self._tlen(child, collapse)
            else:
                acc += len(self._norm(text, collapse))
        raise ValueError("步序号越界: %s" % steps[0])

    # ---------- txtloc ----------
    @staticmethod
    def parse_txtloc(s):
        """txtloc(章:字符:?) -> (章, 字符)"""
        m = re.match(r"^txtloc\((\d+):(\d+):(\d+)\)$", s.strip())
        if not m:
            raise ValueError("不是 txtloc: %s" % s)
        return int(m.group(1)), int(m.group(2))

    @staticmethod
    def make_txtloc(chapter, char, flag=0):
        return "txtloc(%d:%d:%d)" % (chapter, char, flag)


def chapter_char_total(epub, idx, collapse=True):
    """某章的正文总字符数"""
    return epub._tlen(epub.tree(epub.chapter_href(idx)), collapse)
