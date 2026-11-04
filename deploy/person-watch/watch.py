"""person-watch: log every person the home cameras see.

Per camera: decode the RTSP sub-stream, look for motion twice a second on a
96-px thumbnail, and run the person detector (Intel person-detection-0202,
OpenVINO, one CPU thread) only when the picture moves, every KEEPALIVE_S while
someone is in view, and every IDLE_CHECK_S otherwise. START_HITS hits in the
last three checks open an event; END_AFTER_S without a hit closes it.

Each event gets snapshots (start, more people, every PERIODIC_SNAPSHOT_S): the
next 1080p key frame of the main stream, re-checked by the detector and drawn
with boxes, or the sub-stream frame when the main stream gives no person.
Events and snapshots go to SQLite under /data, are kept KEEP_DAYS days, show up
on a small web page, and drive one HA binary_sensor per camera.
"""

import base64
import json
import logging
import os
import queue
import shutil
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import av
import numpy as np
import openvino as ov
from PIL import ImageDraw, ImageFont

env = os.environ.get
TZ = ZoneInfo(env("TZ", "Asia/Shanghai"))
DATA = env("DATA", "/data")
SNAP_DIR = os.path.join(DATA, "snapshots")
MODEL = env("MODEL", "/models/person-detection-0202.xml")
THRESH = float(env("THRESH", "0.5"))
MIN_BOX_H = float(env("MIN_BOX_H", "0.08"))
SAMPLE_FPS = float(env("SAMPLE_FPS", "2"))
DETECT_MAX_FPS = float(env("DETECT_MAX_FPS", "1"))
KEEPALIVE_S = float(env("KEEPALIVE_S", "5"))
IDLE_CHECK_S = float(env("IDLE_CHECK_S", "60"))
START_HITS = int(env("START_HITS", "2"))
END_AFTER_S = float(env("END_AFTER_S", "60"))
MORE_SNAPSHOT_GAP_S = float(env("MORE_SNAPSHOT_GAP_S", "10"))
PERIODIC_SNAPSHOT_S = float(env("PERIODIC_SNAPSHOT_S", "600"))
MOTION_PIXEL_DIFF = int(env("MOTION_PIXEL_DIFF", "20"))
MOTION_MIN_FRACTION = float(env("MOTION_MIN_FRACTION", "0.004"))
KEEP_DAYS = int(env("KEEP_DAYS", "30"))
OFFLINE_AFTER_S = float(env("OFFLINE_AFTER_S", "60"))
INPUT_AREA = int(env("INPUT_AREA", str(544 * 320)))
HA_URL = env("HA_URL", "").rstrip("/")
HA_TOKEN = env("HA_TOKEN", "")
# Set (e.g. "person-watch-") when HA has the trigger-based template sensors from
# ha_templates.yaml: states then go to webhook <prefix><camera>, which needs no token.
HA_WEBHOOK = env("HA_WEBHOOK", "")
PUBLIC_URL = env("PUBLIC_URL", "").rstrip("/")
PORT = int(env("PORT", "8080"))
WEB_USER, WEB_PASSWORD = env("WEB_USER", ""), env("WEB_PASSWORD", "")
DEBUG_DETS = env("DEBUG_DETS", "") == "1"
# QQ push (official bot API, private chat): the start snapshot of an event on these cameras.
QQ_APP_ID, QQ_CLIENT_SECRET, QQ_OPENID = env("QQ_APP_ID", ""), env("QQ_CLIENT_SECRET", ""), env("QQ_OPENID", "")
QQ_NOTIFY_CAMS = {c for c in env("QQ_NOTIFY_CAMS", "").split(",") if c}
QQ_COOLDOWN_S = float(env("QQ_COOLDOWN_S", "120"))
# On-screen text (time, camera name, Wi-Fi icon) as x1, y1, x2, y2 fractions:
# ignored for motion, and a box mostly inside one is not a person.
OSD_MASKS = [tuple(float(v) for v in m.split(",")) for m in env("OSD_MASKS", "0,0,0.75,0.12;0.7,0.88,1,1;0.85,0,1,0.08").split(";") if m]
RTSP_OPTIONS = {"rtsp_transport": "tcp", "timeout": "5000000"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(threadName)s %(message)s")
log = logging.getLogger("person-watch")


def now_local():
    return datetime.now(TZ)


def parse_cams():
    labels = dict(p.split("=", 1) for p in env("CAM_LABELS", "").split(",") if "=" in p)
    cams = []
    for item in env("CAMS", "").split(";"):
        if "=" not in item:
            continue
        name, urls = item.split("=", 1)
        sub, _, main = urls.partition("|")
        if not main:
            main = sub.replace("Channels/102", "Channels/101")
        cams.append((name.strip(), labels.get(name.strip(), name.strip()), sub.strip(), main.strip()))
    return cams


def input_shape(width, height):
    """Detector input with the frame's aspect ratio, about INPUT_AREA pixels, multiples of 32."""
    aspect = width / height
    h = max(32, round((INPUT_AREA / aspect) ** 0.5 / 32) * 32)
    w = max(32, round(h * aspect / 32) * 32)
    return h, w


class Detector:
    def __init__(self, path):
        self.core = ov.Core()
        self.path = path
        self.compiled = {}
        self.lock = threading.Lock()

    def request(self, h, w):
        with self.lock:
            if (h, w) not in self.compiled:
                model = self.core.read_model(self.path)
                model.reshape({model.inputs[0].get_any_name(): [1, 3, h, w]})
                self.compiled[(h, w)] = self.core.compile_model(
                    model, "CPU", {"INFERENCE_NUM_THREADS": 1, "PERFORMANCE_HINT": "LATENCY"}
                )
                log.info("detector compiled for %dx%d", w, h)
            return self.compiled[(h, w)].create_infer_request()


def masked_fraction(box):
    x1, y1, x2, y2 = box
    area = max((x2 - x1) * (y2 - y1), 1e-6)
    inside = 0.0
    for mx1, my1, mx2, my2 in OSD_MASKS:
        iw = max(0.0, min(x2, mx2) - max(x1, mx1))
        ih = max(0.0, min(y2, my2) - max(y1, my1))
        inside = max(inside, iw * ih / area)
    return inside


def detect(req, frame, h, w, raw=None):
    """Person boxes [(conf, x1, y1, x2, y2)] in 0..1 coordinates."""
    img = frame.to_ndarray(width=w, height=h, format="bgr24")
    req.infer({0: np.ascontiguousarray(img.transpose(2, 0, 1)[None])})
    out = req.get_output_tensor(0).data[0, 0]
    out = out[(out[:, 0] >= 0) & (out[:, 2] >= 0.3)]
    dets = []
    for _, _, conf, x1, y1, x2, y2 in out:
        box = tuple(float(np.clip(v, 0, 1)) for v in (x1, y1, x2, y2))
        if raw is not None:
            raw.append([round(float(conf), 3), *(round(v, 3) for v in box)])
        if conf >= THRESH and box[3] - box[1] >= MIN_BOX_H and masked_fraction(box) < 0.5:
            dets.append((float(conf), *box))
    return dets


class Store:
    def __init__(self):
        os.makedirs(SNAP_DIR, exist_ok=True)
        self.db = sqlite3.connect(os.path.join(DATA, "events.db"), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock, self.db:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, cam TEXT, start TEXT, end TEXT,
                    max_persons INTEGER, max_conf REAL, last_seen TEXT);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY, event_id INTEGER, cam TEXT, ts TEXT, reason TEXT,
                    path TEXT, persons INTEGER, conf REAL, hd INTEGER);
                CREATE INDEX IF NOT EXISTS events_start ON events(start);
                CREATE INDEX IF NOT EXISTS snapshots_event ON snapshots(event_id);
                """
            )
            if "last_seen" not in [r[1] for r in self.db.execute("PRAGMA table_info(events)")]:
                self.db.execute("ALTER TABLE events ADD COLUMN last_seen TEXT")
            # Events left open by a crash or restart end when the person was last seen.
            self.db.execute(
                "UPDATE events SET end = COALESCE(last_seen, (SELECT MAX(ts) FROM snapshots WHERE event_id = events.id), start)"
                " WHERE end IS NULL"
            )

    def execute(self, sql, args=()):
        with self.lock, self.db:
            return self.db.execute(sql, args)

    def query(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def purge(self):
        cutoff = (now_local() - timedelta(days=KEEP_DAYS)).date()
        with self.lock, self.db:
            self.db.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff.isoformat(),))
            self.db.execute("DELETE FROM events WHERE start < ?", (cutoff.isoformat(),))
        for day in os.listdir(SNAP_DIR):
            if day < cutoff.isoformat():
                shutil.rmtree(os.path.join(SNAP_DIR, day), ignore_errors=True)


class HomeAssistant:
    def __init__(self):
        self.states = {}
        self.lock = threading.Lock()

    def set(self, cam, state, **attrs):
        with self.lock:
            self.states[cam.name] = (state, {
                "friendly_name": f"{cam.label}摄像头有人",
                "device_class": "occupancy",
                "icon": "mdi:cctv",
                "attribution": "person-watch",
                **attrs,
            })
        self.push(cam.name)

    def push(self, name):
        if not HA_URL or not (HA_WEBHOOK or HA_TOKEN):
            return
        with self.lock:
            state, attrs = self.states[name]
        body = json.dumps({"state": state, "attributes": attrs}).encode()
        if HA_WEBHOOK:
            url, headers = f"{HA_URL}/api/webhook/{HA_WEBHOOK}{name}", {}
        else:
            url, headers = f"{HA_URL}/api/states/binary_sensor.person_{name}", {"Authorization": f"Bearer {HA_TOKEN}"}
        req = urllib.request.Request(url, data=body, method="POST", headers={**headers, "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            log.warning("HA update for %s failed: %r", name, e)

    def heartbeat(self):
        # Re-post every minute so the sensors come back after an HA restart. HA keeps
        # an identical state as is, so with webhooks a separate "heartbeat" webhook
        # stamps sensor.person_watch_heartbeat for HA's "监控中断" alert.
        while True:
            time.sleep(60)
            for name in list(self.states):
                self.push(name)
            if HA_URL and HA_WEBHOOK:
                req = urllib.request.Request(f"{HA_URL}/api/webhook/{HA_WEBHOOK}heartbeat", data=b"{}", method="POST",
                                             headers={"Content-Type": "application/json"})
                try:
                    urllib.request.urlopen(req, timeout=5).read()
                except Exception as e:
                    log.warning("HA heartbeat failed: %r", e)


class Camera(threading.Thread):
    def __init__(self, name, label, sub_url, main_url, detector, store, ha, snapper):
        super().__init__(name=f"cam-{name}", daemon=True)
        self.name, self.label, self.sub_url, self.main_url = name, label, sub_url, main_url
        self.detector, self.store, self.ha, self.snapper = detector, store, ha, snapper
        self.event = None
        self.recent = deque(maxlen=3)  # (monotonic time, hit) of the last checks
        self.pending = False  # a hit not yet confirmed: check again soon
        self.last_frame = 0.0
        self.online = None
        self.stats = {"frames": 0, "checks": 0, "motion_checks": 0, "reconnects": 0, "infer_ms": 0.0}
        self.debug_f = None

    def run(self):
        while True:
            try:
                self.watch()
            except Exception as e:
                log.warning("%s stream error: %r", self.name, e)
            self.stats["reconnects"] += 1
            if self.event and time.monotonic() - self.event["last_hit"] >= END_AFTER_S:
                self.close_event()
            time.sleep(5)

    def set_online(self, online):
        if online == self.online:
            return
        self.online = online
        log.info("%s %s", self.name, "online" if online else "offline")
        if online:
            self.ha.set(self, "on" if self.event else "off", max_persons=self.event["max_persons"] if self.event else 0)
        else:
            self.ha.set(self, "unavailable")

    def watch(self):
        ct = av.open(self.sub_url, options=RTSP_OPTIONS, timeout=(10, 10))
        try:
            vs = ct.streams.video[0]
            vs.codec_context.thread_count = 1
            h, w = input_shape(vs.codec_context.width, vs.codec_context.height)
            req = self.detector.request(h, w)
            mw = 96
            mh = max(8, round(mw * vs.codec_context.height / vs.codec_context.width))
            motion_mask = np.ones((mh, mw), bool)
            for x1, y1, x2, y2 in OSD_MASKS:
                motion_mask[int(y1 * mh):int(np.ceil(y2 * mh)), int(x1 * mw):int(np.ceil(x2 * mw))] = False
            prev = None
            next_sample = last_check = 0.0
            log.info("%s connected: %s %dx%d, detector %dx%d", self.name, vs.codec_context.name,
                     vs.codec_context.width, vs.codec_context.height, w, h)
            for frame in ct.decode(vs):
                now = time.monotonic()
                self.last_frame = now
                self.stats["frames"] += 1
                if not self.online:
                    self.set_online(True)
                if now < next_sample:
                    continue
                next_sample = now + 1.0 / SAMPLE_FPS
                small = frame.to_ndarray(width=mw, height=mh, format="gray").astype(np.int16)
                moved = False
                if prev is not None:
                    changed = (np.abs(small - prev) > MOTION_PIXEL_DIFF) & motion_mask
                    moved = changed.mean() >= MOTION_MIN_FRACTION
                prev = small
                since = now - last_check
                quick = moved or self.pending
                due = (quick and since >= 1.0 / DETECT_MAX_FPS) or (self.event and since >= KEEPALIVE_S) or since >= IDLE_CHECK_S
                if not due:
                    continue
                last_check = now
                raw = [] if DEBUG_DETS else None
                t0 = time.perf_counter()
                dets = detect(req, frame, h, w, raw)
                self.stats["infer_ms"] += (time.perf_counter() - t0) * 1000
                self.stats["checks"] += 1
                self.stats["motion_checks"] += moved
                if raw:
                    self.debug(raw, dets, moved)
                self.on_check(now, dets, frame)
        finally:
            ct.close()

    def debug(self, raw, dets, moved):
        day = now_local().date().isoformat()
        path = os.path.join(DATA, "debug", f"dets-{day}.jsonl")
        if not self.debug_f or self.debug_f.name != path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.debug_f = open(path, "a")
        self.debug_f.write(json.dumps({"cam": self.name, "t": now_local().isoformat(timespec="seconds"),
                                       "moved": bool(moved), "kept": len(dets), "raw": raw}) + "\n")
        self.debug_f.flush()

    def on_check(self, now, dets, frame):
        hit = bool(dets)
        self.recent.append((now, hit))
        ev = self.event
        if ev is None:
            hits = sum(1 for t, h in self.recent if h and now - t <= 10)
            self.pending = hit and hits < START_HITS
            if hit and hits >= START_HITS:
                self.open_event(now, dets, frame)
            return
        if hit:
            if now - ev["last_hit"] >= 60 or now - ev.get("saved_seen", 0) >= 60:
                ev["saved_seen"] = now
                self.store.execute("UPDATE events SET last_seen = ? WHERE id = ?",
                                   (now_local().isoformat(timespec="seconds"), ev["id"]))
            ev["last_hit"], ev["last_hit_wall"] = now, now_local()
            ev["max_conf"] = max(ev["max_conf"], max(d[0] for d in dets))
            more = len(dets) > ev["persons"]
            ev["persons"] = len(dets)
            if len(dets) > ev["max_persons"]:
                ev["max_persons"] = len(dets)
                self.store.execute("UPDATE events SET max_persons = ?, max_conf = ? WHERE id = ?",
                                   (ev["max_persons"], ev["max_conf"], ev["id"]))
            if more and len(dets) == ev["max_persons"]:
                self.ha.set(self, "on", max_persons=len(dets), event_start=ev["start"].isoformat(timespec="seconds"),
                            last_snapshot=ev.get("last_snapshot", ""))
            if more and now - ev["last_snap"] >= MORE_SNAPSHOT_GAP_S:
                self.snapshot("more", dets, frame)
            elif now - ev["last_snap"] >= PERIODIC_SNAPSHOT_S:
                self.snapshot("periodic", dets, frame)
        elif now - ev["last_hit"] >= END_AFTER_S:
            self.close_event()

    def open_event(self, now, dets, frame):
        start = now_local()
        conf = max(d[0] for d in dets)
        cur = self.store.execute("INSERT INTO events (cam, start, max_persons, max_conf) VALUES (?, ?, ?, ?)",
                                 (self.name, start.isoformat(timespec="seconds"), len(dets), conf))
        self.event = {"id": cur.lastrowid, "start": start, "last_hit": now, "last_hit_wall": start,
                      "persons": len(dets), "max_persons": len(dets), "max_conf": conf, "last_snap": 0.0}
        log.info("%s event %d start: %d person(s), conf %.2f", self.name, self.event["id"], len(dets), conf)
        self.ha.set(self, "on", max_persons=len(dets), event_start=start.isoformat(timespec="seconds"))
        self.snapshot("start", dets, frame)

    def close_event(self):
        ev, self.event = self.event, None
        self.recent.clear()
        self.pending = False
        end = ev["last_hit_wall"].isoformat(timespec="seconds")
        self.store.execute("UPDATE events SET end = ?, max_conf = ? WHERE id = ?", (end, ev["max_conf"], ev["id"]))
        log.info("%s event %d end (%s - %s, max %d)", self.name, ev["id"],
                 ev["start"].strftime("%H:%M:%S"), end[11:], ev["max_persons"])
        self.ha.set(self, "off", max_persons=0, last_event_start=ev["start"].isoformat(timespec="seconds"),
                    last_event_end=end, last_snapshot=ev.get("last_snapshot", ""))

    def snapshot(self, reason, dets, frame):
        self.event["last_snap"] = time.monotonic()
        self.snapper.put((self, self.event, reason, dets, frame.to_image(), now_local()))


class QQNotifier(threading.Thread):
    """Sends an image with a caption to one QQ user through the official bot API (C2C)."""

    TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
    API = "https://api.sgroup.qq.com"

    def __init__(self):
        super().__init__(name="qq", daemon=True)
        self.jobs = queue.Queue(maxsize=10)
        self.token, self.expires = "", 0.0
        self.last_sent = {}

    @staticmethod
    def enabled():
        return bool(QQ_APP_ID and QQ_CLIENT_SECRET and QQ_OPENID and QQ_NOTIFY_CAMS)

    def notify(self, cam, text, image_path):
        now = time.monotonic()
        if cam not in QQ_NOTIFY_CAMS or now - self.last_sent.get(cam, -1e9) < QQ_COOLDOWN_S:
            return
        self.last_sent[cam] = now
        try:
            self.jobs.put_nowait((text, image_path))
        except queue.Full:
            log.warning("QQ queue full, dropped: %s", text)

    def post(self, url, body, headers=None):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=30).read() or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}") from None

    def api(self, path, body):
        if time.time() > self.expires - 60:
            r = self.post(self.TOKEN_URL, {"appId": QQ_APP_ID, "clientSecret": QQ_CLIENT_SECRET})
            self.token, self.expires = r["access_token"], time.time() + int(r["expires_in"])
        return self.post(self.API + path, body, {"Authorization": f"QQBot {self.token}"})

    def send(self, text, image_path=None):
        seq = int(time.time() * 1000) % 1_000_000_000
        if image_path:
            with open(image_path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            up = self.api(f"/v2/users/{QQ_OPENID}/files", {"file_type": 1, "file_data": data, "srv_send_msg": False})
            body = {"msg_type": 7, "media": {"file_info": up["file_info"]}, "content": text, "msg_seq": seq}
        else:
            body = {"msg_type": 0, "content": text, "msg_seq": seq}
        return self.api(f"/v2/users/{QQ_OPENID}/messages", body)

    def run(self):
        while True:
            text, image_path = self.jobs.get()
            try:
                self.send(text, image_path)
                log.info("QQ sent: %s", text.splitlines()[0])
            except Exception as e:
                log.warning("QQ image send failed (%r), sending text only", e)
                try:
                    self.send(text)
                except Exception as e2:
                    log.warning("QQ send failed: %r", e2)


class Snapper(threading.Thread):
    """Saves snapshots off the camera threads: the main stream's next key frame, else the sub-stream frame."""

    def __init__(self, detector, store, ha, qq=None):
        super().__init__(name="snapper", daemon=True)
        self.detector, self.store, self.ha, self.qq = detector, store, ha, qq
        self.jobs = queue.Queue(maxsize=20)
        self.font = ImageFont.load_default(size=28)
        self.small_font = ImageFont.load_default(size=14)

    def put(self, job):
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            log.warning("snapshot queue full, dropped %s", job[2])

    def hd_frame(self, url):
        ct = av.open(url, options=RTSP_OPTIONS, timeout=(10, 10))
        try:
            vs = ct.streams.video[0]
            vs.codec_context.skip_frame = "NONKEY"
            vs.codec_context.thread_count = 1
            deadline = time.monotonic() + 6
            for packet in ct.demux(vs):
                if time.monotonic() > deadline:
                    return None
                if packet.is_keyframe:
                    for f in packet.decode():
                        return f
        finally:
            ct.close()
        return None

    def run(self):
        while True:
            cam, ev, reason, dets, sub_img, ts = self.jobs.get()
            try:
                self.save(cam, ev, reason, dets, sub_img, ts)
            except Exception as e:
                log.warning("%s snapshot failed: %r", cam.name, e)

    def save(self, cam, ev, reason, dets, sub_img, ts):
        # The key frame comes 0-2 s after the sub-stream frame; keep the sub-stream
        # boxes when the detector misses the person there (partly in view, moved).
        img, hd = sub_img, 0
        t0 = time.monotonic()
        try:
            f = self.hd_frame(cam.main_url)
            if f is not None:
                h, w = input_shape(f.width, f.height)
                hd_dets = detect(self.detector.request(h, w), f, h, w)
                img, hd = f.to_image(), 1
                dets = hd_dets or dets
        except Exception as e:
            log.info("%s main stream snapshot failed, using sub-stream: %r", cam.name, e)
        grab_s = time.monotonic() - t0
        draw = ImageDraw.Draw(img)
        font = self.font if hd else self.small_font
        for conf, x1, y1, x2, y2 in dets:
            box = [x1 * img.width, y1 * img.height, x2 * img.width, y2 * img.height]
            draw.rectangle(box, outline="#ff2a2a", width=4 if hd else 2)
            draw.text((box[0] + 4, box[1] + 2), f"{conf:.2f}", fill="#ff2a2a", font=font)
        day = ts.date().isoformat()
        rel = f"{day}/{cam.name}_{ts:%H%M%S}_{reason}.jpg"
        os.makedirs(os.path.join(SNAP_DIR, day), exist_ok=True)
        img.save(os.path.join(SNAP_DIR, rel), quality=85)
        conf = max(d[0] for d in dets)
        self.store.execute(
            "INSERT INTO snapshots (event_id, cam, ts, reason, path, persons, conf, hd) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ev["id"], cam.name, ts.isoformat(timespec="seconds"), reason, rel, len(dets), conf, hd))
        ev["last_snapshot"] = f"{PUBLIC_URL}/snap/{rel}"
        if cam.event is ev:
            cam.ha.set(cam, "on", max_persons=ev["max_persons"], event_start=ev["start"].isoformat(timespec="seconds"),
                       last_snapshot=ev["last_snapshot"])
        log.info("%s snapshot %s (%s in %.1f s, %d person(s))", cam.name, rel, "1080p" if hd else "sub-stream",
                 grab_s, len(dets))
        if self.qq and reason == "start":
            link = f"\n记录：{PUBLIC_URL}/?date={day}&cam={cam.name}" if PUBLIC_URL else ""
            self.qq.notify(cam.name, f"{cam.label}有人 · {ts:%m-%d %H:%M:%S} · {len(dets)} 人{link}",
                           os.path.join(SNAP_DIR, rel))


PAGE_CSS = """
:root{--bg:#f6f7f9;--fg:#1d2330;--muted:#69707d;--card:#fff;--line:#e3e6eb;--accent:#d93b3b}
@media (prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e8eaee;--muted:#9aa1ad;--card:#1d2026;--line:#2c3038;--accent:#ff6b6b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:20px;margin:4px 0 12px}
nav{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:16px}
nav a,nav span{padding:4px 10px;border:1px solid var(--line);border-radius:6px;color:var(--fg);text-decoration:none;background:var(--card)}
nav span.on{border-color:var(--accent);color:var(--accent)}
.status{color:var(--muted);font-size:13px;margin-bottom:12px}
.ev{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin-bottom:12px}
.ev b{font-size:16px}.meta{color:var(--muted);font-size:13px;margin-left:8px}
.shots{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.shots a{display:block;width:240px;max-width:100%}.shots img{width:100%;border-radius:4px;display:block}
.shots small{color:var(--muted)}.empty{color:var(--muted);padding:24px 0}
"""
REASONS = {"start": "出现", "more": "人数增加", "periodic": "仍在"}


class Web(BaseHTTPRequestHandler):
    server_version = "person-watch"
    cams = []
    store = None

    def log_message(self, *args):
        pass

    def authorized(self):
        if not WEB_PASSWORD:
            return True
        want = "Basic " + base64.b64encode(f"{WEB_USER}:{WEB_PASSWORD}".encode()).decode()
        if self.headers.get("Authorization") == want:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="person-watch"')
        self.end_headers()
        return False

    def send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/health":
            return self.send(200, json.dumps(self.health(), ensure_ascii=False).encode(), "application/json")
        if not self.authorized():
            return
        if url.path.startswith("/snap/"):
            return self.snap(url.path[len("/snap/"):])
        if url.path == "/api/events":
            day = q.get("date", [now_local().date().isoformat()])[0]
            try:
                day = datetime.fromisoformat(day).date().isoformat()
            except ValueError:
                return self.send(400, b"bad date", "text/plain")
            return self.send(200, json.dumps(self.events(day, q.get("cam", [""])[0]), ensure_ascii=False).encode(),
                             "application/json")
        if url.path == "/":
            day = q.get("date", [now_local().date().isoformat()])[0]
            return self.send(200, self.page(day, q.get("cam", [""])[0]).encode(), "text/html; charset=utf-8")
        self.send(404, b"not found", "text/plain")

    def health(self):
        now = time.monotonic()
        return {c.name: {"online": bool(c.online) and now - c.last_frame < OFFLINE_AFTER_S,
                         "event": bool(c.event), **{k: round(v) for k, v in c.stats.items()}} for c in self.cams}

    def snap(self, rel):
        path = os.path.realpath(os.path.join(SNAP_DIR, rel))
        if not path.startswith(os.path.realpath(SNAP_DIR) + os.sep) or not os.path.isfile(path):
            return self.send(404, b"not found", "text/plain")
        with open(path, "rb") as f:
            self.send(200, f.read(), "image/jpeg")

    def events(self, day, cam=""):
        sql = "SELECT * FROM events WHERE start >= ? AND start < ?" + (" AND cam = ?" if cam else "") + " ORDER BY start DESC"
        nxt = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
        evs = self.store.query(sql, (day, nxt, cam) if cam else (day, nxt))
        for ev in evs:
            ev["snapshots"] = self.store.query("SELECT ts, reason, path, persons, hd FROM snapshots WHERE event_id = ? ORDER BY ts",
                                               (ev["id"],))
        return evs

    def page(self, day, cam):
        try:
            d = datetime.fromisoformat(day).date()
        except ValueError:
            d = now_local().date()
        labels = {c.name: c.label for c in self.cams}
        prev_d, next_d = d - timedelta(days=1), d + timedelta(days=1)
        cam_q = f"&cam={escape(cam)}" if cam else ""
        nav = [f'<a href="/?date={prev_d}{cam_q}">‹ {prev_d:%m-%d}</a>', f'<span class="on">{d:%Y-%m-%d}</span>']
        if next_d <= now_local().date():
            nav.append(f'<a href="/?date={next_d}{cam_q}">{next_d:%m-%d} ›</a>')
        nav.append(f'<a href="/?date={d}">全部</a>' if cam else '<span class="on">全部</span>')
        for c in self.cams:
            nav.append(f'<span class="on">{escape(c.label)}</span>' if cam == c.name else f'<a href="/?date={d}&cam={c.name}">{escape(c.label)}</a>')
        health = self.health()
        status = " · ".join(f"{escape(labels[n])}：{'有人' if h['event'] else ('在线' if h['online'] else '离线')}" for n, h in health.items())
        rows = []
        for ev in self.events(d.isoformat(), cam):
            start = ev["start"][11:19]
            end = ev["end"][11:19] if ev["end"] else "进行中"
            if ev["end"]:
                secs = (datetime.fromisoformat(ev["end"]) - datetime.fromisoformat(ev["start"])).total_seconds()
                dur = f"{int(secs // 60)} 分 {int(secs % 60)} 秒" if secs >= 60 else f"{int(secs)} 秒"
            else:
                dur = ""
            shots = "".join(
                f'<a href="/snap/{escape(s["path"])}" target="_blank"><img loading="lazy" src="/snap/{escape(s["path"])}">'
                f'<small>{s["ts"][11:19]} {REASONS.get(s["reason"], s["reason"])} · {s["persons"]} 人{"" if s["hd"] else " · 子码流"}</small></a>'
                for s in ev["snapshots"])
            rows.append(f'<div class="ev"><b>{escape(labels.get(ev["cam"], ev["cam"]))} {start} – {end}</b>'
                        f'<span class="meta">{dur} · 最多 {ev["max_persons"]} 人 · 置信度 {ev["max_conf"]:.2f}</span>'
                        f'<div class="shots">{shots}</div></div>')
        body = "".join(rows) or '<div class="empty">这一天没有记录。</div>'
        return (f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>有人记录</title>'
                f'<style>{PAGE_CSS}</style></head><body><main><h1>摄像头有人记录</h1><nav>{"".join(nav)}</nav>'
                f'<div class="status">{status} · 共 {len(rows)} 次</div>{body}</main></body></html>')


def main():
    os.nice(10)
    cams_cfg = parse_cams()
    if not cams_cfg:
        raise SystemExit("CAMS is empty")
    store, ha = Store(), HomeAssistant()
    detector = Detector(MODEL)
    qq = None
    if QQNotifier.enabled():
        qq = QQNotifier()
        qq.start()
        log.info("QQ push on for: %s", ", ".join(sorted(QQ_NOTIFY_CAMS)))
    snapper = Snapper(detector, store, ha, qq)
    snapper.start()
    cams = [Camera(n, label, sub, main, detector, store, ha, snapper) for n, label, sub, main in cams_cfg]
    for c in cams:
        c.start()
    threading.Thread(target=ha.heartbeat, name="ha-heartbeat", daemon=True).start()

    def housekeeping():
        while True:
            try:
                store.purge()
            except Exception as e:
                log.warning("purge failed: %r", e)
            for _ in range(60):
                time.sleep(60)
                for c in cams:
                    if c.online and time.monotonic() - c.last_frame >= OFFLINE_AFTER_S:
                        c.set_online(False)

    threading.Thread(target=housekeeping, name="housekeeping", daemon=True).start()
    Web.cams, Web.store = cams, store
    log.info("web on :%d, cameras: %s", PORT, ", ".join(f"{c.name}({c.label})" for c in cams))
    ThreadingHTTPServer(("0.0.0.0", PORT), Web).serve_forever()


if __name__ == "__main__":
    main()
