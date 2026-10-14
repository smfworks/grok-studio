"""Font discovery: GROK_STUDIO_FONT / GROK_STUDIO_SERIF_FONT env, then common install paths, then fc-match, then DejaVu."""
import glob, os, subprocess

def _first(patterns):
    for p in patterns:
        hits = sorted(glob.glob(os.path.expanduser(p), recursive=True))
        if hits: return hits[0]
    return None

def _fc(name):
    try:
        p = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True).stdout.strip()
        return p or None
    except FileNotFoundError:
        return None

def find_font():
    return (os.environ.get("GROK_STUDIO_FONT")
            or _first(["/usr/share/fonts/**/Inter-VariableFont*.ttf", "~/.local/share/fonts/**/Inter*.ttf", "/usr/share/fonts/**/Inter*.ttf"])
            or _first(["/usr/share/fonts/**/DejaVuSans.ttf"]) or _fc("Inter") or "DejaVuSans.ttf")

def find_serif_font():
    return (os.environ.get("GROK_STUDIO_SERIF_FONT")
            or _first(["/usr/share/fonts/**/IBMPlexSerif-SemiBoldItalic.ttf", "~/.local/share/fonts/**/IBMPlexSerif*Italic.ttf"])
            or _first(["/usr/share/fonts/**/DejaVuSerif-Italic.ttf", "/usr/share/fonts/**/DejaVuSerif.ttf"]) or _fc("serif:italic") or find_font())
