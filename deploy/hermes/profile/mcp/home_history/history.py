"""Device history from the Home Assistant recorder, summarised for speech.

Pure functions only (the server does the HTTP): the voice model runs without
thinking and is unreliable at adding up timestamps, so durations, counts,
averages and who switched a device are all worked out here and handed back
ready to read out ("2小时28分", "08:33").
"""

import re
from datetime import datetime, timedelta

PERIODS = ("today", "yesterday", "last_24h", "this_week", "last_7_days", "this_month", "last_30_days")
OFFLINE = {"unavailable", "unknown", ""}
# Domains where "on" means lit / running / open; others are numeric or plain states.
ON_OFF = {"switch", "light", "fan", "input_boolean", "binary_sensor", "siren", "humidifier", "remote"}
COUNTERS = {"total", "total_increasing"}
# Their state is the time of the last press / event, so each change is one occurrence.
EVENTS = {"event", "button", "input_button"}
# Power units -> divisor giving kWh from unit-hours.
POWER_UNITS = {"W": 1000, "kW": 1}
MAX_PERIODS = 8
MAX_CHANGES = 12
# An offline blip shorter than this (cloud reconnects) is not worth mentioning.
OFFLINE_NOTE_SECONDS = 60
# Logbook entries carry the time of the state change they describe.
MATCH_SECONDS = 2
ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def window(now, period="today", start=None, end=None):
    """(from, to) in now's time zone; start/end override the period's edges."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ranges = {
        "today": (midnight, now),
        "yesterday": (midnight - timedelta(days=1), midnight),
        "last_24h": (now - timedelta(hours=24), now),
        "this_week": (midnight - timedelta(days=now.weekday()), now),
        "last_7_days": (midnight - timedelta(days=6), now),
        "this_month": (midnight.replace(day=1), now),
        "last_30_days": (midnight - timedelta(days=29), now),
    }
    if period not in ranges:
        raise ValueError(f"period 只能是 {', '.join(PERIODS)}")
    lo, hi = ranges[period]
    if start:
        lo = parse_time(start, now)
    if end:
        hi = parse_time(end, now)
    hi = min(hi, now)
    if lo >= hi:
        raise ValueError("开始时间要早于结束时间，而且不能晚于现在")
    return lo, hi


def parse_time(text, now):
    """'08:00', 'yesterday 18:00', 'today 08:00', '2026-10-08 18:00' or ISO, in now's zone."""
    text = str(text).strip()
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        match = re.match(r"^(today|yesterday)?\s*(\d{1,2}):(\d{2})(?::(\d{2}))?$", text)
        if not match:
            raise ValueError(f"看不懂时间“{text}”，用 HH:MM、yesterday HH:MM 或 YYYY-MM-DD HH:MM") from None
        day, hour, minute, second = match.groups()
        moment = now.replace(hour=int(hour), minute=int(minute), second=int(second or 0), microsecond=0)
        return moment - timedelta(days=1) if day == "yesterday" else moment
    if moment.tzinfo is None:
        return moment.replace(tzinfo=now.tzinfo)
    return moment.astimezone(now.tzinfo)


def parse_ts(value, tz):
    return datetime.fromisoformat(value).astimezone(tz)


def fmt_duration(seconds):
    if seconds <= 0:
        return "0分钟"
    minutes = int(round(seconds / 60))
    if minutes < 1:
        return "不到1分钟"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes}分钟"
    return f"{hours}小时{minutes}分" if minutes else f"{hours}小时"


def fmt_time(moment, lo, hi):
    """'08:33' inside a one-day range, else '10月8日 07:44'."""
    if lo.date() == (hi - timedelta(microseconds=1)).date():
        return moment.strftime("%H:%M")
    return f"{moment.month}月{moment.day}日 {moment:%H:%M}"


def fmt_range(lo, hi, now):
    def label(moment):
        return f"{moment.month}月{moment.day}日 {moment:%H:%M}"
    return {"from": label(lo), "to": "现在" if hi >= now - timedelta(seconds=5) else label(hi)}


def segments(rows, lo, hi, tz):
    """[(state, since, until)] clipped to [lo, hi], same states merged. Before the first row: nothing."""
    points = [(max(parse_ts(r["last_changed"], tz), lo), str(r.get("state", ""))) for r in rows]
    points = [p for p in points if p[0] < hi]
    out = []
    for i, (since, state) in enumerate(points):
        until = points[i + 1][0] if i + 1 < len(points) else hi
        if until <= since:
            continue
        if out and out[-1][0] == state:
            out[-1] = (state, out[-1][1], until)
        else:
            out.append((state, since, until))
    return out


