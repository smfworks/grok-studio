#!/usr/bin/env python3
"""One-page plan summary + cost estimate. Run BEFORE any paid generation and get the owner's OK.

usage: plan_summary.py PLAN.json [OUTDIR]   (OUTDIR: clips already in manifest.json / broll/ count as reused, $0)
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(os.path.dirname(HERE), "common"))
import xai_imagine as X
WPS = 2.6
def secs(text): return len(text.split()) / WPS
def main():
    plan = json.load(open(sys.argv[1])); out = sys.argv[2] if len(sys.argv) > 2 else None
    man = json.load(open(os.path.join(out, "manifest.json"))) if out and os.path.exists(os.path.join(out, "manifest.json")) else {}
    mode = plan.get("avatar_audio", "ref_voice"); tot = 0.0; usd = {"avatar": 0.0, "pip": 0.0, "broll": 0.0, "tts": 0.0}; chars = 0
    rows = []
    for i, s in enumerate(plan["segments"], 1):
        cites = ",".join(s.get("cite", [])) or "MISSING"
        if s["type"] == "avatar":
            d = secs(s["line"]) + 1.0; m = "grok-imagine-video-1.5" if s.get("audio", mode) == "ref_voice" else "grok-imagine-video-1.5-lite"
            c = 0 if s["id"] in man else X.VIDEO_PRICE[m][s.get("resolution", "720p")] * min(15, d + 0.8); usd["avatar"] += c; chars += len(s["line"])
            rows.append((i, "avatar", s["id"], d, cites, ("reused" if s["id"] in man else f"{m} ${c:.2f}"), s["line"]))
        elif s["type"] == "broll":
            d = secs(s["narration"]) + 0.6; owned = s.get("path"); have = out and os.path.exists(os.path.join(out, "broll", f"{s['id']}.mp4"))
            c = 0 if owned or have else X.VIDEO_PRICE[s.get("model", "grok-imagine-video-1.5-lite")][s.get("resolution", "480p")] * max(3, min(6, int(s.get("duration", 5)))); usd["broll"] += c; chars += len(s["narration"])
            rows.append((i, "broll", s["id"], d, cites, "owner footage: " + s.get("credit", "?") if owned else ("reused" if have else f"lite ${c:.2f}"), s.get("prompt", "")))
        else:
            d = secs(s["narration"]) + 0.6; chars += len(s["narration"]); extra = ""
            if s.get("pip"):
                p = s["pip"]; c = 0 if p["id"] in man else X.VIDEO_PRICE["grok-imagine-video-1.5-lite"]["480p"] * (secs(p["line"]) + 1.8); usd["pip"] += c
                extra = f" +PiP {p['id']} ({'reused' if p['id'] in man else f'${c:.2f}'})"
            if s["type"] == "chart": extra += f" chart:{s.get('chart', 'bar')} {len(s.get('data', []))} values"
            rows.append((i, s["type"], s.get("heading", "")[:40], d, cites, "TTS" + extra, s["narration"][:90]))
        tot += d
    usd["tts"] = chars * X.TTS_PRICE_PER_CHAR
    print(f"PLAN: {plan.get('title', '')}\nvoice {plan.get('voice', 'ursa')} / {plan.get('language', 'en-US')}   avatar audio {mode}   "
          f"music {plan.get('music', True)}   formats {','.join(plan.get('formats', ['16x9']))}\n")
    print(f"{'#':>2} {'type':8} {'id/heading':40} {'sec':>5}  cite     paid")
    for i, t, h, d, c, p, txt in rows: print(f"{i:>2} {t:8} {h[:40]:40} {d:5.1f}  {c:8} {p}\n      \u201c{txt[:110]}\u201d")
    print(f"\nEstimated runtime ~{tot:.0f} s ({tot / 60:.1f} min)")
    print("Estimated new spend: " + ", ".join(f"{k} ${v:.2f}" for k, v in usd.items()) + f"  TOTAL ${sum(usd.values()):.2f}")
    miss = [r for r in rows if r[4] == "MISSING"]
    if miss: print("WARNING: segments without cite:", [r[0] for r in miss])
    print("\nOWNER APPROVAL NEEDED before paid generation (avatar clips, B-roll). Nothing is uploaded by these scripts.")
if __name__ == "__main__": main()
