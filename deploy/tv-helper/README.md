# 小七电视助手（客厅 TCL 电视）

让小七控制客厅的 TCL 雷鸟电视：开关机、打开应用、在奇异果里搜片播放和选集、暂停继续、切集、快进快退、
音量，以及读屏幕上的文字、按文字点击、按遥控键，用来完成其他任意操作。

```text
小七 → xiaozhi（hermes.py 电视规则）→ Hermes → MCP tv_control
                                                 ├→ 电视上的小七电视助手（HTTP :8765，shell 身份运行）
                                                 │     读屏 / 点击 / 输入 / 按键 / 媒体会话 / 打开应用 / 音量
                                                 ├→ HA 红外按钮（小爱音箱）→ 开机
                                                 └→ HA Android TV 集成（ADB）→ 电视重启后把助手拉起来
```

本文后半部分记录了 2026-10-22～23 调查出来的 TCL 系统行为、试过但没采用的方案，后续改动前先看一遍。

## 电视

| 项目 | 值 |
|---|---|
| 型号 | TCL `tcl_mt5879_cn`（MT5879，32 位 ARM，2.8 GB 内存，空闲内存常只有一两百 MB） |
| 系统 | Android 11（SDK 30），TCL 定制，桌面 `com.tcl.cyberui`，输入法搜狗 TV |
| 地址 | `192.168.5.9`，WiFi（MAC `bc:09:b9:b8:3d:fc`） |
| ADB | 网络 ADB 常开：`persist.adb.tcp.port=5555`，重启后仍在；每台新电脑第一次连接要在电视上点“允许” |
| 主要应用 | 银河奇异果 `com.tcl.qiyiguo`（TCL 版爱奇艺，v16）、网易云音乐 TV、Apple Music、YT TV、酷控、有线频道 |
| 待机 | 挂起到内存（STR），WiFi 断电；开机后约 2 秒恢复，不重启 |

## 组成

| 部分 | 位置 | 作用 |
|---|---|---|
| 小七电视助手 | `deploy/tv-helper/`（本目录） | 电视上的 HTTP 服务，shell 身份运行 |
| MCP `tv_control` | `deploy/hermes/profile/mcp/tv_control/` | 小七的电视工具：`tv_status` `tv_power` `tv_open_app` `tv_play` `tv_playback` `tv_volume` `tv_screen` `tv_click` `tv_keys` |
| SOUL 规则 | `deploy/hermes/profile/SOUL.md` | 电视只用 `mcp__tv_control__` 工具，不用 HA 媒体播放器或红外按钮 |
| xiaozhi 规则 | `deploy/hermes/xiaozhi-provider/hermes.py` | 电视工具算“做了”的依据（`ACT_TOOLS`）；提到电视的控制或状态请求必须调用电视工具（`TV_WORDS`） |
| 音乐分流 | `examples/xiaozhi/xiaozhi/services/music/intent.py` | 只说“播放某某”、曲库里没有时交给小七（多半是要在电视上看），不再回答“曲库里没找到” |
| HA 集成 | Android TV（ADB），条目 `01M5K0REMM7NJRG6J61SA4WNHB` | `media_player.living_room_tv`、`remote.living_room_tv`（客厅电视）；tv_control 用 `androidtv.adb_command` 拉起助手 |

Hermes 的 `.env` 要有 `TV_HELPER_URL=http://192.168.5.9:8765` 和 `TV_HELPER_TOKEN=<令牌>`（改完要 `docker compose up -d` 重建容器）。

## 安装和更新

需要 Android SDK（`adb`）和 JDK 17，电视开着：

```bash
cd deploy/tv-helper
./install.sh                    # 默认电视 192.168.5.9:5555；令牌取 $TV_HELPER_TOKEN，没有就新生成
```

脚本编译 APK，把它、`tv-helper.sh` 和令牌文件推到电视的 `/data/local/tmp/xiaoqi-tv-helper.*`，重启助手，
最后打印 `TV_HELPER_URL` 和 `TV_HELPER_TOKEN`。更新时带上原来的令牌，Hermes 不用改。在电视上：

