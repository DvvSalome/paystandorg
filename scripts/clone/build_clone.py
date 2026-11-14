#!/usr/bin/env python3
"""Builds site/index.html (+ site/wix/) : a static copy of https://www.paystand.org/grantapplication
with our application form where the form goes.

Steps (the capture needs network access to paystand.org and the Wix CDNs):
  1. node scripts/clone/capture.js 1440        -> cap/page-1440.html, cap/saved.json, cap/raw/*
  2. python3 scripts/clone/build_clone.py cap   -> site/index.html, site/wix/*
Wix's JavaScript is dropped (the page is already rendered); the images, fonts and styles are copied
so the page no longer depends on Wix. Header links keep pointing to the live paystand.org pages."""
import hashlib, html as H, json, os, pathlib, re, shutil, ssl, sys, urllib.parse, urllib.request

CAP = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else 'cap')
ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = ROOT / 'site'; ASSETS = OUT / 'wix'
EXT = {'image/avif': 'avif', 'font/woff2': 'woff2', 'image/svg+xml': 'svg', 'image/png': 'png', 'image/jpeg': 'jpg',
       'image/webp': 'webp', 'application/font-woff2': 'woff2', 'binary/octet-stream': 'woff2', 'application/octet-stream': 'woff2'}
norm = lambda u: urllib.parse.unquote(H.unescape(u))
def https(u): return ('https:' + u) if u.startswith('//') else u.replace('http://', 'https://', 1)

# Check the capture BEFORE deleting anything. This used to rmtree site/wix/
# on line 1 and read saved.json on line 2, so running the script without a
# capture — which is easy, since the capture needs network access and lives
# outside the repo — wiped 21 assets and then died on FileNotFoundError,
# leaving the page broken with nothing to rebuild it from. Happened on
# 2026-11-13. Validate first, destroy second.
for need in ('saved.json', 'page-1440.html'):
    if not (CAP / need).exists():
        sys.exit(f"{CAP / need} not found. Run the capture first:\n"
                 f"  node scripts/clone/capture.js 1440   (also 768 and 390)\n"
                 f"Nothing was deleted.")
saved = json.load(open(CAP / 'saved.json'))
missing = [v['file'] for v in saved.values() if not (CAP / 'raw' / v['file']).exists()]
if missing:
    sys.exit(f"The capture is incomplete: {len(missing)} files listed in "
             f"saved.json are not in {CAP / 'raw'} (e.g. {missing[0]}). "
             f"Re-run the capture. Nothing was deleted.")

shutil.rmtree(ASSETS, ignore_errors=True); ASSETS.mkdir(parents=True)
local = {}
for url, v in saved.items():
    name = f"{v['file']}.{EXT.get(v['type'], 'bin')}"
    shutil.copy(CAP / 'raw' / v['file'], ASSETS / name); local[norm(url)] = 'wix/' + name

h = open(CAP / 'page-1440.html', encoding='utf-8').read()
# 1. sin JavaScript de Wix, sin precargas
h = re.sub(r'<script\b[^>]*>.*?</script>', '', h, flags=re.S)
h = re.sub(r'<noscript\b[^>]*>.*?</noscript>', '', h, flags=re.S)
h = re.sub(r'<link\b[^>]*rel="(?:modulepreload|preload|preconnect|dns-prefetch|prefetch)"[^>]*>', '', h)
h = re.sub(r'<link\b(?![^>]*rel="(?:icon|shortcut icon|apple-touch-icon|mask-icon|canonical|stylesheet)")[^>]*>', '', h)
# 2. recursos de Wix -> archivos locales
def fix(m):
    raw = m.group(0)
    for cut in range(0, 4):
        cand = raw[:len(raw) - cut] if cut else raw
        if norm(https(cand)) in local: return local[norm(https(cand))] + raw[len(cand):]
    return raw