def is_on(domain, state):
    if state in OFFLINE:
        return None
    if domain in ON_OFF:
        return state == "on"
    if domain == "media_player":
        return state not in ("off", "standby")
    if domain == "climate":
        return state != "off"
    if domain == "cover":
        return state in ("open", "opening", "closing")
    return None


def actor(entry):
    """Who caused a logged state change, in words.

    The household does not use the Home Assistant app: a change made through
    Home Assistant by a user (the agent's token) is 小七 — by voice or a timed
    job. Without any context the change came from the device's own cloud:
    the Mi Home app, the original 小爱同学, the physical button or a Mi Home
    automation.
    """
    if not entry:
        return None
    kind = entry.get("context_event_type")
    name = str(entry.get("context_name") or "").strip()
    if kind == "automation_triggered":
        return "联动：" + name.removeprefix("小七联动：") if name.startswith("小七联动：") else f"自动化：{name}"
    if kind == "script_started":
        return "场景：" + name.removeprefix("小七场景：") if name.startswith("小七场景：") else f"脚本：{name}"
    if entry.get("context_user_id"):
        return "小七"
    if kind or entry.get("context_domain"):
        return "Home Assistant"
    return "米家App、小爱同学或手动"


def _logged(logbook, state, moment, tz):
    for entry in logbook:
        if entry.get("state") != state or not entry.get("when"):
            continue
        if abs((parse_ts(entry["when"], tz) - moment).total_seconds()) <= MATCH_SECONDS:
            return entry
    return None


def _offline_seconds(segs):
    return sum((u - s).total_seconds() for state, s, u in segs if state in OFFLINE)


def summarize(entity_id, current, rows, logbook, lo, hi, now, tz):
    """One entity's history over [lo, hi] as a small dict for the voice model."""
    domain = entity_id.split(".", 1)[0]
    attrs = (current or {}).get("attributes", {})
    out = {"entity_id": entity_id, "name": attrs.get("friendly_name", entity_id)}
    if current:
        out["now"] = current.get("state")
    segs = segments(rows, lo, hi, tz)
    if not segs:
        out["no_records"] = "这段时间没有记录"
        return out
    if segs[0][1] > lo + timedelta(minutes=1):
        out["records_from"] = fmt_time(segs[0][1], lo, hi)
    offline = _offline_seconds(segs)
    if offline >= OFFLINE_NOTE_SECONDS:
        out["offline"] = fmt_duration(offline) + "（离线，没算在内）"
    if domain in EVENTS:
        out.update(_events(segs, lo, hi))
    elif any(is_on(domain, s) is not None for s, _, _ in segs):
        out.update(_on_off(domain, segs, logbook, lo, hi, now, tz))
    elif _numeric(segs):
        out.update(_numbers(segs, attrs, lo, hi))
    else:
        out.update(_states(segs, lo, hi))
    return out


def _on_periods(domain, segs):
    """Merged on periods [(since, until, on_seconds)]: an offline gap inside one doesn't split it."""
    periods = []
    current = None
    for state, since, until in segs:
        on = is_on(domain, state)
        if on:
            if current is None:
                current = [since, until, 0.0]
            current[1] = until
            current[2] += (until - since).total_seconds()
        elif on is False and current is not None:
            periods.append(tuple(current))
            current = None
    if current is not None:
        periods.append(tuple(current))
    return periods


def _on_off(domain, segs, logbook, lo, hi, now, tz):
    periods = _on_periods(domain, segs)
    total = sum(p[2] for p in periods)
    listed = []
    for since, until, on_seconds in periods[-MAX_PERIODS:]:
        item = {"on": fmt_time(since, lo, hi) if since > lo else "开始前就开着"}
        if since > lo:
            item["on_by"] = actor(_logged(logbook, _state_at(segs, since), since, tz))
        if until >= hi and hi >= now - timedelta(seconds=5):
            item["off"] = "现在还开着"
        elif until >= hi:
            item["off"] = "这段时间结束时还开着"
        else:
            item["off"] = fmt_time(until, lo, hi)
            item["off_by"] = actor(_logged(logbook, _state_at(segs, until), until, tz))
        item["duration"] = fmt_duration(on_seconds)
        listed.append({k: v for k, v in item.items() if v is not None})
    out = {
        "on_total": fmt_duration(total),
        "on_seconds": int(total),
        "times_switched_on": sum(1 for p in periods if p[0] > lo),
        "on_periods": listed,
    }
    if len(periods) > MAX_PERIODS:
        out["earlier_periods_not_listed"] = len(periods) - MAX_PERIODS
    days = _per_day(periods, lo, hi, segs[0][1])
    if days:
        out.update(days)
    return out