```sh
sh /data/local/tmp/xiaoqi-tv-helper.sh [start|stop|restart|status]
cat /data/local/tmp/xiaoqi-tv-helper.log
```

`start` 已在运行时什么都不做，所以可以随时调用。启动约 1 秒。`setsid` 会再 fork 一次，进程名要等虚拟机起来后才变成
`xiaoqi-tv-helper`，所以脚本看日志里的 “listening on” 判断是否启动成功，不看 `$!` 或 `pidof`。

电视真正重启（断电、系统升级）后助手不在了，tv_control 下次发现“电视在网络上、助手不响应”时，会通过 HA 执行
`sh /data/local/tmp/xiaoqi-tv-helper.sh start`，约 4 秒后可用。待机开关机不影响助手。

## 助手怎么工作

和 scrcpy 一样：APK 只是代码的容器，不安装，用 `app_process` 以 adb shell 用户运行
（`CLASSPATH=xiaoqi-tv-helper.apk app_process /system/bin --nice-name=xiaoqi-tv-helper com.openxiaoai.tvhelper.Main <令牌文件>`）。

- **系统 Context**：反射 `ActivityThread` 构造一个实例，设为 `sCurrentActivityThread`，取 `getSystemContext()`（`Device.java`）。
- **读屏和点击**：反射 `UiAutomationConnection` 建一个 `UiAutomation`（同 `uiautomator` 命令），连接时用
  `FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES`，否则会把 TCL 自己的辅助功能服务（小T助手）挤掉。读一次屏 40～200 毫秒，
  `uiautomator dump` 要约 4 秒。同一时间只能有一个 UiAutomation，助手运行时不要再用 `uiautomator dump`。
- **点击**：可点击的节点（或祖先）发 `ACTION_CLICK`；只能获得焦点的先 `ACTION_FOCUS` 再按 OK（电视应用大多靠焦点加确认键）；
  都不行就注入一次触摸。焦点容器自己没有文字时，取它第一个有文字的子节点当名字（奇异果的卡片就是这样）。
- **按键**：`UiAutomation.injectInputEvent` 注入 KeyEvent，和遥控器一样，一次约 70 毫秒（`input keyevent` 要半秒以上）。
- **打开应用、启动 Activity**：执行 `am start`（参数数组，不经过 shell 引号）。系统 Context 的包名是 `android`，和 shell 的 uid
  对不上，直接 `startActivity` 会被拒，`am` 命令知道怎么以 shell 身份启动。
- **媒体会话**：shell 有 `MEDIA_CONTENT_CONTROL` 权限，`getActiveSessions(null)` 能拿到所有应用的会话并发送控制和自定义动作。
- **音量**：读 `AudioManager`（TCL 是 0–100）；设音量用 `cmd media_session volume --stream 3 --set N`，静音用静音键。
- **HTTP**：自己写的极简 HTTP/1.1（`Http.java`），每个连接一个 JSON 请求，3 个工作线程，令牌用 `MessageDigest.isEqual` 比较。

### 接口

所有请求带 `Authorization: Bearer <令牌>`：

| 接口 | 作用 |
|---|---|
| `GET /status` | 前台应用、最近的 Activity、屏幕是否亮着、版本 |
| `GET /screen?limit=150` | 屏幕上的文字（阅读顺序，带坐标），焦点项 |
| `POST /click {text, index}` | 点击带这段文字的项（先完全匹配，再前缀，再包含；`index` 选第几个） |
| `POST /type {text}` | 往焦点输入框（没有就第一个输入框）填文字，支持中文 |
| `POST /key {keys}` 或 `{key, repeat, interval_ms}` | 按键：UP DOWN LEFT RIGHT OK BACK HOME MENU SLEEP WAKEUP VOLUME_UP VOLUME_MUTE 数字…（KeyEvent 名去掉 `KEYCODE_`） |
| `POST /global {action}` | back、home、recents、notifications |
| `GET /apps`、`POST /launch {package}` | 桌面上的应用（名称、包名）、打开应用 |
| `POST /intent {action, package, component, data, type, extras}` | `am start`；extras 里整数用 `--ei`，`{"long": n}` 用 `--el` |
| `GET /media`、`POST /media {action, package, value, name, extras}` | 媒体会话；action 为 play pause toggle stop next previous seek_to forward rewind custom |
| `GET /volume`、`POST /volume {level, delta, mute}` | 音量 |

