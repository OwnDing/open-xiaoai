"""Original score, laid out on the timeline.

Dark D-minor ambience and a ticking pulse under the pain points, a riser into
the reveal, then warm D-major arpeggios at 80 BPM whose downbeat is anchored
on the impact frame, a lighter bed under the demos, a build for the montage
and a resolving final chord under the end card.
"""
import json
from pathlib import Path

import numpy as np

from synth import (SR, bell, chime, filt, impact, kick, n_of, pad, piano, place, pluck, reverb, riser,
                   shaker, sub, tick)

ROOT = Path(__file__).resolve().parents[2]
TL = json.loads((ROOT / "build" / "timeline.json").read_text())
FPS = TL["fps"]
SHOT = {s["id"]: s for s in TL["shots"]}
END = TL["frames"] / FPS


def T(sid, mark=None):
    s = SHOT[sid]
    return s["start"] / FPS + (s["marks"][mark] if mark else 0.0)


IMPACT = T("S07", "impact")
BEAT = 0.75                      # 80 BPM
BLOCK = 8 * BEAT                 # one chord every two bars


def grid(k):
    return IMPACT + k * BEAT


DARK = [[50, 57, 64, 65], [46, 53, 57, 62], [43, 50, 58, 62], [45, 52, 55, 62]]
WARM = [[50, 54, 57, 61, 64], [47, 54, 57, 62, 64], [43, 50, 54, 59, 61], [45, 52, 54, 59, 62]]
MOTIF = [(0, 78, 1), (1, 76, 1), (2, 74, 2), (4, 73, 1), (5, 74, 1), (6, 76, 2),
         (8, 81, 1.5), (9.5, 78, 0.5), (10, 76, 2), (12, 74, 4)]


