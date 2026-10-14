#!/usr/bin/env python3
"""Grok Studio v2 builder: kinetic slides + avatar + B-roll/footage + music bed + multi-format export.

usage: build.py PLAN.json OUTDIR [--formats 16x9,9x16,1x1] [--no-music]

Segment types (plan["segments"], in order):
  slide types  title | bullets | steps | quad | cards | quote | stat | chart   (narration + cite required)
               chart: {"chart":"bar|line|donut","data":[{"label","value","display"?}],"max"?,"cite":[...]}
               optional "pip": {"id",...} reusing an avatar clip from manifest.json (gen_avatar_clips.py)
  avatar       {"id","line","cite"}       clip(s) from manifest.json
  broll        {"id","narration","cite","prompt"|"path","credit"?}  muted video under TTS narration
               generated clips come from gen_broll.py (broll/<id>.mp4); owner footage uses "path" + "credit"
Plan-level: voice (default ursa), language (en-US), theme{...} (see kinetic.py), music (true | false | "path.wav"),
  formats ["16x9",...] (CLI overrides).
Outputs per format: OUTDIR/video_<fmt>.mp4 (+ video.mp4 = first format), captions_<fmt>.ass, script.md,
  sources.md, build_info.json (timeline, expected duration, music level) for qa_studio.py.
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, textwrap
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "common"))
import xai_imagine as X, kinetic as K
from fonts import find_font
FORMATS = {"16x9": (1920, 1080), "9x16": (1080, 1920), "1x1": (1080, 1080)}
FPS, XF, PAD = 30, 0.5, 0.6
SLIDE_TYPES = {"title", "bullets", "steps", "quad", "cards", "quote", "stat", "chart"}

def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    if r.returncode: sys.exit(f"cmd failed: {c[:400]}\n{r.stderr[-1500:]}")
    return r.stdout + r.stderr
def dur(p): return float(sh(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"').strip())
def silence_bounds(media):
    out = sh(f'ffmpeg -i "{media}" -af silencedetect=n=-35dB:d=0.2 -f null - 2>&1 || true'); total = dur(media)
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]; en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    start = max(0.0, en[0] - 0.15) if st and st[0] <= 0.05 and en else 0.0
    end = st[-1] if st and (len(en) < len(st) or en[-1] >= total - 0.08) and st[-1] > start + 0.3 else total
    return start, end
def lufs(path):
    out = sh(f'ffmpeg -i "{path}" -af ebur128 -f null - 2>&1 || true'); m = re.findall(r"I:\s+(-?[\d.]+) LUFS", out)
    return float(m[-1]) if m else None
NORM = "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11"

def conform(W, H, kind="avatar"):
    """ffmpeg filter that re-lays-out a 16:9 video for the target frame (not a plain crop for 9:16)."""
    if W / H > 1.5 or abs(W - H) < 10:
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    fw, fh = W, int(W * 5 / 4) // 2 * 2; fy = int(H * 0.07)
    return (f"split[a][b];[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:3,eq=brightness=-0.12[bg];"
            f"[b]crop=ih*4/5:ih,scale={fw}:{fh},setsar=1[fg];[bg][fg]overlay=0:{fy}")

def tag_filter(text_path, W, H, font):
    s = min(W, H) / 1080
    return (f"drawtext=fontfile={font}:textfile={text_path}:x={int(40 * s)}:y={int(36 * s)}:fontsize={int(28 * s)}:"
            f"fontcolor=white@0.9:box=1:boxcolor=black@0.45:boxborderw={int(12 * s)}")

def voice_tts(plan, text, out_dir, cost):
    key = hashlib.sha1((plan.get("voice", "ursa") + plan.get("language", "en-US") + text).encode()).hexdigest()[:12]
    mp3, wav, js = f"{out_dir}/{key}.mp3", f"{out_dir}/{key}.wav", f"{out_dir}/{key}.words.json"
    if not os.path.exists(js):
        words = X.tts_timed(text, mp3, plan.get("voice", "ursa"), plan.get("language", "en-US"), cost_log=cost)
        json.dump(words, open(js, "w"))
        sh(f'ffmpeg -y -v error -i "{mp3}" -af "{NORM}" "{wav}"')
    return wav, json.load(open(js))

def caption_chunks(words, t0, maxc):
    out, cur = [], []
    for w in words:
        if cur and (len(" ".join(x["w"] for x in cur + [w])) > maxc or re.search(r"[.!?]$", cur[-1]["w"])):
            out.append((t0 + cur[0]["start"], t0 + cur[-1]["end"], " ".join(x["w"] for x in cur))); cur = []
        cur.append(w)
    if cur: out.append((t0 + cur[0]["start"], t0 + cur[-1]["end"], " ".join(x["w"] for x in cur)))
    # hold each caption until the next starts (no flicker), max +0.6 s
    return [(a, min(b + 0.6, out[i + 1][0]) if i + 1 < len(out) else b + 0.4, c) for i, (a, b, c) in enumerate(out)]

def fake_words(text, start, length):
    ws = text.split(); tot = sum(len(w) + 1 for w in ws) or 1; t = start; out = []
    for w in ws: d = length * (len(w) + 1) / tot; out.append({"w": w, "start": t, "end": t + d * 0.9}); t += d
    return out

def ass(caps, W, H, path, font_name):
    s = min(W, H) / 1080; portrait = H > W * 1.2; square = abs(W - H) < 10
    size = int((50 if portrait else 44 if square else 40) * s); mv = int(H * (0.24 if portrait else 0.135 if square else 0.105))
    def t(x): h = int(x // 3600); m = int(x % 3600 // 60); return f"{h}:{m:02}:{x % 60:05.2f}"
    with open(path, "w") as f:
        f.write(f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 0\n\n[V4+ Styles]\n"
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
                f"Style: Default,{font_name},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,1,0,0,0,100,100,0,0,3,{max(2, int(10 * s))},0,2,{int(90 * s)},{int(90 * s)},{mv},1\n\n"
                "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        for a, b, c in caps: f.write(f"Dialogue: 0,{t(a)},{t(b)},Default,,0,0,0,,{c}\n")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("plan"); ap.add_argument("out")
    ap.add_argument("--formats", default=None); ap.add_argument("--no-music", action="store_true"); a = ap.parse_args()
    plan = json.load(open(a.plan)); out = os.path.abspath(a.out); os.makedirs(out, exist_ok=True)
    fmts = (a.formats or ",".join(plan.get("formats", ["16x9"]))).split(",")
    for f in fmts:
        if f not in FORMATS: sys.exit(f"unknown format {f}; use {list(FORMATS)}")
    cost = os.path.join(out, "cost.jsonl"); adir = os.path.join(out, "audio"); os.makedirs(adir, exist_ok=True)
    man = json.load(open(os.path.join(out, "manifest.json"))) if os.path.exists(os.path.join(out, "manifest.json")) else {}
    font = os.path.join(out, "_font.ttf"); shutil.copy(K.Theme(plan).font_path, font)
    font_name = plan.get("caption_font", "Inter")
    segs = plan["segments"]; slides = [s for s in segs if s["type"] in SLIDE_TYPES]; n_sl = len(slides)
    # 1) audio + timing, shared by every format
    units = []  # each: dict(kind, seg, D, audio(wav or None), words, video, ss)
    for i, s in enumerate(segs):
        last = i == len(segs) - 1; tail = 0 if last else XF
        if s["type"] == "avatar":
            if s["id"] not in man: sys.exit(f"avatar segment {s['id']} missing from manifest.json: run avatar/gen_avatar_clips.py first")
            for e in man[s["id"]]:
                v = e["video"] if os.path.isabs(e["video"]) else os.path.join(out, e["video"])
                if s.get("audio") == "tts_overlay":
                    wav, words = voice_tts(plan, e["line"], adir, cost); st, D = 0.0, dur(wav) + PAD + tail; aud = wav
                else:
                    st, en = silence_bounds(v); D = min(dur(v) - st, en - st + PAD + tail); aud = None
                    words = fake_words(e["line"], 0.1, en - st - 0.1)
                units.append(dict(kind="avatar", seg=s, D=D, audio=aud, words=words, video=v, ss=st, line=e["line"]))
        elif s["type"] == "broll":
            wav, words = voice_tts(plan, s["narration"], adir, cost); D = dur(wav) + PAD + tail
            v = s.get("path") or os.path.join(out, "broll", f"{s['id']}.mp4")
            if not os.path.exists(v): sys.exit(f"b-roll {s['id']} missing ({v}): run studio/gen_broll.py or set 'path'")
            units.append(dict(kind="broll", seg=s, D=D, audio=wav, words=words, video=v, ss=0.0))
        else:
            wav, words = voice_tts(plan, s["narration"], adir, cost); D = dur(wav) + PAD + tail
            units.append(dict(kind="slide", seg=s, D=D, audio=wav, words=words, idx=slides.index(s) + 1))
    t, timeline = 0.0, []
    for u in units: u["t0"] = t; timeline.append({"kind": u["kind"], "id": u["seg"].get("id", u["seg"].get("heading", "")), "t0": round(t, 3), "D": round(u["D"], 3)}); t += u["D"] - XF
    expected = t + XF
    # 2) per-format video segments
    info = {"formats": {}, "timeline": timeline, "expected": round(expected, 3)}
    for fmt in fmts:
        W, H = FORMATS[fmt]; sd = os.path.join(out, "seg_" + fmt); os.makedirs(sd, exist_ok=True); files = []
        caps = []; maxc = 34 if H > W * 1.2 else 44 if W == H else 80
        for k, u in enumerate(units):
            s = u["seg"]; o = f"{sd}/{k:02}_{u['kind']}.mkv"; D = u["D"]
            caps += caption_chunks(u["words"], u["t0"] + (0 if u["kind"] != "avatar" or u["audio"] else 0), maxc)
            if u["kind"] == "slide":
                K.render_slide(plan, s, u["idx"], n_sl, W, H, D, u["words"], o, audio=u["audio"])
                if s.get("pip") and s["pip"]["id"] in man:
                    pe = man[s["pip"]["id"]][0]; pv = pe["video"] if os.path.isabs(pe["video"]) else os.path.join(out, pe["video"])
                    sc = min(W, H) / 1080; pw = int((s["pip"].get("width", 380) if W > H * 1.2 else 0.34 * W if H > W else 0.28 * W) * (1 if W > H * 1.2 else 1)) // 2 * 2
                    pos = (s["pip"].get("position", "W-w-56:H-h-210") if W > H * 1.2 else f"W-w-{int(50*sc)}:{int(H*0.78)}" if H > W else f"W-w-{int(36*sc)}:{int(24*sc)}")
                    pd = min(dur(pv), D - 0.3); o2 = o.replace(".mkv", "_pip.mkv")
                    sh(f'ffmpeg -y -v error -i "{o}" -i "{pv}" -filter_complex "[1:v]scale={pw}:-2,fps={FPS},trim=0:{pd:.3f},setpts=PTS-STARTPTS,pad=iw+8:ih+8:4:4:color=white,format=yuva420p,'
                       f'fade=t=in:st=0:d=0.4:alpha=1,fade=t=out:st={pd - 0.5:.3f}:d=0.5:alpha=1[p];[0:v][p]overlay={pos}:eof_action=pass,format=yuv420p[v]" -map "[v]" -map 0:a '
                       f'-c:v libx264 -preset veryfast -crf 17 -c:a copy "{o2}"'); os.replace(o2, o)
            else:
                tagf = f"{sd}/{k:02}.tag.txt"; label = "Source: " + ", ".join(f"[{c}]" for c in s.get("cite", []))
                if u["kind"] == "broll": label = (s.get("credit") or "AI-generated illustrative footage") + "  ·  " + label
                open(tagf, "w").write(label)
                vin = f'-ss {u["ss"]:.3f} -i "{u["video"]}"'
                if u["kind"] == "broll":
                    vd = dur(u["video"]); slow = min(1.6, max(1.0, D / max(0.1, vd)))
                    vf = f"[0:v]setpts={slow:.3f}*PTS,{conform(W, H, 'broll')},fps={FPS},tpad=stop_mode=clone:stop_duration={D:.2f},{tag_filter(tagf, W, H, font)},format=yuv420p[v]"
                else:
                    vf = f"[0:v]{conform(W, H)},fps={FPS},{tag_filter(tagf, W, H, font)},format=yuv420p[v]"
                if u["audio"]: ain = f'-i "{u["audio"]}"'; af = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{D:.3f}[a]"
                else: ain = ""; af = f"[0:a]{NORM},apad,atrim=0:{D:.3f}[a]"
                sh(f'ffmpeg -y -v error {vin} {ain} -filter_complex "{vf};{af}" -map "[v]" -map "[a]" -t {D:.3f} -c:v libx264 -preset veryfast -crf 17 -pix_fmt yuv420p -r {FPS} -c:a pcm_s16le "{o}"')
            files.append(o)
        # pairwise crossfade merge (low memory)
        acc, acc_d = files[0], units[0]["D"]
        for i in range(1, len(files)):
            nxt = f"{sd}/merge_{i:02}.mkv"
            sh(f'ffmpeg -y -v error -i "{acc}" -i "{files[i]}" -filter_complex "[0:v]settb=1/30000,fps={FPS}[a0];[1:v]settb=1/30000,fps={FPS}[b0];[a0][b0]xfade=transition=fade:duration={XF}:offset={acc_d - XF:.3f}[v];[0:a][1:a]acrossfade=d={XF}[a]" '
               f'-map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 16 -pix_fmt yuv420p -c:a pcm_s16le "{nxt}"')
            if i > 1: os.remove(f"{sd}/merge_{i - 1:02}.mkv")
            acc = nxt; acc_d += units[i]["D"] - XF
        cap_path = os.path.join(out, f"captions_{fmt}.ass"); ass(caps, W, H, cap_path, font_name)
        info["formats"][fmt] = {"merged": acc, "captions": cap_path, "size": [W, H]}
    # 3) audio mix once (identical across formats): voice + ducked music
    first = info["formats"][fmts[0]]["merged"]; voice = os.path.join(out, "voice.wav")
    sh(f'ffmpeg -y -v error -i "{first}" -vn -c:a pcm_s16le "{voice}"')
    music = plan.get("music", True) and not a.no_music; mix = voice; info["music"] = None
    if music:
        bed = music if isinstance(music, str) else os.path.join(out, "music_bed.wav")
        if not isinstance(music, str): sh(f'python3 "{HERE}/music.py" "{bed}" {expected:.2f} --seed {plan.get("music_seed", 7)}')
        target = plan.get("music_under_voice_db", 26); gain = 0.0; ducked = os.path.join(out, "music_ducked.wav")
        vl = lufs(voice)
        for _ in range(3):
            sh(f'ffmpeg -y -v error -i "{voice}" -stream_loop -1 -i "{bed}" -filter_complex "[1:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain:.2f}dB,atrim=0:{expected:.3f}[m];'
               f'[0:a]aformat=channel_layouts=stereo[sc];[m][sc]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=450[d]" -map "[d]" -t {expected:.3f} "{ducked}"')
            ml = lufs(ducked); diff = vl - ml
            if abs(diff - target) <= 1.5: break
            gain += diff - target
        mix = os.path.join(out, "mix.wav")
        sh(f'ffmpeg -y -v error -i "{voice}" -i "{ducked}" -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95[a]" -map "[a]" "{mix}"')
        info["music"] = {"bed": bed, "voice_lufs": vl, "music_ducked_lufs": ml, "under_voice_db": round(diff, 1), "gain_db": round(gain, 1)}
    # 4) final mux per format with burned captions
    for fmt in fmts:
        F = info["formats"][fmt]; final = os.path.join(out, f"video_{fmt}.mp4"); fontsdir = os.path.dirname(K.Theme(plan).font_path)
        sh(f'ffmpeg -y -v error -i "{F["merged"]}" -i "{mix}" -filter_complex "[0:v]subtitles={F["captions"]}:fontsdir=\'{fontsdir}\'[v]" -map "[v]" -map 1:a '
           f'-c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -movflags +faststart -shortest "{final}"')
        F["final"] = final; F["duration"] = dur(final)
    shutil.copy(info["formats"][fmts[0]]["final"], os.path.join(out, "video.mp4"))
    with open(os.path.join(out, "script.md"), "w") as f:
        f.write(f"# {plan.get('title', '')}\n\nVoice: xai-tts:{plan.get('voice', 'ursa')} ({plan.get('language', 'en-US')})\n\n")
        for i, s in enumerate(segs, 1):
            cites = ", ".join(f"[{c}]" for c in s.get("cite", []))
            text = s.get("line") or s.get("narration", "")
            extra = f" — {s.get('credit') or 'AI-generated illustrative footage'}" if s["type"] == "broll" else ""
            f.write(f"## {i}. {s['type']}{extra} — cites {cites}\n\n{text}\n\n")
    with open(os.path.join(out, "sources.md"), "w") as f:
        f.write("# Sources\n\n" + (f"Primary: {plan['source_post']}\n\n" if plan.get("source_post") else ""))
        for k2, v2 in plan["sources"].items(): f.write(f"- [{k2}] {v2}\n")
        for s in segs:
            if s["type"] == "broll": f.write(f"- B-roll {s['id']}: {s.get('credit') or 'AI-generated with Grok Imagine (illustrative, not documentary)'}\n")
        if info["music"]: f.write("- Music: original procedural ambient bed generated by Grok Studio (no third-party material)\n" if not isinstance(plan.get("music"), str) else f"- Music: {plan['music']}\n")
    json.dump(info, open(os.path.join(out, "build_info.json"), "w"), indent=1)
    for fmt in fmts: print(f"{fmt}: {info['formats'][fmt]['final']} {info['formats'][fmt]['duration']:.2f}s (expected {expected:.2f}s)")
    if info["music"]: print("music under voice:", info["music"]["under_voice_db"], "dB")

if __name__ == "__main__": main()
