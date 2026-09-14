# Talebook 阅读进度桥

把同一套 Talebook 里的 legado（安卓）和 Moeli Reader（iOS）阅读进度对到一起。

它每隔一段时间检查一次两边的位置。差距超过阈值，就把落后的一边改到领先的位置；App 下次同步时仍会按自己的规则弹出“云端进度更靠前”的确认框。脚本不替你点确认。

## 安装

需要：

- Talebook 运行在 Docker 里，数据目录挂载到容器的 `/data`
- 容器里有 Python 3
- 同一个 Talebook 已经生成过 `reader/<用户号>/legado` 和 `reader/<用户号>/moeli_reader`
- 宿主机可以执行 Docker，并能写入 Talebook 数据目录

从 [Releases](https://github.com/molakesizhanfangguangmang/talebook-reading-progress-bridge/releases) 下载单文件安装器：

```sh
curl -fsSLO https://github.com/molakesizhanfangguangmang/talebook-reading-progress-bridge/releases/latest/download/install-reading-progress-bridge.sh
sudo sh install-reading-progress-bridge.sh
```

安装器默认会自动找到 Talebook 容器和 `/data` 对应的数据目录，也可以直接指定：

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

安装脚本会把程序放到数据目录的 `.reading-progress-bridge/`，并在 Talebook 容器里注册为 supervisord 程序。默认每 5 分钟检查一次，容器重启后会跟着启动。

容器重建会删掉容器里的 supervisord 配置。重建后重新执行一次安装器即可：

```sh
sudo sh install-reading-progress-bridge.sh
```

也可以让宿主机每 5 分钟自动补一次：

```sh
sudo sh install-reading-progress-bridge.sh --install-cron
```

这个定时任务只负责确认桥还在运行，不会重复复制文件，也不会每次都扫描并写进度。

## 写入开关

配置文件在：

```text
<数据目录>/.reading-progress-bridge/config.json
```

关键选项：

```json
{
  "interval_seconds": 300,
  "threshold_chars": 200,
  "threshold_percent": 0.3,
  "apply": false
}
```

`apply` 为 `false` 时只计算，不修改任何进度文件；改成 `true` 才会写入。安装器的 `--apply` 就是做这件事。

配置改完后重启受管程序：

```sh
docker exec talebook supervisorctl restart progress-bridge
```

容器名不是 `talebook` 时换成实际名称。

完整配置项可以看 [config.example.json](config.example.json)。环境变量也能覆盖配置，例如 `RPB_INTERVAL_SECONDS=600`。

## 它怎么判断位置

书先按 Talebook 书库、Moeli 书籍副本和 legado 进度文件互相核对。只推领先的一边，差距小于“200 字或全书 0.3%（取较大值）”时不动。每次写入前都会把原文件备份到：

```text
reader/<用户号>/backup/bridge/
```

跨软件时才做坐标转换：epub 使用 CFI，txt 使用 Moeli 的字节偏移和 legado 的切章规则；安卓和安卓之间不换算坐标。

## 日志

默认日志在容器的 `/var/tmp/reading-progress-bridge/run.log`：

```sh
docker exec talebook tail -f /var/tmp/reading-progress-bridge/run.log
```

手动只检查一次，不启动循环：

```sh
docker exec talebook sh -c 'cd /data/.reading-progress-bridge && python3 bridge.py scan'
```

如果要手动执行一次同步：

```sh
docker exec talebook sh -c 'cd /data/.reading-progress-bridge && python3 bridge.py sync'
```

`sync` 默认仍是只算不写；确认无误后才加 `--apply`。

## 卸载

停掉桥，但保留程序目录、配置和备份：

```sh
sudo sh uninstall.sh talebook /srv/talebook/data
```

连程序目录和自动补齐任务一起删掉：

```sh
sudo sh uninstall.sh talebook /srv/talebook/data --purge
```

卸载不会删除书库、阅读进度或已经生成的备份。

## 当前边界

- 不会替手机点击确认框。
- 不会修改 epub、txt 或其它书库文件。
- 只处理已经在两边出现的书，不会凭空创建设备进度文件。
- txt 书第一次跨端使用时，先在 iOS 端打开并完成一次同步，再在安卓端打开。不要先让安卓建立进度后，再让 iOS 首次下载这本 txt。
- 两边已经都有进度后，桥才负责在两套坐标之间搬位置。
- 目前跨软件支持 epub 和 txt；pdf、mobi、azw3、cbz 暂不处理。
- 两边存在无法区分的同名书时会跳过，并在日志里说明。

## 从源码运行测试

```sh
python3 test/test_config.py
python3 test/test_cfi.py
python3 test/test_txt.py
python3 test/test_e2e_txt.py
```

端到端测试使用临时目录，不会改真实书库。

## 许可

MIT，见 [LICENSE](LICENSE)。