## 开关机

- 电视待机后 WiFi 断电，**ADB 和网络唤醒（WoL，试过子网广播和直发）都叫不醒**，只能用小爱音箱的红外开机：
  `button.miir_cn_ir_2102915700556705793_ir01_turn_on_a_2_5`（红外电视控制·开机），从按下到能 ping 通约 4 秒，ADB 约 10 秒。
- 这个红外码是**电源切换**：电视开着时按“开机”会把它关掉（实测）。所以 tv_control 只在电视的 5555 端口连续 3 次都连不上时
  才发红外，一次丢包不会把开着的电视关掉。
- 关机用助手按 `SLEEP`（助手不响应但电视在线时，经 HA 的 `adb_command` 发 `input keyevent SLEEP`）。
- 唤醒原因可在 logcat 的 `MI_PM_GetWakeUpSource ... wakeup_src=1` 看到（1 一般是红外）。
- 在这之前小七不管电视，开关电视靠的是小爱同学自带的红外功能。

## 奇异果（`com.tcl.qiyiguo`）

- **搜片**：`am start -a com.gitvdemo.video.action.ACTION_SEARCHRESULT -p com.tcl.qiyiguo --es playInfo '{"version":"1.0","keyword":"狂飙"}'`
  （只校验 `keyword`）。有精确匹配时结果页顶部是这部剧的卡片，焦点在“播放”上；没有时（如《繁花》，腾讯独播）只有分类标签和相关片名。
  其他跳转动作：`ACTION_SEARCH`、`ACTION_DETAIL`、`ACTION_PLAYVIDEO`（`playInfo` 或 `cmdInfo`）、`ACTION_HOME_TAB` 等，见
  `com.gala.video.app.home.mode.proxy.loading.OutsideActionProxy`。
- **媒体会话**（会话 extras 里有 `screen_mode`，元数据有片名、主演、时长）。自定义动作前缀 `com.gala.video.mediasession.custom.action.`：

  | 动作 | 参数 | 实测 |
  |---|---|---|
  | `SELECT_EPISODE` | `index`（int，**从 1 开始**）或 `action` next/prev/last | 可用；播放器刚起来那一两秒会忽略 |
  | `PLAY_OR_PAUSE` | `action` play/pause | 可用（标准 play/pause 也行） |
  | `SEEK` | `position`（long 毫秒），或 `direction`（int 0 前 1 后）+ `offset`（long 毫秒） | **不生效**，标准 `seekTo` 也不生效 |
  | `SWITCH_BITSTREAM` | `bitstream`（字符串） | 未测 |
  | `SKIP_TAIL` | `isOpen`（boolean） | 未测 |
  | `SCREEN_MODE` | `mode` FULLSCREEN/WINDOWED | 未测 |
  | `FAVORITE` | `isFavorited`（boolean） | 未测 |

  参数格式来自 TCL 小T助手的 `QiYiGuoMediaSessionContext` 和奇异果的 `com.gala.video.app.tob.voice.b.a.a`。
- **快进快退**用左右键：每按一下约 6～9 秒，连按会加速（按 10 下约 90 秒）。按完控制栏会显示，从屏幕上读 `00:03:05` 这样的时间报给用户。
- 奇异果会续播上次看的那一集，所以 `tv_play` 选集后会读控制栏上的“第 N 集”核对，没切过去就再发一次。
- 播放画面受 DRM 保护，截屏是黑的；控制栏、弹幕、标题读屏能读到。

## 调查过、没有采用的方案

### 只用 HA 的 Android TV（ADB）集成

