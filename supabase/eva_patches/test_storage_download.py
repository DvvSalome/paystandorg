import os, sys, tempfile, threading, pathlib
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storage_download import is_supabase_document, download_supabase_document
seen = {}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        seen["path"], seen["auth"] = self.path, self.headers.get("Authorization")
        self.send_response(200); self.end_headers(); self.wfile.write(b"%PDF-1.4 demo")
srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"; tmp = tempfile.mkdtemp()
p = download_supabase_document("storage:APP-2027-0001/C1-demo registro.pdf", base, "k", tmp)
checks = {
  "reconoce el prefijo storage:": is_supabase_document("storage:a/b.pdf") and not is_supabase_document("https://drive.google.com/x"),
  "pide la ruta autenticada del bucket": seen["path"] == "/storage/v1/object/authenticated/applications/APP-2027-0001/C1-demo%20registro.pdf",
  "manda la clave": seen["auth"] == "Bearer k",
  "guarda el archivo": pathlib.Path(p).read_bytes().startswith(b"%PDF"),
}
for bad in ("storage:../etc/passwd", "storage:/abs.pdf", "storage:"):
    try: download_supabase_document(bad, base, "k", tmp); checks[f"rechaza {bad}"] = False
    except ValueError: checks[f"rechaza {bad}"] = True
for k, v in checks.items(): print("OK  " if v else "FAIL", k)
sys.exit(0 if all(checks.values()) else 1)
