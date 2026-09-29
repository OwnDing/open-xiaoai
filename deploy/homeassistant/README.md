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

在 HA 里新增、改名或调整房间后，重新生成设备表：

```powershell
cd ..\hermes
docker run --rm --network xiaozhi-server_default --env-file .env -v ${PWD}:/hermes `
  --entrypoint /app/.venv/bin/python local/open-xiaoai-xiaozhi:smooth-audio /hermes/ha_device_table.py
docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
```

`ha_device_table.py` 的规则：

- 只列出能控制的设备（灯、开关、空调、风扇、窗帘、加湿器、扫地机、热水器、音箱、门锁、场景），以及温湿度、PM2.5、门窗、人体、水浸等传感器；
- 按房间分组；
- 跳过配置类和诊断类实体；
- 设备已有主实体时（比如灯本身、风扇本身、音箱本身），跳过它附带的功能开关，比如助眠模式、童锁、提示音、麦克风静音。其中麦克风静音一旦被误关，音箱就听不到小七了。

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
