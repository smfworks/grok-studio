"""Kinetic slide renderer: per-element build-ins timed to narration, count-up stats, animated charts.

Pure Pillow + numpy, frames piped to ffmpeg at 30 fps. Layout is responsive to the output size,
so the same slide re-lays-out for 16:9, 9:16 and 1:1 (not a crop).

render_slide(plan, slide, idx, n, W, H, duration, words, out_path, audio=None)
  words: [{"w","start","end"}] from xai_imagine.tts_timed (used to cue each element when it is spoken)
"""
import math, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "common"))
from fonts import find_font

FPS = 30
DEFAULT_THEME = {
    "bg": ["#050b24", "#173f9c"], "glow": ["#2a6be0", "#3d8bff", "#0a1f66"],
    "text": "#ffffff", "muted": "#c9d8f5", "accents": ["#4f8cff", "#ff5a5f", "#ffc233", "#3ecf8e"],
    "card": [10, 24, 72, 170], "font": None, "mono_font": None, "logos": [], "kicker": "", "bg_image": None,
}

def hexrgb(h): h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
def ease(p): p = max(0.0, min(1.0, p)); return 1 - (1 - p) ** 3

def resolve_font(f):
    """A theme font may be a file path or a family name (resolved with fc-match)."""
    if not f or os.path.exists(f): return f
    import subprocess
    try: p = subprocess.run(["fc-match", "-f", "%{file}", f], capture_output=True, text=True).stdout.strip()
    except Exception: p = ""
    return p if p and os.path.exists(p) else None


class Theme:
    def __init__(self, plan):
        t = dict(DEFAULT_THEME); t.update(plan.get("theme", {})); self.t = t
        self.font_path = resolve_font(t["font"]) or find_font(); self.mono_path = resolve_font(t["mono_font"]) or self.font_path
        self.text = hexrgb(t["text"]); self.muted = hexrgb(t["muted"]); self.acc = [hexrgb(a) for a in t["accents"]]
        self._fc = {}
    def font(self, size, weight="Regular", mono=False):
        k = (int(size), weight, mono)
        if k not in self._fc:
            f = ImageFont.truetype(self.mono_path if mono else self.font_path, int(size))
            try: f.set_variation_by_name(weight)
            except Exception: pass
            self._fc[k] = f
        return self._fc[k]

def wrap(d, text, f, maxw):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw or not cur: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

class Layout:
    def __init__(self, W, H):
        self.W, self.H = W, H; self.portrait = H > W * 1.2; self.square = not self.portrait and W < H * 1.2
        self.s = min(W, H) / 1080
        self.mx = int((70 if self.portrait else 100) * self.s)
        self.top = int((230 if self.portrait else 170) * self.s)
        # keep content above the caption band
        self.bottom = int(H * (0.68 if self.portrait else 0.77 if self.square else 0.81))

def background(th, L, image=None):
    W, H = L.W, L.H
    if image and os.path.exists(image):
        im = Image.open(image).convert("RGB"); sc = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * sc) + 1, int(im.height * sc) + 1), Image.LANCZOS)
        x = int((im.width - W) * float(th.t.get("bg_focus_x", 0.5))); y = (im.height - H) // 2; im = im.crop((x, y, x + W, y + H))
        shade = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.55))
        return Image.composite(Image.new("RGB", (W, H), (2, 6, 24)), im, shade)
    import numpy as np
    c0, c1 = [np.array(hexrgb(c), float) for c in th.t["bg"]]
    yy, xx = np.mgrid[0:H, 0:W]; g = (xx / W * 0.6 + yy / H * 0.4)[..., None]
    im = Image.fromarray((c0 * (1 - g) + c1 * g).astype("uint8"), "RGB")
    glow = Image.new("RGB", (W, H)); d = ImageDraw.Draw(glow); gl = [hexrgb(c) for c in th.t["glow"]]
    d.ellipse([-0.2 * W, -0.45 * H, 0.75 * W, 0.6 * H], fill=gl[0]); d.ellipse([0.55 * W, -0.35 * H, 1.3 * W, 0.5 * H], fill=gl[1])
    d.ellipse([-0.3 * W, 0.55 * H, 0.45 * W, 1.4 * H], fill=gl[2])
    glow = glow.filter(ImageFilter.GaussianBlur(int(200 * L.s)))
    im = ImageChops.add(im, Image.eval(glow, lambda v: int(v * 0.8)))
    noise = Image.effect_noise((W // 2, H // 2), 10).resize((W, H)).convert("RGB")
    return Image.blend(im, ImageChops.add(im, noise, 1, -5), 0.25)

def rounded_mask(w, h, r):
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255); return m

def card(th, w, h, r=None, fill=None):
    r = r or max(10, h // 7); c = fill or th.t["card"]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); body = Image.new("RGBA", (w, h), tuple(c))
    im.paste(body, (0, 0), rounded_mask(w, h, r))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], r, outline=(255, 255, 255, 70), width=2)
    return im

