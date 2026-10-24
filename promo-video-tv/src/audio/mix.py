"""Assemble the soundtrack: voices, sound effects, what the TV itself plays, and the
score (ducked under speech).

Writes build/audio/mix.wav (48 kHz stereo float).
"""
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

import score
from synth import (SR, beep, chime, click, denied, filt, glitch, impact, n_of, noise, pad, pan, piano, place,
                   pop, reverb, sine, sub, tt, whoosh)

ROOT = Path(__file__).resolve().parents[2]
TL = score.TL
FPS = TL["fps"]
T, LT, SHOT, END = score.T, score.LT, score.SHOT, score.END
rng = np.random.default_rng(5)


# ---------------------------------------------------------------- extra sounds

def env_exp(dur, rate):
    return np.exp(-np.arange(n_of(dur)) / (rate * SR)).astype(np.float32)


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


def remote_click(vel=1.0):
    """A rubber-dome remote button: a dull snap and a tiny plastic rattle."""
    snap = filt(noise(0.012), "band", [1800, 6000]) * env_exp(0.012, 0.0018) * 0.9
    body = sine(320, 0.03) * env_exp(0.03, 0.004) * 0.3
    out = np.zeros(n_of(0.05), np.float32)
    out[: len(snap)] += snap
    out[: len(body)] += body
    return out * vel


def ui_tock(f=1500, vel=1.0):
    """The TV's own focus-move sound."""
    x = (sine(f, 0.045) + 0.4 * sine(f * 1.5, 0.045)) * env_exp(0.045, 0.008)
    return x * 0.18 * vel


def tv_on(vel=1.0):
    """Panel wake: a soft thump, a rising hum and a two-note boot chime."""
    out = np.zeros(n_of(2.0), np.float32)
    th = sub(40, 0.35, 0.7) * env_exp(0.35, 0.06)
    out[: len(th)] += th
    t = tt(0.6)
    hum = np.sin(2 * np.pi * np.cumsum(120 + 400 * t / 0.6) / SR) * np.sin(np.pi * t / 0.6) * 0.04
    j = n_of(0.05)
    out[j:j + len(hum)] += hum.astype(np.float32)
    ch = chime([79, 86], gap=0.12, vel=0.6, dur=1.3)
    j = n_of(0.4)
    out[j:j + len(ch)] += ch[: len(out) - j]
    return out * vel


def tv_off(vel=1.0):
    t = tt(0.5)
    x = np.sin(2 * np.pi * np.cumsum(900 * np.exp(-t * 6) + 200) / SR) * np.exp(-t * 8) * 0.12
    c = click(0.6)
    out = x.astype(np.float32)
    out[: len(c)] += c * 0.5
    return out * vel


def scan_sweep(dur=1.2, vel=1.0):
    t = tt(dur)
    f = 600 * (5000 / 600) ** (t / dur)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / dur) ** 2 * 0.05
    sh = filt(noise(dur), "high", 5000) * np.sin(np.pi * t / dur) ** 2 * 0.03
    return (x + sh).astype(np.float32) * vel


def type_burst(vel=1.0):
    out = np.zeros(n_of(0.4), np.float32)
    for k in range(6):
        c = filt(noise(0.008), "high", 3500) * env_exp(0.008, 0.0012) * 0.15
        j = n_of(k * 0.035)
        out[j:j + len(c)] += c
    p = pop(1600, 0.8)
    j = n_of(0.24)
    out[j:j + len(p)] += p
    return out * vel


# ---------------------------------------------------------------- what the TV plays

def tv_speaker(x, level):
    """Through a TV's small speakers across the room."""
    y = filt(x, "band", [140, 6500])
    return reverb(y, wet=0.3, length=1.2, decay=0.8, seed=12) * level


def foghorn(dur=3.0):
    t = tt(dur)
    env = np.clip(t / 0.6, 0, 1) * np.clip((dur - t) / 1.2, 0, 1)
    x = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate((92, 138, 184, 276)))
    x = x * (0.85 + 0.15 * np.sin(2 * np.pi * 4.5 * t)) * env
    return filt(x.astype(np.float32), "low", 700) * 0.35


