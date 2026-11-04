"""Measure person detection on the live camera sub-streams.

Decodes each camera's RTSP sub-stream, samples FPS frames per second, runs every
model in MODELS on each sample and reports latency, CPU use and hits. Frames with
a detection (at most one per SAVE_EVERY seconds) and one frame per minute are
saved with the boxes drawn, so misses and false hits can be checked by eye.

Env: CAMS="name=rtsp://...;name2=rtsp://...", MODELS, FPS, DURATION, THRESH,
OV_THREADS, OUT.
"""

import json
import os
import resource
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import av
import numpy as np
import openvino as ov
from PIL import ImageDraw

TZ = ZoneInfo("Asia/Shanghai")
CAMS = [c.split("=", 1) for c in os.environ["CAMS"].split(";") if c.strip()]
MODELS = [m for m in os.environ.get("MODELS", "person-detection-0202").split(",") if m]
FPS = float(os.environ.get("FPS", "2"))
DURATION = float(os.environ.get("DURATION", "600"))
THRESH = float(os.environ.get("THRESH", "0.5"))
LOG_THRESH = 0.3
SAVE_EVERY = float(os.environ.get("SAVE_EVERY", "5"))
OUT = os.environ.get("OUT", "/out")
COLORS = ["#ff3030", "#30a0ff", "#30ff60"]

core = ov.Core()
compiled = {}
for m in MODELS:
    cm = core.compile_model(
        f"/models/{m}.xml",
        "CPU",
        {"INFERENCE_NUM_THREADS": int(os.environ.get("OV_THREADS", "1")), "PERFORMANCE_HINT": "LATENCY"},
    )
    _, _, h, w = cm.inputs[0].shape
    compiled[m] = (cm, int(h), int(w))

results = {}
log_lock = threading.Lock()
log_f = open(os.path.join(OUT, "detections.jsonl"), "a")


def run(name, url):
    st = {"frames_decoded": 0, "samples": 0, "errors": 0, "lat": {m: [] for m in MODELS}, "hit_samples": {m: 0 for m in MODELS}}
    results[name] = st
    reqs = {m: cm.create_infer_request() for m, (cm, _, _) in compiled.items()}
    end = time.monotonic() + DURATION
    next_t = last_save = last_periodic = 0.0
    while time.monotonic() < end:
        try:
            container = av.open(url, options={"rtsp_transport": "tcp", "stimeout": "5000000"}, timeout=10)
            vs = container.streams.video[0]
            vs.codec_context.thread_count = 1
            st["codec"] = f"{vs.codec_context.name} {vs.codec_context.width}x{vs.codec_context.height}"
            for frame in container.decode(vs):
                st["frames_decoded"] += 1
                now = time.monotonic()
                if now >= end:
                    break
                if now < next_t:
                    continue
                next_t = now + 1.0 / FPS
                st["samples"] += 1
                hits = {}
                for m, (cm, h, w) in compiled.items():
                    img = frame.to_ndarray(width=w, height=h, format="bgr24")
                    t0 = time.perf_counter()
                    reqs[m].infer({0: np.ascontiguousarray(img.transpose(2, 0, 1)[None])})
                    st["lat"][m].append((time.perf_counter() - t0) * 1000)
                    out = reqs[m].get_output_tensor(0).data[0, 0]
                    out = out[out[:, 0] >= 0]
                    dets = out[out[:, 2] >= LOG_THRESH]
                    hits[m] = [[round(float(v), 3) for v in d[2:7]] for d in dets]
                    if (dets[:, 2] >= THRESH).any():
                        st["hit_samples"][m] += 1
                ts = datetime.now(TZ)
                strong = any(c >= THRESH for ds in hits.values() for c, *_ in ds)
                if any(hits.values()):
                    with log_lock:
                        log_f.write(json.dumps({"cam": name, "t": ts.isoformat(timespec="milliseconds"), "hits": hits}) + "\n")
                        log_f.flush()
                tag = None
                if strong and now - last_save >= SAVE_EVERY:
                    tag, last_save = "hit", now
                elif now - last_periodic >= 60:
                    tag = "periodic"
                if tag:
                    last_periodic = now
                    im = frame.to_image()
                    d = ImageDraw.Draw(im)
                    for i, (m, ds) in enumerate(hits.items()):
                        for c, x1, y1, x2, y2 in ds:
                            box = [x1 * im.width, y1 * im.height, x2 * im.width, y2 * im.height]
                            d.rectangle(box, outline=COLORS[i % 3], width=2 if c >= THRESH else 1)
                            d.text((box[0] + 2, box[1] + 2 + 10 * i), f"{m[-4:]} {c:.2f}", fill=COLORS[i % 3])
                    im.save(os.path.join(OUT, f"{name}_{ts:%H%M%S}_{tag}.jpg"), quality=85)
            container.close()
        except Exception as e:  # stream drop: count it and reconnect
            st["errors"] += 1
            st["last_error"] = repr(e)
            time.sleep(2)


t_start, cpu_start = time.monotonic(), time.process_time()
threads = [threading.Thread(target=run, args=(n, u), daemon=True) for n, u in CAMS]
for t in threads:
    t.start()
for t in threads:
    t.join()
elapsed = time.monotonic() - t_start
cpu = time.process_time() - cpu_start

summary = {"elapsed_s": round(elapsed), "process_cpu_cores": round(cpu / elapsed, 3), "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024, "fps": FPS, "cams": {}}
infer_ms_total = 0.0
for name, st in results.items():
    s = {k: st[k] for k in ("codec", "frames_decoded", "samples", "errors", "hit_samples") if k in st}
    if "last_error" in st:
        s["last_error"] = st["last_error"]
    for m, lat in st["lat"].items():
        if lat:
            a = np.array(lat)
            infer_ms_total += a.sum()
            s[f"{m}_ms"] = {"mean": round(float(a.mean()), 1), "p95": round(float(np.percentile(a, 95)), 1), "max": round(float(a.max()), 1)}
    summary["cams"][name] = s
summary["inference_cpu_cores"] = round(infer_ms_total / 1000 / elapsed, 3)
print(json.dumps(summary, ensure_ascii=False, indent=1))
with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump(summary, f, ensure_ascii=False, indent=1)
