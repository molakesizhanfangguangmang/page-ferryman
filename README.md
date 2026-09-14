# 阅读进度桥

在 Talebook 容器里跑的一个小脚本，把同一个人的安卓 legado 和 iOS Moeli 的阅读进度对齐。

三边各自记自己的位置：Talebook 书库（文件本身不认识进度）、安卓 legado（`reader/<用户号>/legado/bookProgress/*.json`）、
iOS Moeli（`reader/<用户号>/moeli_reader/book.db`）。这个脚本每轮把三边按书对上，找出谁更靠前，
把落后的那一侧改成领先的那一侧的位置，让下一次打开 App 时弹出「云端进度更靠前」的确认框。

## 它做什么，不做什么

做：

- 按书对齐两侧进度，只写落后的那一侧。
- 跨软件（一端是 Moeli）时做坐标换算：epub 用 `epubcfi`，txt 用 `txtloc`（字节偏移）。
- 写之前把原文件备份到 `reader/<用户号>/backup/bridge/`。
- 一轮一轮地跑，上一轮没跑完不重叠。

不做：

- 不替手机点确认框。写过去的文件要手机自己弹框确认才生效，脚本碰不到 App。
- 不改书库文件、不改 epub/txt 内容，只读。
- 不处理 pdf / mobi / azw3 / cbz（等有样本再说）。
- 不在云端创建新的进度文件；设备上没这本书就不动。

## 环境要求

- Talebook 一套，数据卷挂在容器的 `/data`，并且已经在用它自带的阅读进度目录
  （`<数据目录>/reader/<用户号>/legado` 与 `moeli_reader`，一般用过一次 App 就生成了）。
- 安卓侧：legado（阅读 3.0 以后），开了书签同步（`syncBookProgress`）。
- iOS 侧：Moeli Reader。
- 两边都指向同一个 Talebook。
- 容器里有 `python3`（Talebook 镜像自带）。

## 装

要能执行 `docker`，还要能写数据目录（不是 root 的话就 `sudo`）。

两条路，装出来的东西一样。

**从 release 下那个单文件安装器**：里面就是整包（base64），跑之前先按包里的
`SHA256SUMS` 自校验，不通过就停手。用法和 `install.sh` 完全一样，参数原样传下去。

```sh
curl -fsSLO https://github.com/molakesizhanfangguangmang/talebook-reading-progress-bridge/releases/latest/download/install-reading-progress-bridge.sh
sudo sh install-reading-progress-bridge.sh
```

想先看看里面是什么，不碰 docker：

```sh
sh install-reading-progress-bridge.sh --extract-only /tmp/rpb
```

**或者走仓库**：

```sh
git clone https://github.com/molakesizhanfangguangmang/talebook-reading-progress-bridge.git
cd talebook-reading-progress-bridge
sudo sh install.sh
```

两条路下面的步骤一样。
容器名与数据目录可以当参数传（`sudo sh install.sh talebook /srv/talebook/data`），
省略时自动找：容器名挑名字或镜像里带 `talebook` 的，数据目录从容器挂到 `/data` 的那个卷取。

脚本做四件事：

1. 把 `bridge.py`、`cfi.py`、`txt.py`、`run.sh`、`install.sh`、`uninstall.sh`、`README.md`、
   `LICENSE` 与一份默认 `config.json` 放进 `<数据目录>/.reading-progress-bridge/`（在数据卷上，
   容器重建不掉），属主改成进度文件那个 uid（从 `/data/reader` 下的属主读出来），
   免得它写不动自己的状态与切章规则副本。
2. 在容器里起循环。容器里有 `supervisord`（Talebook 官方镜像就有）时挂成受管程序
   `/etc/supervisor/conf.d/progress-bridge.conf`，跟容器一起起、崩了自己重启；没有就丢一个后台循环。
3. 干跑一遍，把这一轮的对齐结果打出来。
4. 带 `--install-cron` 时在宿主写 `/etc/cron.d/reading-progress-bridge`（见下面「自动起停」）。

**装完是干跑**：`config.json` 里 `apply` 是 `false`，只算不写。干跑结果看过没问题，改配置再重启循环：

```sh
sudo sed -i 's/"apply": *false/"apply": true/' <数据目录>/.reading-progress-bridge/config.json
docker exec <容器名> supervisorctl restart progress-bridge
```

改 `interval_seconds` 也要这样重启一次才生效，其它键下一轮就读到了。

`install.sh` 的选项：`--apply`（顺手把 `apply` 改成 `true`）、`--no-start`（只放文件不起循环）、
`--rearm`（只保证循环在跑，不复制、不扫描）、`--install-cron`、`--quiet`。

### 自动起停

- 跟容器一起起：受管程序自己做到（容器在跑它就活着），`docker restart` 也一样。
- 容器**重建**（换镜像、改 compose、手工删了重建）会带走容器里那份受管程序，循环跟着没。
  两种补法：重建完重跑一次 `install.sh`；或者装一次定时补齐，之后它自己回来：

  ```sh
  sudo sh install.sh --install-cron    # 写 /etc/cron.d/reading-progress-bridge，每 5 分钟一次
  sudo sh install.sh --rearm           # 手动补一次；幂等，在跑就什么都不做
  ```

  补齐只看循环在不在跑，不在跑才拉起来，不复制文件、不扫描。

容器里没有 `supervisord` 时，循环由 `docker exec -d` 起，`docker restart` 之后也会没，
同样靠重建后重跑 `install.sh` 或定时补齐。也可以把 compose 里那个服务的启动命令改成：

```yaml
command: sh -c "/data/.reading-progress-bridge/run.sh & exec /var/www/talebook/docker/start.sh"
```