def drama_harbor(dur, seed=1):
    """Episode 2: water lapping, a distant foghorn, a sparse sad piano."""
    t = tt(dur)
    water = filt(noise(dur), "low", 900) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.35 * t + 1.0)) ** 2 * 0.05
    out = water.astype(np.float32)
    r = np.random.default_rng(seed)
    for t0 in np.arange(1.2, dur, 7.5):
        fh = foghorn(3.2)
        j = n_of(t0)
        out[j:j + len(fh)] += fh[: len(out) - j]
    melody = [62, 65, 69, 67, 65, 64, 62, 57]
    for i, t0 in enumerate(np.arange(0.4, dur, 1.6)):
        p = piano(melody[i % len(melody)], 2.4, 0.22 + 0.05 * r.random())
        j = n_of(t0)
        out[j:j + len(p)] += p[: len(out) - j]
    bed = pad([50, 57, 60, 65], dur, cutoff=600, attack=1.0, release=1.0)[: len(out)].mean(axis=1) * 0.3
    out[: len(bed)] += bed
    return out


def drama_rain(dur):
    """Episode 3: rain on a street, a buzzing sign."""
    t = tt(dur)
    rain = filt(noise(dur), "band", [900, 7000]) * 0.06
    drops = np.zeros(n_of(dur), np.float32)
    for _ in range(int(dur * 50)):
        i = rng.integers(0, len(drops) - 2000)
        d = filt(noise(0.02), "high", 3000) * env_exp(0.02, 0.002) * rng.uniform(0.05, 0.2)
        drops[i:i + len(d)] += d
    buzz = (np.sign(np.sin(2 * np.pi * 120 * t)) * 0.004 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.3 * t))).astype(np.float32)
    return (rain + drops + buzz).astype(np.float32)


def tv_song(dur):
    """《晚风慢慢》: a gentle tune the music app plays (F major, 80 BPM)."""
    beat = 0.75
    out = np.zeros(n_of(dur + 3), np.float32)
    mel = [(0, 72, 1), (1, 74, 1), (2, 76, 2), (4, 77, 1), (5, 76, 1), (6, 74, 2), (8, 72, 1), (9, 69, 1), (10, 72, 2),
           (12, 74, 1), (13, 72, 1), (14, 70, 2)]
    for b, m, d in mel:
        if b * beat >= dur:
            break
        p = piano(m, d * beat + 1.0, 0.5)
        j = n_of(b * beat)
        out[j:j + len(p)] += p
    for k, ch in enumerate([[53, 60, 64, 69], [50, 57, 62, 65], [46, 53, 58, 62], [48, 55, 60, 64]]):
        t0 = k * 4 * beat
        if t0 >= dur:
            break
        for i, m in enumerate(ch):
            p = piano(m - 12 if i == 0 else m, 3.0, 0.25)
            j = n_of(t0 + i * 0.12)
            out[j:j + len(p)] += p
    return out[: n_of(dur)]


def tv_audio():
    """Everything that comes out of the TV, faded at the shot boundaries."""
    b = np.zeros((n_of(END + 4), 2), np.float32)

    def put(x, t0, t1, level, fade_in=0.4, fade_out=0.35):
        n = min(len(x), n_of(t1 - t0))
        x = x[:n].copy()
        e = np.minimum(1, np.arange(n) / max(1, n_of(fade_in))) * np.minimum(1, (n - np.arange(n)) / max(1, n_of(fade_out)))
        place(b, tv_speaker(x * e, level), t0)
    # Opening: episode 1 for a moment, then episode 2 under the title.
    s3e = T("S04")
    put(drama_harbor(T("S02", "ep2") - T("S02", "play") + 0.2, seed=2), T("S02", "play"), T("S02", "ep2"), 0.5, 0.2, 0.1)
    put(drama_harbor(s3e - T("S02", "ep2"), seed=3), T("S02", "ep2"), s3e + 0.2, 0.55, 0.15, 1.2)
    # The 37th press starts episode 2.
    last = SHOT["S05"]["start"] / FPS + SHOT["S05"]["marks"]["last"]
    put(drama_harbor(T("S06") - last + 0.3, seed=4), last + 0.1, T("S06") + 0.3, 0.35, 0.3, 0.6)
    # Replay: episode 1 from the play click, episode 2 after the switch.
    s13, s14 = T("S13"), T("S14")
    put(drama_harbor(s14 - T("S13", "k4"), seed=5), T("S13", "k4") + 0.35, s14 + 0.3, 0.45, 0.3, 0.4)
    # Over the shoulder: episode 2, then episode 3 in the rain, a little quieter after "声音小一点".
    nxt = T("S14", "next") + 0.35
    vol = T("S14", "vol")
    put(drama_harbor(nxt - s14 + 0.4, seed=6), s14 - 0.2, nxt, 0.55, 0.4, 0.15)
    rain = drama_rain(T("S15") - nxt + 0.5)
    k = np.where(np.arange(len(rain)) / SR + nxt < vol, 1.0, 10 ** (-3.5 / 20)).astype(np.float32)
    k = np.convolve(k, np.ones(n_of(0.3)) / n_of(0.3), mode="same").astype(np.float32)
    put(rain * k, nxt, T("S15") + 0.3, 0.6, 0.2, 0.4)
    # The music app.
    a = T("S15", "all") + 0.4
    put(tv_song(T("S16") - a + 0.5), a, T("S16") + 0.4, 0.9, 0.6, 0.6)
    # Episode 3 until the TV goes to standby.
    off = T("S17", "off")
    put(drama_rain(off - T("S17") + 0.6), T("S17") - 0.3, off + 0.05, 0.4, 0.5, 0.1)
    return b


