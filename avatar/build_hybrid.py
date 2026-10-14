#!/usr/bin/env python3
"""Build the hybrid avatar + slide explainer from a plan.json and the manifest written by gen_avatar_clips.py.

usage: build_hybrid.py PLAN.json OUTDIR

segments[]:
  {"type":"avatar", id, line, cite[], audio}   -> full-frame presenter clip(s)
  any other type                               -> slide; rendered with the source-grounded builder's renderer
      unless slide_png given; narration audio from audio_file or fresh xAI TTS; optional "pip" (avatar overlay)
Audio per avatar mode: "imagine"/"ref_voice" = clip's own lip-synced speech; "tts_overlay" = narrator TTS laid on the
muted clip. Everything normalised to 1920x1080, 30 fps, yuv420p, 48 kHz stereo AAC, -16 LUFS; 0.5 s crossfades;
burned-in captions; every segment shows its citation tag. Writes hybrid.mp4, captions.srt, script.md, sources.md.
"""
import json, os, re, shutil, subprocess, sys, textwrap
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(ROOT, "common")); sys.path.insert(0, os.path.join(ROOT, "explainer"))
from fonts import find_font
import xai_imagine as X
W, H, FPS, XF, PAD = 1920, 1080, 30, 0.5, 0.6
FONT = os.path.join(os.environ.get("TMPDIR", "/tmp"), "grok_studio_font.ttf")
def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    if r.returncode: sys.exit(f"cmd failed: {c[:300]}\n{r.stderr[-1500:]}")
    return r.stdout + r.stderr
