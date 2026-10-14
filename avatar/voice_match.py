#!/usr/bin/env python3
"""Rank candidate voice samples by similarity to a reference voice (e.g. the avatar's Imagine speech).
usage: voice_match.py REF1 [REF2 ...] -- CAND1 CAND2 ...
Features: median F0, spectral centroid, mean log-spectrum shape (voiced frames). Lower score = closer."""
import sys, subprocess, numpy as np
SR = 16000
def load(f):
    b = subprocess.check_output(["ffmpeg", "-v", "error", "-i", f, "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"])
    return np.frombuffer(b, np.int16).astype(float) / 32768
def feats(x):
    f0, specs = [], []
    for i in range(0, len(x) - 1024, 320):
        w = x[i:i + 1024]
        if np.sqrt((w ** 2).mean()) < 0.03: continue
        w = w - w.mean(); ac = np.correlate(w, w, "full")[1023:]; lo, hi = SR // 400, SR // 70; k = lo + np.argmax(ac[lo:hi])
        if ac[k] > 0.4 * ac[0]: f0.append(SR / k)
        specs.append(np.abs(np.fft.rfft(w * np.hanning(1024))))
    S = np.mean(specs, 0); bands = np.array_split(S[8:400], 24); logb = np.log([b.mean() + 1e-9 for b in bands]); logb -= logb.mean()
    cent = (S * np.arange(len(S))).sum() / S.sum() * SR / 1024
    return np.median(f0), cent, logb
args = sys.argv[1:]
if not args or args[0] in ("-h", "--help") or "--" not in args: print(__doc__); sys.exit(0 if args and args[0] in ("-h","--help") else 2)
sep = args.index("--"); refs, cands = args[:sep], args[sep + 1:]
R = [feats(load(f)) for f in refs]; rf0 = np.mean([r[0] for r in R]); rc = np.mean([r[1] for r in R]); rl = np.mean([r[2] for r in R], 0)
print(f"REF f0={rf0:.0f}Hz centroid={rc:.0f}Hz")
rows = []
for c in cands:
    f0, ce, lb = feats(load(c))
    score = abs(np.log(f0 / rf0)) * 4 + abs(np.log(ce / rc)) * 2 + np.sqrt(((lb - rl) ** 2).mean())
    rows.append((score, c, f0, ce))
for s, c, f0, ce in sorted(rows): print(f"{s:.3f}  {c}  f0={f0:.0f}  centroid={ce:.0f}")
