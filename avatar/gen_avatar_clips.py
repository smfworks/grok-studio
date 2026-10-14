#!/usr/bin/env python3
"""Generate avatar clips for every 'avatar' segment (and slide 'pip') in a hybrid plan.json.

usage: gen_avatar_clips.py PLAN.json OUTDIR [--budget 5.0] [--only ID,ID] [--force]

Per segment fields (see SKILL.md):
  id, line (exact words, must restate cited sources only), cite[],
  audio: "imagine" (default) | "ref_voice" | "tts_overlay"
  model (default grok-imagine-video-1.5-lite; ref_voice forces grok-imagine-video-1.5), resolution (720p)
  action: optional body-language hint
Long lines are split at sentence boundaries so each clip is <= 14 s of speech (API cap 15 s).
Each chunk: TTS first (gives exact duration + narrator audio), then Imagine clip with
plan['presenter'] as pinned first frame and the exact line in the prompt (drives lip motion).
Writes OUTDIR/avatar/<id>_<k>.mp4, <id>_<k>.tts.mp3, manifest.json, cost.jsonl.
"""
import argparse, json, math, os, re, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import xai_imagine as X

MAX_SPEECH = 13.5
def dur(p): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",p]).strip())

def split_line(line, est):  # est(text)->seconds
    if est(line) <= MAX_SPEECH: return [line]
    sents = re.split(r"(?<=[.!?])\s+", line.strip()); out, cur = [], ""
    for s in sents:
        cand = (cur + " " + s).strip()
        if cur and est(cand) > MAX_SPEECH: out.append(cur); cur = s
        else: cur = cand
    if cur: out.append(cur)
    return out

def prompt_for(line, action, voice_tag=False, spec="", accent="a natural American accent"):
    who = "<AUDIO_0> " if voice_tag else ""
    return ((f"The presenter in the image ({spec}) " if spec else "The presenter in the image ") + f"looks directly into the camera and speaks clearly in a warm, friendly tone with " + accent + ", "
            f"saying exactly these words in English and nothing else: \"{line}\" "
            f"{action or 'Subtle natural head movement and small hand gestures.'} {who}"
            f"Static locked-off camera, same framing, same lighting, same outfit, plain studio background, no music, no text on screen.")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--budget", type=float, default=5.0); ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    plan = json.load(open(a.plan)); base = os.path.dirname(os.path.abspath(a.plan))
    od = os.path.join(a.out, "avatar"); os.makedirs(od, exist_ok=True)
    cost = os.path.join(a.out, "cost.jsonl"); voice = plan.get("voice", "ursa")
    presenter = os.path.join(base, plan["presenter"]) if not plan["presenter"].startswith("/") else plan["presenter"]
    mpath = os.path.join(a.out, "manifest.json")
    manifest = json.load(open(mpath)) if os.path.exists(mpath) else {}
    segs = [s for s in plan["segments"] if s["type"] == "avatar"]
    segs += [dict(s["pip"], id=s["pip"].get("id", f"pip_{i}"), _pip=True) for i, s in enumerate(plan["segments"]) if s.get("pip")]
    only = set(filter(None, a.only.split(",")))
    # opening line: first avatar segment always starts with plan['opening_line'] (e.g. "Hi, <name> from <brand> here.")
    ol = plan.get("opening_line") or (f"Hi, {plan['presenter_name']} here." if plan.get("presenter_name") else "")
    if ol and segs and not segs[0]["line"].startswith(ol): segs[0]["line"] = ol + " " + segs[0]["line"]
    for s in segs:
        if only and s["id"] not in only: continue
        mode = s.get("audio", plan.get("avatar_audio", "ref_voice"))
        mode = "imagine" if (s.get("_pip") and mode == "ref_voice") else mode  # PiP audio is muted: lite is enough
        model = "grok-imagine-video-1.5" if mode == "ref_voice" else s.get("model", "grok-imagine-video-1.5-lite")
        res = s.get("resolution", "480p" if s.get("_pip") else "720p")
        # TTS each chunk first (cheap) to measure real speech length
        words_ps = 2.6
        chunks = split_line(s["line"], lambda t: len(t.split()) / words_ps)
        entries = []
        for k, line in enumerate(chunks):
            stem = os.path.join(od, f"{s['id']}_{k}"); mp4, mp3 = stem + ".mp4", stem + ".tts.mp3"
            if a.force or not os.path.exists(mp3):
                X.tts(line, stem + ".raw.mp3", voice, language=plan.get("language", "en-US"), cost_log=cost)
                subprocess.run(["ffmpeg","-y","-v","error","-i",stem+".raw.mp3","-af","loudnorm=I=-16:TP=-1.5","-ar","48000",mp3], check=True)
            td = dur(mp3)
            if td > 14.5: sys.exit(f"{s['id']}_{k}: TTS {td:.1f}s exceeds 15 s cap; shorten or add a sentence break")
            secs = min(15, math.ceil(td + 0.8))
            if a.force or not os.path.exists(mp4):
                est = X.VIDEO_PRICE[model][res] * secs
                if X.total_cost(cost) + est > a.budget: sys.exit(f"budget stop before {stem}: spent {X.total_cost(cost):.2f} + {est:.2f} > {a.budget}")
                print(f"gen {s['id']}_{k}: {model} {res} {secs}s mode={mode} (~${est:.2f})", flush=True)
                X.generate_video(prompt_for(line, s.get("action"), mode == "ref_voice", plan.get("presenter_spec", ""), plan.get("accent", "a natural American accent")), mp4, image=presenter, model=model,
                                 duration=secs, resolution=res, cost_log=cost,
                                 reference_audios=[voice] if mode == "ref_voice" else None)
            entries.append({"line": line, "video": mp4, "tts": mp3, "tts_dur": td, "clip_dur": dur(mp4), "mode": mode, "model": model, "res": res})
        manifest[s["id"]] = entries
        json.dump(manifest, open(mpath, "w"), indent=1)
    print(f"spent so far: ${X.total_cost(cost):.2f}")

if __name__ == "__main__": main()
