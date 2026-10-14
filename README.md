# Grok Studio: Explainer and Avatar Videos

Drop in a link, PDF or topic and get back a cited, narrated explainer video, optionally hosted by your own AI presenter. Everything runs on xAI: **Grok Imagine** (presenter portrait and lip-synced talking clips) and **Grok Voice** (TTS narration and STT checks).

- Every slide shows its source. Every spoken line must be covered by its citations.
- Every avatar clip is transcribed and checked against the script before delivery.
- **Nothing uploads or posts without the owner's explicit OK.** The scripts only write local files.

By SMF Works. MIT licensed.

## Two modes

| Mode | Folder | Output |
|---|---|---|
| Source-grounded explainer | `explainer/` | Cited slides + narration -> `explainer.mp4` |
| Avatar explainer (hybrid) | `avatar/` | Presenter clips cut between cited slides, optional picture-in-picture -> `hybrid.mp4` |
| **Studio** (recommended) | `studio/` | Kinetic slides + charts + B-roll + avatar + music bed, in 16:9, 9:16 and 1:1 -> `video_<fmt>.mp4` |

## Studio quickstart

```bash
export GS=/workspace/grok-studio   # your clone
cd work   # plan.json here (see examples/studio-plan.json)
python3 $GS/studio/plan_summary.py plan.json          # 1. one-page plan + cost estimate -> get the owner's OK
python3 $GS/avatar/gen_avatar_clips.py plan.json . --budget 3   # 2. paid: avatar + PiP clips (if any)
python3 $GS/studio/gen_broll.py plan.json . --budget 2          # 3. paid: generated B-roll (if any)
python3 $GS/studio/build.py plan.json . --formats 16x9,9x16,1x1 # 4. render (TTS is the only spend)
python3 $GS/studio/qa_studio.py plan.json . --keyterms Name,Brand  # 5. QA gate + stills/
```

- **Kinetic slides** (`studio/kinetic.py`, Pillow, 30 fps): every element builds in when the narrator says it, using xAI TTS `with_timestamps` word timings (set `cue` to a word on bullets/charts). Stat values count up. Types: title, bullets, steps, quad, cards, quote, stat, **chart** (`bar` | `line` | `donut`, with `data: [{label, value, display?}]`, `max?` and a required `cite`).
- **B-roll**: `{"type":"broll","prompt":...}` is generated with grok-imagine-video-1.5-lite text-to-video (480p/720p, 3-6 s, muted, a safety suffix bans text, logos, brands and identifiable people) and tagged "AI-generated illustrative footage". Owner footage: `{"type":"broll","path":"clip.mp4","credit":"..."}`. Narration plays over it.
- **Music bed**: an original procedural ambient pad (`studio/music.py`, royalty-free because it is synthesized), ducked to `music_under_voice_db` (default 26 dB) under the voice. `"music": "track.mp3"` uses your own track; `"music": false` or `--no-music` turns it off.
- **Formats**: `--formats 16x9,9x16,1x1` (or plan `formats`). Each format is laid out on its own canvas, not cropped: slides re-render, avatar clips are re-framed over a blurred fill, captions and PiP move.
- **Theme**: `theme: {bg, glow, accents, text, muted, font (path or family), logos, kicker, bg_image, bg_focus_x}`.
- **Data-driven QA**: every number on screen must appear in `source_text` (or `--sources`); numbers only found in the script are warnings. Charts without a cite fail.

## Imagine via browser (default, no API credits)

Grok Studio's default clip route drives **Grok Imagine on https://grok.com/imagine** in the bot's own browser (a computerUse browser subagent), signed in to your grok.com account. Clips count against your grok.com / SuperGrok plan limits instead of xAI API credits.

- **Setup:** on first run the bot asks you to sign in to grok.com in its browser, using a secure sign-in form or a desktop handoff. It never asks for passwords in chat. It then makes one short test clip, downloads it, shows it to you, and remembers that the route is ready.
- **Video options:** 6 / 10 / 15 s; 480p / 720p / 1080p; aspect Auto, 2:3, 3:2, 1:1, 9:16, 16:9; audio toggle; Upload for image-to-video; Download. A clip takes about 3-4 minutes and lands in `~/Downloads/grok-video-*.mp4`.
- **Character lock:** presenter and B-roll stills come from the bot's built-in image generation, using the approved portrait as a reference image plus a fixed character-lock description. The stills are then uploaded to Imagine for image-to-video.
- **xAI API key (optional):** used for TTS narration, and as the fallback for clips (`avatar/gen_avatar_clips.py`, `studio/gen_broll.py`) when the browser route isn't set up or hits a plan limit. Skip the key and turn Imagine's audio on to use its native voice instead.
- The cost table below applies to the API fallback.

## Requirements

