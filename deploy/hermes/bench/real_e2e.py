"""Real-speech latency from timestamped container logs.

Pairs each xiaozhi-server `listen stop` (the bridge VAD decided the user
finished) with the bridge's next `💬 我说`, `🤖 小智` and first
`原生小爱 TTS 已生成` lines.

    docker logs -t xiaozhi-esp32-server 2>&1 | findstr /C:"\"state\": \"stop\"" > DIR/server_stop.log
    docker logs -t open-xiaoai-xiaozhi > DIR/bridge.log 2>&1
    python real_e2e.py DIR <server module tag, e.g. SiFuHe> [since_epoch] [label]
"""
import re, sys, datetime, statistics as st, json
S = sys.argv[1]
def ts(s):
    s = s[:26] + "Z" if len(s) > 27 else s
    return datetime.datetime.strptime(s[:26], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
stops = []
for l in open(S + "/server_stop.log", encoding="utf-8", errors="ignore"):
    if '"state": "stop"' in l and sys.argv[2] in l:
        stops.append(ts(l.split()[0]))
events = []
for l in open(S + "/bridge.log", encoding="utf-8", errors="ignore"):
    parts = l.split(" ", 1)
    if len(parts) < 2 or not parts[0].startswith("20"): continue
    t = ts(parts[0]); msg = parts[1]
    if "💬 我说" in msg: events.append((t, "stt", msg.strip()))
    elif "🤖 小智" in msg: events.append((t, "text", msg.strip()))
    elif "已生成" in msg: events.append((t, "gen", msg.strip()))
since = float(sys.argv[3]) if len(sys.argv) > 3 else 0
rows = []
for i, t0 in enumerate(stops):
    if t0 < since: continue
    nxt = stops[i + 1] if i + 1 < len(stops) else t0 + 30
    r = {"stop": t0}
    for t, kind, msg in events:
        if t0 <= t < min(nxt, t0 + 30) and kind not in r:
            r[kind] = round(t - t0, 3); r[kind + "_msg"] = msg[:40]
    if "gen" in r and "stt" in r and "text" in r:
        rows.append(r)
print("complete turns", len(rows), "of", len([s for s in stops if s >= since]))
for k in ("stt", "text", "gen"):
    v = sorted(r[k] for r in rows)
    print(k, "median", round(st.median(v), 3), "p90", v[int(len(v) * .9) - 1], "min", v[0], "max", v[-1])
json.dump(rows, open(S + "/results/real_" + (sys.argv[4] if len(sys.argv) > 4 else "baseline") + ".json", "w"), ensure_ascii=False)
