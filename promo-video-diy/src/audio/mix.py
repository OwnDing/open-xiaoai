"""Assemble the soundtrack: voices, sound effects and the score (ducked under speech).

Writes build/audio/mix.wav (48 kHz stereo float).
"""
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

import score
from synth import (SR, beep, chime, click, denied, filt, glitch, impact, motor, n_of, noise, pan, place, pop,
                   reverb, sine, sub, tt, warn_tone, whoosh)

ROOT = Path(__file__).resolve().parents[2]
TL = score.TL
FPS = TL["fps"]
META = json.loads((ROOT / "build" / "audio" / "voice" / "meta.json").read_text())
T, LT = score.T, score.LT
SHOT = score.SHOT
END = score.END
rng = np.random.default_rng(5)


# ---------------------------------------------------------------- extra sounds

def env_exp(dur, rate):
    return np.exp(-np.arange(n_of(dur)) / (rate * SR)).astype(np.float32)


def rain(dur):
    x = filt(noise(dur), "band", [900, 7000]) * 0.08
    drops = np.zeros(n_of(dur), np.float32)
    for _ in range(int(dur * 40)):
        i = rng.integers(0, len(drops) - 2000)
        d = filt(noise(0.02), "high", 3000) * env_exp(0.02, 0.002) * rng.uniform(0.05, 0.25)
        drops[i:i + len(d)] += d
    return filt(x + drops, "low", 9000)


def door():
    """Smart lock chirp, latch, door swing, soft close."""
    out = np.zeros(n_of(2.2), np.float32)
    lock = beep((1568, 2093), 0.7)
    out[: len(lock)] += lock * 0.7
    latch = click(1.0)
    j = n_of(0.45)
    out[j:j + len(latch)] += latch
    swing = filt(noise(0.9), "band", [120, 600]) * np.sin(np.linspace(0, np.pi, n_of(0.9))) * 0.12
    j = n_of(0.6)
    out[j:j + len(swing)] += swing
    thud = sub(40, 0.4, 0.6) * env_exp(0.4, 0.06)
    j = n_of(1.6)
    out[j:j + len(thud)] += thud
    return out


def step(vel=1.0):
    return (filt(noise(0.12), "low", 700) * env_exp(0.12, 0.02) * 0.35 + sub(36, 0.12, 0.3) * env_exp(0.12, 0.03)) * vel


def sparkle_whoosh(dur=1.0, vel=1.0):
    w = whoosh(dur, 500, 6000, vel * 0.8)
    t = tt(dur)
    shim = sum(np.sin(2 * np.pi * f * t) * (0.5 + 0.5 * np.sin(2 * np.pi * (3 + i) * t)) for i, f in enumerate((2637, 3136, 3520, 4186)))
    shim = shim * np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2 * 0.03 * vel
    return w + pan(shim.astype(np.float32), 0)


def bloop(f=880, vel=1.0):
    t = tt(0.25)
    x = np.sin(2 * np.pi * np.cumsum(f * (1 + 0.6 * np.exp(-t * 20))) / SR) * np.exp(-t * 14)
    return x.astype(np.float32) * 0.3 * vel


def zap(f0=600, f1=3000, dur=0.35, vel=1.0):
    t = tt(dur)
    f = f0 * (f1 / f0) ** (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / dur) ** 2
    return x.astype(np.float32) * 0.12 * vel


def data_hum(dur, vel=1.0):
    t = tt(dur)
    hum = sum(np.sin(2 * np.pi * 100 * k * t) / k for k in (1, 2, 3, 5))
    buzz = filt(noise(dur), "band", [2000, 6000]) * (0.5 + 0.5 * np.sin(2 * np.pi * 7 * t))
    x = (hum * 0.05 + buzz * 0.04) * (t / dur) ** 1.5
    return x.astype(np.float32) * vel


def blips(dur, rate=14, vel=1.0, seed=3):
    r = np.random.default_rng(seed)
    out = np.zeros(n_of(dur), np.float32)
    for _ in range(int(dur * rate)):
        i = r.integers(0, max(1, len(out) - 4000))
        b = sine(r.choice([1760, 2093, 2349, 2637, 3136]), 0.04) * env_exp(0.04, 0.008) * r.uniform(0.02, 0.06)
        out[i:i + len(b)] += b
    return out * vel


