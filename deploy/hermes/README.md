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
| `profile/` | The voice profile: `config.yaml`, `SOUL.md` (persona + device table), `skills/` (sleep-mode) |
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
