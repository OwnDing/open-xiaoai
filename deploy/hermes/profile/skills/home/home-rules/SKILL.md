---
name: home-rules
description: 用户要教你新场景（“以后我说……就……”）或新联动（“当……的时候……”“……了就提醒我”“双击开关就……”），或者要查看、修改、删除、试运行已经教过的场景和联动时使用。
version: 1.0.0
author: xiaoqi-home
metadata:
  hermes:
    tags: [Home, HomeAssistant, Automation]
---

# 教场景和联动

家里没有预置任何场景或联动，全部按用户说的来建。有两种：

- 场景：用户说一句口令就执行的一组动作，例如“以后我说‘我回来了’，就开客厅灯，空调调到二十六度”。
  kind 为 scene，没有触发条件。
- 联动：家里发生某件事时由 Home Assistant 自动执行，例如“洗衣机洗完了提醒我”“主卧开关双击就关掉全屋的灯”
  “阳台漏水马上告诉我”。kind 为 rule，必须有触发条件。

联动分一次性和长期两种：
- 没有“以后”“每次”“每当”“总是”这类词的（“洗衣机洗完了提醒我”“冰箱门关上了告诉我”），只管下一次：once 为 true，
  触发一次后自动停用。现在没在运行也照样建，等下一次发生时提醒。
- 带这类词的（“以后洗衣机洗完都提醒我”“每次漏水都马上告诉我”）是长期联动：once 为 false。

需要每次临场判断的事（“每天晚上十一点看看有没有没关的灯，有就关掉告诉我”）不做成联动，
用 `cronjob_manage` 建定时任务，prompt 里写清楚要检查什么、做什么、播报什么。
每天定时汇报设备情况（“每天晚上八点告诉我鱼缸灯今天亮了多久”）也一样：prompt 里先调用
`mcp__home_history__device_history` 查询，再用 xiaoqi_announce 播报查到的结果。

## 步骤

1. 弄清楚三件事：由什么触发（场景就是口令）、做哪些动作、什么情况下不做。设备表里有的直接用实体 ID，
   没有的用 `ha_list_entities` 查；缺关键信息时只问一句。
   选触发用的传感器时，先用 `ha_list_entities`（area 填设备名）把这个设备的传感器都看一遍，选最直接表示这件事的：
   洗完、烘完、做完这类，优先用“阶段”“进度”“工作状态”变成“结束”“完成”的那个，可选值在 options 里；
   不要用“启动／暂停”这类控制状态，中途暂停也会触发。门、漏水这类用二值传感器。
2. 一次性的提醒（once 为 true）直接保存，不用确认，保存后说一句，例如“好，洗完我提醒你”。
   场景和长期联动分两步：先调用 `mcp__home_rules__home_rule_save`（confirmed 为 false），它只检查不保存，
   返回 needs_confirmation 和 summary；用一句话按 summary 复述，问“要我保存吗？”。
   用户同意后，用同样的参数再调用一次，confirmed 为 true，才真正保存。没有这次调用成功，不能说“保存好了”。
3. 返回 ok 为 false 时，按 problems 改好再保存；需要用户决定的（比如高风险设备不能放进去），用一句话告诉用户。
4. 保存成功后用一句话说明，例如“好，以后你说‘我回来了’，我就开客厅灯，把空调调到二十六度”。
   场景的口令会自动出现在人设最后“已保存的场景”清单里，以后听到就调用 `mcp__home_rules__home_rule_run`，不用写进记忆。

## 怎么填

- name：用户的叫法；场景就用口令本身（“我出门了”，不要改成“出门了”或“出门关灯”）。summary：一句中文说明。
- 场景就是 kind 为 scene，不管口令听起来像不像一件事发生；只有由设备或时间触发的才是 rule。
- trigger（只有联动有）：
  - 状态变化：type 为 state，填 entity_id 和 to（新状态），from 可选。门、漏水、洗衣机是否运行这类二值传感器
    只有 on 和 off：门开、漏水、正在运行都是 on。洗衣机洗完 = 程序是否已运行从 on 变成 off。
  - 持续一段时间才算：再加 for_seconds，例如冰箱门开着超过两分钟：to 为 on，for_seconds 为 120。
  - 数值越过某个值：type 为 numeric，填 above 或 below，例如客厅温度超过三十度。
  - 按键：type 为 event，entity_id 用 event. 开头的那个实体；单击、双击、长按各是一个实体。
  - 每天某个时间：type 为 time，at 为 HH:MM，weekdays 可选（mon、tue、wed、thu、fri、sat、sun）。
- conditions（可选，只有联动有）：state（某设备当前必须是某状态）、numeric、time（after、before 时间段，weekdays）。
- actions：
  - device：entity_id、service（turn_on、turn_off、toggle、set_temperature 等）、data（例如 {"temperature": 26}）。
  - announce：message 是要播报的中文口语，会在客厅的小爱音箱上念出来。只有漏水、烟雾、燃气这类安全报警
    urgent 为 true（夜里勿扰时段也会播报），其他一律为 false，勿扰时段会自动静音。
  - scene：运行已保存的另一个场景，填场景名。
  - delay：等待 seconds 秒。
- 门锁、取暖器、热水器这类高风险设备不能放进场景或联动，用户需要时让他直接说。
  空调、窗帘、电视放进联动时，要再加一条 announce 说明做了什么。

## 查看、修改、删除、试运行

- “有哪些场景／联动”：调用 `mcp__home_rules__home_rules_list`，简短念出名字和说明。
- “删掉／取消……”：明确是哪一个时直接调用 `mcp__home_rules__home_rule_delete`，有多个可能时先问是哪个。
- 修改：用同一个 name 重新调用 `mcp__home_rules__home_rule_save`（会覆盖原来的），保存前同样复述确认。
- “试一下……”：调用 `mcp__home_rules__home_rule_run`。
