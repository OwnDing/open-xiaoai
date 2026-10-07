"""The "小七播报" Home Assistant script: one place that speaks on the XiaoAi speaker.

Linkages, reminders (cron jobs) and the agent itself call script.xiaoqi_announce
with a message and an urgent flag. The quiet hours are the speaker's own
do-not-disturb setting (switch + time period, editable in the Mi Home app),
so there is nothing to configure here: outside them every message is spoken,
inside them only urgent ones (water leak and other safety alarms). The
speaker's do-not-disturb does not block play-text (tested on the OH2P), so an
urgent message is simply spoken and do-not-disturb is left alone.
"""

import re

from .rules import ANNOUNCE_SCRIPT

PLAY_TEXT = re.compile(r"^notify\.(?P<prefix>.+)_play_text(?:_[a-z0-9_]+)?$")


def find_speaker(states):
    """The first speaker with a play-text action: {play_text, no_disturb, quiet_period}."""
    by_id = {s["entity_id"]: s for s in states}
    for entity_id in sorted(by_id):
        match = PLAY_TEXT.match(entity_id)
        if not match:
            continue
        prefix = match.group("prefix")

        def first(domain, word):
            return next((e for e in sorted(by_id) if e.startswith(f"{domain}.{prefix}_{word}")), None)

        return {
            "play_text": entity_id,
            "name": by_id[entity_id].get("attributes", {}).get("friendly_name", entity_id),
            "no_disturb": first("switch", "no_disturb"),
            "quiet_period": first("text", "enable_time_period"),
        }
    return None


# "HH:MM:SS-HH:MM:SS"; the period may run past midnight.
QUIET_TEMPLATE = (
    "{%- set p = states(period_entity).split('-') if period_entity else [] -%}"
    "{%- if dnd_entity and is_state(dnd_entity, 'on') and p | length == 2 -%}"
    "{%- set a = p[0] | trim -%}{%- set b = p[1] | trim -%}"
    "{%- set t = now().strftime('%H:%M:%S') -%}"
    "{{ (a <= t < b) if a <= b else (t >= a or t < b) }}"
    "{%- else -%}false{%- endif -%}"
)


def script_config(speaker):
    play = {"action": "notify.send_message", "target": {"entity_id": speaker["play_text"]},
            "data": {"message": "{{ message }}"}}
    sequence = [
        {"variables": {
            "dnd_entity": speaker.get("no_disturb") or "",
            "period_entity": speaker.get("quiet_period") or "",
        }},
        {"variables": {"quiet": QUIET_TEMPLATE, "is_urgent": "{{ urgent | default(false) | bool }}"}},
        {"if": [{"condition": "template", "value_template": "{{ quiet and not is_urgent }}"}],
         "then": [{"stop": "勿扰时段，非紧急播报不出声"}]},
        play,
    ]
    return {
        "alias": "小七播报",
        "description": (f"由小七的家庭规则工具生成，请勿手动修改。在 {speaker['name']} 上播报；"
                        "勿扰时段内只播报紧急消息（如漏水）。"),
        "mode": "queued",
        "max": 10,
        "fields": {
            "message": {"name": "播报内容", "required": True, "selector": {"text": {}}},
            "urgent": {"name": "紧急", "description": "勿扰时段也播报，只用于漏水、烟雾、燃气这类安全报警",
                       "default": False, "selector": {"boolean": {}}},
        },
        "sequence": sequence,
    }


def ensure(ha):
    """Create or update script.xiaoqi_announce; returns a short status string."""
    speaker = find_speaker(ha.states())
    if speaker is None:
        return "no speaker with a play-text action in Home Assistant"
    wanted = script_config(speaker)
    try:
        current = ha.get_config("script", ANNOUNCE_SCRIPT)
    except Exception:
        current = None
    if current == wanted:
        return f"up to date ({speaker['play_text']})"
    ha.save_config("script", ANNOUNCE_SCRIPT, wanted)
    return f"installed for {speaker['play_text']}"
