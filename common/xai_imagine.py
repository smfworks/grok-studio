"""Shared xAI Imagine helpers: portrait, video clips (poll/retry), TTS, STT, cost log.
Never prints the API key."""
import os, json, time, base64, urllib.request, urllib.error, mimetypes, datetime

API = "https://api.x.ai/v1"
VIDEO_PRICE = {  # USD per output second
    "grok-imagine-video-1.5-lite": {"480p": 0.02, "720p": 0.03, "1080p": 0.14},
    "grok-imagine-video-1.5": {"480p": 0.08, "720p": 0.14, "1080p": 0.25},
}
IMAGE_PRICE = {"grok-imagine-image": 0.02, "grok-imagine-image-quality": 0.07, "grok-imagine-image-2.0": 0.07}  # estimates
TTS_PRICE_PER_CHAR = 15 / 1e6

def _key():
    k = os.environ.get("XAI_API_KEY")
    if not k: raise SystemExit("XAI_API_KEY not set")
    return k

def _req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=data, method=method,
        headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read())

def log_cost(log_path, kind, model, usd, **meta):
    if not log_path: return
    rec = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "kind": kind, "model": model, "usd": round(usd, 4), **meta}
    with open(log_path, "a") as f: f.write(json.dumps(rec) + "\n")

def total_cost(log_path):
    if not os.path.exists(log_path): return 0.0
    return sum(json.loads(l)["usd"] for l in open(log_path) if l.strip())

def data_uri(path):
    mt = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mt};base64," + base64.b64encode(open(path, "rb").read()).decode()

def download(url, out):
    r = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (grok-studio)"})
    with urllib.request.urlopen(r, timeout=300) as resp: open(out, "wb").write(resp.read())
    return out

def generate_image(prompt, out, model="grok-imagine-image", aspect_ratio="16:9", cost_log=None):
    body = {"model": model, "prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio, "response_format": "b64_json"}
    try:
        d = _req("POST", "/images/generations", body)
    except urllib.error.HTTPError as e:
        if e.code == 400:  # older schema without aspect_ratio
            body.pop("aspect_ratio"); d = _req("POST", "/images/generations", body)
        else: raise RuntimeError(f"image API {e.code}: {e.read()[:300]}")
    item = d["data"][0]
    if item.get("url"): download(item["url"], out)
    else: open(out, "wb").write(base64.b64decode(item["b64_json"]))
    log_cost(cost_log, "image", model, IMAGE_PRICE.get(model, 0.07), out=out)
    return out

def generate_video(prompt, out, image=None, model="grok-imagine-video-1.5-lite", duration=8,
                   resolution="720p", generate_audio=True, reference_audios=None, reference_images=None,
                   cost_log=None, retries=2, poll_s=6, timeout_s=900, **extra):
    body = {"model": model, "prompt": prompt, "duration": int(duration), "resolution": resolution}
    if image: body["image"] = {"url": image if image.startswith(("http", "data:")) else data_uri(image)}
    if not generate_audio: body["generate_audio"] = False
    if reference_audios: body["reference_audios"] = [{"voice_id": v} for v in reference_audios]
    if reference_images: body["reference_images"] = [{"url": u if u.startswith(("http", "data:")) else data_uri(u)} for u in reference_images]
    body.update(extra)
    last = None
    for attempt in range(retries + 1):
        try:
            rid = _req("POST", "/videos/generations", body)["request_id"]
        except urllib.error.HTTPError as e:
            msg = e.read()[:400].decode(errors="ignore"); last = f"HTTP {e.code}: {msg}"
            if e.code in (429, 500, 502, 503) and attempt < retries: time.sleep(20 * (attempt + 1)); continue
            raise RuntimeError(last)
        t0 = time.time()
        while time.time() - t0 < timeout_s:
            time.sleep(poll_s)
            try: d = _req("GET", f"/videos/{rid}")
            except Exception as e: last = str(e); continue
            st = d.get("status")
            if st == "done":
                v = d["video"]
                if v.get("respect_moderation") is False: raise RuntimeError("filtered by moderation")
                download(v["url"], out)
                secs = float(v.get("duration") or duration)
                log_cost(cost_log, "video", model, VIDEO_PRICE[model][resolution] * secs, seconds=secs,
                         resolution=resolution, request_id=rid, out=out, audio=generate_audio,
                         ref_voice=reference_audios)
                return out
            if st == "failed":
                err = d.get("error", {}); last = f"failed {err}"
                if err.get("code") in ("internal_error", "service_unavailable") and attempt < retries: break
                raise RuntimeError(last)
        else:
            last = "timeout"
    raise RuntimeError(f"video generation failed after retries: {last}")

def tts(text, out_mp3, voice="ursa", language="en-US", cost_log=None):
    r = urllib.request.Request(API + "/tts", data=json.dumps({"text": text, "voice_id": voice, "language": language}).encode(),
        headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=180) as resp: open(out_mp3, "wb").write(resp.read())
    log_cost(cost_log, "tts", voice, len(text) * TTS_PRICE_PER_CHAR, chars=len(text))
    return out_mp3

def tts_timed(text, out_mp3, voice="ursa", language="en-US", cost_log=None):
    """TTS with character-level timestamps. Writes out_mp3 and returns a list of words:
    [{"w": word, "start": s, "end": e, "i": char_index}] in seconds (spoken text after any replacements)."""
    body = {"text": text, "voice_id": voice, "language": language, "with_timestamps": True}
    r = urllib.request.Request(API + "/tts", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=240) as resp: d = json.loads(resp.read())
    open(out_mp3, "wb").write(base64.b64decode(d["audio"]))
    log_cost(cost_log, "tts", voice, len(text) * TTS_PRICE_PER_CHAR, chars=len(text), timed=True)
    ts = d.get("audio_timestamps") or {}
    return chars_to_words(ts.get("graph_chars", []), ts.get("graph_times", []))

def chars_to_words(chars, times):
    words, cur, st, en, i0 = [], "", None, None, 0
    for i, (c, t) in enumerate(zip(chars, times)):
        if c.isspace():
            if cur: words.append({"w": cur, "start": st, "end": en, "i": i0}); cur = ""
            continue
        if not cur: st, i0 = t[0], i
        cur += c; en = t[1]
    if cur: words.append({"w": cur, "start": st, "end": en, "i": i0})
    return words

def stt(audio_path, keyterms=(), language="en"):
    """Transcribe with xAI STT (multipart). Returns text."""
    import uuid
    b = uuid.uuid4().hex; parts = []
    def field(n, v): parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{n}"\r\n\r\n{v}\r\n'.encode())
    field("model", "grok-voice-transcribe-2.0"); field("format", "true"); field("language", language)
    for k in keyterms: field("keyterm", k)
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{os.path.basename(audio_path)}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                 + open(audio_path, "rb").read() + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    r = urllib.request.Request(API + "/stt", data=b"".join(parts), method="POST",
        headers={"Authorization": "Bearer " + _key(), "Content-Type": f"multipart/form-data; boundary={b}"})
    with urllib.request.urlopen(r, timeout=300) as resp: d = json.loads(resp.read())
    return d.get("text") or d.get("transcript") or json.dumps(d)[:2000]