能按键、打开应用、查当前应用和音量，但读屏只能用 `uiautomator dump`（约 4 秒）、不能输入中文（`input text` 不支持）、
不能控制媒体会话（选集）。它也开不了机（待机时 ADB 不在线）。现在保留它做两件事：电视重启后拉起助手，以及 HA 里的电视实体。

### TCL 小T语音助手代劳（文字指令）

小T助手（`com.tcl.walleve`，讯飞内核）的 `SpeechService` 对外开放，不需要权限：

```sh
am start-foreground-service -n com.tcl.walleve/.SpeechService -a com.tcl.walleve.pitch --es text "打开银河奇异果"
```

它会把文字当成用户说的话处理（`startSession(...).dispatchUserText(text, true)`），TCL 的语义理解能直接操控奇异果（播放某剧
第几集、快进等）。但这台电视的小T从没启用过，第一次调用就弹出“欢迎使用小T语音助手”，要同意《TCL小T助手隐私协议》
和用户体验改进计划，数据会上传 TCL 和讯飞的云端，而且执行时电视上会弹出小T的界面。**用户决定不启用**，也没有替用户同意协议。
其他入口：`com.tcl.ai.soundbox.command`（`SoundBoxCommandService`）只能开关背光；`com.tcl.walleve.tts` 让电视念一段文字；
`com.tcl.walleve.command` 带 `config=homepage:N` 打开小T主页。

### 在电视上安装 App（辅助功能服务 + 通知监听 + HTTP）

最初的方案：App 用辅助功能服务读屏点击，用通知使用权控制媒体会话，后台开 HTTP 服务。装上并跑通过一次，但 TCL 有三道限制：

1. **不能用 adb 安装**：`INSTALL_FAILED_VERIFICATION_FAILURE`，见下文“安装校验”。只能用 APKMirror Installer 打开 `content://` 地址，
   再在电视上点“安装”。
2. **服务不让启动**：辅助功能和通知监听都被拦（`forbid bind service`）。把 App 的 TCL 自启动权限打开
   （`appops set <包名> APP_AUTO_START allow`，以及 `APP_ASSOC_START`）后能绑定。
3. **进程被冻结**：进入后台约 5 秒，FreezeManager 冻结进程，HTTP 不再响应。常规豁免是前台服务的常驻通知，但 TCL 不让第三方 App
   开前台服务（`block startForeground`）。剩下的办法是把包名加进 TCL 配置库里的冻结白名单。这要改 TCL 的系统配置，
   而 TCL 云端下发配置时可能覆盖，助手会悄悄失效，所以**没有采用**，改成现在的 shell 方式。那个 App 已经卸载，相关设置都已恢复。

### 其他

- **网络唤醒、ADB 唤醒**：待机时 WiFi 断电，都不行。
- **包名带 “cts”**：TCL 的启动管控对包名含 `cts` 的应用一律放行（给兼容性测试留的口子），能绕过绑定和前台服务限制，但不管冻结，
  而且是钻空子，没有用。
- **全局关掉冻结**：FreezeManager 的 dumpsys 命令有 `freezer switch on/off`，只在内存里生效，重启恢复，而且影响全机，没有用。

## TCL 系统的限制（调查记录）

TCL 的定制代码在 `/apex/com.tcl.tcore/javalib/tcl-service.jar`（`SYSTEMSERVERCLASSPATH` 里，`services.jar` 通过
`tcl.com.android.server.common.TclServiceFactoryImpl` 反射加载）和系统应用里。用 jadx 反编译即可看。
`adb pull /vendor/...` 会因为 stat 权限失败，但 `adb exec-out cat <路径> > 文件` 能读出来。

### 安装校验

- 系统安装器 `com.android.packageinstaller`（TCL 改过）的校验策略链，配置在 `content://com.tcl.providers.config/InstallConfig`：
  safeStrategy（直接通过）、blackListStrategy、thridStrategy（第三方应用市场来源，已关闭）、launcherStrategy（第三方桌面）、
  overDueStrategy、pmStrategy。
