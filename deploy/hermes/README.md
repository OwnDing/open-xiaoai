# Hermes Agent for Xiaozhi (xiaoqi-home)

Hermes Agent sits between `xiaozhi-esp32-server` and DeepSeek as an
OpenAI-compatible endpoint, adding memory, skills, web search, Home Assistant
and cron without touching the Open-XiaoAI voice path.

```text
小爱音箱 → Open-XiaoAI bridge → xiaozhi-esp32-server ──http://hermes:8642/v1──▶ Hermes ──▶ DeepSeek (deepseek-flash)
```

Latency results and the POC evaluation are in
[`docs/xiaoai-xiaozhi-hermes-latency-report.md`](../../docs/xiaoai-xiaozhi-hermes-latency-report.md).

## Layout

| Path | Purpose |
|---|---|
| `docker-compose.yml` | Hermes gateway (`hermes` container, volume `hermes-data`), joined to `xiaozhi-server_default` |
| `.env.example` | Keys: `API_SERVER_KEY`, `DEEPSEEK_API_KEY`, `TAVILY_API_KEY`, `HASS_URL`, `HASS_TOKEN` |
| `profile/` | The voice profile: `config.yaml`, `SOUL.md` (persona + device table + saved scene phrases), `skills/` (sleep-mode, home-rules), `mcp/home_rules` (scene/linkage MCP server), `mcp/home_history` (device history MCP server) |
| `switch-llm.ps1`, `switch_llm.py` | Switch xiaozhi-server between `hermes` and direct `deepseek` (backs up `.config.yaml` first) |
| `ha_device_table.py` | Generates the Home Assistant device table inside `profile/SOUL.md` |
| `demo-ha/` | Virtual Home Assistant used for the POC benchmarks (not deployed any more) |
| `bench/` | Latency harness and the raw results of the POC |

## Deploy (Windows MINI, PowerShell)

The container is dedicated to the speaker, so the default Hermes home inside
the `hermes-data` volume *is* the `xiaoqi-home` profile (Hermes allows only one
gateway per home, so a named profile would need multiplexing).

```powershell
cd C:\Users\djcmy\Documents\develop\ai\open-xiaoai\deploy\hermes
copy .env.example .env     # then fill in the keys
docker volume create hermes-data
docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
docker compose up -d
curl http://127.0.0.1:8642/health
```

Re-run the `install.sh` line after editing anything under `profile/`
(`SOUL.md` changes apply to the next request; `config.yaml` changes need
`docker restart hermes`).

Docker Hub pulls fail over SSH on this machine (Windows credential helper).
Pull from an interactive desktop session, or pull elsewhere and stream it in:

```sh
crane pull --platform linux/amd64 nousresearch/hermes-agent:<tag> hermes.tar
ssh djcmy@192.168.5.10 'docker load' < hermes.tar
```

## Switch Xiaozhi's brain

```powershell
powershell -ExecutionPolicy Bypass -File .\switch-llm.ps1 hermes     # via Hermes
powershell -ExecutionPolicy Bypass -File .\switch-llm.ps1 deepseek   # direct DeepSeek
```

Both LLM entries stay in `data/.config.yaml`; only `selected_module.LLM`
changes and xiaozhi-server is restarted (about 30 s without the speaker).

### Xiaozhi-side provider with a tool-call guard

The Hermes entry uses `type: hermes`, i.e. [`xiaozhi-provider/hermes.py`](xiaozhi-provider/hermes.py),
mounted into the server by its compose file:

```yaml
      - ../open-xiaoai/deploy/hermes/xiaozhi-provider/hermes.py:/opt/xiaozhi-esp32-server/core/providers/llm/hermes/hermes.py:ro
```

xiaozhi sends the dialogue as plain text, so earlier turns look like the
assistant switched devices without any tool call, and `deepseek-flash`
(non-thinking) sometimes copies that: in a multi-turn test it answered
“好了，次卧灯关了” without calling Home Assistant in 2 of 8 turns, despite the
rules in `SOUL.md`. For requests that mention a device and an action
(开/关/调/设…), the provider holds the reply until Hermes reports a tool call
(`event: hermes.tool.progress`, which precedes any text). A reply that ends
without one is discarded — never spoken — and the request is retried once with
an explicit reminder. Other requests stream through untouched. With the guard
all 16 commands of that test reached the devices. Set `tool_guard: false` in
the LLM entry to disable it; retries are logged as `设备控制请求未调用工具`.

A command for later (“两个小时后关鱼缸灯”, “三点关空调”, “待会儿开灯”: a concrete
duration or clock time, not “几点”) gets a different reminder, logged as
`定时控制请求未调用工具`: create a one-shot `cronjob_manage` job instead of
calling `ha_call_service` now. Any tool still satisfies the guard there, since
“现在三点了，把灯关了” means now.

