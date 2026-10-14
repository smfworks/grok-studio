#!/usr/bin/env python3
"""Original procedural ambient music bed (no samples, no copyrighted material).

usage: music.py OUT.wav DURATION_S [--seed N] [--bpm 64]
Soft detuned-sine pad chords (I-vi-IV-V style progression in a random key), slow swells,
a quiet high shimmer, gentle low-pass + room reverb, 2 s fade in / 3 s fade out, normalised to -30 LUFS.
"""
import argparse, subprocess, wave, numpy as np
SR = 44100
PROGS = [[0, 9, 5, 7], [0, 5, 9, 7], [9, 5, 0, 7], [0, 7, 9, 5]]
def chord(root, minor):  # root in semitones from A2
    return [root, root + (3 if minor else 4), root + 7, root + 11 if not minor else root + 10]
def tone(freqs, n, rng):
    t = np.arange(n) / SR; out = np.zeros(n)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            ph = rng.uniform(0, 2 * np.pi); ff = f * 2 ** (det / 12)
            out += np.sin(2 * np.pi * ff * t + ph) + 0.18 * np.sin(4 * np.pi * ff * t + ph)
    return out / (len(freqs) * 3)
def make(duration, seed=7, bpm=64):
    rng = np.random.default_rng(seed); key = int(rng.integers(0, 7)); prog = PROGS[seed % len(PROGS)]
    bar = 4 * 60 / bpm; n_total = int((duration + 1) * SR); out = np.zeros(n_total); i = 0; k = 0
    seg = int(bar * 2 * SR); xf = int(1.2 * SR)
    while i < n_total:
        deg = prog[k % 4]; minor = deg == 9; root = 110 * 2 ** ((key + deg - 12) / 12)
        notes = [root * 2 ** (s / 12) for s in chord(0, minor)] + [root / 2]
        n = min(seg + xf, n_total - i); env = np.ones(n)
        a = min(xf, n); env[:a] = np.linspace(0, 1, a); env[-a:] *= np.linspace(1, 0, a)
        swell = 0.85 + 0.15 * np.sin(np.linspace(0, np.pi, n))
        out[i:i + n] += tone(notes, n, rng) * env * swell
        sh = tone([notes[2] * 4], n, rng) * env * 0.12 * (0.5 + 0.5 * np.sin(np.linspace(0, 6 * np.pi, n)))
        out[i:i + n] += sh; i += seg; k += 1
    out = out[: int(duration * SR)]
    out /= np.max(np.abs(out)) + 1e-9
    stereo = np.stack([out, np.roll(out, int(0.011 * SR))], 1) * 0.7
    return (stereo * 32767).astype(np.int16)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("out"); ap.add_argument("duration", type=float)
    ap.add_argument("--seed", type=int, default=7); ap.add_argument("--bpm", type=float, default=64); a = ap.parse_args()
    raw = a.out + ".raw.wav"; data = make(a.duration, a.seed, a.bpm)
    with wave.open(raw, "wb") as w: w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(data.tobytes())
    fo = max(0.1, a.duration - 3)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", raw, "-af",
        f"lowpass=f=2200,aecho=0.8:0.6:120|260:0.25|0.15,afade=t=in:d=2,afade=t=out:st={fo:.2f}:d=3,loudnorm=I=-30:TP=-6:LRA=7,aresample=48000",
        "-t", f"{a.duration:.3f}", a.out], check=True)
    import os; os.remove(raw); print(a.out)
if __name__ == "__main__": main()