- **pmStrategy 拒绝带 `INSTALL_FROM_ADB`（0x20）标志的安装**。shell 或 root 创建的安装会话一律带这个标志，所以
  `adb install`、`pm install`、`cmd package install` 都会失败。
- 系统安装器不接受 `file://`；从 shell 用 `content://` 打开它，会一闪就关。能用的路子是 APKMirror Installer：先把 APK 推到
  `/sdcard/Download`，用媒体扫描拿到 `content://media/external/file/<id>`，再用
  `am start -n com.apkmirror.helper.prod/com.apkmirror.presentation.installer.InstallerActivity -a android.intent.action.VIEW -d <uri> -t application/vnd.android.package-archive --grant-read-uri-permission`
  打开，点 “Install app”，再在系统弹窗里点“安装”。

### 启动管控（`com.android.server.am.TclAppBootManagerImpl`）

- `canBindServiceGo`（绑定服务，包括系统绑定辅助功能、通知监听）放行条件：目标进程已在运行、调用方是 root/shell、
  CTS 包（包名含 `cts`）、TCL 或系统应用、配置白名单，或 AppOps 允许。被拦时 logcat 有 `forbid bind service`。
- TCL 自定义的 AppOps：100 = `APP_AUTO_START`（自启动），101 = `APP_ASSOC_START`（关联启动），第三方应用默认 `ignore`。
  `appops set <包名> APP_AUTO_START allow` 后系统能绑定它的服务。
- `canStartForegroundGo`（前台服务）只放行：应用正在前台、CTS 包、TCL 或系统应用、`inServiceStartForegroundWhiteList`。
  被拦时有 `block startForeground`。

### 冻结（`com.android.server.am.appfreeze.FreezeManager`）

- 后台应用进程很快被冻结（日志 `doFreeze <pid> pkg <包名> ... freeze : true`；配置里 `tcl_fastHibernateTimeout` 是 1500 毫秒，
  实测启动后约 5 秒）。冻结后进程收不到任何东西，socket 也不响应。
- 配置在 `content://com.tcl.providers.config/freeze`（`enable`、`tcl_fastHibernate`、`freezeProcessList` 白名单 67 项、
  `fastFreezeProcessList`），由 `ConfigObserver` 监听，改了实时生效，TCL 云端也会下发。
- 不冻结的情况：在 `freezeProcessList` 里、输入法、应用带某些状态标志。亮屏时的标志包括 FrontApp（前台）、HASNOCLEAR
  （有不可清除的通知，即前台服务通知，由 NotificationManagerService 报告）、FloatWin（悬浮窗）、Audio、Video、Camera 等。
- shell 进程不是应用，不归 FreezeManager 和启动管控管，这就是助手用 shell 身份运行的原因。

## 小七这边的规则

- 提到“电视、奇异果、爱奇艺”的控制或状态请求，xiaozhi 要求调用 `mcp__tv_control__` 工具，否则带提示重试一次。
- 音乐桥接先听：“暂停”只在音乐正在播时被它接走，“继续播放”在有停着的音乐时会被它接走去续播音乐。
  桥接不接的交给小七，SOUL 让它先用 `tv_status` 看电视在不在播。
- “播放某某”：说了歌、曲、音乐、专辑、歌手（“某某的某某”）、“一首”，或者用“听”，按音乐处理；否则曲库里没有就交给小七，
  小七会用 `tv_play` 在电视上找。
- 定时开关电视用 `cronjob_manage`，prompt 写“调用 mcp__tv_control__tv_power，on 为 false”。

## 已知限制和后续

- 奇异果不接受外部跳转进度，“跳到第 20 分钟”做不了。
- 选集、快进依赖奇异果的界面和会话；其他视频应用只支持标准的播放、暂停、上下一个。
- 声纹权限（`feat/voiceprint` 的 `permissions.yaml`）现在只管 `ha_call_service`，要限制孩子用电视，得把 `mcp__tv_control__` 工具加进规则。
- HA 的 `media_player.living_room_tv` 开机命令走 ADB，待机时无效；场景和联动要开电视，以后可以加一个先判断状态再发红外的 HA 脚本。