CDN = r'(?:https?:)?//(?:static\.wixstatic\.com|static\.parastorage\.com|siteassets\.parastorage\.com|video\.wixstatic\.com)/[^\s"\'<>]+'
h = re.sub(CDN, fix, h)
ctx = ssl.create_default_context(cafile=os.environ.get('SSL_CERT_FILE') or '/root/.ccr/ca-bundle.crt')
def grab(m):                                          # íconos y fuentes que Wix no pidió al cargar
    key = norm(https(m.group(0)))
    if key in local: return local[key]
    if not re.search(r'static\.wixstatic\.com/(media/|ufonts/[^/]+/woff2/)', key): return m.group(0)
    try:
        with urllib.request.urlopen(urllib.request.Request(key), timeout=30, context=ctx) as r: data, ct = r.read(), r.headers.get('content-type', '').split(';')[0]
    except Exception as e:
        print('  no pude bajar', key[:80], e); return m.group(0)
    name = hashlib.md5(key.encode()).hexdigest()[:12] + '.' + EXT.get(ct, 'png')
    (ASSETS / name).write_bytes(data); local[key] = 'wix/' + name; return 'wix/' + name
h = re.sub(r'(?:https?:)?//static\.wixstatic\.com/(?:media|ufonts)/[^\s"\'<>]+', grab, h)

# 2c. Wix sirve otro recorte de cada foto según el ancho: <source media> con las variantes de 768 y 390 px
def img_srcs(path):
    if not path.exists(): return {}
    t = path.read_text(encoding='utf-8'); out = {}
    for m in re.finditer(r'<img\b[^>]*>', t):
        alt = re.search(r'\salt="([^"]*)"', m.group(0)); src = re.search(r'\ssrc="([^"]*)"', m.group(0))
        if alt and src: out[alt.group(1)] = local.get(norm(https(src.group(1))))
    return out
variants = {W: img_srcs(CAP / f'page-{W}.html') for W in (768, 390)}
def add_sources(m):
    tag = m.group(0); alt = re.search(r'\salt="([^"]*)"', tag)
    if not alt: return tag
    own = re.search(r'\ssrc="([^"]*)"', tag).group(1)
    srcs = ''
    for W, media in ((390, '(max-width: 750px)'), (768, '(max-width: 1000px)')):     # el más específico va primero
        v = variants[W].get(alt.group(1))
        if v and v != own: srcs += f'<source media="{media}" srcset="{v}">'
    return srcs + tag
h = re.sub(r'<img\b[^>]*>', lambda m: add_sources(m) if '<picture' in h[max(0, m.start() - 12):m.start()] else m.group(0), h)

# 3. el botón "Apply Online" baja al formulario
i = h.index('>Apply Online<'); a = h.rindex('<a ', 0, i); tag_end = h.index('>', a)
tag = h[a:tag_end + 1]
tag2 = re.sub(r'\shref="[^"]*"', ' href="#ga27-apply"', tag); tag2 = re.sub(r'\s(?:target|rel)="[^"]*"', '', tag2)
h = h[:a] + tag2 + h[tag_end + 1:]

# 3b. "Grants" (la página actual) no debe sacar al visitante a la página original de paystand.org,
#     que todavía lleva el botón viejo hacia el Google Form. Solo se tocan los <a>, no el <link rel="canonical">.
SELF = re.compile(r'(<a\b[^>]*\shref=")https://www\.paystand\.org/grantapplication/?(")')
h = SELF.sub(r'\1./\2', h)

# 4. sección del formulario, justo después de "How to Apply" y antes del pie
s0 = h.index('id="comp-mj0bswls"'); s0 = h.rindex('<section', 0, s0)
depth, pos = 0, s0
for m in re.finditer(r'<(/?)section\b', h[s0:]):
    depth += -1 if m.group(1) else 1; pos = s0 + m.end()
    if depth == 0: break
s_end = h.index('>', pos) + 1
FORM = '''<section id="ga27-apply" class="ga27-apply" aria-labelledby="ga27-title">
  <h2 id="ga27-title" class="ga27-title">Apply Online</h2>
  <iframe id="ga27-form" class="ga27-iframe" title="Grant Application 2027" src="form/?embed=1" scrolling="no" loading="lazy"></iframe>
</section>'''
h = h[:s_end] + FORM + h[s_end:]

