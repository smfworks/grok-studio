#!/usr/bin/env python3
"""Extract plain text from sources: URLs, .pdf, .docx, .txt/.md. Usage: extract_source.py OUT.txt SRC [SRC...]"""
import sys, subprocess, urllib.request, os
if len(sys.argv) < 3 or sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0 if len(sys.argv) > 1 else 2)
from bs4 import BeautifulSoup
out = open(sys.argv[1], "w")
for i, src in enumerate(sys.argv[2:], 1):
    if src.startswith("http"):
        html = urllib.request.urlopen(urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})).read()
        s = BeautifulSoup(html, "html.parser"); a = s.find("article") or s.find("main") or s.body
        for t in a(["script", "style", "nav", "footer"]): t.decompose()
        txt = (s.title.string if s.title else "") + "\n" + a.get_text("\n", strip=True)
    elif src.endswith(".pdf"):
        txt = subprocess.run(["pdftotext", "-layout", src, "-"], capture_output=True, text=True).stdout
    elif src.endswith(".docx"):
        import zipfile, re
        x = zipfile.ZipFile(src).read("word/document.xml").decode()
        txt = re.sub(r"<[^>]+>", "", x.replace("</w:p>", "\n"))
    else:
        txt = open(src).read()
    out.write(f"===== SOURCE [{i}] {src} =====\n{txt}\n\n")
print("wrote", sys.argv[1])
