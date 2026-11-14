#!/usr/bin/env python3
"""
Carpetas y documentos de cada solicitante en Drive — 2026-11-13.

Corre la INGESTA REAL (step_ingest) con un Drive simulado en memoria, Supabase
simulado y salida en un directorio temporal. No habla con la red.

Lo que fija:
  - Carpeta "GR-id - Nombre" dentro de Grant Application 2027 para cada
    solicitud: nuevas Y renovaciones (antes, solo nuevas).
  - Los cuatro tipos de adjunto (C1, C2, I2, J3) y una copia completa de la
    solicitud como Google Doc, con el ID de aplicación al inicio del nombre.
    Antes no se guardaba ningún documento.
  - Nunca se escribe fuera de Grant Application 2027.
  - Volver a correr no duplica nada.
  - Un nombre con apóstrofo funciona (antes rompía la búsqueda en silencio).
  - Sin nombre legal no se crea grantee ni carpeta, y se marca.
  - Un documento que no se pudo guardar levanta una bandera con el detalle.
  - La renovación no pierde su folder_link anterior; el nuevo grantee no
    hereda E4 (la barrera económica) como "pilar".

Uso:
  python3 test_documentos.py
"""

import importlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_import_guard import install_google_stubs  # noqa: E402

FAILS, PASSED = [], 0
GA2027 = "GA2027-FOLDER"
OUTSIDE = "LEGAL-1.1-ADMIN"   # una carpeta que existe pero donde Eva no debe escribir


def check(cond, msg, got=None):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {msg}")
    else:
        FAILS.append(msg)
        print(f"  ✗ {msg}" + (f"\n      obtuvo: {got!r}" if got is not None else ""))


# ── Drive simulado ─────────────────────────────────────────────────────────

def _unq(s):
    return s.replace("\\'", "'").replace("\\\\", "\\")


class _Call:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeFiles:
    def __init__(self, drive):
        self.d = drive

    def list(self, q="", **kw):
        self.d.queries.append(q)
        name = re.search(r"name='((?:\\.|[^'\\])*)'", q)
        parent = re.search(r"'((?:\\.|[^'\\])*)' in parents", q)
        folders_only = "mimeType='application/vnd.google-apps.folder'" in q
        def run():
            out = []
            for fid, it in self.d.items.items():
                if name and it["name"] != _unq(name.group(1)):
                    continue
                if parent and _unq(parent.group(1)) not in it["parents"]:
                    continue
                if folders_only and it["mimeType"] != "application/vnd.google-apps.folder":
                    continue
                out.append({"id": fid, "name": it["name"]})
            return {"files": out}
        return _Call(run)

    def create(self, body=None, media_body=None, **kw):
        def run():
            fid = f"F{len(self.d.items) + 1:03d}"
            self.d.items[fid] = {
                "name": body["name"], "parents": list(body.get("parents", [])),
                "mimeType": body.get("mimeType") or (media_body.mimetype if media_body else ""),
                "data": media_body.data if media_body else b"",
                "upload_mime": media_body.mimetype if media_body else "",
            }
            self.d.creates.append(fid)
            return {"id": fid, "name": body["name"]}
        return _Call(run)


class FakeDrive:
    def __init__(self):
        self.items = {OUTSIDE: {"name": "1.1 Administration", "parents": ["ROOT"],
                                "mimeType": "application/vnd.google-apps.folder",
                                "data": b"", "upload_mime": ""}}
        self.creates, self.queries = [], []

    def files(self):
        return FakeFiles(self)


class FakeMedia:
    def __init__(self, fh, mimetype=None, resumable=False):
        self.data, self.mimetype = fh.read(), mimetype


# ── Datos ficticios ────────────────────────────────────────────────────────

REGISTRY = [
    {"grantee_id": "GR-2026-015", "legal_name": "Fundación Mi Tierra Digital",
     "country": "Colombia", "folder_link": "Mi Tierra (carpeta 2026)", "pillar": "Education"},
]

ROWS = [   # (application_id, B1, A3, archivos)
    ("APP-2027-0001", "Fundación Semillas Digitales (DEMO)", "No",
     [("C1", "registro.pdf"), ("C2", "w8ben-e.pdf"), ("I2", "politica.pdf")]),
    ("APP-2027-0002", "Fundación Mi Tierra Digital", "Yes, in 2026",
     [("C1", "registro.pdf"), ("J3", "reporte-2026.pdf")]),
    ("APP-2027-0003", "Women's Bitcoin Fund (DEMO)", "No",
     [("C1", "falla.pdf"), ("C2", "w9.pdf")]),
    ("APP-2027-0004", "", "No", [("C1", "sin-nombre.pdf")]),
]
FILES = {a: f for a, _, _, f in ROWS}


