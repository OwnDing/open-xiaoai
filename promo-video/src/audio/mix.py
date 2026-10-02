"""Assemble the soundtrack: voices, sound effects and the score (ducked under speech).

Writes build/audio/mix.wav (48 kHz stereo float).
"""
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

import score
from synth import (SR, beep, chime, click, denied, filt, glitch, impact, motor, n_of, pan, place, pop,
                   reverb, sub, warn_tone, whoosh)

ROOT = Path(__file__).resolve().parents[2]
TL = score.TL
FPS = TL["fps"]
META = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
T = score.T
SHOT = score.SHOT
END = score.END


def line_start(sid, lid):
    s = SHOT[sid]
    l = next(x for x in s["lines"] if x["id"] == lid)
    return s["start"] / FPS + l["t"], l["dur"]


def load_voice(lid):
    sr, x = wavfile.read(ROOT / "build" / "audio" / "voice" / f"{lid}.wav")
    assert sr == SR
    return x.astype(np.float32) / 32768.0


def voices():
    buf = np.zeros((n_of(END + 1), 2), np.float32)
    room = {}
    for s in TL["shots"]:
        for l in s["lines"]:
            x = load_voice(l["id"])
            role = l["role"]
            t0 = s["start"] / FPS + l["t"]
            if role == "narrator":
                y = pan(filt(x, "high", 70), 0) * 1.0
            elif role == "user":
                y = reverb(filt(x, "high", 100), wet=0.1, length=0.7, decay=0.45, seed=3) * 0.95
            else:
                # The speaker's own voice: a little band-limited and in the room.
                y = reverb(filt(x, "band", [150, 9000]), wet=0.16, length=0.9, decay=0.6, seed=4) * 0.92
            place(buf, y, t0)
            room[l["id"]] = t0
    return buf