A question about a device's past (“鱼缸灯今天亮了多久”, “客厅灯几点开的”, “空调昨天开了几次”,
“书房灯是谁关的”) must reach `mcp__home_history__device_history`; without it the
reply is dropped and retried, logged as `设备历史问题未查询`. Only past phrasing
counts (了/过/着/的 after the verb) together with a device word, so “去纽约要多久”
(no device), “空调开多久合适” (advice), “洗衣机还要多久” (what is left) and
“鱼缸灯几点关” (the future) are left alone. A follow-up without a device name
(“我问你今天开了多久？”) counts when the previous question named one and the last
reply gave no figures. Tested on all 944 distinct user utterances in Hermes'
history (2026-10-09): 5 matched, all real history questions.

## Timed device control (cron)

Hermes' `cronjob_manage` tool schedules device actions; the gateway ticks about
once a minute, so a job fires up to a minute late. `SOUL.md` tells the model to
create a one-shot job (`schedule` such as `in 2h` or a dated time) whose prompt
names the entity and the action, with `deliver: local` (the API server cannot
push to a speaker, so nothing is announced when it fires) and
`enabled_toolsets: ["homeassistant"]`. Cancelling or listing goes through the
same tool (`list`, then `remove`).

A job runs unattended, auto-approved, in a fresh agent session, so
`config.yaml` limits it twice:

- `platform_toolsets.cron: [homeassistant]` — left unset, cron gets the full
  default set (terminal, files, code execution, browser, computer use...).
- `agent.disabled_toolsets` — a job's own `enabled_toolsets` overrides the cron
  platform list (the tool tells the model to "infer" it: it once wrote
  `["home"]`, which is no toolset at all, and the run had no tools), so the
  risky toolsets are denied globally as well. The API-server tool list is
  unchanged by it; composite sets such as `debugging` stay off the list because
  they also carry web search.

Check jobs with `docker exec -u hermes hermes hermes cron list --all`; each run
is a `cron_<job>_<time>` session in `state.db` and its reply is saved under
`/opt/data/cron/output/<job>/`. A run whose reply is raw tool-call markup
(`<｜｜DSML｜｜ calls>`) had no tools.

`bench/multiturn_text.py` replays such a conversation on one connection;
`bench/tool_honesty.py` measures the same effect directly against Hermes.

## Voice-taught scenes and linkages (home_rules)

Nothing is preset: the user teaches scenes (“以后我说‘我回来了’，就开客厅灯”) and
linkages (“洗衣机洗完了提醒我”, “主卧开关双击就关书房灯”, “阳台漏水马上告诉我”) by voice.
[`profile/mcp/home_rules`](profile/mcp/home_rules) is a stdio MCP server that Hermes
starts from `config.yaml` (`mcp_servers.home_rules`; only `HASS_URL`/`HASS_TOKEN`
reach it, and the generic resource/prompt helper tools are off). It offers four
tools, `mcp__home_rules__home_rule_save`, `home_rules_list`, `home_rule_delete`
and `home_rule_run`; the [`home-rules`](profile/skills/home/home-rules/SKILL.md)
skill tells the model how to use them.

- Scenes become HA scripts (`script.xiaoqi_scene_*`), linkages HA automations
  (config id `xiaoqi_rule_*`), so they run inside Home Assistant and show up in
  its UI. The server only ever lists, changes or deletes objects with these ids.
- The model describes a rule in a fixed vocabulary (triggers: state, numeric,
  event, time; conditions: state, numeric, time; actions: device, announce,
  scene, delay); `rules.py` checks entities, services and state values against
  live HA and translates it. High-risk devices (locks, heaters, water heaters)
  are refused; a linkage that switches a medium-risk device (AC, curtains, TV)
  must also announce it; only a linkage triggered by a leak/smoke/gas sensor may
  speak in quiet hours.
- Scenes and lasting linkages need two calls: the first returns
  `needs_confirmation` and a summary to read back, the second
  (`confirmed: true`, after the user agreed) saves. A one-shot linkage
  (`once: true`, “这次洗完提醒我”) saves at once, switches itself off after
  running and is deleted on the next listing. Saving the same behaviour under
  another name returns `already_saved` instead of a duplicate.
- Saved scene phrases are written into `SOUL.md` between `<!-- scenes:start -->`
  and `<!-- scenes:end -->` (at server start and after every scene change);
  Hermes reads SOUL.md for each new conversation, so a phrase taught once works
  in later conversations. `install.sh` resets the block, so restart Hermes after
  installing the profile.
- The provider guard leaves teaching phrases (`RULE_WORDS`: 以后我说…, 当…的时候,
  …了提醒我, 每天…) to the normal path, and when the user agrees to an
  “要我保存吗？” it requires a `mcp__home_rules__` tool call, retrying once
  (logged as `确认保存后未调用规则工具`).

Unit tests: `cd profile/mcp && python3 -m unittest test_home_rules`. Inspect or
remove what was taught from the HA UI, or by voice (“现在有哪些联动”, “把……删掉”).

### Proactive announcements (script.xiaoqi_announce)

