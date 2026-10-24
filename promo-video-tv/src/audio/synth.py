"""Tiny numpy synthesizer: instruments, sound effects and a convolution reverb.

Everything returns float32 arrays at SR; stereo signals are shaped (n, 2).
"""
import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
rng = np.random.default_rng(7)


def n_of(dur):
    return max(1, int(round(dur * SR)))


def tt(dur):
    return np.arange(n_of(dur)) / SR


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def filt(x, kind, f, order=2):
    if isinstance(f, (list, tuple)):
        wn = [min(0.999, v / (SR / 2)) for v in f]
    else:
        wn = min(0.999, f / (SR / 2))
    sos = butter(order, wn, btype=kind, output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def adsr(n, a, d, s, r, hold=None):
    """Envelope of n samples; the release starts at `hold` seconds (default: n - r)."""
    t = np.arange(n) / SR
    end = (hold if hold is not None else n / SR - r)
    e = np.where(t < a, t / max(a, 1e-4), 1 - (1 - s) * np.clip((t - a) / max(d, 1e-4), 0, 1))
    rel = np.clip((t - end) / max(r, 1e-4), 0, 1)
    return (e * (1 - rel)).astype(np.float32)


def pan(x, p):
    """p in [-1, 1], constant power."""
    a = (p + 1) * np.pi / 4
    return np.stack([x * np.cos(a), x * np.sin(a)], axis=1).astype(np.float32)


def place(buf, x, t0, gain=1.0):
    """Mix x (mono or stereo) into stereo buf at time t0."""
    if x.ndim == 1:
        x = pan(x, 0)
    i = int(round(t0 * SR))
    if i < 0:
        x = x[-i:]
        i = 0
    j = min(len(buf), i + len(x))
    if j > i:
        buf[i:j] += x[: j - i] * gain


# ---------------------------------------------------------------- oscillators

def saw(f, dur, phase=0.0):
    p = (f * tt(dur) + phase) % 1.0
    return (2 * p - 1).astype(np.float32)


def sine(f, dur, phase=0.0):
    return np.sin(2 * np.pi * f * tt(dur) + phase).astype(np.float32)


def sweep_sine(f0, f1, dur, curve=3.0):
    t = tt(dur)
    f = f1 + (f0 - f1) * np.exp(-curve * t / dur)
    return np.sin(2 * np.pi * np.cumsum(f) / SR).astype(np.float32)


def noise(dur):
    return rng.standard_normal(n_of(dur)).astype(np.float32)


# ---------------------------------------------------------------- instruments

def pad(notes, dur, cutoff=1400, attack=1.6, release=2.2, detune=0.09, bright=0.0):
    """Warm detuned-saw pad, stereo."""
    total = dur + release
    out = np.zeros((n_of(total), 2), np.float32)
    for k, m in enumerate(notes):
        f = midi(m)
        for d, p in ((-detune, -0.6), (0.0, 0.0), (detune, 0.6)):
            v = saw(f * 2 ** (d / 12), total, phase=rng.random())
            out += pan(v, p * 0.8) * 0.22
        out += pan(sine(f / 2, total), 0) * 0.07 if k == 0 else 0
    out = filt(out, "low", cutoff * (1 + bright), 2)
    env = adsr(len(out), attack, 0.5, 0.9, release, hold=dur)
    return out * env[:, None] / max(1, len(notes)) ** 0.5


def piano(m, dur=3.0, vel=1.0):
    f = midi(m)
    t = tt(dur)
    x = np.zeros_like(t, dtype=np.float32)
    for n in range(1, 11):
        fn = f * n * np.sqrt(1 + 0.00035 * n * n)
        if fn > SR / 2.2:
            break
        amp = (1 / n ** 1.15) * np.exp(-t * (0.9 + 0.75 * n) * (1 + 0.3 * (m - 60) / 24))
        x += (amp * np.sin(2 * np.pi * fn * t + rng.random())).astype(np.float32)
    click = filt(noise(0.012), "high", 2500) * np.exp(-np.arange(n_of(0.012)) / 90.0)
    x[: len(click)] += click * 0.15
    rel = np.clip((t - (dur - 0.25)) / 0.25, 0, 1)
    return (x * (1 - rel) * vel * 0.35).astype(np.float32)


def pluck(m, dur=0.9, vel=1.0, bright=1.0):
    f = midi(m)
    t = tt(dur)
    x = np.zeros_like(t, dtype=np.float32)
    for n in range(1, 8):
        amp = (1 / n) * np.exp(-t * (3.5 + 2.8 * n / bright))
        x += (amp * np.sin(2 * np.pi * f * n * t)).astype(np.float32)
    x *= np.minimum(1, t / 0.003)
    return x * vel * 0.3


def bell(m, dur=2.5, vel=1.0):
    f = midi(m)
    t = tt(dur)
    x = np.zeros_like(t, dtype=np.float32)
    for r, a, d in ((1.0, 1.0, 1.6), (2.76, 0.45, 3.2), (5.40, 0.25, 5.5), (8.93, 0.12, 8.0)):
        x += (a * np.exp(-t * d) * np.sin(2 * np.pi * f * r * t)).astype(np.float32)
    x *= np.minimum(1, t / 0.002)
    return x * vel * 0.25


def sub(m, dur, vel=1.0):
    x = sine(midi(m), dur) * adsr(n_of(dur), 0.4, 0.3, 0.9, 1.0)
    return np.tanh(x * 1.5) * 0.5 * vel


def kick(vel=1.0):
    t = tt(0.5)
    f = 44 + 95 * np.exp(-t * 28)
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)
    click = filt(noise(0.006), "high", 3000) * 0.3
    x[: len(click)] += click
    return (np.tanh(x * 1.6) * 0.8 * vel).astype(np.float32)


