"""Original score for 《遥控器退休了》, laid out on the timeline.

Night piano and a pad while the room is dark; a bloom when the TV wakes and a
swell under the title; a D-minor drone with a ticking pulse under the pain
points, three hits and silence; a bright F-major bloom on the turn; a light
96 BPM groove while the helper is explained; a warm bed under the demos that
steps aside when the TV plays music; a build to the final chord in the museum.
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

    # ---------------- prologue: a dark room, the TV wakes, the title
    s1, s3, s4 = T("S01"), T("S03"), T("S04")
    on, title = T("S02", "tv_on"), T("S03", "title")
    place(bed, pad(NIGHT[0], on - s1 + 0.5, cutoff=650, attack=3.0, release=2.0), s1, 0.42)
    place(lows, sub(38, on - s1), s1 + 0.5, 0.16)
    for dt, m in [(0.9, 74), (2.4, 69), (3.8, 72), (5.6, 76), (7.4, 74)]:
        place(keys, piano(m, 4.0, 0.3), s1 + dt, 0.9)
    place(hits, riser(1.2, 0.5), T("S02", "thread") - 0.2, 0.3)
    # The TV comes on: a soft bloom, a plucked line while 小七 works the screen.
    place(bed, pad([41, 53, 57, 60, 64, 69], title - on + 0.6, cutoff=1800, attack=0.6, release=2.5, bright=0.2), on, 0.42)
    place(lows, sub(29, title - on + 0.6), on, 0.2)
    arp(keys, [[53, 57, 60, 64, 69]], on + 0.3, T("S02", "verify") + 0.3, 4, BEAT / 2, vel=0.26, up=12)
    place(keys, chime([77, 81, 84, 88], gap=0.07, vel=0.5, dur=2.0), T("S02", "verify"), 0.45)
    place(hits, impact(0.6), title - 0.05, 0.5)
    place(bed, pad([38, 50, 57, 62, 65, 69, 72], s4 - title + 0.4, cutoff=2400, attack=0.1, release=3.0, bright=0.35), title, 0.55)
    place(keys, chime([74, 77, 81, 86], gap=0.09, vel=0.65, dur=3.5), title + 0.05, 0.55)
    place(lows, sub(26, s4 - title + 0.8), title, 0.28)

    # ---------------- act 1: pain (D minor drone, a pulse that gets busier with the presses)
    s5, s6, s7, s8 = T("S05"), T("S06"), T("S07"), T("S08")
    chords(bed, lows, DARK, s4 + 0.2, s7, 4.0, gain=0.4, cutoff=760, attack=1.6, sub_gain=0.2)
    t = s4 + 1.0
    while t < s7 - 0.3:
        place(drums, kick(0.32), t, 0.5)
        place(drums, kick(0.18), t + 0.26, 0.38)
        t += 1.0 if t < s6 else 0.8
    for k in range(int((s7 - s4) / 0.5)):
        tk = s4 + 0.5 * k
        if not (s5 <= tk < s6):
            place(drums, tick(0.3, 2300 if k % 2 else 1700), tk, 0.22)
    place(hits, riser(s7 - s6 - 0.5, 0.6), s6 + 0.5, 0.25)
    for k in (1, 2, 3):
        place(hits, impact(0.75), T("S07", f"w{k}"), 0.5)
        place(lows, sub(33 - k * 2, 1.0), T("S07", f"w{k}"), 0.35)
    col = T("S07", "collapse")
    place(hits, riser(0.9, 0.8), col - 0.9, 0.3)

    # ---------------- act 2: the turn
    wake = T("S08", "wake")
    place(hits, impact(0.9), s8, 0.75)
    place(lows, sub(29, 4.0), s8, 0.4)
    s9 = T("S09")
    place(bed, pad([41, 53, 57, 60, 64, 67, 72], s9 - wake + 0.6, cutoff=3000, attack=0.08, release=3.0, bright=0.5), wake, 0.65)
    place(keys, chime([72, 76, 79, 84, 88], gap=0.06, vel=0.8, dur=4.0), wake + 0.02, 0.6)
    arp(keys, [[53, 57, 60, 64, 67]], wake + 0.5, s9 - 0.3, 4, BEAT / 2, vel=0.28, up=12)
    place(keys, chime([79, 84, 88], gap=0.08, vel=0.55, dur=2.5), T("S08", "claim"), 0.45)

    # ---------------- act 3: eyes and hands (96 BPM groove)
    s13 = T("S13")
    chords(bed, lows, WARM, s9, s13, 8 * BEAT, gain=0.34, cutoff=1500, attack=0.6, sub_gain=0.17)
    arp(keys, WARM, s9 + 4 * BEAT, s13 - 0.2, 8 * BEAT, BEAT / 2, vel=0.28, up=12)
    k, t = 0, s9 + 4 * BEAT
    while t < s13 - 0.4:
        if k % 2 == 0:
            place(drums, kick(0.48), t, 0.5)
        place(drums, shaker(0.65), t + BEAT / 2, 0.42)
        if t >= T("S11"):
            place(drums, shaker(0.4), t + BEAT / 4, 0.28)
            place(drums, shaker(0.4), t + 3 * BEAT / 4, 0.28)
        k += 1
        t += BEAT
    place(lows, sub(31, 2.0), T("S12", "lan"), 0.4)

    # ---------------- act 4: one sentence each (warm, light; steps aside for the TV's song)
    s14, s15, s16, s17, s18 = T("S14"), T("S15"), T("S16"), T("S17"), T("S18")
    allm = T("S15", "all")
    chords(bed, lows, WARM, s13, allm + 0.2, 8 * BEAT, gain=0.3, cutoff=1300, attack=0.8, sub_gain=0.14)
    arp(keys, WARM, s13 + 0.3, s15 - 0.2, 8 * BEAT, BEAT, vel=0.24, up=12)
    for i in range(1, 7):
        place(keys, pluck(72 + [0, 2, 4, 5, 7, 9][i - 1], 1.2, 0.5, bright=1.4), T("S13", f"k{i}") + 0.25, 0.6)
    chords(bed, lows, WARM, s16 - 0.3, s17, 8 * BEAT, gain=0.28, cutoff=1300, attack=1.2, sub_gain=0.12)
    arp(keys, WARM, s16 + 0.2, s17 - 0.2, 8 * BEAT, BEAT / 2, vel=0.22, up=12)
    # Lights down: a few piano notes.
    for i, (b, m) in enumerate([(0, 72), (2, 69), (4, 65), (6, 67)]):
        place(keys, piano(m, 3.0, 0.32), s17 + 0.4 + b * BEAT, 0.9)
    place(bed, pad([41, 48, 57, 64], s18 - s17 + 0.5, cutoff=900, attack=1.0, release=2.0), s17, 0.26)

    # ---------------- act 5: the museum and the end card
    s19 = T("S19")
    retire = T("S18", "retire")
    chords(bed, lows, [[41, 53, 57, 60, 64], [46, 53, 58, 62, 65], [48, 55, 60, 64, 67]], s18, retire - 0.3, 6 * BEAT,
           gain=0.42, cutoff=1700, attack=0.8, bright=0.25, sub_gain=0.18)
    arp(keys, [[53, 57, 60, 64, 67], [58, 62, 65, 69, 70], [60, 64, 67, 72, 74]], s18 + 0.4, retire - 0.2, 6 * BEAT, BEAT / 2,
        vel=0.3, up=12)
    for i in range(1, 6):
        place(keys, chime([79 + [0, 2, 4, 7, 9][i - 1]], gap=0.05, vel=0.45, dur=1.5), T("S18", f"k{i}"), 0.35)
    t = s18 + 1.2
    while t < retire - 0.3:
        place(drums, kick(0.5), t, 0.45)
        place(drums, shaker(0.55), t + BEAT / 2, 0.38)
        t += BEAT
    place(hits, riser(retire - (s18 + 3.5), 0.65), s18 + 3.5, 0.28)
    place(hits, impact(0.8), retire - 0.05, 0.55)
    place(bed, pad([29, 41, 48, 53, 57, 60, 64, 69, 72], END - retire + 1.0, cutoff=2600, attack=0.08, release=5.0, bright=0.4),
          retire, 0.72)
    place(lows, sub(29, END - retire + 2.0), retire, 0.42)
    place(keys, chime([72, 76, 79, 84, 88, 91], gap=0.08, vel=0.75, dur=5.0), retire + 0.02, 0.55)
    for i, m in enumerate([77, 76, 72, 69, 72]):
        place(keys, piano(m, 4.0, 0.4), s19 + 0.5 + i * 2 * BEAT, 0.9)
    place(keys, piano(53, 6.0, 0.48), s19 + 0.5, 0.8)
    place(keys, piano(60, 6.0, 0.38), s19 + 0.52, 0.8)

    mix = (reverb(bed, wet=0.45, length=4.0, decay=3.8)
           + reverb(keys, wet=0.38, length=3.5, decay=3.0, bright=7000)
           + reverb(drums, wet=0.12, length=1.2, decay=0.8)
           + reverb(hits, wet=0.25, length=4.0, decay=3.5)
           + reverb(lows, wet=0.15, length=2.0, decay=1.5))
    mix = filt(mix, "high", 30)
    t = np.arange(len(mix)) / SR
    kt = [0, 1.5, on - 0.2, on + 0.5, title, s4 - 0.3, s4 + 0.6, s6, s7 - 0.1, s7, col + 0.1, s8 - 0.05, s8 + 0.3, s9, s13,
          allm, allm + 0.6, s16 - 0.4, s16 + 0.4, s17, s18, retire - 0.2, retire + 0.3, END]
    gv = [0.0, 0.3, 0.34, 0.75, 1.25, 0.5, 0.55, 0.7, 0.95, 1.0, 0.0, 0.0, 1.2, 0.85, 0.75,
          0.7, 0.12, 0.12, 0.65, 0.6, 0.8, 1.2, 1.55, 1.2]
    mix *= np.interp(t, kt, gv)[:, None]
    mix *= np.clip((END + 0.3 - t) / 2.5, 0, 1)[:, None]
    return mix[: n_of(END)]


if __name__ == "__main__":
    from scipy.io import wavfile
    m = build()
    out = ROOT / "build" / "audio" / "music.wav"
    wavfile.write(out, SR, (m / np.max(np.abs(m)) * 0.9).astype(np.float32))
    print("music", len(m) / SR, "s ->", out)
