# 页渡者

“摆渡”出自中国文学中反复出现的渡河意象，摆渡人不替行者决定去处，只负责把人送到彼岸。
“页渡者”借这个意象，为不同阅读器之间失落的进度搭一叶小舟，让同一本书在不同设备上接得上。

*从安卓渡向 iOS，从一页渡向另一页。*

*不改书，只渡进度；不改章，只接前后。*

把同一套 Talebook 里的 legado（安卓）和 Moeli Reader（iOS）阅读进度对到一起。上传进度后会立即检查两边的位置，10 分钟扫描作为兜底；跨软件 txt 章节不同优先保证章节一致，同章才使用字数阈值。

## 安装

需要 Docker Talebook、容器内 Python 3，以及宿主机执行 Docker 和写入数据目录的权限。Talebook 数据目录应挂载到容器 `/data`。

从 [Releases](https://github.com/molakesizhanfangguangmang/page-ferryman/releases) 下载单文件安装器：

```sh
curl -fsSLO https://github.com/molakesizhanfangguangmang/page-ferryman/releases/latest/download/install-reading-progress-bridge.sh
sudo sh install-reading-progress-bridge.sh
```

默认安装两部分：阅读进度桥，以及 Talebook WebDAV 上传完成触发。App 上传 `book.db` 或 `bookProgress/*.json` 后，桥会在几秒内运行；10 分钟扫描作为兜底。

第一次安装默认只干跑，不写阅读进度。确认输出里的书和方向后再执行：

```sh
sudo sh install-reading-progress-bridge.sh --apply
```

只安装桥、不注入 Talebook WebDAV：

```sh
sudo sh install-reading-progress-bridge.sh --no-event-trigger
```

安装器会备份被注入的 Talebook 文件。Talebook 容器重建后重新执行安装器即可补回注入。

## 错误通知

页渡者会把无法自动处理的情况写入日志。安装器还会在 Talebook 管理员设置页加入“页渡者错误通知”区块，通知方式是下拉选择：`关闭`、`Webhook` 或 `Telegram Bot`；选择后只显示对应配置，并提供测试发送按钮。

配置保存在数据目录的 `.reading-progress-bridge/notify.json`。Bot Token 只由后端使用，设置页返回时会掩码显示。

如果当前 Talebook 版本的设置页结构无法匹配，安装器会停止注入并保留原文件。

## 运行与配置

程序位于数据目录的 `.reading-progress-bridge/`，由 Talebook 容器内 supervisord 管理。配置文件是 `.reading-progress-bridge/config.json`：

```json
{
  "interval_seconds": 600,
  "threshold_chars": 200,
  "threshold_percent": 0.3,
  "apply": false
}
```

`apply=false` 只计算，`apply=true` 才写入。跨软件 epub 使用 CFI，txt 使用字节偏移和切章规则；安卓与安卓之间不换算。写入前会备份到 `reader/<用户号>/backup/bridge/`。

日志：

```sh
docker exec talebook tail -f /var/tmp/reading-progress-bridge/run.log
```

## 边界

- 不会替 App 点击云端进度确认。
- txt 第一次跨端使用时，先在 iOS 端打开并同步，再在安卓端打开。
- 无法匹配书籍、切章失败或内容不一致时跳过并记录日志。
- 目前跨软件支持 epub 和 txt；pdf、mobi、azw3、cbz 暂不处理。

## 卸载

```sh
sudo sh uninstall.sh talebook /srv/talebook/data
```

`uninstall.sh` 会尝试恢复 WebDAV 和设置页备份，不删除书库、阅读进度或桥的备份。

## 测试

```sh
python3 test/test_config.py
python3 test/test_cfi.py
python3 test/test_txt.py
python3 test/test_e2e_txt.py
```

## 许可

MIT，见 [LICENSE](LICENSE)。
