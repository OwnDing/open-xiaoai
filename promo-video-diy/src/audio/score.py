"""Original score for 《家的大脑》, laid out on the timeline.

Night piano and a pad for the opening, a bloom when the home wakes and a swell
under the title; a D-minor drone with a heartbeat pulse under the pain points
that rises with the uploads and cuts to silence before "no secrets"; three hits
and a collapse; a bright F-major bloom on the turn; a light 96 BPM groove for
the DIY recipe and the explainer; a warm bed under the demos; soft piano for the
extensions; a build to the final chord under the vision and the end card.
"""
import json
from pathlib import Path

import numpy as np

from synth import SR, chime, filt, impact, kick, n_of, pad, piano, place, pluck, reverb, riser, shaker, sub, tick

ROOT = Path(__file__).resolve().parents[2]
TL = json.loads((ROOT / "build" / "timeline.json").read_text())
FPS = TL["fps"]
SHOT = {s["id"]: s for s in TL["shots"]}
END = TL["frames"] / FPS


def T(sid, mark=None):
    s = SHOT[sid]
    return s["start"] / FPS + (s["marks"][mark] if mark else 0.0)


def LT(sid, lid):
    s = SHOT[sid]
    l = next(x for x in s["lines"] if x["id"] == lid)
    return s["start"] / FPS + l["t"], l["dur"]


DARK = [[50, 57, 62, 65], [46, 53, 58, 62], [43, 50, 58, 62], [45, 52, 57, 61]]          # Dm Bb Gm A
WARM = [[41, 53, 57, 60, 64], [48, 52, 55, 60, 62], [50, 53, 57, 60, 64], [46, 53, 57, 60, 65]]  # Fmaj7 C(add9) Dm9 Bbmaj7
NIGHT = [[50, 57, 60, 64, 65], [46, 53, 57, 60, 62]]                                        # Dm(add9) Bbmaj7
BEAT = 0.625                                                                                # 96 BPM


def chords(buf_bed, buf_sub, prog, t0, t1, block, gain=0.5, cutoff=1400, attack=0.9, bright=0.0, sub_gain=0.2):
    t, i = t0, 0
    while t < t1 - 0.2:
        dur = min(block, t1 - t)
        ch = prog[i % len(prog)]
        place(buf_bed, pad(ch, dur, cutoff=cutoff, attack=attack, release=2.0, bright=bright), t, gain)
        place(buf_sub, sub(ch[0] - 12, dur + 0.5), t, sub_gain)
        t += block
        i += 1