def shaker(vel=1.0):
    x = filt(noise(0.09), "high", 7000) * np.exp(-np.arange(n_of(0.09)) / (0.018 * SR))
    return x * 0.18 * vel


def tick(vel=1.0, f=2200):
    x = filt(noise(0.03), "band", [f * 0.8, f * 1.25]) * np.exp(-np.arange(n_of(0.03)) / (0.004 * SR))
    return x * 0.9 * vel


# ---------------------------------------------------------------- effects

def tv_bandpass(x, f_start, f_end, q=1.2):
    """Chamberlin state-variable band-pass whose centre glides f_start -> f_end."""
    n = len(x)
    fc = np.geomspace(f_start, f_end, n)
    F = 2 * np.sin(np.pi * np.minimum(fc, SR / 6) / SR)
    damp = 1.0 / q
    low = band = 0.0
    y = np.empty(n, np.float32)
    for i in range(n):
        high = x[i] - low - damp * band
        band += F[i] * high
        low += F[i] * band
        y[i] = band
    return y


def whoosh(dur=1.2, f0=300, f1=4000, vel=1.0, rev=False):
    x = tv_bandpass(noise(dur), f0, f1, q=1.6)
    t = tt(dur)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    if rev:
        env = (t / dur) ** 3
    y = x * env * 0.5 * vel
    p = np.linspace(-0.5, 0.5, len(y))
    a = (p + 1) * np.pi / 4
    return np.stack([y * np.cos(a), y * np.sin(a)], axis=1).astype(np.float32)


def riser(dur=3.0, vel=1.0):
    t = tt(dur)
    x = tv_bandpass(noise(dur), 200, 6000, q=2.5) * 0.6
    f = 180 * 2 ** (2.5 * t / dur)
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25
    env = (t / dur) ** 2.2
    return ((x + tone) * env * vel).astype(np.float32)


def impact(vel=1.0):
    t = tt(4.0)
    boom = np.sin(2 * np.pi * np.cumsum(30 + 40 * np.exp(-t * 6)) / SR) * np.exp(-t * 1.1)
    hit = filt(noise(4.0), "low", 1800) * np.exp(-t * 7)
    y = np.tanh((boom * 1.2 + hit * 0.6) * 1.4) * 0.7
    return (y * vel).astype(np.float32)