def _state_at(segs, moment):
    return next((s for s, since, _ in segs if since == moment), None)


def _per_day(periods, lo, hi, first):
    """On time per calendar day, for ranges longer than a day.

    first: the earliest recorded moment. Days before it are "没有记录", and only
    whole days with records count towards the average.
    """
    if lo.date() == (hi - timedelta(microseconds=1)).date():
        return None
    day = lo.replace(hour=0, minute=0, second=0, microsecond=0)
    rows, full = [], []
    while day < hi:
        nxt = day + timedelta(days=1)
        a, b = max(day, lo), min(nxt, hi)
        label = f"{day.month}月{day.day}日"
        if b <= first:
            rows.append({"date": label, "on": "没有记录"})
            day = nxt
            continue
        on = sum(max(0.0, (min(u, b) - max(s, a)).total_seconds()) for s, u, _ in periods)
        rows.append({"date": label, "on": fmt_duration(on)})
        if a == day and b == nxt and first <= day:
            full.append(on)
        day = nxt
    out = {"per_day": rows}
    if full:
        out["average_per_full_day"] = fmt_duration(sum(full) / len(full))
        out["full_days"] = len(full)
    return out


def power_of(summary):
    """The parts of a power sensor's summary worth adding to its switch.

    No average: over a day that is mostly off it reads as "1.3 瓦" while the
    lamp draws 12 W; max is the power while on.
    """
    keys = ("unit", "max", "estimated_energy_kwh")
    if "estimated_energy_kwh" not in summary:
        return None
    return {"name": summary.get("name"), **{k: summary[k] for k in keys if k in summary}}


def _value(state):
    try:
        return float(state)
    except (TypeError, ValueError):
        return None


def _numeric(segs):
    values = [_value(s) for s, _, _ in segs if s not in OFFLINE]
    return bool(values) and all(v is not None for v in values)


def _numbers(segs, attrs, lo, hi):
    unit = attrs.get("unit_of_measurement") or ""
    points = [(_value(s), since, until) for s, since, until in segs if s not in OFFLINE]
    if attrs.get("state_class") in COUNTERS:
        used = 0.0
        for (a, _, _), (b, _, _) in zip(points, points[1:]):
            if b >= a:
                used += b - a
            elif attrs.get("state_class") == "total_increasing":
                used += b  # the meter was reset to zero
            else:
                used += b - a
        return {"used": round(used, 3), "unit": unit, "start_value": points[0][0], "end_value": points[-1][0]}
    low = min(points, key=lambda p: p[0])
    high = max(points, key=lambda p: p[0])
    seconds = sum((u - s).total_seconds() for _, s, u in points)
    weighted = sum(v * (u - s).total_seconds() for v, s, u in points)
    out = {
        "unit": unit,
        "min": {"value": low[0], "at": fmt_time(low[1], lo, hi)},
        "max": {"value": high[0], "at": fmt_time(high[1], lo, hi)},
        "average": round(weighted / seconds, 1),
        "latest": points[-1][0],
    }
    # Plugs' own energy counters are often too coarse (0.01 kWh steps); a power
    # sensor integrated over time answers "用了多少电" better.
    if unit in POWER_UNITS:
        out["estimated_energy_kwh"] = round(weighted / 3600 / POWER_UNITS[unit], 3)
    return out


def _events(segs, lo, hi):
    times = [fmt_time(since, lo, hi) for state, since, _ in segs if since > lo and state not in OFFLINE]
    out = {"times_happened": len(times), "at": times[-MAX_CHANGES:]}
    if len(times) > MAX_CHANGES:
        out["earlier_not_listed"] = len(times) - MAX_CHANGES
    return out


def _states(segs, lo, hi):
    """Time spent in each state and the latest changes (washer phase, door lock...)."""
    spent = {}
    for state, since, until in segs:
        if state not in OFFLINE:
            spent[state] = spent.get(state, 0.0) + (until - since).total_seconds()
    changes = [{"at": fmt_time(since, lo, hi), "state": state}
               for state, since, _ in segs if since > lo and state not in OFFLINE]
    out = {"time_in_state": {k: fmt_duration(v) for k, v in sorted(spent.items(), key=lambda kv: -kv[1])},
           "changes": changes[-MAX_CHANGES:]}
    if len(changes) > MAX_CHANGES:
        out["earlier_changes_not_listed"] = len(changes) - MAX_CHANGES
    return out
