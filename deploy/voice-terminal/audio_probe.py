"""Audio probe for the voice-terminal P0.5 hardware tests.

Uses sounddevice / PortAudio (WASAPI on Windows), the same stack the terminal
will use. Subcommands:

  devices   list audio devices (WASAPI only unless --all)
  play      play a speech WAV plus stepped test tones to one output
  record    record N seconds from one input to a WAV
  soak      keep one input open for N minutes, play scheduled clips to
            outputs, log levels / dropouts to <dir>/events.jsonl
  analyze   summarize a soak directory: did each clip reach the mic,
            which test tones came back
  bands     band-energy profile of a WAV (narrowband vs wideband capture)
  levels    RMS / peak / test-tone levels of a WAV over time

Devices are given as an index or a name; an exact name wins over a substring.
"""

import argparse
import ctypes
import json
import os
import queue
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

TONES_HZ = (1000, 3000, 5000, 7000, 10000)
TONE_SECONDS = 0.6
TONE_GAP_SECONDS = 0.4
SPEECH_PEAK = 0.5
TONE_AMPLITUDE = 0.25
STALL_SECONDS = 3.0
REOPEN_INTERVAL_SECONDS = 5.0

# PortAudio is not safe to re-initialize while another stream is opening.
pa_lock = threading.Lock()


def session_id():
    if os.name != "nt":
        return None
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def hostapi_name(dev):
    return sd.query_hostapis(dev["hostapi"])["name"]


def find_device(spec, kind, api="WASAPI"):
    key = "max_input_channels" if kind == "input" else "max_output_channels"
    devices = list(enumerate(sd.query_devices()))
    if str(spec).isdigit():
        idx = int(spec)
        if devices[idx][1][key] <= 0:
            raise SystemExit(f"device [{idx}] has no {kind} channels")
        return idx
    cands = [
        (i, d)
        for i, d in devices
        if d[key] > 0 and (not api or api.lower() in hostapi_name(d).lower())
    ]
    for matches in (
        [c for c in cands if c[1]["name"] == spec],
        [c for c in cands if spec in c[1]["name"]],
    ):
        if len(matches) == 1:
            return matches[0][0]
        if matches:
            names = ", ".join(f"[{i}] {d['name']}" for i, d in matches)
            raise SystemExit(f"{kind} device {spec!r} is ambiguous: {names}")
    names = ", ".join(f"[{i}] {d['name']}" for i, d in cands)
    raise SystemExit(f"{kind} device {spec!r} not found among: {names}")


def device_rate(idx):
    return int(sd.query_devices(idx)["default_samplerate"])


def refresh_devices():
    with pa_lock:
        sd._terminate()
        sd._initialize()


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"{path}: only 16-bit PCM WAV is supported")
        rate, channels = w.getframerate(), w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    samples = data.reshape(-1, channels).mean(axis=1) / 32768.0
    return samples.astype(np.float32), rate