def logo_chip(path, h):
    lg = Image.open(path).convert("RGBA"); lg = lg.crop(lg.getbbox()); ih = int(h * 0.62)
    lg = lg.resize((max(1, int(lg.width * ih / lg.height)), ih), Image.LANCZOS)
    w = lg.width + int(h * 0.7); chip = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    chip.paste(Image.new("RGBA", (w, h), (255, 255, 255, 255)), (0, 0), rounded_mask(w, h, h // 3))
    chip.alpha_composite(lg, ((w - lg.width) // 2, (h - lg.height) // 2)); return chip

# ---------------------------------------------------------------- elements
class El:
    """A sprite that builds in at time t0 (fade + rise). dynamic(t) may redraw it while animating."""
    def __init__(self, img, x, y, t0=0.0, dur=0.45, dynamic=None, settle=None):
        self.img, self.x, self.y, self.t0, self.dur, self.dynamic = img, int(x), int(y), t0, dur, dynamic
        self.settle = settle if settle is not None else t0 + dur
    def draw(self, frame, t, rise):
        if t < self.t0: return
        img = self.dynamic(t - self.t0) if self.dynamic else self.img
        p = ease((t - self.t0) / self.dur)
        if p >= 1: frame.alpha_composite(img, (self.x, self.y)); return
        a = img.getchannel("A").point(lambda v: int(v * p)); im2 = img.copy(); im2.putalpha(a)
        frame.alpha_composite(im2, (self.x, max(0, self.y + int(rise * (1 - p)))))

def text_sprite(th, lines, f, color, lh, w=None):
    d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w = w or int(max(d0.textlength(l, font=f) for l in lines) + 4)
    im = Image.new("RGBA", (w, int(lh * len(lines) + f.size * 0.4)), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    for i, l in enumerate(lines): d.text((0, i * lh), l, font=f, fill=color)
    return im

NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
def counter_text(value, p):
    """Count the first number in value up from 0 with the same formatting (commas, decimals); the rest stays static."""
    def rep(m):
        s = m.group(0); dec = len(s.split(".")[1]) if "." in s else 0; v = float(s.replace(",", "")) * ease(p)
        out = f"{v:,.{dec}f}" if "," in s else f"{v:.{dec}f}"
        return out
    return NUM.sub(rep, value, count=1) if p < 1 else value

# ---------------------------------------------------------------- cue timing
def norm(w): return re.sub(r"[^a-z0-9.]", "", w.lower())
def cue_time(words, phrase, after=0.0):
    if not words or not phrase: return None
    toks = [norm(x) for x in str(phrase).split()][:3]; toks = [t for t in toks if t]
    if not toks: return None
    ws = [norm(w["w"]) for w in words]
    for i in range(len(ws)):
        if words[i]["start"] < after: continue
        if all(i + j < len(ws) and (ws[i + j] == t or ws[i + j].rstrip(".") == t.rstrip(".")) for j, t in enumerate(toks)):
            return max(0.0, words[i]["start"] - 0.15)
    return None

def schedule(n, words, cues, D):
    """Element start times: matched cue words, else spread over the first 70% of narration; monotonic."""
    speech = words[-1]["end"] if words else D * 0.8
    out, last = [], 0.35
    for i in range(n):
        t = cue_time(words, cues[i], after=last - 0.2) if cues[i] else None
        if t is None: t = 0.6 + (speech * 0.7) * i / max(1, n)
        t = max(t, last); out.append(t); last = t + 0.12
    return out

# ---------------------------------------------------------------- slide builders
def header(th, plan, s, idx, n, L, els):
    x = L.mx; y = int(50 * L.s); ch = int(64 * L.s)
    for p in th.t.get("logos", []):
        if os.path.exists(p): chip = logo_chip(p, ch); els.append(El(chip, x, y, 0.0, 0.01)); x += chip.width + int(18 * L.s)
    kick = s.get("kicker", th.t.get("kicker", ""))
    f = th.font(28 * L.s, "SemiBold")
    if kick:
        ky = y + int(ch * 0.22) if not (L.portrait or L.square) else y + ch + int(22 * L.s)
        kx = x + int(12 * L.s) if not (L.portrait or L.square) else L.mx
        els.append(El(text_sprite(th, [kick], f, th.muted, f.size * 1.2), kx, ky, 0.0, 0.01))
    num = text_sprite(th, [f"{idx:02d}/{n:02d}"], f, th.text, f.size * 1.2)
    els.append(El(num, L.W - L.mx - num.width, y + int(ch * 0.22), 0.0, 0.01))

def footer(th, plan, s, L, base):
    cites = s.get("cite", [])
    if not cites: return
    d = ImageDraw.Draw(base); f = th.font((21 if not L.portrait else 26) * L.s, "Medium")
    txt = "Source: " + "  ·  ".join(f"[{c}] {plan['sources'].get(c, c)}" for c in cites)
    lines = wrap(d, txt, f, L.W - 2 * L.mx)[:3]; lh = f.size * 1.3; y = L.H - int(24 * L.s) - lh * len(lines)
    for i, l in enumerate(lines): d.text((L.mx, y + i * lh), l, font=f, fill=(215, 225, 245))

def heading_el(th, text, L, t0=0.1, size=None):
    size = size or (80 if not L.portrait else 84) * L.s; f = th.font(size, "Bold")
    d = ImageDraw.Draw(Image.new("RGB", (1, 1))); lines = wrap(d, text, f, L.W - 2 * L.mx)
    sp = text_sprite(th, lines, f, th.text, size * 1.12); return El(sp, L.mx, L.top, t0), L.top + sp.height + int(36 * L.s)

def items_of(s):
    """Normalise bullets / steps / items / quad into [(title, body, cue)]."""
    out = []
    for key in ("bullets", "steps", "items"):
        for it in s.get(key, []):
            if isinstance(it, dict): out.append((it.get("text") or it.get("title", ""), it.get("body", ""), it.get("cue")))
            elif isinstance(it, (list, tuple)): out.append((it[0], it[1] if len(it) > 1 else "", None))
            else: out.append((it, "", None))
    return out

def build_elements(th, plan, s, idx, n, L, words, D):
    base = background(th, L, s.get("bg_image") or (th.t.get("bg_image") if s["type"] == "title" else None))
    els = []; header(th, plan, s, idx, n, L, els); footer(th, plan, s, L, base)
    t = s["type"]; d0 = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if t == "title":
        y = int(L.H * (s.get("title_y") or ((0.62 if L.portrait else 0.66) if (s.get("bg_image") or th.t.get("bg_image")) else (0.36 if L.portrait else 0.40))))
        if s.get("heading"):
            f = th.font((104 if not L.portrait else 96) * L.s, "Bold"); lines = wrap(d0, s["heading"], f, L.W - 2 * L.mx)
            sp = text_sprite(th, lines, f, th.text, f.size * 1.1); els.append(El(sp, L.mx, y, 0.15, 0.6)); y += sp.height + int(20 * L.s)
        if s.get("sub"):
            f2 = th.font(44 * L.s, "Medium"); sp2 = text_sprite(th, wrap(d0, s["sub"], f2, L.W - 2 * L.mx), f2, th.muted, f2.size * 1.3)
            els.append(El(sp2, L.mx, y, 0.7, 0.6))
        return base, els
    hel, y = heading_el(th, s.get("heading", ""), L); els.append(hel)
    if s.get("quote"):
        f = th.font((46 if not L.portrait else 50) * L.s, "Medium"); w = L.W - 2 * L.mx
        lines = wrap(d0, "\u201c" + s["quote"] + "\u201d", f, w - int(80 * L.s)); lh = f.size * 1.3
        c = card(th, w, int(lh * len(lines) + 110 * L.s)); dd = ImageDraw.Draw(c)
        for i, l in enumerate(lines): dd.text((int(40 * L.s), int(26 * L.s) + i * lh), l, font=f, fill=th.text)
        dd.text((int(40 * L.s), int(34 * L.s) + lh * len(lines)), "\u2014 " + s.get("who", ""), font=th.font(28 * L.s, "SemiBold"), fill=th.acc[0])
        tq = cue_time(words, s.get("quote_cue") or s["quote"]) or 0.6
        els.append(El(c, L.mx, y, tq, 0.6)); y += c.height + int(30 * L.s)
    if t == "stat" or s.get("stats"):
        stats = s.get("stats", []); k = len(stats); cols = 1 if L.portrait else min(k, 3); rows = math.ceil(k / cols)
        gap = int(28 * L.s); cw = (L.W - 2 * L.mx - gap * (cols - 1)) // cols; ch = min(int(300 * L.s), (L.bottom - y - gap * (rows - 1)) // rows)
        times = schedule(k, words, [st[2] if len(st) > 2 else st[1] for st in stats], D)
        for i, st in enumerate(stats):
            val, label = st[0], st[1]; r, c = divmod(i, cols); x0 = L.mx + c * (cw + gap); y0 = y + r * (ch + gap)
            bg = card(th, cw, ch); fl = th.font(30 * L.s, "Medium"); sz = min(ch * 0.46, 120 * L.s)
            while sz > 20 and d0.textlength(val, font=th.font(sz, "Bold")) > cw - 72 * L.s: sz -= 4
            fv = th.font(sz, "Bold")
            col = th.acc[i % len(th.acc)]
            def dyn(dt, bg=bg, val=val, label=label, fv=fv, fl=fl, col=col, cw=cw, ch=ch):
                im = bg.copy(); d = ImageDraw.Draw(im); pad = int(36 * L.s)
                d.text((pad, int(ch * 0.12)), counter_text(val, dt / 1.3), font=fv, fill=col)
                for j, l in enumerate(wrap(d, label, fl, cw - 2 * pad)[:2]): d.text((pad, int(ch * 0.12) + fv.size * 1.15 + j * fl.size * 1.3), l, font=fl, fill=th.muted)
                return im
            els.append(El(dyn(99), x0, y0, times[i], 0.45, dynamic=dyn, settle=times[i] + 1.35))
        return base, els
    if t == "chart":
        return base, els + chart_elements(th, s, L, y, words, D)
    its = items_of(s)
    if its:
        k = len(its); cols = 1 if L.portrait else s.get("cols", 1 if t in ("bullets", "steps") else min(k, 2 if k == 4 else 3))
        rows = math.ceil(k / cols); gap = int(22 * L.s); cw = (L.W - 2 * L.mx - gap * (cols - 1)) // cols
        ch = min(int((200 if cols > 1 else 120) * L.s), (L.bottom - y - gap * (rows - 1)) // rows)
        cues = [it[2] or it[0] for it in its]; times = schedule(k, words, cues, D)
        for i, (title, body, _) in enumerate(its):
            r, c = divmod(i, cols); x0 = L.mx + c * (cw + gap); y0 = y + r * (ch + gap)
            im = card(th, cw, ch); d = ImageDraw.Draw(im); pad = int(30 * L.s); col = th.acc[i % len(th.acc)]
            if t == "steps":
                fn = th.font(ch * 0.42, "Bold"); d.text((pad, ch // 2), str(i + 1), font=fn, fill=col, anchor="lm"); tx = pad + int(ch * 0.55)
            else:
                rr = int(9 * L.s); d.ellipse([pad, ch // 2 - rr, pad + 2 * rr, ch // 2 + rr], fill=col); tx = pad + int(38 * L.s)
            ft = th.font(min(40 * L.s, ch * 0.3), "Bold"); fb = th.font(min(30 * L.s, ch * 0.22), "Medium")
            tl = wrap(d, title, ft, cw - tx - pad)[:2]; bl = wrap(d, body, fb, cw - tx - pad)[:2] if body else []
            hgt = len(tl) * ft.size * 1.15 + len(bl) * fb.size * 1.3; yy = (ch - hgt) / 2
            for l in tl: d.text((tx, yy), l, font=ft, fill=th.text); yy += ft.size * 1.15
            for l in bl: d.text((tx, yy), l, font=fb, fill=th.muted); yy += fb.size * 1.3
            els.append(El(im, x0, y0, times[i]))
    return base, els

def chart_elements(th, s, L, y, words, D):
    data = s["data"]; kind = s.get("chart", "bar"); els = []
    w = L.W - 2 * L.mx; h = L.bottom - y; vmax = s.get("max") or max(float(d["value"]) for d in data)
    bg = card(th, w, h); t0 = cue_time(words, s.get("cue")) or 0.5; stagger = s.get("stagger", 0.18)
    fl = th.font((32 if not L.portrait else 34) * L.s, "SemiBold"); fv = th.font((34 if not L.portrait else 36) * L.s, "Bold")
    pad = int(40 * L.s); n = len(data)
    if kind == "bar":
        horizontal = not s.get("vertical", False) or L.portrait
        def dyn(dt):
            im = bg.copy(); d = ImageDraw.Draw(im)
            if horizontal:
                lw = int(max(d.textlength(str(x["label"]), font=fl) for x in data) + 30 * L.s)
                rowh = (h - 2 * pad) / n; bh = rowh * 0.58; vw = int(150 * L.s)
                for i, x in enumerate(data):
                    p = ease((dt - i * stagger) / 0.9); yy = pad + i * rowh + (rowh - bh) / 2; col = th.acc[i % len(th.acc)]
                    d.text((pad, yy + bh / 2), str(x["label"]), font=fl, fill=th.text, anchor="lm")
                    full = w - pad * 2 - lw - vw; bw = max(2, full * float(x["value"]) / vmax * p)
                    d.rounded_rectangle([pad + lw, yy, pad + lw + full, yy + bh], int(bh / 2), fill=(255, 255, 255, 28))
                    d.rounded_rectangle([pad + lw, yy, pad + lw + bw, yy + bh], int(bh / 2), fill=col)
                    if p > 0: d.text((pad + lw + full + 20 * L.s, yy + bh / 2), counter_text(str(x.get("display", x["value"])), p), font=fv, fill=th.text, anchor="lm")
            else:
                colw = (w - 2 * pad) / n; bw = colw * 0.55; base_y = h - pad - fl.size * 1.6; top = pad + fv.size * 1.6
                for i, x in enumerate(data):
                    p = ease((dt - i * stagger) / 0.9); xx = pad + i * colw + (colw - bw) / 2; col = th.acc[i % len(th.acc)]
                    bh = (base_y - top) * float(x["value"]) / vmax * p
                    d.rounded_rectangle([xx, base_y - max(2, bh), xx + bw, base_y], int(bw / 6), fill=col)
                    d.text((xx + bw / 2, base_y + 10 * L.s), str(x["label"]), font=fl, fill=th.text, anchor="ma")
                    if p > 0: d.text((xx + bw / 2, base_y - bh - 10 * L.s), counter_text(str(x.get("display", x["value"])), p), font=fv, fill=th.text, anchor="md")
            return im
        settle = n * stagger + 1.0
    elif kind == "line":
        def dyn(dt):
            im = bg.copy(); d = ImageDraw.Draw(im); p = ease(dt / 1.6)
            x0, x1 = pad + 20 * L.s, w - pad - 20 * L.s; y0, y1 = pad + fv.size * 1.5, h - pad - fl.size * 1.8
            vmin = s.get("min", 0); pts = [(x0 + (x1 - x0) * i / max(1, n - 1), y1 - (y1 - y0) * (float(x["value"]) - vmin) / (vmax - vmin)) for i, x in enumerate(data)]
            for gy in range(5): yy = y0 + (y1 - y0) * gy / 4; d.line([(x0, yy), (x1, yy)], fill=(255, 255, 255, 30), width=1)
            seg = p * (n - 1); full = int(seg); col = th.acc[0]
            path = pts[:full + 1]
            if full < n - 1: a, b = pts[full], pts[full + 1]; fr = seg - full; path = path + [(a[0] + (b[0] - a[0]) * fr, a[1] + (b[1] - a[1]) * fr)]
            if len(path) > 1: d.line(path, fill=col, width=int(7 * L.s), joint="curve")
            for i, (px, py) in enumerate(pts):
                d.text((px, y1 + 14 * L.s), str(data[i]["label"]), font=fl, fill=th.muted, anchor="ma")
                if i <= seg + 1e-6:
                    r = int(10 * L.s); d.ellipse([px - r, py - r, px + r, py + r], fill=th.text)
                    d.text((px, py - 20 * L.s), str(data[i].get("display", data[i]["value"])), font=fv, fill=th.text, anchor="md")
            return im
        settle = 1.7
    else:  # donut
        tot = sum(float(x["value"]) for x in data)
        def dyn(dt):
            im = bg.copy(); d = ImageDraw.Draw(im); p = ease(dt / 1.4)
            R = int(min(h - 2 * pad, (w if L.portrait else w * 0.5) - 2 * pad) / 2); cx = pad + R if not L.portrait else w // 2; cy = pad + R
            if L.portrait: R = int(min(R, (h - 2 * pad) * 0.32)); cy = pad + R
            a0 = -90
            for i, x in enumerate(data):
                sweep = 360 * float(x["value"]) / tot * p
                d.pieslice([cx - R, cy - R, cx + R, cy + R], a0, a0 + sweep, fill=th.acc[i % len(th.acc)]); a0 += 360 * float(x["value"]) / tot * p
            ri = int(R * 0.62); d.ellipse([cx - ri, cy - ri, cx + ri, cy + ri], fill=tuple(th.t["card"][:3]) + (255,))
            if s.get("center"): d.text((cx, cy), counter_text(s["center"], p), font=th.font(R * 0.34, "Bold"), fill=th.text, anchor="mm")
            lx = cx + R + int(60 * L.s) if not L.portrait else pad; ly = pad + R * 0.4 if not L.portrait else cy + R + int(50 * L.s)
            for i, x in enumerate(data):
                yy = ly + i * fl.size * 2.0; d.rounded_rectangle([lx, yy, lx + fl.size, yy + fl.size], 6, fill=th.acc[i % len(th.acc)])
                d.text((lx + fl.size * 1.6, yy - 2), f"{x['label']}: {x.get('display', x['value'])}", font=fl, fill=th.text)
            return im
        settle = 1.5
    els.append(El(dyn(99), L.mx, y, t0, 0.4, dynamic=dyn, settle=t0 + settle))
    return els

def render_slide(plan, s, idx, n, W, H, D, words, out_path, audio=None, pip=None):
    th = Theme(plan); L = Layout(W, H); base, els = build_elements(th, plan, s, idx, n, L, words, D)
    base = base.convert("RGBA"); rise = int(36 * L.s)
    statics = [e for e in els if e.settle <= 0.02]
    for e in statics: base.alpha_composite(e.img, (e.x, e.y))
    live = [e for e in els if e not in statics]; settled = max([e.settle for e in live] + [0])
    N = int(round(D * FPS)); cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio: cmd += ["-i", audio]
    cmd += ["-map", "0:v"] + (["-map", "1:a", "-af", f"aresample=48000,aformat=channel_layouts=stereo,apad,atrim=0:{D:.3f}"] if audio else []) + \
           ["-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", out_path]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE); cache = None
    for i in range(N):
        t = i / FPS
        if t > settled + 0.05 and cache is not None: p.stdin.write(cache); continue
        fr = base.copy()
        for e in live: e.draw(fr, t, rise)
        b = fr.convert("RGB").tobytes()
        if t > settled + 0.05: cache = b
        p.stdin.write(b)
    p.stdin.close()
    if p.wait(): raise RuntimeError("ffmpeg failed rendering " + out_path)
    return out_path