def source_rows(m):
    cols = ["application_id"] + list(m.QUESTION_MAP.values())
    rows = []
    for k, (app_id, b1, a3, _) in enumerate(ROWS):
        vals = {c: "" for c in cols}
        vals["application_id"] = app_id
        vals[m.QUESTION_MAP["timestamp"]] = f"2027-01-2{k}T10:00:00Z"
        vals[m.QUESTION_MAP["B1"]] = b1
        vals[m.QUESTION_MAP["B2"]] = "Colombia"
        vals[m.QUESTION_MAP["A3"]] = a3
        vals[m.QUESTION_MAP["E4"]] = "Barrera <script>alert(1)</script> & comisiones"
        vals[m.QUESTION_MAP["I2"]] = "Responsable: Ana Ejemplo"
        rows.append([vals[c] for c in cols])
    return cols, rows


def setup(m, tmp, drive_ref):
    m.CONFIG_DIR, m.CACHE_DIR, m.RUNS_DIR = tmp, tmp, tmp / "intake_runs"
    shutil.copy(HERE / "data" / "question_labels.json", tmp / "question_labels.json")
    m.MediaIoBaseUpload = FakeMedia
    m.fetch_source_rows = lambda sheets_api, sheet_id, config, since_ts=None: (*source_rows(m), "supabase")
    m.get_existing_app_ids = lambda *a, **k: set()
    m.get_existing_app_timestamps = lambda *a, **k: {}
    m.load_grantee_registry = lambda: REGISTRY
    m.load_seguimiento_2027 = lambda: []
    m.load_tracker_listas = lambda: {}
    m.add_grantee_to_registry_tab = lambda *a, **k: None
    m.fetch_application_files = lambda app_id, cfg: [
        {"question": q, "storage_path": f"{app_id}/{q}-{n}", "file_name": n,
         "mime_type": "application/pdf", "size_bytes": 10} for q, n in FILES.get(app_id, [])]
    m.download_supabase_doc = lambda value, cfg=None: (
        (None, None) if value.endswith("falla.pdf") else (b"%PDF " + value.encode(), "application/pdf"))


def ingest(m, drive):
    cfg = {"active": {"intake_sheet_id": "TEST-SHEET"}, "active_env": "test",
           "grant_application_2027_folder": {"id": GA2027},
           "ingest": {"source": "supabase", "supabase": {"url": "https://x", "table": "intake_rows"}}}
    return m.step_ingest(None, drive, cfg, {}, "RUN-DOCS")["applications"]