# ---------------------------------------------------------------- voices

def load_voice(lid):
    sr, x = wavfile.read(ROOT / "build" / "audio" / "voice" / f"{lid}.wav")
    assert sr == SR
    return x.astype(np.float32) / 32768.0


def voices():
    buf = np.zeros((n_of(END + 1), 2), np.float32)
    for s in TL["shots"]:
        for l in s["lines"]:
            x = load_voice(l["id"])
            role = l["role"]
            t0 = s["start"] / FPS + l["t"]
            if role == "narrator":
                y = pan(filt(x, "high", 70), 0) * 1.0
            elif role == "user":
                y = reverb(filt(x, "high", 100), wet=0.1, length=0.7, decay=0.45, seed=3) * 0.95
            elif role == "generic":
                z = filt(x, "band", [300, 3400])
                z = np.round(z * 48) / 48
                y = reverb(z, wet=0.18, length=0.8, decay=0.5, seed=6) * 0.95
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

    # Prologue: night room tone, the wake chime, thread, IR, TV on, 小七 working the menus.
    s1 = T("S01")
    t = tt(T("S04") - s1)
    tone = filt(noise(T("S04") - s1), "low", 400) * 0.01 + (np.sin(2 * np.pi * 50 * t) * 0.002).astype(np.float32)
    place(b, pan(tone.astype(np.float32), 0), s1, 1.0)
    u, d = LT("S01", "U01")
    place(b, reverb(warm, 0.3), u + d + 0.05, 0.4)
    th, arr = T("S02", "thread"), T("S02", "arrive")
    place(b, sparkle_whoosh(0.9, 0.9), th, 0.55)
    place(b, bloop(660), arr, 0.45)
    place(b, blips(T("S02", "ir") - arr + 0.2, rate=18, seed=4), arr, 0.5)
    place(b, reverb(beep((3136,), 0.6), 0.2), T("S02", "ir"), 0.35)
    place(b, reverb(tv_on(), 0.3, length=1.5, decay=1.0), T("S02", "tv_on"), 0.55)
    for k, mk in enumerate(("app", "search", "play", "ep", "ep2")):
        place(b, zap(700, 2400, 0.3, 0.7), T("S02", mk) - 0.4, 0.35)
        place(b, tv_speaker(ui_tock(1300 + 120 * k), 1.0), T("S02", mk), 0.9)
    place(b, reverb(chime([84, 91], gap=0.06, vel=0.5, dur=1.0), 0.3), T("S02", "verify"), 0.3)

    # Pain 1: the cloud speaker switches the TV on, and that's all.
    u, d = LT("S04", "U03")
    place(b, reverb(cold, 0.3), u + d + 0.1, 0.32)
    place(b, reverb(beep((3136,), 0.5), 0.2), T("S04", "ir"), 0.3)
    place(b, reverb(tv_on(0.8), 0.3, length=1.5, decay=1.0), T("S04", "tv_on"), 0.45)
    u, d = LT("S04", "U04")
    place(b, reverb(cold, 0.3), u + d + 0.1, 0.32)
    place(b, glitch(0.4, seed=11), T("S04", "fail") + 0.1, 0.45)
    place(b, denied(), T("S04", "fail") + 0.15, 0.5)
    place(b, thud, T("S04", "card"), 0.4)
    place(b, glitch(0.3, seed=5), T("S04", "card") + 0.05, 0.3)
    # Pain 2: every press -- the button and the TV's tock.
    s5 = T("S05")
    for i, (pt, key) in enumerate(SHOT["S05"]["data"]["presses"]):
        place(b, pan(remote_click(0.9 + 0.2 * rng.random()), -0.15), s5 + pt, 0.8)
        place(b, tv_speaker(ui_tock(1700 if key == "ok" else 1350), 1.0), s5 + pt + 0.04, 0.8)
    place(b, thud, T("S05", "card"), 0.4)
    # Pain 3: three TVs answer in three ways; the speaker only clicks them on and off.
    for k, f in zip(("a", "b", "c"), ((1047, 1319), (880, 1175), (659, 523))):
        place(b, reverb(beep(f, 0.7), 0.3), T("S06", k), 0.35)
    for i in range(3):
        place(b, zap(1200, 500, 0.4, 0.6), T("S06", "c") + 0.15 * i, 0.3)
    place(b, thud, T("S06", "card"), 0.4)
    col = T("S07", "collapse")
    place(b, whoosh(0.8, 4000, 200, rev=True), col - 0.6, 0.45)

    # The turn.
    s8 = T("S08")
    place(b, whoosh(1.6, 300, 6000, 0.8), s8 + 0.3, 0.42)
    place(b, reverb(tv_on(), 0.35, length=1.8, decay=1.2), T("S08", "wake"), 0.45)
    place(b, scan_sweep(1.6, 0.9), T("S08", "scan"), 0.45)
    place(b, sparkle_whoosh(1.2, 0.6), T("S08", "thread"), 0.35)

    # Eyes and hands.
    for k in ("l1", "l2", "l3"):
        place(b, studio_light(0.9), T("S09", k), 0.65)
    place(b, scan_sweep(1.2), T("S10", "scan"), 0.55)
    place(b, reverb(chime([84, 88], gap=0.05, vel=0.5, dur=1.0), 0.3), T("S10", "scan") + 1.2, 0.3)
    place(b, type_burst(), T("S11", "type") + 0.05, 0.6)
    place(b, reverb(pop(1300), 0.3), T("S11", "click"), 0.5)
    place(b, remote_click(0.7), T("S11", "keys"), 0.6)
    place(b, remote_click(0.7), T("S11", "keys") + 0.45, 0.6)
    place(b, reverb(pop(900), 0.3), T("S11", "media"), 0.45)
    for k in ("n1", "n2", "n3"):
        place(b, reverb(pop(1100), 0.3), T("S12", k), 0.42)
    place(b, reverb(sub(38, 1.6, 0.8), 0.3), T("S12", "lan"), 0.4)

    # Demos.
    for i in range(1, 7):
        place(b, reverb(pop(1000 + 90 * i, 0.8), 0.3), T("S13", f"k{i}") + 0.25, 0.4)
    place(b, reverb(tv_on(0.7), 0.3, length=1.5, decay=1.0), T("S13", "k1") + 0.15, 0.4)
    place(b, reverb(chime([84, 91], gap=0.06, vel=0.5, dur=1.0), 0.3), T("S13", "k6"), 0.32)
    for mk in ("seek", "next", "vol"):
        u = T("S14", mk)
        place(b, tv_speaker(ui_tock(1500), 1.0), u, 0.8)
        place(b, reverb(warm, 0.3), u - 0.25, 0.22)
    for mk in ("app", "daily", "all"):
        place(b, reverb(pop(1250), 0.3), T("S15", mk), 0.38)
        place(b, tv_speaker(ui_tock(1450), 1.0), T("S15", mk) + 0.3, 0.8)
    place(b, reverb(pop(1250), 0.3), T("S16", "app"), 0.38)
    place(b, reverb(pop(1350), 0.3), T("S16", "click"), 0.38)
    place(b, type_burst(), T("S16", "type"), 0.6)
    place(b, whoosh(0.6, 800, 3000, 0.5), T("S16", "enter"), 0.3)
    place(b, reverb(tv_off(), 0.3, length=1.4, decay=0.9), T("S17", "off"), 0.5)

    # The museum: a quiet hall, a glassy shimmer when the remote retires.
    s18 = T("S18")
    hall = filt(noise(T("S19") - s18 + 1), "low", 300) * 0.012
    place(b, reverb(hall, 0.6, length=3.0, decay=2.5), s18, 1.0)
    place(b, sparkle_whoosh(2.2, 0.5), T("S18", "retire") - 0.3, 0.35)
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
    tv = tv_audio()
    n = n_of(END)
    v, m, fx, tv = v[:n], np.pad(m, ((0, max(0, n - len(m))), (0, 0)))[:n], fx[:n], tv[:n]
    m *= 0.08 / (np.sqrt(np.mean(m ** 2)) + 1e-9)
    duck = duck_gain(v)[:, None]
    m *= duck
    tv *= 0.55 + 0.45 * duck
    mix = v + m + fx * 0.8 + tv * 0.8
    mix = np.tanh(mix * 1.1) / 1.1
    out = ROOT / "build" / "audio" / "mix.wav"
    wavfile.write(out, SR, mix.astype(np.float32))
    for name, x in (("voice", v), ("music", m), ("sfx", fx), ("tv", tv), ("mix", mix)):
        print(f"{name:6} rms {20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9):6.1f} dB  peak {np.max(np.abs(x)):.2f}")
    print("->", out)


if __name__ == "__main__":
    main()
