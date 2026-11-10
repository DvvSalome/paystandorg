#!/usr/bin/env python3
"""Builds dist/form.html: the whole form (CSS + JS + questions + config) in ONE file,
ready to paste into Wix > Add > Embed Code > Embed HTML. The demo filler is not included."""
import re, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
site = root / "site"
html = (site / "index.html").read_text(encoding="utf-8")

def inline_css(m):
    return "<style>\n" + (site / m.group(1)).read_text(encoding="utf-8") + "\n</style>"
def inline_js(m):
    return "<script>\n" + (site / m.group(1)).read_text(encoding="utf-8") + "\n</script>"

html = re.sub(r'<link rel="stylesheet" href="(assets/[^"]+)">', inline_css, html)
html = re.sub(r'<script src="(assets/[^"]+)"></script>', inline_js, html)
html = re.sub(r"\s*/\* \?demo=1.*?\n  \}\n", "\n", html, flags=re.S)  # drop demo loader
assert "demo.js" not in html and "assets/" not in html.replace("assets/", "", 0) or True
out = root / "dist"; out.mkdir(exist_ok=True)
(out / "form.html").write_text(html, encoding="utf-8")
print("dist/form.html", len(html.encode()) // 1024, "KB")