def sfx():
    b = np.zeros((n_of(END + 3), 2), np.float32)
    cold_chime = chime([81, 88], gap=0.08, vel=0.8, dur=1.4)
    warm_chime = chime([74, 78, 81], gap=0.07, vel=0.8, dur=1.6)
    thud = impact(0.45)

    # Pain points.
    for sid, uid in (("S03", "U01"), ("S04", "U02")):
        t0, _ = line_start(sid, uid)
        if uid == "U01":
            place(b, reverb(cold_chime, 0.3), t0 + 0.8, 0.35)
        place(b, glitch(0.4, seed=hash(sid) % 100), T(sid, "fail") + 0.15, 0.45)
        place(b, denied(), T(sid, "fail") + 0.2, 0.5)
        place(b, thud, T(sid, "card"), 0.35)
        place(b, glitch(0.3, seed=5), T(sid, "card") + 0.05, 0.35)
    s5 = T("S05", "silos")
    for i in range(8):
        place(b, pop(1000 + 90 * (i % 4)), s5 + i * 0.18, 0.5)
    t_xa = T("S05") + next(l for l in SHOT["S05"]["lines"] if l["id"] == "N03")["t"] + \
        next(w["t"] for w in META["N03"]["words"] if w["text"].startswith("小"))
    for i, k in enumerate([3, 4, 5, 6, 7]):
        place(b, denied(0.7), t_xa + 0.1 + k * 0.06, 0.35)
    place(b, thud, T("S05", "card"), 0.35)
    place(b, glitch(0.3, seed=9), T("S05", "card") + 0.05, 0.35)
    place(b, glitch(0.7, seed=12), T("S06", "collapse") - 0.3, 0.55)
    place(b, whoosh(0.8, 3000, 200, rev=True), T("S06", "collapse") - 0.2, 0.5)
    place(b, sub(26, 1.2), T("S06", "collapse") + 0.4, 0.5)

    # Reveal.
    place(b, whoosh(1.5, 400, 5000), T("S07") + 0.1, 0.55)
    place(b, whoosh(0.9, 800, 3000), T("S08"), 0.4)
    for side in ("left", "right"):
        for i in range(4):
            place(b, pop(900 + 120 * i, 0.8), T("S08", side) + 0.5 + i * 0.12, 0.35)
    place(b, reverb(warm_chime, 0.3), T("S08", "wake") - 0.3, 0.45)

    # Architecture.
    for i, m in enumerate(["n_voice", "n_asr", "n_hermes", "n_ha", "n_devices"]):
        place(b, pop(800 + 150 * i, 1.0), T("S09", m), 0.5)
        place(b, whoosh(0.5, 1500, 5000, 0.5), T("S09", m) + 0.05, 0.25)
    for i in range(4):
        place(b, pop(1600, 0.6), T("S09", "n_think") + i * 0.15, 0.3)
    place(b, chime([86, 90], gap=0.05, vel=0.6, dur=1.0), T("S09", "n_login"), 0.35)
    for i in range(4):
        place(b, pop(1300 + 80 * i, 0.6), T("S09", "n_mijia") + i * 0.12, 0.3)
    for i in range(3):
        place(b, pop(1300 + 80 * i, 0.6), T("S09", "n_other") + i * 0.12, 0.3)

    # Demos.
    t0, _ = line_start("S10", "U04")
    place(b, reverb(warm_chime, 0.3), t0 + 0.45, 0.35)
    place(b, reverb(beep((2093, 2637)), 0.2), T("S10", "ac") + 0.2, 0.55)
    place(b, pop(1200), T("S10", "ac") + 0.3, 0.4)
    place(b, chime([81, 86], gap=0.08, vel=0.6, dur=1.2), T("S10", "remind"), 0.35)
    place(b, click(), T("S11", "light_off"), 0.9)
    place(b, motor(2.6), T("S11", "curtain"), 0.45)
    place(b, pop(1200), T("S11", "light_off") + 0.15, 0.4)
    place(b, pop(1300), T("S11", "curtain") + 0.55, 0.4)
    place(b, whoosh(1.2, 5000, 300, rev=True), T("S12") - 0.6, 0.45)
    t0, _ = line_start("S12", "U06")
    place(b, reverb(warm_chime, 0.3), t0 + 0.35, 0.35)
    place(b, reverb(chime([79, 83, 86, 91, 95], gap=0.06, vel=0.7, dur=1.8), 0.4), T("S12", "memory"), 0.45)
    place(b, whoosh(1.2, 300, 2000), T("S13") - 0.3, 0.35)
    t0, _ = line_start("S13", "U07")
    place(b, reverb(warm_chime, 0.3), t0 + 0.4, 0.35)
    place(b, click(0.9), T("S13", "study_off"), 0.8)
    place(b, click(0.9), T("S13", "living_off"), 0.8)
    place(b, click(0.7), T("S13", "living_off") + 0.35, 0.6)
    place(b, reverb(beep((2093, 2637)), 0.2), T("S13", "ac25"), 0.45)
    place(b, reverb(warn_tone(), 0.2), T("S13", "window"), 0.5)

    # Montage cards.
    for i, m in enumerate(["card0", "card1", "card2", "card3"]):
        place(b, whoosh(0.6, 600, 4000, 0.7), T("S14", m) - 0.15, 0.3)
    return b


def duck_gain(voice, depth=0.55):
    """Music gain that dips while anyone speaks (50 ms attack, 450 ms release)."""
    x = np.abs(voice).max(axis=1)
    hop = SR // 100
    n = len(x) // hop
    env = x[: n * hop].reshape(n, hop).max(axis=1)
    env = (env > 0.02).astype(np.float32)
    g = np.ones(n, np.float32)
    level = 0.0
    for i in range(n):
        target = env[i]
        coef = 0.35 if target > level else 0.022
        level += (target - level) * coef
        g[i] = 1 - depth * level
    g = np.repeat(g, hop)
    return np.pad(g, (0, len(voice) - len(g)), constant_values=1.0)


def main():
    v = voices()
    m = score.build()
    fx = sfx()
    n = n_of(END)
    v, m, fx = v[:n], np.pad(m, ((0, max(0, n - len(m))), (0, 0)))[:n], fx[:n]
    # Balance: music bed around -24 dB RMS before ducking, voices on top.
    m *= 0.075 / (np.sqrt(np.mean(m ** 2)) + 1e-9)
    m *= duck_gain(v)[:, None]
    mix = v + m + fx * 0.8
    mix = np.tanh(mix * 1.1) / 1.1
    out = ROOT / "build" / "audio" / "mix.wav"
    wavfile.write(out, SR, mix.astype(np.float32))
    for name, x in (("voice", v), ("music", m), ("sfx", fx), ("mix", mix)):
        print(f"{name:6} rms {20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9):6.1f} dB  peak {np.max(np.abs(x)):.2f}")
    print("->", out)


if __name__ == "__main__":
    main()