def resample(x, src, dst):
    if src == dst or len(x) == 0:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def tone(freq, seconds, rate):
    t = np.arange(int(seconds * rate)) / rate
    y = TONE_AMPLITUDE * np.sin(2 * np.pi * freq * t)
    fade = min(len(y) // 2, int(0.01 * rate))
    ramp = np.linspace(0.0, 1.0, fade)
    y[:fade] *= ramp
    y[-fade:] *= ramp[::-1]
    return y.astype(np.float32)


def build_clip(speech, speech_rate, rate, with_tones=True):
    """Speech, then stepped tones; returns samples and tone offsets (s)."""
    parts, offsets, skipped = [], [], []
    length = 0
    if speech is not None:
        peak = float(np.max(np.abs(speech))) or 1.0
        parts += [resample(speech, speech_rate, rate) * (SPEECH_PEAK / peak)]
        parts += [np.zeros(int(0.4 * rate), dtype=np.float32)]
        length = sum(len(p) for p in parts)
    for freq in TONES_HZ if with_tones else ():
        if freq >= rate * 0.45:
            skipped.append(freq)
            continue
        offsets.append((length / rate, freq))
        parts += [tone(freq, TONE_SECONDS, rate)]
        parts += [np.zeros(int(TONE_GAP_SECONDS * rate), dtype=np.float32)]
        length = sum(len(p) for p in parts)
    return np.concatenate(parts), offsets, skipped


def play_clip(idx, speech, speech_rate, with_tones=True):
    """Blocking playback; returns a dict describing what was played."""
    dev = sd.query_devices(idx)
    rate = device_rate(idx)
    channels = min(2, dev["max_output_channels"])
    clip, offsets, skipped = build_clip(speech, speech_rate, rate, with_tones)
    frames = np.repeat(clip[:, None], channels, axis=1)
    info = {
        "output": dev["name"],
        "output_index": idx,
        "output_rate": rate,
        "output_channels": channels,
        "clip_seconds": round(len(clip) / rate, 3),
        "tone_offsets": offsets,
        "tones_skipped": skipped,
    }
    with pa_lock:
        stream = sd.OutputStream(
            device=idx, samplerate=rate, channels=channels, dtype="float32", latency="high"
        )
    with stream:
        stream.write(frames)
    return info


class Recorder:
    """Continuous mono S16 capture into a WAV with level / dropout stats."""

    def __init__(self, spec, path):
        self.spec = spec
        self.device = find_device(spec, "input")
        self.rate = device_rate(self.device)
        self.name = sd.query_devices(self.device)["name"]
        self.queue = queue.Queue(maxsize=4000)
        self.frames = 0
        self.overflows = 0
        self.dropped = 0
        self.max_gap = 0.0
        self.last_callback = None
        self.stream = None
        self.wav = wave.open(str(path), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.rate)

    def _callback(self, indata, frames, _time_info, status):
        now = time.monotonic()
        if self.last_callback is not None:
            self.max_gap = max(self.max_gap, now - self.last_callback)
        self.last_callback = now
        if status.input_overflow:
            self.overflows += 1
        try:
            self.queue.put_nowait(indata[:, 0].copy())
        except queue.Full:
            self.dropped += frames

    def open(self):
        with pa_lock:
            self.stream = sd.InputStream(
                device=self.device,
                samplerate=self.rate,
                channels=1,
                dtype="int16",
                callback=self._callback,
                latency="high",
            )
            self.stream.start()
        self.last_callback = time.monotonic()

    def close_stream(self):
        if self.stream is not None:
            try:
                self.stream.abort()
                self.stream.close()
            except sd.PortAudioError:
                pass
            self.stream = None

    def reopen(self):
        self.close_stream()
        refresh_devices()
        self.device = find_device(self.spec, "input")
        if device_rate(self.device) != self.rate:
            raise RuntimeError(f"input rate changed to {device_rate(self.device)}")
        self.open()

    def drain(self):
        """Write queued audio; yields each chunk for statistics."""
        while True:
            try:
                chunk = self.queue.get_nowait()
            except queue.Empty:
                return
            self.wav.writeframes(chunk.tobytes())
            self.frames += len(chunk)
            yield chunk

    def close(self):
        self.close_stream()
        for _ in self.drain():
            pass
        self.wav.close()


def dbfs(value):
    return round(float(20 * np.log10(max(float(value), 1e-9))), 2)


def run_soak(args):
    out = Path(args.dir)
    out.mkdir(parents=True, exist_ok=True)
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    events = (out / "events.jsonl").open("a", encoding="utf-8")
    lock = threading.Lock()

    def log(event):
        event["wall"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with lock:
            events.write(json.dumps(event, ensure_ascii=False) + "\n")
            events.flush()

    rec = Recorder(plan["input"], out / "mic.wav")
    log({
        "type": "start",
        "input": rec.name,
        "input_index": rec.device,
        "input_rate": rec.rate,
        "session_id": session_id(),
        "portaudio": sd.get_portaudio_version()[1],
        "minutes": plan["minutes"],
    })
    print(f"session={session_id()} input=[{rec.device}] {rec.name} @ {rec.rate} Hz", flush=True)

    # Expand the schedule: each clip at its "at" offset, then every "every" s.
    total = plan["minutes"] * 60
    schedule = []
    for clip in plan["clips"]:
        speech, speech_rate = read_wav(clip["speech"]) if clip.get("speech") else (None, 0)
        at = clip["at"]
        while at < total - 15:
            schedule.append((at, clip, speech, speech_rate))
            if not clip.get("every"):
                break
            at += clip["every"]
    schedule.sort(key=lambda item: item[0])

    stop = threading.Event()
    t0 = time.monotonic()

    def player():
        for at, clip, speech, speech_rate in schedule:
            if stop.wait(max(0.0, t0 + at - time.monotonic())):
                return
            event = {"type": "play", "label": clip["label"], "start_frame": rec.frames}
            try:
                idx = find_device(clip["output"], "output")
                event.update(play_clip(idx, speech, speech_rate, clip.get("tones", True)))
                event["ok"] = True
            except Exception as exc:  # report and keep soaking
                event.update(ok=False, error=f"{type(exc).__name__}: {exc}")
            event["end_frame"] = rec.frames
            log(event)
            status = "ok" if event["ok"] else event["error"]
            print(f"  play {clip['label']} -> {status}", flush=True)

    rec.open()
    threading.Thread(target=player, daemon=True).start()

    second_samples = []
    next_report = 10
    stalled_since = None
    last_reopen = 0.0
    try:
        while time.monotonic() - t0 < total:
            time.sleep(0.05)
            for chunk in rec.drain():
                second_samples.append(chunk)
                while sum(len(c) for c in second_samples) >= rec.rate:
                    flat = np.concatenate(second_samples).astype(np.float32) / 32768.0
                    sec, rest = flat[: rec.rate], flat[rec.rate:]
                    second_samples = [(rest * 32768.0).astype(np.int16)] if len(rest) else []
                    log({
                        "type": "level",
                        "t": round((rec.frames - len(rest)) / rec.rate, 2),
                        "rms": dbfs(np.sqrt(np.mean(sec ** 2))),
                        "peak": dbfs(np.max(np.abs(sec))),
                    })

            now = time.monotonic()
            if now - rec.last_callback > STALL_SECONDS:
                if stalled_since is None:
                    stalled_since = rec.last_callback
                    log({"type": "stall", "frame": rec.frames})
                    print(f"  input stalled at {rec.frames / rec.rate:.1f} s", flush=True)
                if now - last_reopen > REOPEN_INTERVAL_SECONDS:
                    last_reopen = now
                    try:
                        rec.reopen()
                        log({
                            "type": "reopened",
                            "frame": rec.frames,
                            "gap_seconds": round(now - stalled_since, 2),
                        })
                        print("  input reopened", flush=True)
                        stalled_since = None
                    except Exception as exc:
                        log({"type": "reopen_failed", "error": f"{type(exc).__name__}: {exc}"})

            elapsed = now - t0
            if elapsed >= next_report:
                next_report += 10
                deficit_ms = (elapsed * rec.rate - rec.frames) / rec.rate * 1000
                print(
                    f"{elapsed:7.1f}s frames={rec.frames} deficit={deficit_ms:.0f}ms "
                    f"overflows={rec.overflows} dropped={rec.dropped} "
                    f"max_gap={rec.max_gap * 1000:.0f}ms",
                    flush=True,
                )
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        rec.close()
        elapsed = time.monotonic() - t0
        log({
            "type": "end",
            "elapsed": round(elapsed, 2),
            "frames": rec.frames,
            "expected_frames": int(elapsed * rec.rate),
            "overflows": rec.overflows,
            "dropped": rec.dropped,
            "max_gap_ms": round(rec.max_gap * 1000, 1),
        })
        events.close()


def narrowband_db(x, rate, freq, window=0.2):
    """Level (dBFS) of a sine at freq inside each window of x."""
    n = int(window * rate)
    if len(x) < n:
        return np.array([])
    hops = range(0, len(x) - n + 1, n // 2)
    t = np.arange(n) / rate
    ref = np.exp(-2j * np.pi * freq * t) * np.hanning(n)
    scale = 2.0 / np.sum(np.hanning(n))
    return np.array([dbfs(abs(np.dot(x[h:h + n], ref)) * scale) for h in hops])


def run_analyze(args):
    out = Path(args.dir)
    mic, rate = read_wav(out / "mic.wav")
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    plays = [e for e in events if e["type"] == "play"]
    for e in events:
        if e["type"] in ("start", "end", "stall", "reopened", "reopen_failed"):
            print(json.dumps(e, ensure_ascii=False))

    busy = np.zeros(len(mic), dtype=bool)
    for p in plays:
        busy[p["start_frame"]:p["end_frame"] + rate] = True
    quiet = mic[~busy]
    print(f"\nmic {len(mic) / rate:.1f} s @ {rate} Hz; quiet-time RMS {dbfs(np.sqrt(np.mean(quiet ** 2))) if len(quiet) else 'n/a'} dBFS")

    for p in plays:
        head = f"{p['wall']} {p['label']:<10} -> {p.get('output', '?')}"
        if not p["ok"]:
            print(f"{head}: FAILED {p['error']}")
            continue
        seg = mic[p["start_frame"]:p["end_frame"] + rate // 2]
        print(f"{head} @ {p['output_rate']} Hz: mic RMS {dbfs(np.sqrt(np.mean(seg ** 2)))} dBFS during clip")
        found = []
        for offset, freq in p["tone_offsets"]:
            if freq >= rate * 0.45:
                found.append(f"{freq}:above-mic-band")
                continue
            start = p["start_frame"] + int((offset - 0.1) * rate)
            seg = mic[max(0, start):start + int((TONE_SECONDS + 0.8) * rate)]
            floor = narrowband_db(quiet[: rate * 30], rate, freq) if len(quiet) else np.array([-120.0])
            level = narrowband_db(seg, rate, freq)
            if not len(level):
                continue
            margin = float(np.max(level) - np.median(floor))
            found.append(f"{freq}:{'Y' if margin > 10 else 'n'}({margin:+.0f}dB)")
        if p["tones_skipped"]:
            found.append(f"skipped {p['tones_skipped']}")
        print("    tones " + " ".join(found))


def run_levels(args):
    x, rate = read_wav(args.wav)
    n = int(args.window * rate)
    print(f"{args.wav}: {len(x) / rate:.1f} s @ {rate} Hz")
    for start in range(0, len(x) - n + 1, n):
        seg = x[start:start + n]
        tones = " ".join(
            f"{freq}:{float(np.max(narrowband_db(seg, rate, freq))):6.1f}"
            for freq in TONES_HZ
            if freq < rate * 0.45
        )
        print(f"  {start / rate:6.1f}s rms {dbfs(np.sqrt(np.mean(seg ** 2))):6.1f} peak {dbfs(np.max(np.abs(seg))):6.1f}  {tones}")


def run_bands(args):
    x, rate = read_wav(args.wav)
    n = 512
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[:: n // 2]
    energy = np.mean(frames ** 2, axis=1)
    voiced = frames[energy >= np.quantile(energy, 0.7)]
    spectrum = np.mean(np.abs(np.fft.rfft(voiced * np.hanning(n), axis=1)) ** 2, axis=0)
    freqs = np.fft.rfftfreq(n, 1 / rate)
    ref = np.sum(spectrum[(freqs >= 300) & (freqs < 3400)])
    print(f"{args.wav}: {len(x) / rate:.1f} s @ {rate} Hz, voiced frames {len(voiced)}")
    edges = [0, 300, 3400, 4000, 5000, 6000, 7000, 8000, 12000, 16000, 24000]
    for lo, hi in zip(edges, edges[1:]):
        if lo >= rate / 2:
            break
        band = np.sum(spectrum[(freqs >= lo) & (freqs < hi)])
        print(f"  {lo:5d}-{hi:5d} Hz  {10 * np.log10(max(band, 1e-20) / ref):+7.1f} dB vs 300-3400 Hz")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("devices")
    p.add_argument("--all", action="store_true", help="include MME / DirectSound / WDM-KS")
    p = sub.add_parser("play")
    p.add_argument("--out", required=True)
    p.add_argument("--speech")
    p.add_argument("--no-tones", action="store_true")
    p = sub.add_parser("record")
    p.add_argument("--in", dest="input", required=True)
    p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--wav", required=True)
    p = sub.add_parser("soak")
    p.add_argument("--plan", required=True, help="JSON: input, minutes, clips[label, output, speech, at, every, tones]")
    p.add_argument("--dir", required=True)
    p = sub.add_parser("analyze")
    p.add_argument("--dir", required=True)
    p = sub.add_parser("bands")
    p.add_argument("wav")
    p = sub.add_parser("levels")
    p.add_argument("wav")
    p.add_argument("--window", type=float, default=0.5, help="seconds per line")
    args = parser.parse_args()

    if args.cmd == "devices":
        print(f"session={session_id()} {sd.get_portaudio_version()[1]}")
        for i, dev in enumerate(sd.query_devices()):
            api = hostapi_name(dev)
            if args.all or "WASAPI" in api:
                print(
                    f"[{i:2d}] {api:<20} in={dev['max_input_channels']} out={dev['max_output_channels']} "
                    f"rate={dev['default_samplerate']:.0f}  {dev['name']}"
                )
    elif args.cmd == "play":
        speech, speech_rate = read_wav(args.speech) if args.speech else (None, 0)
        info = play_clip(find_device(args.out, "output"), speech, speech_rate, not args.no_tones)
        print(json.dumps(info, ensure_ascii=False))
    elif args.cmd == "record":
        rec = Recorder(args.input, args.wav)
        print(f"session={session_id()} input=[{rec.device}] {rec.name} @ {rec.rate} Hz", flush=True)
        rec.open()
        t0 = time.monotonic()
        while time.monotonic() - t0 < args.seconds:
            time.sleep(0.05)
            for _ in rec.drain():
                pass
        rec.close()
        print(f"frames={rec.frames} ({rec.frames / rec.rate:.2f} s) overflows={rec.overflows} dropped={rec.dropped}")
    elif args.cmd == "soak":
        run_soak(args)
    elif args.cmd == "analyze":
        run_analyze(args)
    elif args.cmd == "bands":
        run_bands(args)
    elif args.cmd == "levels":
        run_levels(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
