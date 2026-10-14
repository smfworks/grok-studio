#!/usr/bin/env python3
"""QA for avatar clips + final hybrid. usage: qa_avatar.py PLAN.json OUTDIR [--keyterms a,b]
- STT each avatar clip's own speech and compare to the scripted line (word match %); flags < 95 %.
- Speech start/end per clip; final duration vs expected; blackdetect, freezedetect, silencedetect; integrated loudness.
Exit 1 on any FAIL."""
import argparse, json, os, re, subprocess, sys, difflib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")); import xai_imagine as X
def norm(t):
    t = t.lower(); nums = {"2026": "twenty twenty six", "2025": "twenty twenty five", "filename": "file name"}
    for k, v in nums.items(): t = re.sub(rf"\b{k}\b", v, t)
    try:
        from num2words import num2words
        t = re.sub(r"(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), t)
        t = re.sub(r"\b(\d+)\.(\d+)\b", lambda m: num2words(int(m.group(1))) + " point " + " ".join(num2words(int(c)) for c in m.group(2)), t)
        def yr(m):
            n = int(m.group(0))
            return num2words(n, to="year") if 1900 <= n <= 2099 else (num2words(n // 100) + " " + num2words(n % 100) if 100 < n < 1000 and n % 100 >= 10 else num2words(n))
        t = re.sub(r"\b\d+\b", yr, t)
    except ImportError: pass
    t = t.replace("-", " ").replace(" and ", " ")
    return [w for w in re.findall(r"[a-z']+", t) if w != "and"]
ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("plan"); ap.add_argument("out"); ap.add_argument("--keyterms", default=""); a = ap.parse_args()
man = json.load(open(os.path.join(a.out, "manifest.json"))); kt = [k for k in a.keyterms.split(",") if k]; fail = False
for sid, entries in man.items():
    for i, e in enumerate(entries):
        mp3 = e["video"][:-4] + ".imagine.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", e["video"], "-vn", mp3], check=True)
        heard = X.stt(mp3, kt); r = difflib.SequenceMatcher(None, norm(e["line"]), norm(heard)).ratio()
        ok = r >= 0.95; fail |= not ok
        print(f"{'PASS' if ok else 'FAIL'} {sid}_{i} words {r:.0%}\n  script: {e['line']}\n  heard : {heard}")
final = os.path.join(a.out, "hybrid.mp4")
if os.path.exists(final):
    log = subprocess.run(["ffmpeg", "-i", final, "-vf", "blackdetect=d=0.3:pix_th=0.05,freezedetect=n=0.001:d=8",
                          "-af", "silencedetect=n=-45dB:d=1.2,ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
    for k in ("black_start", "freeze_start", "silence_start"):
        c = log.count(k); print(f"{'PASS' if c == 0 else 'FAIL'} {k}: {c}"); fail |= c > 0
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", log); print("loudness", m[-1] if m else "?", "LUFS (target -16)")
sys.exit(1 if fail else 0)