def arp(keys, prog, t0, t1, block, step, vel=0.4, up=12, pattern=(0, 1, 2, 3, 4, 3, 2, 1), bright=1.0):
    t, i = t0, 0
    while t < t1 - 0.05:
        ch = prog[(int((t - t0) // block)) % len(prog)]
        tones = [m + up for m in ch]
        m = tones[pattern[i % len(pattern)] % len(tones)]
        place(keys, pluck(m, 0.9, vel * (1.15 if i % 8 == 0 else 1.0), bright=bright), t, 0.7)
        t += step
        i += 1


def build():
    L = n_of(END + 8)
    bed = np.zeros((L, 2), np.float32)
    keys = np.zeros((L, 2), np.float32)
    drums = np.zeros((L, 2), np.float32)
    hits = np.zeros((L, 2), np.float32)
    lows = np.zeros((L, 2), np.float32)

    # ---------------- prologue: night, the home wakes, the title
    s1, s3, s4 = T("S01"), T("S03"), T("S04")
    burst, title = T("S02", "burst"), T("S03", "title")
    place(bed, pad(NIGHT[0], burst - s1 + 0.5, cutoff=700, attack=3.0, release=2.0), s1, 0.45)
    place(lows, sub(38, burst - s1), s1 + 0.5, 0.18)
    for k, (dt, m) in enumerate([(1.2, 74), (2.6, 69), (3.9, 72), (5.3, 76)]):
        place(keys, piano(m, 4.0, 0.32), s1 + dt, 0.9)
    place(hits, riser(1.4, 0.6), T("S02", "thread") - 0.2, 0.35)
    # Bloom when the lights come on, then a swell into the title.
    place(bed, pad([41, 53, 57, 60, 64, 69], title - burst + 0.6, cutoff=2200, attack=0.25, release=2.5, bright=0.3), burst, 0.55)
    place(lows, sub(29, title - burst + 0.6), burst, 0.25)
    arp(keys, [[53, 57, 60, 64, 69]], burst + 0.1, title + 0.2, 4, BEAT / 2, vel=0.34, up=12)
    place(keys, chime([77, 81, 84, 88], gap=0.07, vel=0.6, dur=2.0), burst + 0.05, 0.5)
    place(hits, impact(0.7), title - 0.05, 0.55)
    place(bed, pad([38, 50, 57, 62, 65, 69, 72], s4 - title + 0.4, cutoff=2600, attack=0.1, release=3.0, bright=0.4), title, 0.6)
    place(keys, chime([74, 77, 81, 86], gap=0.09, vel=0.7, dur=3.5), title + 0.05, 0.6)
    place(lows, sub(26, s4 - title + 0.8), title, 0.3)

    # ---------------- act 1: pain
    s6, s7, s8 = T("S06"), T("S07"), T("S08")
    silence = T("S06", "silence")
    chords(bed, lows, DARK, s4 + 0.2, silence, 4.0, gain=0.42, cutoff=800, attack=1.6, sub_gain=0.22)
    # Heartbeat pulse, getting closer under the uploads.
    t = s4 + 1.0
    while t < silence - 0.3:
        ramp = 0.35 + 0.65 * min(1.0, max(0.0, (t - s6) / 9.0))
        place(drums, kick(0.35 * ramp + 0.15), t, 0.55)
        place(drums, kick(0.22 * ramp + 0.1), t + 0.26, 0.4)
        period = 1.0 if t < s6 else max(0.62, 1.0 - 0.38 * (t - s6) / 9.0)
        t += period
    for k in range(int((silence - s4) / 0.5)):
        tk = s4 + 0.5 * k
        place(drums, tick(0.35, 2300 if k % 2 else 1700), tk, 0.25)
    # Rising cluster under the uploads, cut dead at "silence".
    up_dur = silence - (s6 + 0.7)
    place(hits, riser(up_dur, 0.9), s6 + 0.7, 0.35)
    cl = pad([62, 63, 65, 68], up_dur, cutoff=1800, attack=up_dur * 0.8, release=0.05)
    place(bed, cl, s6 + 0.7, 0.35)
    # The three words: three hits; the collapse sucks into a point.
    for k in (1, 2, 3):
        place(hits, impact(0.75), T("S07", f"w{k}"), 0.5)
        place(lows, sub(33 - k * 2, 1.0), T("S07", f"w{k}"), 0.35)
    col = T("S07", "collapse")
    place(hits, riser(0.9, 0.8), col - 0.9, 0.3)

    # ---------------- act 2: the turn
    spark = s8
    place(hits, impact(1.0), spark, 0.85)
    place(lows, sub(29, 4.0), spark, 0.45)
    s9 = T("S09")
    place(bed, pad([41, 53, 57, 60, 64, 67, 72], s9 - spark + 0.6, cutoff=3000, attack=0.05, release=3.0, bright=0.5), spark, 0.7)
    place(keys, chime([72, 76, 79, 84, 88], gap=0.06, vel=0.85, dur=4.0), spark + 0.02, 0.65)
    arp(keys, [[53, 57, 60, 64, 67]], spark + 0.6, s9 - 0.3, 4, BEAT / 2, vel=0.3, up=12)
    place(keys, chime([79, 84, 88], gap=0.08, vel=0.6, dur=2.5), T("S08", "title"), 0.5)

    # ---------------- act 3 + 4: the recipe and the explainer (96 BPM groove)
    g0 = s9 + 0.0
    s13, s14 = T("S13"), T("S14")
    chords(bed, lows, WARM, g0, s14, 8 * BEAT, gain=0.36, cutoff=1500, attack=0.6, sub_gain=0.18)
    arp(keys, WARM, g0 + 4 * BEAT, s14 - 0.2, 8 * BEAT, BEAT / 2, vel=0.3, up=12)
    k = 0
    t = g0 + 4 * BEAT
    while t < s14 - 0.3:
        if k % 2 == 0:
            place(drums, kick(0.5), t, 0.55)
        place(drums, shaker(0.7), t + BEAT / 2, 0.45)
        if t >= s13:
            place(drums, shaker(0.45), t + BEAT / 4, 0.3)
            place(drums, shaker(0.45), t + 3 * BEAT / 4, 0.3)
        k += 1
        t += BEAT
    # The wall moment in the explainer: a deep, protective swell.
    place(lows, sub(31, 2.2), T("S13", "wall"), 0.45)

    # ---------------- act 5: demos (warm bed, lighter)
    s15, s16, s17 = T("S15"), T("S16"), T("S17")
    chords(bed, lows, WARM, s14, s17, 8 * BEAT, gain=0.32, cutoff=1300, attack=0.8, sub_gain=0.15)
    arp(keys, WARM, s14 + 0.3, s16 - 0.3, 8 * BEAT, BEAT, vel=0.26, up=12)
    # Time-lapse in S15: a fast twinkle run.
    lap0, lap1 = T("S15", "lapse"), T("S15", "done")
    arp(keys, [[60, 64, 67, 72, 76]], lap0, lap1, 4, BEAT / 4, vel=0.22, up=12, pattern=(0, 1, 2, 3, 4, 3, 2, 1), bright=1.5)
    # Flashback S16: piano only, sunny.
    for i, (b, m) in enumerate([(0, 72), (1, 76), (2, 79), (4, 77), (5, 76), (6, 72), (8, 74), (10, 72)]):
        place(keys, piano(m, 2.5, 0.38), s16 + 0.4 + b * BEAT, 0.9)

    # ---------------- act 6: extensions (soft, a little suspense in the kitchen)
    s18, s19 = T("S18"), T("S19")
    chords(bed, lows, [[45, 52, 57, 60, 64], [41, 48, 53, 57, 64]], s17, s18, 6 * BEAT, gain=0.3, cutoff=900, attack=1.2, sub_gain=0.15)
    t = s17 + 0.5
    while t < s18 - 0.4:
        place(drums, tick(0.3, 2600), t, 0.25)
        t += BEAT
    chords(bed, lows, [[48, 55, 60, 64, 67], [45, 52, 57, 60, 64], [41, 53, 57, 60, 65], [43, 50, 55, 59, 62]],
           s18, s19, 6 * BEAT, gain=0.3, cutoff=1200, attack=1.0, sub_gain=0.12)
    for i, (b, m) in enumerate([(0, 76), (2, 79), (3, 81), (4, 79), (6, 76), (8, 74), (9, 76), (10, 72), (12, 74), (14, 76),
                                (16, 79), (18, 81)]):
        ts = s18 + 0.6 + b * BEAT
        if ts < s19 - 0.3:
            place(keys, piano(m, 3.0, 0.3), ts, 0.9)

    # ---------------- act 7: vision and the end card
    s20 = T("S20")
    claim = T("S19", "claim")
    chords(bed, lows, [[41, 53, 57, 60, 64], [46, 53, 58, 62, 65], [48, 55, 60, 64, 67]], s19, claim - 0.3, 6 * BEAT,
           gain=0.45, cutoff=1800, attack=0.6, bright=0.3, sub_gain=0.2)
    arp(keys, [[53, 57, 60, 64, 67], [58, 62, 65, 69, 70], [60, 64, 67, 72, 74]], s19 + 0.2, claim - 0.2, 6 * BEAT, BEAT / 2,
        vel=0.32, up=12)
    t = s19 + 1.2
    while t < claim - 0.3:
        place(drums, kick(0.55), t, 0.5)
        place(drums, shaker(0.6), t + BEAT / 2, 0.4)
        t += BEAT
    place(hits, riser(claim - (s19 + 3.0), 0.7), s19 + 3.0, 0.3)
    place(hits, impact(0.8), claim - 0.05, 0.6)
    place(bed, pad([29, 41, 48, 53, 57, 60, 64, 69, 72], END - claim + 1.0, cutoff=2600, attack=0.08, release=5.0, bright=0.4),
          claim, 0.75)
    place(lows, sub(29, END - claim + 2.0), claim, 0.45)
    place(keys, chime([72, 76, 79, 84, 88, 91], gap=0.08, vel=0.8, dur=5.0), claim + 0.02, 0.6)
    for i, m in enumerate([77, 76, 72, 69, 72]):
        place(keys, piano(m, 4.0, 0.42), s20 + 0.5 + i * 2 * BEAT, 0.9)
    place(keys, piano(53, 6.0, 0.5), s20 + 0.5, 0.8)
    place(keys, piano(60, 6.0, 0.4), s20 + 0.52, 0.8)

    mix = (reverb(bed, wet=0.45, length=4.0, decay=3.8)
           + reverb(keys, wet=0.38, length=3.5, decay=3.0, bright=7000)
           + reverb(drums, wet=0.12, length=1.2, decay=0.8)
           + reverb(hits, wet=0.25, length=4.0, decay=3.5)
           + reverb(lows, wet=0.15, length=2.0, decay=1.5))
    mix = filt(mix, "high", 30)
    # Section dynamics.
    t = np.arange(len(mix)) / SR
    kt = [0, 1.5, burst - 0.2, burst + 0.5, title, s4 - 0.3, s4 + 0.6, s6, silence - 0.1, silence + 0.05, s7 - 0.1, s7,
          spark - 0.05, spark + 0.3, s9, s13, s14, s16, s17, s19, claim - 0.2, claim + 0.3, END]
    gv = [0.0, 0.32, 0.38, 0.95, 1.35, 0.5, 0.55, 0.75, 1.25, 0.0, 0.0, 1.0,
          0.95, 1.6, 0.85, 0.9, 0.7, 0.7, 0.62, 0.9, 1.45, 1.7, 1.2]
    mix *= np.interp(t, kt, gv)[:, None]
    mix *= np.clip((END + 0.3 - t) / 2.5, 0, 1)[:, None]
    return mix[: n_of(END)]


if __name__ == "__main__":
    from scipy.io import wavfile
    m = build()
    out = ROOT / "build" / "audio" / "music.wav"
    wavfile.write(out, SR, (m / np.max(np.abs(m)) * 0.9).astype(np.float32))
    print("music", len(m) / SR, "s ->", out)
