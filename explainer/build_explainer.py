#!/usr/bin/env python3
"""Source-grounded explainer video builder.
Usage: build_explainer.py plan.json OUTDIR
plan.json: {title, brand, voice, sources:{id:label}, slides:[{type,heading,...,cite:[ids],narration}]}
Slide types: title, bullets, quote, stat, quad, steps.
Outputs: OUTDIR/explainer.mp4, captions.srt, slides/*.png, audio/*.mp3, script.md, sources.md
TTS engine (env TTS or plan "tts"): "xai" (default; xAI Grok voice, plan "voice" default "ursa", "language" default "en-US"),
"edge" (edge-tts, plan voice e.g. en-US-AndrewMultilingualNeural), "piper" (local; set PIPER_VOICE=/path/model.onnx).
Needs: ffmpeg, Pillow; XAI_API_KEY for xai TTS. Fonts: Inter + IBM Plex Serif if installed (GROK_STUDIO_FONT to override), else DejaVu.
"""
import re, json, os, subprocess, sys, glob, textwrap
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
BG = (14, 20, 36); BG2 = (24, 34, 60); ACC = (247, 181, 56); FG = (240, 242, 248); MUT = (150, 160, 185)
import sys as _s, os as _o
_s.path.insert(0, _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "common"))
from fonts import find_font, find_serif_font

def font(size, weight="Regular", serif=False):
    try:
        if serif:
            return ImageFont.truetype(find_serif_font(), size)
        f = ImageFont.truetype(find_font(), size)
        try: f.set_variation_by_name(weight)
        except Exception: pass
        return f
    except Exception:
        return ImageFont.truetype("DejaVuSans-Bold.ttf" if weight != "Regular" else "DejaVuSans.ttf", size)

