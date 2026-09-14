#!/usr/bin/env python3
"""Patch Talebook's WebDAV sync provider for reading-progress events.

The patch is deliberately text-based and version-checked: an unknown source layout
fails instead of silently changing an unrelated Talebook installation.
"""
import re
import sys

MARKER = "# reading-progress-bridge event hook"

HELPER = r'''# reading-progress-bridge event hook
class _ProgressTriggerFile:
    def __init__(self, fileobj, path):
        self._file = fileobj
        self._path = path

    def __getattr__(self, name):
        return getattr(self._file, name)

    def close(self):
        self._file.close()
        _trigger_progress_bridge(self._path)


def _trigger_progress_bridge(path):
    normalized = os.path.normpath(path)
    if not (normalized.endswith("/moeli_reader/book.db") or
            ("/legado/bookProgress/" in normalized and normalized.endswith(".json"))):
        return
    script = "/opt/reading-progress-bridge/trigger.sh"
    if not os.path.isfile(script):
        return
    try:
        subprocess.Popen(
            ["/bin/sh", script, normalized],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,
        )
    except Exception:
        logging.exception("reading progress bridge event trigger failed: %s", normalized)


'''


def patch(s):
    if MARKER in s:
        return s, False
    if "from wsgidav.fs_dav_provider import FilesystemProvider" not in s:
        raise SystemExit("找不到 FilesystemProvider 导入，Talebook WebDAV 结构不匹配")

    s = s.replace("import re\n", "import re\nimport subprocess\n", 1)
    anchor = "from wsgidav.fs_dav_provider import FilesystemProvider\n\n"
    if "class UserSyncFilesystemProvider" in s:
        s = s.replace(anchor, anchor + HELPER, 1)
        old = '''    def _relative_path(self, path):
        if self.url_prefix != "/":'''
        new = '''    def _relative_path(self, path):
        for _ in range(3):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        if self.url_prefix != "/":'''
        if old not in s:
            raise SystemExit("找不到同步目录路径入口，未修改")
        s = s.replace(old, new, 1)
        pattern = re.compile(
            r'''    def get_resource_inst\(self, path, environ\):\n        resource = super\(\)\.get_resource_inst\(self\._relative_path\(path\), environ\)\n        if resource is not None:\n            resource\.path = path\n        return resource\n'''
        )
        replacement = '''    def get_resource_inst(self, path, environ):
        resource = super().get_resource_inst(self._relative_path(path), environ)
        if resource is not None:
            resource.path = path
            if resource.path != "/" and hasattr(resource, "begin_write"):
                original_begin_write = resource.begin_write

                def begin_write(content_type=None):
                    fileobj = original_begin_write(content_type=content_type)
                    file_path = resource.provider._loc_to_file_path(
                        resource.path, resource.environ
                    )
                    return _ProgressTriggerFile(fileobj, file_path)

                resource.begin_write = begin_write
        return resource
'''
        s, n = pattern.subn(replacement, s, count=1)
        if n != 1:
            raise SystemExit("找不到同步目录写入入口，未修改")
        return s, True

    # Official v26.09.01 uses a plain FilesystemProvider per user.
    helper = HELPER + '''class ReadingProgressFilesystemProvider(FilesystemProvider):
    def get_resource_inst(self, path, environ):
        resource = super().get_resource_inst(path, environ)
        if resource is not None and resource.path != "/":
            original_begin_write = resource.begin_write

            def begin_write(content_type=None):
                return _ProgressTriggerFile(
                    original_begin_write(content_type=content_type), resource._file_path
                )

            resource.begin_write = begin_write
        return resource


'''
    s = s.replace(anchor, anchor + helper, 1)
    old = "self._user_fs_providers[user_id] = FilesystemProvider(path)"
    new = "self._user_fs_providers[user_id] = ReadingProgressFilesystemProvider(path)"
    if old not in s:
        raise SystemExit("找不到 FilesystemProvider 创建入口，未修改")
    return s.replace(old, new, 1), True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法：event_patch.py dav_provider.py")
    path = sys.argv[1]
    text = open(path, encoding="utf-8").read()
    out, changed = patch(text)
    if changed:
        open(path, "w", encoding="utf-8").write(out)
    print("already-patched" if not changed else "patched")