def dur(p): return float(sh(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"').strip())
def ts(t): h, m = int(t // 3600), int(t % 3600 // 60); s = t % 60; return f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")
def speech_end(audio):
    out = sh(f'ffmpeg -i "{audio}" -af silencedetect=n=-35dB:d=0.3 -f null - 2>&1 || true')
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]; ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    total = dur(audio)
    if starts and (len(ends) < len(starts) or ends[-1] >= total - 0.08): return starts[-1]
    return total
def speech_start(audio):
    out = sh(f'ffmpeg -i "{audio}" -af silencedetect=n=-35dB:d=0.2 -f null - 2>&1 || true')
    st = re.findall(r"silence_start: (-?[\d.]+)", out); en = re.findall(r"silence_end: ([\d.]+)", out)
    return max(0.0, float(en[0]) - 0.15) if st and float(st[0]) <= 0.05 and en else 0.0
def cite_tag(seg, path):
    open(path, "w").write("Source: " + ", ".join(f"[{c}]" for c in seg.get("cite", [])))
    return f"drawtext=fontfile={FONT}:textfile={path}:x=48:y=40:fontsize=30:fontcolor=white@0.85:box=1:boxcolor=black@0.45:boxborderw=12"
NORM_A = "aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-16:TP=-1.5:LRA=11"
ENC = "-c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -r 30 -c:a aac -b:a 192k -ar 48000"

def main(plan_path, out):
    if not os.path.exists(os.path.join(out, "manifest.json")): sys.exit("run gen_avatar_clips.py PLAN OUTDIR first (manifest.json missing)")
    plan = json.load(open(plan_path)); base = os.path.dirname(os.path.abspath(plan_path))
    man = json.load(open(os.path.join(out, "manifest.json")))
    font_src = find_font()
    shutil.copy(font_src, FONT); seg_dir = os.path.join(out, "segments"); os.makedirs(seg_dir, exist_ok=True)
    clips, durs, caps, t0 = [], [], [], 0.0
    def add_caps(text, start, length):
        chunks = textwrap.wrap(text, 90); tot = sum(map(len, chunks)) or 1; cur = start + 0.15
        for c in chunks: L = length * len(c) / tot; caps.append((cur, cur + L, c)); cur += L
    n = len(plan["segments"]); k = 0
    for si, s in enumerate(plan["segments"]):
        last = si == n - 1
        if s["type"] == "avatar":
            for e in man[s["id"]]:
                k += 1; o = f"{seg_dir}/{k:02}_{s['id']}.mp4"; tag = cite_tag(s, f"{seg_dir}/{k:02}.cite.txt")
                ss = 0.0
                if s.get("audio", e["mode"]) == "tts_overlay":
                    a_src, sp = e["tts"], e["tts_dur"]; amap = "[1:a]"; extra_in = f'-i "{e["tts"]}"'
                else:
                    a_src = e["video"]; ss = speech_start(e["video"]); sp = speech_end(e["video"]) - ss; amap = "[0:a]"; extra_in = ""
                D = min(e["clip_dur"] - ss, sp + PAD + (0 if last else XF))
                sh(f'ffmpeg -y -ss {ss:.3f} -i "{e["video"]}" {extra_in} -filter_complex "[0:v]scale={W}:{H}:flags=lanczos,fps={FPS},setsar=1,{tag},format=yuv420p[v];{amap}{NORM_A},apad,atrim=0:{D:.3f}[a]" -map "[v]" -map "[a]" -t {D:.3f} {ENC} "{o}"')
                add_caps(e["line"], t0, sp); clips.append(o); durs.append(D); t0 += D - XF
        else:
            k += 1; o = f"{seg_dir}/{k:02}_slide.mp4"
            png = s.get("slide_png"); mp3 = s.get("audio_file")
            if not png:
                import build_explainer as B; png = f"{seg_dir}/{k:02}.png"; B.render(plan, s, k, n, png)
            if not mp3:
                mp3 = f"{seg_dir}/{k:02}.mp3"; X.tts(s["narration"], mp3, plan.get("voice", "ursa"), language=plan.get("language", "en-US"), cost_log=os.path.join(out, "cost.jsonl"))
            a = dur(mp3); D = a + PAD + (0 if last else XF)
            v = f"[0:v]scale={W}:{H},setsar=1,fps={FPS}"
            inputs = f'-loop 1 -i "{png}" -i "{mp3}"'
            if s.get("pip"):
                e = man[s["pip"].get("id")][0]; pd = min(e["clip_dur"], a)
                pw = s["pip"].get("width", 360)  # default sits top-right above the slide's content area
                pos = {"top-right": "W-w-40:24", "bottom-right": "W-w-48:H-h-150", "top-left": "40:24"}.get(s["pip"].get("position", "top-right"), s["pip"].get("position"))
                inputs += f' -i "{e["video"]}"'
                v += (f"[bg];[2:v]scale={pw}:-2,fps={FPS},trim=0:{pd:.3f},setpts=PTS-STARTPTS,"
                      f"pad=iw+8:ih+8:4:4:color=0xF7B538,format=yuva420p,fade=t=in:st=0:d=0.4:alpha=1,fade=t=out:st={pd-0.5:.3f}:d=0.5:alpha=1[pip];"
                      f"[bg][pip]overlay={pos}:eof_action=pass")
            sh(f'ffmpeg -y {inputs} -filter_complex "{v},format=yuv420p[v];[1:a]{NORM_A},apad,atrim=0:{D:.3f}[a]" -map "[v]" -map "[a]" -t {D:.3f} {ENC} "{o}"')
            add_caps(re.sub(r"\b([A-Z]) (?=[A-Z]\b)", r"\1", s.get("caption", s["narration"])), t0, a)
            clips.append(o); durs.append(D); t0 += D - XF
    srt = os.path.join(out, "captions.srt")
    with open(srt, "w") as f:
        for i, (a, b, c) in enumerate(caps, 1): f.write(f"{i}\n{ts(a)} --> {ts(b)}\n{c}\n\n")
    # Pairwise crossfade merge: low memory (a single ffmpeg graph with 10+ 1080p inputs can exceed 5 GB RAM).
    final = os.path.join(out, "hybrid.mp4"); acc, acc_d = clips[0], durs[0]
    for i in range(1, len(clips)):
        nxt = f"{seg_dir}/merge_{i:02}.mkv"
        sh(f'ffmpeg -y -i "{acc}" -i "{clips[i]}" -filter_complex "[0:v]settb=1/30000,fps=30[a0];[1:v]settb=1/30000,fps=30[b0];[a0][b0]xfade=transition=fade:duration={XF}:offset={acc_d - XF:.3f}[v];[0:a][1:a]acrossfade=d={XF}[a]" -map "[v]" -map "[a]" -c:v libx264 -preset veryfast -crf 14 -pix_fmt yuv420p -c:a pcm_s16le -threads 4 "{nxt}"')
        acc = nxt; acc_d = acc_d + durs[i] - XF
        if i > 1: os.remove(f"{seg_dir}/merge_{i-1:02}.mkv")
    sh(f'ffmpeg -y -i "{acc}" -vf "subtitles={srt}:force_style=\'FontName=Inter,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=36\'" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -ar 48000 -threads 4 -movflags +faststart "{final}"')
    with open(os.path.join(out, "script.md"), "w") as f:
        f.write(f"# {plan['title']} (avatar hybrid)\n\nNarrator voice: xai-tts:{plan.get("voice","ursa")}\n\n")
        for i, s in enumerate(plan["segments"], 1):
            cites = ", ".join(f"[{c}]" for c in s.get("cite", []))
            if s["type"] == "avatar": f.write(f"## {i}. Avatar: {s['id']} ({s.get('audio', plan.get('avatar_audio','ref_voice'))}) — cites {cites}\n\n{s['line']}\n\n")
            else: f.write(f"## {i}. Slide ({s['type']}){' + PiP' if s.get('pip') else ''} — cites {cites}\n\n{s['narration']}\n\n")
    with open(os.path.join(out, "sources.md"), "w") as f:
        f.write("# Sources\n\n" + (f"Primary: {plan['source_post']}\n\n" if plan.get("source_post") else ""))
        for kk, vv in plan["sources"].items(): f.write(f"- [{kk}] {vv}\n")
    exp = sum(durs) - XF * (len(durs) - 1)
    print(f"done: {final} duration={dur(final):.2f}s expected={exp:.2f}s")

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
    main(sys.argv[1], sys.argv[2])
