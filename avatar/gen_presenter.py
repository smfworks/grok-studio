#!/usr/bin/env python3
"""Generate ONE presenter portrait reused as pinned first frame for every avatar clip.
usage: gen_presenter.py OUT.png [--description TEXT | --plan plan.json (uses plan['presenter_spec'])] [--model ...] [--cost-log cost.jsonl]
The description is configurable per project; the framing template below keeps it usable as a first frame."""
import argparse, json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))
import xai_imagine as X
DEFAULT_DESC = "a friendly adult professional presenter with natural features and natural makeup"
TEMPLATE = ("Photorealistic, lifelike medium close-up portrait of {desc}. Looking straight into the camera, mouth closed, relaxed warm expression, wearing a simple solid-colour professional top, "
            "plain softly lit dark navy studio background with gentle rim light, head and shoulders centered with headroom, 16:9 frame, "
            "sharp focus, natural skin texture, not glamorized, not uncanny, no text, no logos")
ap = argparse.ArgumentParser(description=__doc__); ap.add_argument("out"); ap.add_argument("--description"); ap.add_argument("--plan")
ap.add_argument("--model", default="grok-imagine-image"); ap.add_argument("--cost-log", default="cost.jsonl")
a = ap.parse_args()
desc = a.description or (json.load(open(a.plan)).get("presenter_spec") if a.plan else None) or DEFAULT_DESC
X.generate_image(TEMPLATE.format(desc=desc), a.out, model=a.model, cost_log=a.cost_log); print(a.out)