### 卸载

```sh
sudo sh uninstall.sh [容器名] [数据目录]           # 停循环，删掉容器里那份受管程序
sudo sh uninstall.sh [容器名] [数据目录] --purge   # 再删掉 <数据目录>/.reading-progress-bridge 与定时补齐记录
```

卸载不动书库、不动已经写进去的进度、不动备份。要还原进度，把
`reader/<用户号>/backup/bridge/` 下的备份拷回去。

## 怎么判断推哪边

认书：

- 书库目录名末尾的 `(N)` 是编号，例如 `某本书 (23)`。
- Moeli 在 `reader/<用户号>/moeli_reader/book/` 下留一份副本，用**副本内容**的 md5 对上书库文件。
  `Books.md5` 字段本身是那份副本的文件名（内容 md5 + 时间戳），不是内容哈希。
- 安卓的 `originName` 前缀就是编号（`23.某本书.epub`）；云端进度文件名是 `${name}_${author}.json`。
- 位置取云端进度文件与备份 zip 里书架快照中 `durChapterTime` 较新的那个。

比位置：先比章号，再比章内偏移，不看时间 —— 跟 legado 自己的判断口径一致。

推的条件：落后超过阈值才推。阈值是「200 字」和「全书 0.3%」里大的那个，
避免把刚读完的位置往回拉。只推领先的那一侧。

跨软件才换算：一端是 Moeli 时，epub 走 `epubcfi`，txt 走 `txtloc`；
安卓↔安卓同软件时两边坐标本来就是一套，原样搬章号和章内偏移。

## txt 的坐标

- Moeli 的 `txtloc(章:字节:标志)` 里第二个字段是 **utf-8 字节偏移**，不是字符数。
  `txt.py` 建字节↔字符的累积表，用折半查找换算。
- 切章用使用者自己那份 `txtTocRule.json`：优先用
  `<数据目录>/.reading-progress-bridge/txt-toc-rule.json`，没有就从 legado 最新一份
  `backup*.zip` 里抽，抽到会存一份。脚本不随包带任何切章规则。
- 准绳是设备快照里报过的总章数（`totalChapterNum`）；没有准绳时按规则顺序取第一条能切出多章的。
  准绳对不上会写进日志。
- 手机（legado）看到的章号比规则切出来的章号大 1：开头那段正文被它当成第 0 章「前言」。

## 配置

同目录的 `config.json`，也可以全部用环境变量（`RPB_<键名大写>`），环境变量优先。

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `data` | `/data` | 数据目录（容器里看到的路径） |
| `reader_user` | 空 | `reader/<用户号>` 里的用户号；空着就自动挑带 `moeli_reader` 的那个 |
| `interval_seconds` | `300` | 每轮间隔 |
| `threshold_chars` | `200` | 阈值下限（字） |
| `threshold_percent` | `0.3` | 阈值（全书百分比），与 `threshold_chars` 取大的 |
| `apply` | `false` | `true` 才真写；`false` 只算不写 |
| `state_dir` | `/var/tmp/reading-progress-bridge` | 缓存、状态、锁、日志放这里 |
| `rules_file` | 脚本目录下 `txt-toc-rule.json` | 切章规则；没有就从备份抽并写到这里 |
| `skip_books` | `[]` | 要跳过的书库编号 |

命令行 `python3 bridge.py scan`（只读看对齐）与 `python3 bridge.py sync [--apply]` 也可以直接用，
`--apply` 等价于 `apply: true`。

## 日志与排错

日志在容器里 `state_dir/run.log`：

```sh
docker exec <容器名> tail -f /var/tmp/reading-progress-bridge/run.log
```

一轮的输出里，「不动」的每一条都写了原因：落后多少字、同软件没解析正文、
没有键文件不新造、认不出的坐标等。「对不准」列表是两种情形：书库里没有这本，
或者书名互相套得住分不清 —— 后者用 `skip_books` 跳过，或者把书名改得能区分。

写入前每个文件都会备份到 `reader/<用户号>/backup/bridge/`，文件名带原文件名字与时间戳；
要还原就把备份拷回去。

## 自测

不需要真实数据也跑得起来（`RPB_DATA` 指到数据目录，默认 `/data`）：

```sh
python3 test/test_config.py       # 配置与目录发现（临时目录，假数据）
python3 test/test_cfi.py          # epub 的 CFI 往返（只读书库）
python3 test/test_txt.py          # txt 换算与切章规则抽取（只读）
python3 test/test_e2e_txt.py      # 端到端：临时目录里造数据，真跑一遍写入路径
```

`test_e2e_txt.py` 的书库、`book.db`、进度文件全是临时目录里的副本，不碰真实数据。

## 已知边界

- 不能替手机点确认框；写过去之后要自己点一下。
- 两本同名的书分不清，会跳过。
- 手机没导入、或从没打开过的书没有进度文件，脚本不新造。
- 手机侧的备份 zip 是设备列表的来源；某台设备从没做过备份，就看不到它。
- 只在 Talebook 这套目录结构上验证过，其它阅读服务不适用。

## 变更

- **v1.0.2**：release 里多一个单文件安装器（内嵌整包，自校验后转交 `install.sh`）；
  打包走 `.github/workflows/release.yml`，打 tag 自动出包。
- **v1.0.1**：安装脚本用容器里的 `supervisord` 起循环（跟容器同起、崩了自动重启），
  加 `--rearm` 与 `--install-cron` 两条补齐路径；卸载会一起清掉受管程序；包里不再带运行残留。
- **v1.0.0**：首版。配置化、自动发现容器与数据目录、切章规则从使用者自己的备份里抽。

## 许可

MIT，见 `LICENSE`。