def main():
    print("=" * 68)
    print("CARPETAS Y DOCUMENTOS EN DRIVE")
    print("=" * 68)
    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    tmp = Path(tempfile.mkdtemp(prefix="documentos-"))
    try:
        drive = FakeDrive()
        setup(m, tmp, drive)
        apps = {a["app_id"]: a for a in ingest(m, drive)}
        it = drive.items

        def kids(parent):
            return {v["name"]: k for k, v in it.items() if parent in v["parents"]}

        print("\n1. Una carpeta por organización dentro de Grant Application 2027")
        folders = kids(GA2027)
        check("GR-2027-001 - Fundación Semillas Digitales (DEMO)" in folders, "organización nueva", sorted(folders))
        check("GR-2026-015 - Fundación Mi Tierra Digital" in folders,
              "renovación: mismo GR-id, carpeta 2027 (antes no se creaba)", sorted(folders))
        check("GR-2027-002 - Women's Bitcoin Fund (DEMO)" in folders,
              "nombre con apóstrofo: carpeta creada", sorted(folders))
        check(any("\\'" in q for q in drive.queries), "y la búsqueda lo escapó")
        check(len(folders) == 3, "sin carpeta para la solicitud sin nombre legal", sorted(folders))

        print("\n2. Documentos y copia de la solicitud")
        f1 = kids(folders.get("GR-2027-001 - Fundación Semillas Digitales (DEMO)", "?"))
        for want in ("APP-2027-0001 · C1 · registro.pdf", "APP-2027-0001 · C2 · w8ben-e.pdf",
                     "APP-2027-0001 · I2 · politica.pdf", "APP-2027-0001 · Solicitud"):
            check(want in f1, f"guardado: {want}", sorted(f1))
        f2 = kids(folders.get("GR-2026-015 - Fundación Mi Tierra Digital", "?"))
        check("APP-2027-0002 · J3 · reporte-2026.pdf" in f2, "renovación: J3, el reporte 2026", sorted(f2))
        pdf = it.get(f1.get("APP-2027-0001 · C1 · registro.pdf", ""), {})
        check(pdf.get("data", b"").startswith(b"%PDF") and pdf.get("upload_mime") == "application/pdf",
              "el archivo sube con su contenido y tipo")
        copy = it.get(f1.get("APP-2027-0001 · Solicitud", ""), {})
        html = copy.get("data", b"").decode("utf-8", "replace")
        check(copy.get("mimeType") == "application/vnd.google-apps.document",
              "la copia es un Google Doc", copy.get("mimeType"))
        check("Legal name" in html and "B1." in html, "lleva el texto de cada pregunta", html[:200])
        check("&lt;script&gt;" in html and "<script>" not in html,
              "las respuestas van escapadas: texto del solicitante, nunca HTML")
        check(f1.get("APP-2027-0001 · C1 · registro.pdf", "#") in html, "enlaza cada adjunto")
        check("Ana Ejemplo" in html, "I2 muestra el archivo y también el responsable")
        a1 = apps["APP-2027-0001"]
        check(a1["documents"]["copy_url"].startswith("https://docs.google.com/document/d/"),
              "el enlace a la copia queda en la aplicación", a1["documents"])
        check(a1["drive_folder_id"] == folders.get("GR-2027-001 - Fundación Semillas Digitales (DEMO)"),
              "y el de la carpeta")

        print("\n3. Nunca fuera de Grant Application 2027")
        inside = {GA2027} | set(folders.values())
        bad = [(it[f]["name"], it[f]["parents"]) for f in drive.creates
               if not set(it[f]["parents"]) <= inside]
        check(not bad, "todo lo creado está en Grant Application 2027 o en una carpeta suya", bad)
        check(not kids(OUTSIDE), "nada en 1.1 Administration")

        print("\n4. Registro de grantees")
        reg = {g["grantee_id"]: g for g in REGISTRY}
        check(reg["GR-2026-015"]["folder_link"] == "Mi Tierra (carpeta 2026)",
              "la renovación conserva su folder_link anterior")
        check(reg["GR-2026-015"].get("folder_2027") == folders.get("GR-2026-015 - Fundación Mi Tierra Digital"),
              "y gana folder_2027")
        new = reg.get("GR-2027-001", {})
        check(new.get("pillar") == "", "el grantee nuevo no hereda E4 como pilar", new.get("pillar"))
        check(not any(not g.get("legal_name") for g in REGISTRY), "ningún grantee sin nombre en el registro")

        print("\n5. Fallas visibles")
        a3, a4 = apps["APP-2027-0003"], apps["APP-2027-0004"]
        check(any("C1: download failed" in e for e in a3["documents"]["errors"]),
              "descarga fallida → error registrado", a3["documents"])
        check("APP-2027-0003 · C2 · w9.pdf" in kids(a3["drive_folder_id"]),
              "los demás documentos de esa solicitud sí se guardan")
        check(a4["grantee_id"] == "" and a4["drive_folder_id"] == "", "sin nombre legal: sin grantee ni carpeta")
        flagged = {a["app_id"]: a["flags"] for a in m.step_flag(list(apps.values()), "RUN-DOCS")["applications"]}
        check(flagged["APP-2027-0003"].get("documents_not_stored") == "YES",
              "bandera documents_not_stored con el detalle", flagged["APP-2027-0003"].get("Flags_Detail"))
        check(flagged["APP-2027-0004"].get("missing_legal_name") == "YES"
              and flagged["APP-2027-0004"].get("Critical_Flags_Count", 0) >= 1,
              "bandera crítica missing_legal_name")
        check(flagged["APP-2027-0001"].get("documents_not_stored", "") != "YES",
              "sin bandera cuando todo se guardó")

        print("\n6. Volver a correr no duplica")
        before = len(drive.creates)
        ingest(m, drive)
        check(len(drive.creates) == before, "segunda corrida: cero archivos o carpetas nuevos",
              [it[f]["name"] for f in drive.creates[before:]])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"DOCUMENTOS: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