def studio_light(vel=1.0):
    t = tt(1.2)
    clunk = filt(noise(0.05), "low", 1500) * env_exp(0.05, 0.01) * 0.6
    hum = (np.sin(2 * np.pi * 60 * t) + 0.3 * np.sin(2 * np.pi * 120 * t)) * np.exp(-t * 2.5) * 0.08
    out = hum.astype(np.float32)
    out[: len(clunk)] += clunk
    return out * vel


def washer_rumble(dur):
    t = tt(dur)
    x = filt(noise(dur), "low", 300) * (0.6 + 0.4 * np.sin(2 * np.pi * 0.8 * t)) * 0.12
    return x.astype(np.float32)


def washer_tune(vel=1.0):
    out = np.zeros(n_of(1.6), np.float32)
    for i, f in enumerate((1047, 1319, 1568, 2093)):
        b = (sine(f, 0.22) + 0.25 * sine(f * 2, 0.22)) * env_exp(0.22, 0.08)
        j = n_of(0.24 * i)
        out[j:j + len(b)] += b * 0.12
    return out * vel


def gas_hiss(dur):
    t = tt(dur)
    x = filt(noise(dur), "band", [600, 5000]) * (0.85 + 0.15 * np.sin(2 * np.pi * 3.1 * t)) * 0.035
    return x.astype(np.float32)


def cam_switch(vel=1.0):
    out = np.zeros(n_of(0.3), np.float32)
    b = sine(3000, 0.05) * env_exp(0.05, 0.01) * 0.15
    out[: len(b)] += b
    g = glitch(0.18, 0.8, seed=21)
    j = n_of(0.05)
    out[j:j + len(g)] += g
    return out * vel


def typing(dur, vel=1.0):
    out = np.zeros(n_of(dur), np.float32)
    for k in range(int(dur / 0.07)):
        c = filt(noise(0.01), "high", 3500) * env_exp(0.01, 0.0015) * 0.12
        j = n_of(k * 0.07 + rng.uniform(0, 0.02))
        out[j:j + len(c)] += c
    return out * vel


def pencil(dur):
    t = tt(dur)
    x = filt(noise(dur), "band", [2500, 8000]) * (0.5 + 0.5 * np.sin(2 * np.pi * 6 * t)) ** 2 * 0.02
    return x.astype(np.float32)


# ---------------------------------------------------------------- voices

def load_voice(lid):
    sr, x = wavfile.read(ROOT / "build" / "audio" / "voice" / f"{lid}.wav")
    assert sr == SR
    return x.astype(np.float32) / 32768.0


# Lines heard from another room (the living-room speaker announcing while we watch elsewhere).
FAR = {"Q05", "Q07"}


def voices():
    buf = np.zeros((n_of(END + 1), 2), np.float32)
    for s in TL["shots"]:
        for l in s["lines"]:
            x = load_voice(l["id"])
            role = l["role"]
            t0 = s["start"] / FPS + l["t"]
            if role == "narrator":
                y = pan(filt(x, "high", 70), 0) * 1.0
            elif role in ("user", "child"):
                y = reverb(filt(x, "high", 100), wet=0.1, length=0.7, decay=0.45, seed=3) * 0.95
            elif role == "generic":
                # A cheap cloud speaker: narrow band, a little crunchy.
                z = filt(x, "band", [300, 3400])
                z = np.round(z * 48) / 48
                y = reverb(z, wet=0.18, length=0.8, decay=0.5, seed=6) * 0.95
            else:
                if l["id"] in FAR:
                    y = reverb(filt(x, "band", [200, 5000]), wet=0.45, length=1.6, decay=1.1, seed=8) * 0.8
                else:
                    y = reverb(filt(x, "band", [140, 9500]), wet=0.16, length=0.9, decay=0.6, seed=4) * 0.92
            place(buf, y, t0)
    return buf


# ---------------------------------------------------------------- sound effects