HEAD = '''<meta name="robots" content="noindex">
<style id="ga27-layout">
html { scroll-behavior: smooth; }
/* The cloned page carries Wix's site search. It has no backend here, so it
   either does nothing or sends people to the live site mid-application — and
   it lands next to section F, where it reads as part of the form. Hidden by
   the stable wixui- class, not by comp-id: those are regenerated whenever the
   Wix page is republished. */
.wixui-search-bar, [data-testid="search-box-container"] { display: none !important; }
.xxr34-container { grid-template-rows: auto auto auto auto auto auto !important; }
#comp-m06zws6u { grid-row: 6 / 7 !important; }
#ga27-apply { grid-row: 5 / 6; grid-column: 1; pointer-events: auto; padding: 90px 20px 90px; box-sizing: border-box; }
.ga27-title { margin: 0 0 40px; text-align: center; font: 400 54px/1.3 wfont_6f2075_adfa73542aa444be87f46a82b8ae9eb4, wf_adfa73542aa444be87f46a82b, orig_tt_firs_neue_medium, sans-serif; color: rgb(0, 27, 91); }
.ga27-iframe { display: block; width: 100%; max-width: 860px; margin: 0 auto; border: 0; height: 1400px; background: transparent; }
html.noform #ga27-apply { display: none !important; }
#ga27-menu { position: fixed; inset: 0; z-index: 100000; background: #f5f8fa; display: none; }
#ga27-menu[data-open="1"] { display: block; }
#ga27-menu button { position: absolute; top: 30px; right: 30px; width: 40px; height: 40px; background: none; border: 0; cursor: pointer; padding: 0; }
#ga27-menu nav { padding-top: 100px; display: flex; flex-direction: column; align-items: center; }
#ga27-menu a { color: #ff6a2f; font: 400 16px/45px "space grotesk", sans-serif; text-decoration: none; }
#ga27-menu a[aria-current] { color: #d3e9fe; }
@media (max-width: 1000px) { .ga27-title { font-size: 28.8px; } #ga27-apply { padding: 60px 20px; } }
@media (max-width: 750px) { .ga27-title { font-size: 26px; } }
</style>
'''
h = h.replace('</head>', HEAD + '</head>', 1)

BODY = '''<div id="ga27-menu" role="dialog" aria-modal="true" aria-label="Menu">
  <button type="button" aria-label="Close menu"><svg viewBox="0 0 40 40" width="40" height="40" fill="none" stroke="#c6e4ff" stroke-width="2"><path d="M10 10l20 20M30 10L10 30"/></svg></button>
  <nav aria-label="Main"><a href="https://www.paystand.org">Home</a><a href="./" aria-current="page">Grants</a><a href="https://www.paystand.org/impact-report">Reports</a><a href="https://www.paystand.org/blog">Blog</a></nav>
</div>
<script>
(function () {
  var q = location.search, de = document.documentElement;
  if (/[?&]noform=1\\b/.test(q)) de.classList.add("noform");
  var f = document.getElementById("ga27-form");
  if (f && /[?&]demo=1\\b/.test(q)) f.src = "form/?embed=1&demo=1";
  window.addEventListener("message", function (e) {
    if (e.origin === location.origin && e.data && e.data.type === "ga27-height" && f) f.style.height = Math.ceil(e.data.height) + "px";
  });
  var menu = document.getElementById("ga27-menu"), burger = document.getElementById("comp-m06zws4g_r_comp-kkmqi5lg");
  function set(open) { menu.setAttribute("data-open", open ? "1" : "0"); document.body.style.overflow = open ? "hidden" : ""; }
  if (burger) burger.addEventListener("click", function () { set(true); });
  menu.querySelector("button").addEventListener("click", function () { set(false); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") set(false); });
})();
</script>
'''
h = h.replace('</body>', BODY + '</body>', 1)
(OUT / 'index.html').write_text(h, encoding='utf-8')
left = sorted(set(re.findall(r'(?:https?:)?//(static\.wixstatic\.com|static\.parastorage\.com|siteassets\.parastorage\.com)/[^\s"\'<>]+', h)))
print(f'site/index.html: {len(h)//1024} KB | recursos locales: {len(local)} | referencias a Wix que quedan: {left}')