- `XAI_API_KEY`: an xAI API key **with credits** (TTS, STT, image and video generation are billed).
- Python 3.9+, `ffmpeg`/`ffprobe`, `poppler-utils` (PDF sources), `fontconfig`. Inter and IBM Plex Serif fonts look best; DejaVu is the fallback (`GROK_STUDIO_FONT` / `GROK_STUDIO_SERIF_FONT` override).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/smfworks/grok-studio/main/install.sh | bash
```

Clones to `/workspace/grok-studio` (if `/workspace` exists) or `~/grok-studio`; set `GROK_STUDIO_DIR` to change it. Installs pip deps with `--break-system-packages` and prints apt/brew hints for missing system tools.

## Quickstart: explainer

```bash
cd ~/grok-studio            # or /workspace/grok-studio
python3 explainer/extract_source.py work/source.txt https://example.com/article   # URLs, .pdf, .docx, .txt
# write work/plan.json from the source (see examples/explainer-plan.json); cite every slide
python3 explainer/build_explainer.py work/plan.json work/out
```

Slide types: `title`, `bullets`, `quote`, `stat`, `quad`, `steps`. TTS engine: plan `"tts"` or env `TTS` = `xai` (default, voice `ursa`, language `en-US`), `edge` (edge-tts), or `piper` (local). Piper models are not bundled; download one, e.g.:

```bash
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx
curl -LO https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json
pip install --break-system-packages piper-tts    # then TTS=piper or PIPER_VOICE=/path/model.onnx
```

## Quickstart: avatar explainer

```bash
cp examples/avatar-plan.json work/plan.json        # edit presenter_spec, opening_line, sources, segments
python3 avatar/gen_presenter.py work/presenter.png --plan work/plan.json   # owner approves this portrait first
python3 avatar/gen_avatar_clips.py work/plan.json work/out --budget 5      # resumable; --only id,id ; --force
python3 avatar/build_hybrid.py work/plan.json work/out
python3 avatar/qa_avatar.py work/plan.json work/out --keyterms "Name,Jargon"
```

Plan fields: `presenter` (portrait path, reused as the pinned first frame of every clip, which keeps the face consistent), `presenter_spec`, `presenter_name`, `opening_line` (forced onto the first avatar segment), `voice` (xAI preset, shared by TTS and avatar, default `ursa`), `language` (default `en-US`), `accent`, `avatar_audio` (`ref_voice` default | `imagine` | `tts_overlay`). Segments are `{"type":"avatar","id","line","cite"}` or any slide type, with optional `"pip":{"id","line","cite","position","width"}`. Lines over ~13.5 s are split at sentence ends (clips cap at 15 s).

Audio modes:
- `ref_voice`: avatar speaks in the same preset voice as the narration with native lip sync (grok-imagine-video-1.5, 720p max). Short lines can come out slightly higher-pitched than long narration; check a consistency clip.
- `imagine`: cheapest (lite), but the model picks its own voice/accent.
- `tts_overlay`: perfect voice match, lip sync off by 0.2 to 0.5 s; use for small PiPs.

`avatar/voice_match.py REF... -- CAND...` ranks candidate voices by pitch and spectrum. List voices with `GET https://api.x.ai/v1/tts/voices`.

## Costs (estimates, USD)

| Item | 480p | 720p | 1080p |
|---|---|---|---|
| grok-imagine-video-1.5-lite, per second | $0.02 | $0.03 | $0.14 |
| grok-imagine-video-1.5, per second | $0.08 | $0.14 | $0.25 |

- ~3 min video with 5 full-frame `ref_voice` segments (~45 s) + 2 lite PiPs: roughly **$6.5**. All-lite version: about **$1.7**.
- Generated B-roll (lite): $0.02/s at 480p, $0.03/s at 720p, so a 5 s clip is $0.10-0.15. Studio narration TTS: about $15 per 1M characters, so cents.
- Slide-only explainer with xAI TTS: cents. Portrait: a few cents.
- `--budget` stops before any clip that would exceed the limit; spending is logged to `cost.jsonl`.

## QA gate (must pass before delivery)

- STT word match >= 95% per avatar clip (pass names/jargon as `--keyterms`); the opening line verbatim.
- Final duration within 0.1 s of expected; no blackdetect, freezedetect (8 s) or silencedetect (1.2 s at -45 dB) hits; about -16 LUFS.
- Studio: per format duration, black/freeze/silence and loudness; music 22-30 dB under the voice; every on-screen number found in the sources; every chart cited.
- Stills: same face, PiP not covering text/captions, a citation on every segment.
- Content: each line is covered by its cites; project exclusion rules followed.
- Deliver privately. **Do not upload or post anywhere without the owner's explicit OK.**

## Layout

```
common/   xai_imagine.py (xAI image/video/TTS/STT + cost log), fonts.py
explainer/ extract_source.py, build_explainer.py
avatar/   gen_presenter.py, gen_avatar_clips.py, build_hybrid.py, qa_avatar.py, voice_match.py
studio/   plan_summary.py, gen_broll.py, build.py, kinetic.py, music.py, qa_studio.py
examples/ explainer-plan.json, avatar-plan.json, studio-plan.json
```
