#!/usr/bin/env python3
"""QA gate for studio/build.py output. Exit 1 on any FAIL.

usage: qa_studio.py PLAN.json OUTDIR [--sources a.txt,b.txt] [--keyterms a,b] [--skip-stt]
Checks:
  numbers  every number shown on screen (headings, items, stats, chart data/labels, quotes) appears in the
           source text files (--sources or plan "source_text"); numbers found only in the script are WARN.
           Chart segments must carry a cite.
  avatar   STT word match >= 95% per avatar/PiP clip used by the plan (avatar/qa_avatar.py).
  formats  duration within 0.15 s of build_info expected; blackdetect / freezedetect (8 s) / silencedetect
           (1.2 s at -45 dB); loudness ~-16 LUFS; music bed 22-30 dB under the voice when enabled.
  stills   writes OUTDIR/stills/<fmt>_<n>_<kind>.png at the middle of every segment for a visual check.
"""
import argparse, json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
def screen_texts(s):
    out = []
    for k in ("heading", "sub", "quote", "kicker"):
        if s.get(k): out.append(str(s[k]))
    for k in ("bullets", "steps", "items", "stats", "table"):
        for it in s.get(k, []):
            if isinstance(it, dict): out += [str(v) for v in it.values() if isinstance(v, (str, int, float))]
            elif isinstance(it, (list, tuple)): out += [str(v) for v in it]
            else: out.append(str(it))
    for d in s.get("data", []): out += [str(d.get("label", "")), str(d.get("display", d.get("value", "")))]
    if s.get("center"): out.append(str(s["center"]))
    return out
def canon(n):
    n = n.replace(",", "")
    return n.rstrip("0").rstrip(".") if "." in n else n
def nums_in(text): return {canon(x) for x in NUM.findall(text.replace("\u2009", ""))}
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("out"); ap.add_argument("--sources", default="")
    ap.add_argument("--keyterms", default=""); ap.add_argument("--skip-stt", action="store_true"); a = ap.parse_args()
    plan = json.load(open(a.plan)); info = json.load(open(os.path.join(a.out, "build_info.json"))); fail = False
    srcs = [p for p in (a.sources.split(",") if a.sources else plan.get("source_text", [])) if p]
    src_nums = set()
    for p in srcs: src_nums |= nums_in(open(p, errors="ignore").read())
    script_nums = set()
    for s in plan["segments"]: script_nums |= nums_in(s.get("narration", "") + " " + s.get("line", ""))
    print(f"== numbers on screen (source files: {len(srcs)})")
    for i, s in enumerate(plan["segments"], 1):
        if s["type"] in ("avatar", "broll"): continue
        if s["type"] == "chart" and not s.get("cite"): print(f"FAIL seg {i}: chart without cite"); fail = True
        for txt in screen_texts(s):
            for n in nums_in(txt):
                if n in src_nums: continue
                if not srcs: print(f"WARN seg {i}: {n!r} not verified (no --sources)"); continue
                if n in script_nums: print(f"WARN seg {i}: {n!r} in script but not in sources ({txt[:50]!r})")
                else: print(f"FAIL seg {i}: {n!r} not in sources or script ({txt[:50]!r})"); fail = True
    print("PASS numbers" if not fail else "numbers: see FAIL lines")
    if not a.skip_stt and os.path.exists(os.path.join(a.out, "manifest.json")):
        print("== avatar STT")
        r = subprocess.run([sys.executable, os.path.join(ROOT, "avatar", "qa_avatar.py"), a.plan, a.out, "--keyterms", a.keyterms], capture_output=True, text=True)
        print(r.stdout.strip()); fail |= r.returncode != 0
    sd = os.path.join(a.out, "stills"); os.makedirs(sd, exist_ok=True)
    for fmt, F in info["formats"].items():
        print(f"== format {fmt}"); f = F["final"]; d = F["duration"]
        ok = abs(d - info["expected"]) <= 0.15; fail |= not ok; print(f"{'PASS' if ok else 'FAIL'} duration {d:.2f}s vs expected {info['expected']:.2f}s")
        log = subprocess.run(["ffmpeg", "-i", f, "-vf", "blackdetect=d=0.3:pix_th=0.05,freezedetect=n=0.001:d=8", "-af", "silencedetect=n=-45dB:d=1.2,ebur128",
                              "-f", "null", "-"], capture_output=True, text=True).stderr
        for k in ("black_start", "freeze_start", "silence_start"):
            c = log.count(k); print(f"{'PASS' if c == 0 else 'FAIL'} {k}: {c}"); fail |= c > 0
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", log); L = float(m[-1]) if m else 0
        ok = abs(L + 16) <= 1.5; fail |= not ok; print(f"{'PASS' if ok else 'FAIL'} loudness {L} LUFS (target -16)")
        for j, u in enumerate(info["timeline"]):
            t = u["t0"] + u["D"] * 0.6
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", f, "-frames:v", "1", os.path.join(sd, f"{fmt}_{j + 1:02}_{u['kind']}.png")])
    if info.get("music"):
        u = info["music"]["under_voice_db"]; ok = 22 <= u <= 30; fail |= not ok
        print(f"{'PASS' if ok else 'FAIL'} music bed {u} dB under voice (target 22-30)")
    print("stills:", sd); print("QA", "FAIL" if fail else "PASS"); sys.exit(1 if fail else 0)
if __name__ == "__main__": main()
