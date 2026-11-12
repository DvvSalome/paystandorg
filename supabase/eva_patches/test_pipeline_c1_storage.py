"""Tests the exact text Eva pastes into intake_pipeline.py (pipeline_c1_storage.py) against a fake Supabase."""
import json, os, pathlib, sys, tempfile, threading, urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

seen = {}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        seen["path"], seen["auth"], seen["apikey"] = self.path, self.headers.get("Authorization"), self.headers.get("apikey")
        if "missing" in self.path: self.send_response(404); self.end_headers(); self.wfile.write(b'{"error":"not found"}'); return
        self.send_response(200); self.end_headers(); self.wfile.write(b"%PDF-1.4 demo")
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"

# stubs for what the real pipeline already has at module level
def load_supabase_key(cfg): return cfg.get("test_key", "")
ns = {"os": os, "json": json, "urllib": urllib, "load_supabase_key": load_supabase_key, "__file__": __file__}
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pipeline_c1_storage.py"), encoding="utf-8").read(), ns)
dl = ns["download_supabase_doc"]
cfg = {"url": BASE, "test_key": "k"}

d, m = dl("storage:APP-2027-0002/C1-demo registro.pdf", cfg)
checks = {
  "descarga bytes y mime del PDF": d == b"%PDF-1.4 demo" and m == "application/pdf",
  "ruta autenticada del bucket, con la ruta codificada": seen["path"] == "/storage/v1/object/authenticated/applications/APP-2027-0002/C1-demo%20registro.pdf",
  "manda la clave en apikey y Authorization": seen["apikey"] == "k" and seen["auth"] == "Bearer k",
  "mime de imagen (.png)": dl("storage:X/C1-a.png", cfg)[1] == "image/png",
  "archivo inexistente -> (None, None), sin excepción": dl("storage:missing/C1.pdf", cfg) == (None, None),
  "ruta con .. -> (None, None)": dl("storage:../etc/passwd", cfg) == (None, None),
  "ruta absoluta -> (None, None)": dl("storage:/abs.pdf", cfg) == (None, None),
  "vacía -> (None, None)": dl("storage:", cfg) == (None, None),
  "sin clave -> (None, None)": dl("storage:A/C1.pdf", {"url": BASE}) == (None, None),
}
# la lógica nueva de C1 (las dos líneas que cambian) con los tres tipos de valor
def is_downloadable(c1_val):
    c1_is_storage = c1_val.startswith("storage:")
    return c1_is_storage or c1_val.startswith("http") or (len(c1_val) > 20 and "/" not in c1_val and "." not in c1_val)
checks["storage:... ahora es descargable"] = is_downloadable("storage:APP-2027-0002/C1-registro.pdf")
checks["enlace de Drive sigue siendo descargable"] = is_downloadable("https://drive.google.com/file/d/abc/view")
checks["ID de Drive sigue siendo descargable"] = is_downloadable("1abcDEFghiJKLmnoPQRstuVWXyz0123")
checks["solo un nombre de archivo sigue sin descargarse"] = not is_downloadable("registration.pdf")
for k, v in checks.items(): print("OK  " if v else "FAIL", k)
sys.exit(0 if all(checks.values()) else 1)