The server also installs (and keeps up to date) the HA script
`script.xiaoqi_announce` with fields `message` and `urgent`. It speaks through
the XiaoAi speaker's play-text action (`notify.*_play_text_*`, found
automatically). The quiet hours are the speaker's own do-not-disturb switch and
time period (editable in the Mi Home app): inside them a non-urgent message is
dropped and an urgent one is spoken. Do-not-disturb does not block play-text
(tested on the OH2P), so the script never switches it. Linkages, reminders (cron jobs) and timed device actions all call it through
`ha_call_service` (domain `script`, service `xiaoqi_announce`). Only the
living-room XiaoAi speaks; the voice terminals do not.

## Device history (home_history)

Hermes' own Home Assistant tools only see the present, so 小七 used to answer
“鱼缸灯今天亮了多久” with “插座没有记录” (and wrote that into its memory).
[`profile/mcp/home_history`](profile/mcp/home_history) is a read-only stdio MCP
server (`mcp_servers.home_history`, same `HASS_URL`/`HASS_TOKEN`) with one tool,
`mcp__home_history__device_history(entity_ids, period, start?, end?)`. It reads
`/api/history` and `/api/logbook` and does all the arithmetic, because the
non-thinking voice model is unreliable at adding up timestamps:

- `period`: `today`, `yesterday`, `last_24h`, `this_week`, `last_7_days`,
  `this_month`, `last_30_days`, in HA's time zone; `start`/`end` (`HH:MM`,
  `yesterday 18:00`, `YYYY-MM-DD HH:MM`) for spans such as 昨晚.
- Switches, lights, fans, binary sensors, TVs, AC: `on_total` (“2小时28分”),
  `times_switched_on`, `on_periods` with on/off times and who did it
  (`小七` = through Home Assistant: voice or a cron job; `联动：…`/`场景：…`;
  `米家App、小爱同学或手动` when the change came from the device's cloud),
  `per_day` and `average_per_full_day` for longer spans. Offline time is left
  out and does not split a period. For a device with a power sensor (W/kW,
  found through HA's device registry) it adds `power` with `max` and
  `estimated_energy_kwh`: the plug's own 0.01 kWh counter is too coarse.
- Sensors: min/max with times, time-weighted average; meters (`total_increasing`):
  amount used, surviving a reset. Event entities: how often. Other states:
  time in each state and the latest changes.
- `records_from` / `no_records` when the span starts before the recorder's
  history (HA keeps 30 days here, see `../homeassistant`).

Cron jobs get the tool as well: Hermes adds every MCP server to a job's
`enabled_toolsets`, so “每天晚上八点告诉我鱼缸灯今天亮了多久” is a daily job
that queries and then calls `script.xiaoqi_announce`.

Unit tests: `cd profile/mcp && python3 -m unittest test_home_history`
(uses the fish tank's real history of 2026-10-05..09).

## Profile choices that matter for latency

- `agent.reasoning_effort: none` — Hermes turns DeepSeek thinking **on** for
  `deepseek-flash` by default.
- Only `memory, session_search, skills, web, homeassistant, cronjob` are
  enabled for the API server; terminal/file/browser/code/delegation are off.
- Bundled skills are not seeded (`.no-bundled-skills`), keeping the skill
  index in the prompt short.
- `SOUL.md` lists Home Assistant entity ids so a command needs one tool round
  instead of list-then-call (light switches ~0.65 s sooner). The table is
  generated by `ha_device_table.py`; re-run it after changing devices in HA.
- `SOUL.md` asks for a short “我查一下。” before web search so the speaker is
  not silent while searching, and forbids any text before device/memory tools.

## Home Assistant (Mijia)

The production Home Assistant with the Xiaomi Home integration lives in
[`../homeassistant`](../homeassistant/README.md). After adding, renaming or
moving devices there, refresh the device table and reinstall the profile:

```powershell
docker run --rm --network xiaozhi-server_default --env-file .env -v ${PWD}:/hermes `
  --entrypoint /app/.venv/bin/python local/open-xiaoai-xiaozhi:smooth-audio /hermes/ha_device_table.py
docker compose run --rm --entrypoint sh hermes /seed/profile/install.sh
```

`demo-ha/` is the virtual Home Assistant the POC benchmarks ran against
(`onboard.py` creates its owner and writes `HASS_URL`/`HASS_TOKEN`); it is
not needed with a real Home Assistant.

## Benchmarks

See `bench/`. Everything runs inside the bridge image on the MINI:

```powershell
$run = "docker run --rm --network xiaozhi-server_default --env-file ..\.env -v ${PWD}:/bench -w /bench --entrypoint"
# LLM-level A/B (direct DeepSeek vs Hermes, interleaved)
iex "$run sh local/open-xiaoai-xiaozhi:smooth-audio ab_llm.sh"
# Voice pipeline through xiaozhi-server (fake device, real ASR); label, rounds
iex "$run sh local/open-xiaoai-xiaozhi:smooth-audio ab_voice.sh hermes 3"
# Device-control latency against the demo HA
iex "$run sh local/open-xiaoai-xiaozhi:smooth-audio ha_case.sh hermes 5"
```

Test utterances are generated on macOS with `bench/make_audio.sh`.