def sfx():
    b = np.zeros((n_of(END + 4), 2), np.float32)
    warm = chime([74, 78, 81], gap=0.07, vel=0.8, dur=1.6)
    cold = chime([81, 88], gap=0.08, vel=0.8, dur=1.4)
    thud = impact(0.45)

    # Prologue.
    s1, s3 = T("S01"), T("S03")
    place(b, pan(rain(s3 - s1 + 1.0), 0), s1, 0.5)
    place(b, reverb(door(), 0.35, length=1.5, decay=1.0), T("S01", "door"), 0.6)
    for i in range(3):
        place(b, pan(step(0.8), -0.2 + 0.1 * i), T("S01", "door") + 1.9 + 0.42 * i, 0.5)
    u, d = LT("S01", "U01")
    place(b, reverb(warm, 0.3), u + d + 0.05, 0.4)
    th, arr, burst = T("S02", "thread"), T("S02", "arrive"), T("S02", "burst")
    place(b, sparkle_whoosh(1.1, 0.9), th, 0.6)
    place(b, bloop(660), arr, 0.5)
    place(b, blips(burst - arr, rate=20, seed=4), arr, 0.6)
    for i, k in enumerate(("pendant", "floor", "ac", "curtain")):
        place(b, zap(800, 2800, 0.3, 0.8), burst + 0.02 * i, 0.5)
    place(b, click(0.9), T("S02", "pendant"), 0.8)
    place(b, click(0.8), T("S02", "floor"), 0.7)
    place(b, reverb(beep((2093, 2637)), 0.2), T("S02", "ac"), 0.45)
    place(b, motor(2.8, 0.8), T("S02", "curtain"), 0.4)
    place(b, whoosh(2.4, 200, 1800, 0.6), s3 + 0.3, 0.4)

    # Pain.
    u, d = LT("S04", "U03")
    place(b, reverb(cold, 0.3), u + d + 0.1, 0.35)
    place(b, glitch(0.4, seed=11), T("S04", "fail") + 0.1, 0.45)
    place(b, denied(), T("S04", "fail") + 0.15, 0.5)
    place(b, thud, T("S04", "card"), 0.4)
    place(b, glitch(0.3, seed=5), T("S04", "card") + 0.05, 0.3)
    s5 = T("S05", "silos")
    for i in range(11):
        place(b, pop(900 + 80 * (i % 5)), s5 + 0.12 * i, 0.4)
    for j in range(7):
        place(b, glitch(0.12, 0.7, seed=30 + j), s5 + 1.3 + 0.18 * j + 0.6, 0.35)
    place(b, thud, T("S05", "card"), 0.4)
    rise, silence = T("S06", "rise"), T("S06", "silence")
    place(b, pan(data_hum(silence - rise), 0), rise, 0.8)
    place(b, pan(blips(silence - rise, rate=16, seed=7), 0), rise, 0.7)
    place(b, thud, T("S06", "card"), 0.45)
    col = T("S07", "collapse")
    place(b, whoosh(0.8, 4000, 200, rev=True), col - 0.6, 0.45)

    # Turn.
    s8 = T("S08")
    place(b, whoosh(1.6, 300, 6000, 0.8), s8 + 0.3, 0.45)
    place(b, sparkle_whoosh(2.0, 0.7), T("S08", "dome") - 0.2, 0.4)

    # Recipe.
    place(b, studio_light(), T("S09", "light_l"), 0.7)
    place(b, studio_light(0.9), T("S09", "light_r"), 0.7)
    place(b, reverb(bloop(520, 0.8), 0.4), T("S10", "mouth"), 0.5)
    place(b, whoosh(1.4, 400, 3000, 0.5), T("S11", "sweep"), 0.4)
    place(b, reverb(chime([79, 86], gap=0.06, vel=0.6, dur=1.2), 0.3), T("S11", "brain"), 0.35)
    for k in range(4):
        place(b, reverb(pop(1000 + 150 * k), 0.4), T("S12", f"l{k + 1}") + 0.3, 0.55)
        place(b, zap(400, 1200 + 300 * k, 0.4, 0.6), T("S12", f"l{k + 1}"), 0.4)
    place(b, zap(800, 4000, 0.6, 0.9), T("S12", "api"), 0.45)

    # Explainer.
    for k in ("wave", "wake", "asr", "api"):
        place(b, pop(1100), T("S13", k), 0.45)
    place(b, pan(typing(0.8), 0), T("S13", "text"), 0.8)
    place(b, reverb(sub(38, 1.6, 0.8), 0.3), T("S13", "wall"), 0.45)
    place(b, zap(700, 2600, 0.8, 0.9), T("S13", "send"), 0.45)
    place(b, zap(2600, 700, 0.8, 0.9), T("S13", "reply"), 0.45)
    for i in range(3):
        place(b, pop(1300 + 100 * i, 0.8), T("S13", "devices") + 0.15 * i, 0.4)

    # Demos.
    u, d = LT("S14", "U04")
    place(b, reverb(warm, 0.3), u + d + 0.05, 0.35)
    place(b, sparkle_whoosh(0.7, 0.6), T("S14", "thread"), 0.4)
    place(b, reverb(beep((2093, 2637)), 0.2), T("S14", "ac") + 0.15, 0.5)
    place(b, chime([81, 86], gap=0.08, vel=0.6, dur=1.2), T("S14", "remind"), 0.3)
    s15, done = T("S15"), T("S15", "done")
    place(b, pan(washer_rumble(done - s15 + 0.8), 0.3), s15, 0.9)
    place(b, whoosh(0.8, 300, 3000, 0.6), T("S15", "lapse"), 0.4)
    place(b, whoosh(0.8, 3000, 300, 0.6), done - 0.5, 0.35)
    place(b, reverb(washer_tune(), 0.3), done + 0.1, 0.6)
    place(b, sparkle_whoosh(1.0, 0.6), T("S15", "thread"), 0.4)
    place(b, reverb(warm, 0.5, length=1.6, decay=1.1), T("S15", "arrive"), 0.3)
    s16 = T("S16")
    place(b, whoosh(1.0, 5000, 300, rev=True), s16 - 0.5, 0.45)
    u, d = LT("S16", "U06")
    place(b, reverb(warm, 0.3), u - 0.3, 0.3)
    place(b, reverb(chime([79, 83, 86, 91], gap=0.06, vel=0.7, dur=1.6), 0.4), T("S16", "rule"), 0.4)
    place(b, sparkle_whoosh(1.3, 0.6), T("S16", "fly"), 0.4)
    place(b, bloop(740), T("S16", "fly") + 1.3, 0.45)

    # Extensions.
    s17, s18 = T("S17"), T("S18")
    place(b, pan(gas_hiss(s18 - s17 + 0.3), -0.1), s17, 1.0)
    place(b, cam_switch(), T("S17", "cam"), 0.6)
    place(b, reverb(beep((2637, 2637)), 0.2), T("S17", "detect"), 0.4)
    place(b, reverb(warn_tone(), 0.4, length=1.5, decay=1.0), T("S17", "alert") - 0.35, 0.4)
    place(b, pan(pencil(1.5), 0.2), s18 + 0.3, 0.8)
    place(b, cam_switch(0.9), T("S18", "detect"), 0.55)
    place(b, reverb(beep((2349, 2793)), 0.2), T("S18", "detect") + 0.35, 0.35)
    place(b, pop(1400, 0.7), T("S18", "count"), 0.35)

    # Vision.
    place(b, sparkle_whoosh(2.5, 0.5), T("S19") + 0.2, 0.3)
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
    m *= 0.08 / (np.sqrt(np.mean(m ** 2)) + 1e-9)
    m *= duck_gain(v)[:, None]
    mix = v + m + fx * 0.8
    mix = np.tanh(mix * 1.1) / 1.1
    out = ROOT / "build" / "audio" / "mix.wav"
    wavfile.write(out, SR, mix.astype(np.float32))
    wavfile.write(ROOT / "build" / "audio" / "music.wav", SR, m.astype(np.float32))
    for name, x in (("voice", v), ("music", m), ("sfx", fx), ("mix", mix)):
        print(f"{name:6} rms {20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9):6.1f} dB  peak {np.max(np.abs(x)):.2f}")
    print("->", out)


if __name__ == "__main__":
    main()