def glitch(dur=0.45, vel=1.0, seed=0):
    r = np.random.default_rng(seed)
    out = np.zeros(n_of(dur), np.float32)
    i = 0
    while i < len(out):
        seg = int(r.uniform(0.012, 0.05) * SR)
        kind = r.integers(3)
        t = np.arange(seg) / SR
        if kind == 0:
            s = np.sign(np.sin(2 * np.pi * r.uniform(200, 1800) * t))
        elif kind == 1:
            s = np.repeat(r.standard_normal(seg // 40 + 1), 40)[:seg]
        else:
            s = np.zeros(seg)
        out[i:i + seg] = s[: len(out) - i] * r.uniform(0.2, 0.7)
        i += seg
    return filt(out, "band", [150, 6000]) * vel * 0.35


def click(vel=1.0):
    body = sine(170, 0.04) * np.exp(-np.arange(n_of(0.04)) / (0.006 * SR))
    snap = filt(noise(0.006), "high", 2500) * 0.8
    body[: len(snap)] += snap
    return body * 0.6 * vel


def motor(dur=2.6, vel=1.0):
    t = tt(dur)
    f = 95 + 12 * t / dur
    ph = 2 * np.pi * np.cumsum(f) / SR
    hum = sum(np.sin(ph * k) / k for k in range(1, 7))
    hiss = filt(noise(dur), "band", [800, 3000]) * 0.25
    env = adsr(len(t), 0.15, 0.1, 1.0, 0.25)
    return filt(hum * 0.3 + hiss, "low", 2500) * env * 0.35 * vel


def beep(freqs=(2093, 2637), vel=1.0):
    out = []
    for f in freqs:
        b = sine(f, 0.09) * adsr(n_of(0.09), 0.004, 0.02, 0.8, 0.03)
        out += [b, np.zeros(n_of(0.05), np.float32)]
    return np.concatenate(out) * 0.22 * vel


def pop(f=1100, vel=1.0):
    t = tt(0.08)
    x = np.sin(2 * np.pi * np.cumsum(f * (1 - 0.35 * t / 0.08)) / SR) * np.exp(-t * 45)
    return x.astype(np.float32) * 0.28 * vel


def denied(vel=1.0):
    out = []
    for f in (330, 262):
        s = np.sign(sine(f, 0.09)) * adsr(n_of(0.09), 0.003, 0.03, 0.6, 0.03)
        out += [filt(s, "low", 1800), np.zeros(n_of(0.03), np.float32)]
    return np.concatenate(out) * 0.12 * vel


def chime(notes, gap=0.07, vel=1.0, dur=2.2):
    out = np.zeros(n_of(gap * len(notes) + dur), np.float32)
    for i, m in enumerate(notes):
        b = bell(m, dur, vel * (0.8 + 0.2 * (i == len(notes) - 1)))
        j = n_of(gap * i)
        out[j:j + len(b)] += b
    return out


def warn_tone(vel=1.0):
    out = []
    for f in (880, 660, 880, 660):
        s = sine(f, 0.13) + 0.3 * sine(f * 2, 0.13)
        out += [s * adsr(n_of(0.13), 0.01, 0.03, 0.7, 0.05), np.zeros(n_of(0.05), np.float32)]
    return np.concatenate(out) * 0.13 * vel


# ---------------------------------------------------------------- reverb

def ir(length=3.2, decay=2.6, pre=0.018, bright=5500, seed=1):
    r = np.random.default_rng(seed)
    n = n_of(length)
    t = np.arange(n) / SR
    chans = []
    for c in range(2):
        x = r.standard_normal(n) * np.exp(-t * 6.9 / decay)
        x = filt(x, "low", bright)
        x[: n_of(pre)] = 0
        chans.append(x)
    y = np.stack(chans, 1)
    return (y / np.sqrt(np.sum(y ** 2) / 2)).astype(np.float32)


def reverb(x, wet=0.3, **kw):
    if x.ndim == 1:
        x = pan(x, 0)
    h = ir(**kw)
    y = np.stack([fftconvolve(x[:, c], h[:, c])[: len(x)] for c in range(2)], 1)
    return (x * (1 - wet) + y * wet).astype(np.float32)
