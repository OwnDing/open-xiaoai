---
name: sleep-mode
description: 用户说“我睡觉了”“我要睡了”“晚安”时执行的睡觉模式：关灯、按记忆里的偏好设置卧室空调，并简短道晚安。
version: 1.0.0
author: xiaoqi-home
metadata:
  hermes:
    tags: [Home, HomeAssistant, Routine]
---

# 睡觉模式

用户表示要睡觉时，按下面顺序执行，不要逐步汇报：

1. 用 `ha_list_entities` 找到客厅、书房的灯（domain 为 light），用 `ha_call_service` 调用 `light.turn_off` 关闭。
2. 查看记忆里用户的睡眠空调温度偏好；没有记录时使用二十六度。
3. 找到卧室空调（domain 为 climate），调用 `climate.set_temperature` 设置该温度。
4. 如果有门窗传感器（binary_sensor，device_class 为 door 或 window），检查是否有开着的，有则提醒一句。
5. 最后只说一句简短的话，例如“灯关好了，空调调到二十五度，晚安”。

某个设备不存在或调用失败时跳过它，并在最后那句话里如实带一句。
