#!/usr/bin/env python3
"""Generate B-roll clips for 'broll' segments (text-to-video, grok-imagine-video-1.5-lite, muted).

usage: gen_broll.py PLAN.json OUTDIR [--budget USD] [--force]
Segment: {"type":"broll","id","prompt","duration":3-6,"resolution":"480p|720p","narration","cite"}
Segments with "path" (owner footage) are skipped. Prompts get a safety suffix: generic illustrative scene,
no text, letters, logos, brands, watermarks or real people. Spend is checked against cost.jsonl first.
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
import xai_imagine as X
SUFFIX = (" Generic illustrative B-roll, cinematic, slow smooth camera motion. No text, no letters, no numbers, no logos, "
          "no brand names, no watermarks, no screens with readable content, no recognizable real people.")
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--budget", type=float, default=2.0); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    plan = json.load(open(a.plan)); od = os.path.join(a.out, "broll"); os.makedirs(od, exist_ok=True); cost = os.path.join(a.out, "cost.jsonl")
    for s in plan["segments"]:
        if s["type"] != "broll" or s.get("path"): continue
        o = os.path.join(od, f"{s['id']}.mp4")
        if os.path.exists(o) and not a.force: print("exists", o); continue
        model = s.get("model", "grok-imagine-video-1.5-lite"); res = s.get("resolution", "480p"); secs = max(3, min(6, int(s.get("duration", 5))))
        est = X.VIDEO_PRICE[model][res] * secs
        if X.total_cost(cost) + est > a.budget: sys.exit(f"budget stop before {s['id']}: spent {X.total_cost(cost):.2f} + {est:.2f} > {a.budget}")
        print(f"gen broll {s['id']}: {model} {res} {secs}s (~${est:.2f})", flush=True)
        X.generate_video(s["prompt"] + SUFFIX, o, model=model, duration=secs, resolution=res, generate_audio=False, cost_log=cost, aspect_ratio="16:9")
    print(f"spent so far: ${X.total_cost(cost):.2f}")
if __name__ == "__main__": main()