def wrap(d, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def base(plan, s, idx, n):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for y in range(H):  # vertical gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=tuple(int(BG[i] * (1 - t) + BG2[i] * t) for i in range(3)))
    d.rectangle([0, 0, 18, H], fill=ACC)
    d.text((120, 70), plan.get("brand", "").upper(), font=font(28, "Bold"), fill=ACC)
    d.text((W - 120, 70), f"{idx}/{n}", font=font(28, "Medium"), fill=MUT, anchor="ra")
    cites = s.get("cite", [])
    if cites:
        txt = "Source: " + "  ·  ".join(f"[{c}] {plan['sources'].get(c, c)}" for c in cites)
        f = font(24)
        lines = wrap(d, txt, f, W - 240)[:2]
        y = H - 60 - 34 * len(lines)
        d.line([(120, y - 20), (W - 120, y - 20)], fill=(60, 72, 100), width=2)
        for i, l in enumerate(lines): d.text((120, y + 34 * i), l, font=f, fill=MUT)
    return im, d

def heading(d, text, y=170):
    f = font(76, "ExtraBold")
    for i, l in enumerate(wrap(d, text, f, W - 240)):
        d.text((120, y + i * 92), l, font=f, fill=FG)
    return y + 92 * len(wrap(d, text, f, W - 240)) + 40

def render(plan, s, idx, n, path):
    im, d = base(plan, s, idx, n); t = s["type"]
    if t == "title":
        f = font(110, "ExtraBold"); lines = wrap(d, s["heading"], f, W - 300)
        y = 330
        for l in lines: d.text((120, y), l, font=f, fill=FG); y += 128
        d.rectangle([120, y + 20, 360, y + 30], fill=ACC)
        d.text((120, y + 70), s.get("sub", ""), font=font(46), fill=MUT)
    elif t == "bullets":
        y = heading(d, s["heading"]) + 20; f = font(52, "Medium")
        for b in s["bullets"]:
            d.ellipse([130, y + 22, 152, y + 44], fill=ACC)
            for j, l in enumerate(wrap(d, b, f, W - 400)):
                d.text((190, y), l, font=f, fill=FG); y += 68
            y += 34
    elif t == "quote":
        d.text((120, 200), "\u201C", font=font(300, serif=True), fill=ACC)
        f = font(80, serif=True); y = 400
        for l in wrap(d, s["quote"], f, W - 400): d.text((220, y), l, font=f, fill=FG); y += 104
        d.text((220, y + 40), "— " + s.get("attr", ""), font=font(40, "Medium"), fill=MUT)
    elif t == "stat":
        y = heading(d, s["heading"]) + 30; k = len(s["stats"]); gap = 50
        cw = (W - 240 - gap * (k - 1)) // k
        for i, (big, lab) in enumerate(s["stats"]):
            x = 120 + i * (cw + gap)
            d.rounded_rectangle([x, y, x + cw, y + 400], 28, fill=(30, 42, 72))
            d.text((x + 50, y + 50), big, font=font(130 if k < 3 else 100, "ExtraBold"), fill=ACC)
            for j, l in enumerate(wrap(d, lab, font(38), cw - 100)):
                d.text((x + 50, y + 230 + j * 50), l, font=font(38), fill=FG)
        if s.get("note"): d.text((120, y + 440), s["note"], font=font(32), fill=MUT)
    elif t == "quad":
        y0 = heading(d, s["heading"]); gw, gh = (W - 240 - 40) // 2, 270
        for i, (a, b) in enumerate(s["items"]):
            x = 120 + (i % 2) * (gw + 40); y = y0 + (i // 2) * (gh + 30)
            hi = i == 2
            d.rounded_rectangle([x, y, x + gw, y + gh], 24, fill=(52, 44, 20) if hi else (30, 42, 72), outline=ACC if hi else None, width=4)
            d.text((x + 44, y + 50), a, font=font(54, "Bold"), fill=ACC if hi else FG)
            d.text((x + 44, y + 140), b, font=font(40), fill=FG if hi else MUT)
    elif t == "steps":
        y = heading(d, s["heading"]) + 10; f = font(46, "Medium")
        for i, st in enumerate(s["steps"]):
            d.ellipse([120, y, 196, y + 76], fill=ACC)
            d.text((158, y + 38), str(i + 1), font=font(42, "ExtraBold"), fill=BG, anchor="mm")
            ls = wrap(d, st, f, W - 420)
            for j, l in enumerate(ls): d.text((230, y + 10 + j * 60), l, font=f, fill=FG)
            y += max(110, 60 * len(ls) + 50)
    im.save(path)

def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if r.returncode: sys.exit(f"FAILED: {cmd}\n{r.stderr[-2000:]}")
    return r.stdout

def dur(p): return float(sh(f'ffprobe -v error -show_entries format=duration -of csv=p=0 "{p}"').strip())

def ts(t):
    h, m = int(t // 3600), int(t % 3600 // 60); s = t % 60
    return f"{h:02}:{m:02}:{int(s):02},{int(round((s % 1) * 1000)) % 1000:03}"

HERE = os.path.dirname(os.path.abspath(__file__))
PIPER_VOICE = os.environ.get("PIPER_VOICE", os.path.expanduser("~/.local/share/piper/en_US-ryan-high.onnx"))
USED_TTS = []

ENGINE = os.environ.get("TTS", "")
LANGUAGE = "en-US"

def tts(text, mp3, voice, rate):
    """xai (default) | edge | piper. edge falls back to local piper if it fails."""
    if ENGINE == "xai":
        import xai_imagine as X
        raw = mp3[:-4] + ".raw.mp3"
        X.tts(text, raw, voice, language=LANGUAGE, cost_log=os.path.join(os.path.dirname(os.path.dirname(mp3)), "cost.jsonl"))
        sh(f'ffmpeg -y -i "{raw}" -af "loudnorm=I=-16:TP=-1.5" -ar 48000 -b:a 192k "{mp3}"')
        USED_TTS.append("xai-tts:" + voice); return
    if ENGINE == "edge":
        r = subprocess.run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", mp3], capture_output=True)
        if r.returncode == 0 and os.path.getsize(mp3) > 1000:
            USED_TTS.append("edge-tts:" + voice); return
    wav = mp3[:-4] + ".wav"
    r = subprocess.run([sys.executable, "-m", "piper", "-m", PIPER_VOICE, "-f", wav, "--length-scale", os.environ.get("PIPER_SPEED", "1.0"), "--sentence-silence", "0.25"], input=text.encode(), capture_output=True)
    if r.returncode: sys.exit("TTS failed: " + r.stderr.decode()[-1000:])
    sh(f'ffmpeg -y -i {wav} -af "loudnorm=I=-16:TP=-1.5" -ar 48000 -b:a 192k {mp3}')
    USED_TTS.append("piper:" + os.path.basename(PIPER_VOICE))

def main(plan_path, out):
    plan = json.load(open(plan_path)); S = plan["slides"]; n = len(S)
    for sub in ("slides", "audio", "clips"): os.makedirs(f"{out}/{sub}", exist_ok=True)
    global ENGINE, LANGUAGE
    ENGINE = ENGINE or plan.get("tts", "xai"); LANGUAGE = plan.get("language", "en-US")
    voice = plan.get("voice", "ursa" if ENGINE == "xai" else "en-US-AndrewMultilingualNeural"); rate = plan.get("rate", "+0%")
    PAD, XF = 0.6, 0.5  # silence after each narration; crossfade length
    srt, t0, durs = [], 0.0, []
    for i, s in enumerate(S, 1):
        png, mp3, vtt = f"{out}/slides/{i:02}.png", f"{out}/audio/{i:02}.mp3", f"{out}/audio/{i:02}.vtt"
        render(plan, s, i, n, png)
        tts(s["narration"], mp3, voice, rate)
        a = dur(mp3); D = a + PAD + (XF if i < n else 0.3); durs.append(D)
        # captions: split narration into sentence chunks, time proportional to characters
        cap = re.sub(r"\b([A-Z]) (?=[A-Z]\b)", r"\1", s.get("caption", s["narration"]))
        chunks = [c.strip() for c in textwrap.wrap(cap, 90)]
        tot = sum(len(c) for c in chunks); cur = t0 + 0.15
        for c in chunks:
            L = a * len(c) / tot; srt.append((cur, cur + L, c)); cur += L
        fr = int(D * 30)
        z = f"min(1+0.00012*on,1.05)" if i % 2 else f"max(1.05-0.00012*on,1.0)"
        sh(f'ffmpeg -y -loop 1 -i {png} -i {mp3} -filter_complex "[0:v]scale=2400:-1,zoompan=z=\'{z}\':x=\'iw/2-(iw/zoom/2)\':y=\'ih/2-(ih/zoom/2)\':d={fr}:s={W}x{H}:fps=30,format=yuv420p[v];[1:a]apad,atrim=0:{D:.3f},aresample=48000[a]" -map "[v]" -map "[a]" -t {D:.3f} -c:v libx264 -preset medium -crf 18 -c:a aac -b:a 192k {out}/clips/{i:02}.mp4')
        t0 += D - XF
    with open(f"{out}/captions.srt", "w") as f:
        for k, (a, b, c) in enumerate(srt, 1): f.write(f"{k}\n{ts(a)} --> {ts(b)}\n{c}\n\n")
    # crossfade chain
    ins = " ".join(f"-i {out}/clips/{i:02}.mp4" for i in range(1, n + 1))
    fc, off, lv, la = [], 0.0, "[0:v]", "[0:a]"
    for i in range(1, n):
        off += durs[i - 1] - XF
        fc.append(f"{lv}[{i}:v]xfade=transition=fade:duration={XF}:offset={off:.3f}[v{i}]")
        fc.append(f"{la}[{i}:a]acrossfade=d={XF}[a{i}]"); lv, la = f"[v{i}]", f"[a{i}]"
    fc.append(f"{lv}subtitles={out}/captions.srt:force_style='FontName=Inter,FontSize=11,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=1,Shadow=0,MarginV=36'[vout]")
    sh(f'ffmpeg -y {ins} -filter_complex "{";".join(fc)}" -map "[vout]" -map "{la if n > 1 else '0:a'}" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -c:a aac -b:a 192k -movflags +faststart {out}/explainer.mp4')
    with open(f"{out}/script.md", "w") as f:
        f.write(f"# {plan['title']}\n\nVoice: {', '.join(sorted(set(USED_TTS)))}\n\n")
        for i, s in enumerate(S, 1):
            f.write(f"## Slide {i} ({s['type']}) — cites {', '.join('['+c+']' for c in s.get('cite', []))}\n\n{s['narration']}\n\n")
    with open(f"{out}/sources.md", "w") as f:
        f.write("# Sources\n\n" + (f"Primary: {plan['source_post']}\n\n" if plan.get("source_post") else ""))
        for k, v in plan["sources"].items(): f.write(f"- [{k}] {v}\n")
    print("tts:", sorted(set(USED_TTS))); print(f"done: {out}/explainer.mp4 duration={dur(out + '/explainer.mp4'):.1f}s")

if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0 if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help") else 2)
    main(sys.argv[1], sys.argv[2])
