# 页渡者

“摆渡”出自中国文学中反复出现的渡河意象，摆渡人不替行者决定去处，只负责把人送到彼岸。
“页渡者”借这个意象，为不同阅读器之间失落的进度搭一叶小舟，让同一本书在不同设备上接得上。
*从安卓渡向 iOS，从一页渡向另一页。* *不改书，只渡进度；不替人点，只把路铺平。*

把同一套 Talebook 里的 legado（安卓）和 Moeli Reader（iOS）阅读进度对到一起。

它会在进度文件上传完成后立即检查两边的位置；10 分钟扫描作为兜底。差距超过规则后，桥会把落后的一边改到领先的位置；App 下次同步时仍会按自己的规则弹出“云端进度更靠前”的确认框，脚本不替你点确认。

## 安装

需要：

- Talebook 运行在 Docker 里，数据目录挂载到容器的 `/data`
- 容器里有 Python 3
- 同一个 Talebook 已经生成过 `reader/<用户号>/legado` 和 `reader/<用户号>/moeli_reader`
- 宿主机可以执行 Docker，并能写入 Talebook 数据目录

从 [Releases](https://github.com/molakesizhanfangguangmang/page-ferryman/releases) 下载单文件安装器：

```sh
curl -fsSLO https://github.com/molakesizhanfangguangmang/page-ferryman/releases/latest/download/install-reading-progress-bridge.sh
sudo sh install-reading-progress-bridge.sh
```

安装脚本会同时安装阅读进度桥和 Talebook WebDAV 事件触发。App 上传 `book.db` 或 `bookProgress/*.json` 完成后，桥会在几秒内运行；10 分钟扫描作为兜底。

安装器会先备份 Talebook 的 WebDAV 文件，再注入触发代码。备份在容器内：

```text
/var/tmp/reading-progress-bridge/webdav-backup/dav_provider.py
```

如果只想安装桥、不改 Talebook WebDAV：

```sh
sudo sh install-reading-progress-bridge.sh --no-event-trigger
```

也可以直接指定容器和数据目录：

```sh
sudo sh install-reading-progress-bridge.sh talebook /srv/talebook/data
```

第一次安装只做检查，不写阅读进度。确认输出里的书和方向没问题后，再打开写入：

```sh
sudo sh install-reading-progress-bridge.sh --apply
```

也可以先把安装器解开查看，不执行安装：

```sh
sh install-reading-progress-bridge.sh --extract-only /tmp/reading-progress-bridge
```

## 运行方式

安装脚本会把程序放到数据目录的 `.reading-progress-bridge/`，并在 Talebook 容器里注册为 supervisord 程序。默认每 10 分钟检查一次，容器重启后会跟着启动。