def build():
    L = n_of(END + 8)
    bed = np.zeros((L, 2), np.float32)      # pads, sub: long reverb
    keys = np.zeros((L, 2), np.float32)     # piano, plucks, bells
    drums = np.zeros((L, 2), np.float32)    # kick, shaker, ticks: short room
    hits = np.zeros((L, 2), np.float32)     # impact and riser: dry-ish

    # ---- Act 0-1: dark ambience until the pain section collapses.
    pain_end = T("S06")
    t, i = 0.0, 0
    while t < pain_end:
        dur = min(6.0, pain_end + 1.0 - t)
        place(bed, pad(DARK[i % 4], dur, cutoff=850, attack=2.2 if i == 0 else 1.2, release=2.5), t, 0.55)
        place(bed, sub(DARK[i % 4][0] - 12, dur + 1.0), t, 0.22)
        t += 6.0
        i += 1
    for k, m in enumerate([69, 65, 64, 62, 69, 67, 65, 64, 62, 60, 62]):
        tk = 2.0 + k * 3.0
        if tk < pain_end - 1:
            place(keys, piano(m, 3.5, 0.45), tk, 0.9)
    # Ticking pulse from the first pain point to the collapse.
    k0, k1 = int(np.ceil((T("S03") - IMPACT) / BEAT)), int(np.floor((T("S06", "collapse") - IMPACT) / BEAT))
    for k in range(k0, k1 + 1):
        tg = grid(k)
        ramp = min(1.0, (tg - T("S03")) / 6.0)
        place(drums, tick(0.5 * ramp, 2300 if k % 2 == 0 else 1750), tg, 0.5)
        if k % 4 == 0:
            place(drums, sub(38, 0.5, 0.5), tg, 0.35 * ramp)
    # Low drone that holds through the collapse into the reveal.
    place(bed, sub(33, IMPACT - pain_end + 0.5), pain_end - 0.5, 0.4)
    place(hits, riser(IMPACT - (T("S07") + 0.2), 1.0), T("S07") + 0.2, 0.5)

    # ---- Act 2: the hit.
    place(hits, impact(1.0), IMPACT, 0.9)
    place(bed, pad([38, 50, 57, 62, 66, 69, 76], 2 * BLOCK - 1, cutoff=3200, attack=0.02, release=3.0), IMPACT, 0.75)
    place(keys, chime([74, 78, 81, 86, 90], gap=0.06, vel=0.9, dur=3.5), IMPACT + 0.02, 0.7)

    # ---- Warm progression from the hit to the outro.
    outro = T("S15")
    montage = T("S14")
    demo = T("S10")
    day, night = T("S12"), T("S13")
    blk = 0
    while grid(blk * 8) < outro - 0.1:
        t0 = grid(blk * 8)
        chord = WARM[blk % 4]
        dur = min(BLOCK, outro + 0.5 - t0)
        if blk >= 1:
            bright = 0.5 if montage <= t0 else (0.25 if day <= t0 < night else 0.0)
            place(bed, pad(chord, dur, cutoff=1500, attack=0.9, release=2.0, bright=bright), t0, 0.5)
        place(bed, sub(chord[0] - 12, dur), t0, 0.22)
        # Arpeggio: eighths, quarters in the quiet night scene, sixteenths in the montage.
        tones = [m + 12 for m in chord]
        pattern = [0, 1, 2, 3, 4, 3, 2, 1]
        for step in range(32):
            ts = t0 + step * BEAT / 4
            if ts >= outro or ts < grid(4):
                continue
            in_montage = ts >= montage
            if not in_montage and step % 2:
                continue
            if night <= ts < montage and step % 4:
                continue
            m = tones[pattern[(step // (1 if in_montage else 2)) % 8]]
            up = 12 if day <= ts < night else 0
            vel = 0.55 if in_montage else (0.32 if ts >= demo else 0.45)
            if T("S09") <= ts < demo:
                vel = 0.5
            place(keys, pluck(m + up, 0.9, vel, bright=1.4 if in_montage else 1.0), ts,
                  0.8 if step % 8 == 0 else 0.6)
        # Light rhythm under the explanation and the montage.
        for b in range(8):
            tb = t0 + b * BEAT
            if tb >= outro:
                break
            if T("S09") <= tb < demo and b % 2 == 0:
                place(drums, kick(0.45), tb, 0.6)
            if montage <= tb:
                place(drums, kick(0.8), tb, 0.75)
            if (T("S09") <= tb < demo) or montage <= tb or day <= tb < night:
                place(drums, shaker(0.8), tb + BEAT / 2, 0.55)
                if montage <= tb:
                    place(drums, shaker(0.5), tb + BEAT / 4, 0.4)
                    place(drums, shaker(0.5), tb + 3 * BEAT / 4, 0.4)
        blk += 1

    # Piano motif: softly under the first demo, clearly in the outro.
    for tstart, vel in ((demo + 0.6, 0.3), (outro + 0.3, 0.6)):
        for b, m, d in MOTIF:
            ts = tstart + b * BEAT
            if ts < END:
                place(keys, piano(m, d * BEAT + 1.5, vel), ts, 0.9)

    # ---- Outro: IV -> V -> final I with a long tail.
    endcard = T("S16")
    place(bed, pad([43, 50, 54, 59, 62], endcard - outro - 1.5, cutoff=1600, attack=1.2, release=2.0), outro, 0.55)
    place(bed, pad([45, 52, 57, 61, 64], 2.2, cutoff=1700, attack=0.8, release=1.8), endcard - 2.0, 0.45)
    place(bed, pad([38, 50, 57, 62, 66, 69, 73, 76], END - endcard + 0.5, cutoff=2400, attack=0.4, release=4.0),
          endcard, 0.7)
    place(bed, sub(38, END - endcard + 2.0), endcard, 0.4)
    place(keys, chime([74, 78, 81, 85, 86], gap=0.09, vel=0.7, dur=4.5), endcard + 0.3, 0.6)
    place(keys, piano(62, 5.0, 0.5), endcard, 0.8)
    place(keys, piano(69, 5.0, 0.4), endcard + 0.02, 0.8)

    mix = (reverb(bed, wet=0.45, length=4.0, decay=3.8)
           + reverb(keys, wet=0.38, length=3.5, decay=3.0, bright=7000)
           + reverb(drums, wet=0.12, length=1.2, decay=0.8)
           + reverb(hits, wet=0.25, length=4.0, decay=3.5))
    mix = filt(mix, "high", 38)
    # Section dynamics: quiet pain, a big reveal, a lifted montage, a warm close.
    t = np.arange(len(mix)) / SR
    keys_t = [0, 6, T("S03"), T("S06"), T("S07") + 0.5, IMPACT - 0.05, IMPACT + 0.3, IMPACT + 6, T("S09"),
              T("S10"), T("S13"), T("S14") - 0.5, T("S14") + 1.5, T("S15"), T("S16"), END]
    gains = [0.35, 0.7, 0.75, 0.75, 0.45, 0.9, 1.35, 1.05, 1.0, 0.85, 0.7, 0.8, 1.25, 1.0, 1.1, 1.0]
    mix *= np.interp(t, keys_t, gains)[:, None]
    mix *= np.clip((END + 0.2 - t) / 1.8, 0, 1)[:, None]
    return mix[: n_of(END)]


if __name__ == "__main__":
    from scipy.io import wavfile
    m = build()
    out = ROOT / "build" / "audio" / "music.wav"
    wavfile.write(out, SR, (m / np.max(np.abs(m)) * 0.9).astype(np.float32))
    print("music", len(m) / SR, "s ->", out)
