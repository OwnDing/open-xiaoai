# Home Assistant + 米家（Xiaomi Home）

让小七（Hermes）通过 Home Assistant 控制米家设备：

```text
小七 → Hermes (homeassistant 工具) → http://homeassistant:8123 → Xiaomi Home 集成 → 米家云 → 设备
```

- 容器名：`homeassistant`
- 浏览器访问：`http://<mini PC IP>:8123`
- Docker 内部网络：`xiaozhi-server_default`，Hermes 使用 `http://homeassistant:8123` 访问
- 配置和数据：命名卷 `homeassistant-config`。HA 的 SQLite 数据库放在 Windows 挂载目录上不稳定，所以不用绑定目录。
- 米家集成：小米官方 [XiaoMi/ha_xiaomi_home](https://github.com/XiaoMi/ha_xiaomi_home)，走米家云控制

## 部署

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\homeassistant
docker compose up -d
```

## 安装 Xiaomi Home 集成

```powershell
docker exec homeassistant python3 /opt/xiaoqi-scripts/install_xiaomi_home.py
docker restart homeassistant
```

在 mini PC 上从 GitHub 下载 release 文件经常超时。这时先在别的电脑下载 `xiaomi_home.zip`，再拷进容器安装：

```powershell
docker cp xiaomi_home.zip homeassistant:/tmp/xiaomi_home.zip
docker exec homeassistant python3 /opt/xiaoqi-scripts/install_xiaomi_home.py /tmp/xiaomi_home.zip
docker restart homeassistant
```

升级集成时也用同样的命令。集成需要的依赖（construct、paho-mqtt、numpy、cryptography、psutil）HA 镜像里已经自带。

每次安装或升级集成后，都要再打一次本地补丁：

```powershell
docker exec homeassistant python3 /opt/xiaoqi-scripts/patch_xiaomi_home.py
docker restart homeassistant
```

这个补丁修复的是 v0.5.0 在 Python 3.14 下的问题：米家云报告设备离线时，集成会抛出 `TypeError: a coroutine was expected, got None`，HA 返回 500，而不是正常的“设备离线”错误。

## 安装 HACS（接入海尔等第三方集成）

HACS 的 release 包（约 19 MB）同样从 GitHub 下载，所以先在别的电脑下载
[hacs.zip](https://github.com/hacs/integration/releases/latest)，再拷进容器安装：

```powershell
docker cp hacs.zip homeassistant:/tmp/hacs.zip
docker exec homeassistant python3 /opt/xiaoqi-scripts/install_custom_component.py hacs /tmp/hacs.zip
docker restart homeassistant
```

`install_custom_component.py` 也能安装 GitHub 源码包里的 `custom_components/<domain>`，
HACS 自己下载失败时可以用它手动安装其他集成。

HA 重启后，在浏览器里：

1. 设置 → 设备与服务 → 添加集成 → **HACS**，勾选全部说明，提交；
2. 按提示打开 `https://github.com/login/device`，用 GitHub 账号登录并输入页面上的验证码，完成授权；
3. [banto6/haier](https://github.com/banto6/haier) 不在 HACS 默认列表里（能搜到的 **Haier hOn** 是海外版 hOn App 用的，
   国内海尔智家账号登录不了）：HACS 右上角 ⋮ → 自定义存储库 → 填 `https://github.com/banto6/haier`，类型选“集成”，
   添加后搜索 **Haier** → 下载 → 重启 HA；
4. 设置 → 设备与服务 → 添加集成 → **Haier** → “使用账号密码自动获取 Token 登录”，
   填海尔智家 App 的手机号和密码（密码只用于这次登录，HA 只保存 Token）。

HA 容器访问 GitHub API 和海尔云都正常，HACS 浏览、下载集成不需要额外代理。
海尔设备加入 HA 后，按下文“让小七认识设备”重新生成设备表，小七就能控制它们。

## 排查“说了没反应”

书房灯、主卧灯、次卧灯这类设备，是由音箱（`parent` 为音箱的 did）作为网关转发命令的，流程如下：

1. 米家云收到命令，返回 `code: 1`，意思只是“已受理”；
2. 灯真正执行后，会推送 `properties_changed`；
3. 如果音箱没有把命令转发到灯，HA 仍然会显示新状态，但灯实际上没有变化。

排查方法：

1. 打开 Xiaomi Home 的调试日志：`logger.set_level` → `custom_components.xiaomi_home: debug`。HA 重启后需要重新设置。
2. 复现问题。
3. 核对每条命令有没有收到设备的确认：

   ```powershell
   docker logs --tail 2000 homeassistant > ha.log 2>&1
   python ..\hermes\bench\ha_confirmations.py ha.log 21:30
   ```

   输出里的 `NO CONFIRM` 就是命令发出了、但设备没有确认执行的那一次。

## 登录米家

小米登录完成后，固定跳转回 `http://homeassistant.local:8123`，浏览器必须能把这个名字解析到 HA。mini PC 的 hosts 文件里已经加了：

```text
127.0.0.1 homeassistant.local
```

所以请在 **mini PC 本机的浏览器**（可以通过 RDP）里操作：

1. 打开 `http://homeassistant.local:8123`，按向导创建 HA 账号。
2. 设置 → 设备与服务 → 添加集成 → **Xiaomi Home**：
   - 服务器区域选 **中国大陆**，用小米账号登录；
   - 勾选要导入的家庭和设备；
   - 房间同步选按米家房间，这样 HA 的区域就是米家的房间。
3. 用户头像 → 安全 → 长期访问令牌 → 创建一个令牌，填到 `deploy/hermes/.env` 的 `HASS_TOKEN`。

## 让小七认识设备

米家的实体 ID 很长，比如 `light.<厂商>_cn_<设备ID>_<型号>_s_2_light`。可以把设备表写进小七的人设 `SOUL.md`，这样每条控制命令少一轮“先列出设备”的推理，约快 0.6 秒。

米家里新增了设备，HA 不会自动导入。先拉取新设备（等同于界面上 Xiaomi Home → 配置 → 更新设备；`--check` 只看会增减几台，不保存；会移除设备时默认放弃）：

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\homeassistant
docker exec --env-file ..\hermes\.env homeassistant python3 /opt/xiaoqi-scripts/xiaomi_update_devices.py --check
docker exec --env-file ..\hermes\.env homeassistant python3 /opt/xiaoqi-scripts/xiaomi_update_devices.py
```

在 HA 里新增、改名或调整房间后，重新生成设备表：

```powershell
cd ..\hermes
docker run --rm --network xiaozhi-server_default --env-file .env -v ${PWD}:/hermes `
  --entrypoint /app/.venv/bin/python local/open-xiaoai-xiaozhi:smooth-audio /hermes/ha_device_table.py
docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
```

`ha_device_table.py` 的规则：

- 小米集成里名字带 `*` 的非标准实体（插座的指示灯勿扰、充电保护、倒计时等）不列入；配置类实体（如插座指示灯）不影响“这个设备本身就是开关”的判断；

- 以 HA 的 **设置 → 语音助手 → 公开** 为准：公开的实体列入设备表，取消公开的不列；
- HA 还没决定是否公开的实体，按默认规则：只列出能控制的设备（灯、开关、空调、风扇、窗帘、加湿器、扫地机、热水器、音箱、门锁、场景），以及温湿度、PM2.5、门窗、人体、水浸等传感器；
- 状态类传感器、`select`、`number`（比如冰箱的冷藏温度设定、洗衣机的剩余时间）只有手动公开后才列入；
- 按房间分组；
- 跳过配置类和诊断类实体；
- 设备已有主实体时（比如灯本身、风扇本身、音箱本身），跳过它附带的功能开关，比如助眠模式、童锁、提示音、麦克风静音。其中麦克风静音一旦被误关，音箱就听不到小七了。

海尔这类家电一台就有几十个实体，HA 默认会把它们的功能开关全部公开。接入后先到“公开”页面整理：
取消公开不需要语音控制的开关（尤其是“RO复位”“初滤复位”这类会清零滤芯寿命的），
再公开常用的状态和设定（运行状态、剩余时间、冷藏/冷冻温度、滤芯剩余等），然后重新生成设备表。
注意：“公开”只决定设备表里列出哪些实体，小七仍然可以用 `ha_list_entities` 查到其他实体。
HA 默认不公开水浸传感器，需要在“公开”页面手动打开，否则它会从设备表里消失。

## 历史记录保留 30 天

小七回答“鱼缸灯今天亮了多久”“这个月平均每天开多久”这类问题，查的是 HA 的历史记录
（Hermes 的 `home_history`，见 [`../hermes`](../hermes/README.md#device-history-home_history)）。
HA 默认只保留 10 天，这里在 `configuration.yaml`（在 `homeassistant-config` 卷里，不在仓库中）
末尾加了：

```yaml
recorder:
  purge_keep_days: 30
```

改完先检查配置再重启：

```powershell
docker exec homeassistant python -m homeassistant --script check_config -c /config
docker restart homeassistant
```

350 个实体、10 天时数据库约 15 MB，30 天大约 45 MB。

## 实测（2026-09-29）

| 命令 | 灯状态变化 | 小七回复第一句 |
|---|---|---|
| 把书房灯打开（Hermes API，热启动） | 1.06 s | 1.61 s |
| 把书房灯关掉（Hermes 刚重启，冷启动） | 3.39 s | 3.92 s |

用户说完话到灯亮，还要再加上 VAD 约 0.5 秒和语音识别约 0.7~1.1 秒。

## 测试

`deploy/hermes/bench/real_ha_test.py` 通过 Hermes 切换一个真实设备并计时，测试结束后恢复原状态：

```powershell
docker run --rm --network xiaozhi-server_default --env-file ..\hermes\.env `
  -v ${PWD}\..\hermes\bench:/bench -w /bench --entrypoint /app/.venv/bin/python `
  local/open-xiaoai-xiaozhi:smooth-audio real_ha_test.py light.<实体> 把书房灯打开 把书房灯关掉
```
