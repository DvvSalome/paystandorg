#!/usr/bin/env python3
"""
Reproceso de una solicitud — 2026-11-16.

Calibrar exige volver a pasar los mismos casos después de cambiar una regla.
Esta prueba comprueba que reprocesar_solicitud.py:
  1. en seco no escribe nada;
  2. con --apply reemplaza solo la fila de esa solicitud (buscada por App_ID)
     en las pestañas 2–6, deja intactas las demás filas;
  3. conserva todo lo que escribió el equipo (Status, Status_Since, columnas
     de revisión);
  4. crea un documento de evaluación NUEVO y deja el anterior;
  5. registra el cambio en el Review Log;
  6. no toca watermark ni registro de grantees, y se niega en producción,
     con App_ID duplicado o ausente, o si faltan columnas.

Necesita el repositorio completo (lee questions.js con node).
  python3 test_reproceso.py
"""
import contextlib
import copy
import importlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from test_import_guard import install_google_stubs  # noqa: E402

FAILS, PASSED = [], 0


def check(cond, msg, got=None):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  ✓ {msg}")
    else:
        FAILS.append(msg)
        print(f"  ✗ {msg}" + (f"\n      obtuvo: {got!r}" if got is not None else ""))


def col(sheet, tab, row_n, name):
    h = [str(x).lower() for x in sheet.tabs[tab][0]]
    r = sheet.tabs[tab][row_n - 1]
    j = h.index(name.lower())
    return r[j] if j < len(r) else ""


def main():
    print("=" * 68)
    print("REPROCESO DE UNA SOLICITUD")
    print("=" * 68)
    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    import reprocesar_solicitud as R
    import test_form_options as T
    import test_documentos as D
    from fake_google import FakeSheet

    tmp = Path(tempfile.mkdtemp(prefix="reproceso-"))
    m.CACHE_DIR, m.CONFIG_DIR = tmp, tmp
    m.RUNS_DIR, m.NOTES_DIR = tmp / "intake_runs", tmp / "notes"
    m.MediaIoBaseUpload = D.FakeMedia
    m.download_ofac_sdn = lambda *a, **k: ([], {"source": "t", "download_date": "", "entry_count": 0,
                                                "cache_path": "", "cache_age_days": 0, "cache_fresh": True})
    (tmp / "grantee_registry.json").write_text("[]")
    cfg = json.loads((HERE / "data" / "scorecard_config.json").read_text())
    F = T.form_fields()
    APP = "APP-2027-0002"

    drive = D.FakeDrive()
    folder = drive.files().create(body={"name": "GR-2027-002 - Trap", "parents": ["TEST"],
                                        "mimeType": m.FOLDER_MIME}).execute()["id"]
    old_doc = drive.files().create(body={"name": f"{APP} · Eva assessment", "parents": [folder],
                                         "mimeType": "application/vnd.google-apps.document"}).execute()["id"]

    fields = T.application(F, E1="Teaches 60 women textile artisans; they will receive payments "
                                 "from two local buyers and shops.", E5="18",
                           E12=T.opt(F, "E12", "Awareness"))
    ingested = {"app_id": APP, "timestamp": fields["timestamp"], "timestamp_raw": fields["timestamp"],
                "fields": fields, "row_index": 3, "grantee_id": "GR-2027-002",
                "grantee_match_status": "NEW", "grantee_matched_name": fields["B1"], "is_renewal": False,
                "grantee_registry_data": {}, "seg_2027_data": None, "drive_folder_id": folder}
    (m.RUNS_DIR / "20261116-153007").mkdir(parents=True)
    (m.RUNS_DIR / "20261116-153007" / "ingest.json").write_text(json.dumps({"applications": [ingested]}))

    # La hoja como la dejó la corrida anterior: otra solicitud en la fila 2,
    # ésta en la 3 con las reglas viejas (verde) y el equipo ya trabajando.
    tabs = [m.TAB_CLEAN, m.TAB_CLASSIFY, m.TAB_FLAGS, m.TAB_SCORE, m.TAB_PACKAGE]
    sheet_tabs = {}
    for t in tabs:
        cols = list(m.TAB_COLUMNS[t])
        other = ["APP-2027-0001" if c.lower() == "app_id" else f"keep-{c}" for c in cols]
        mine = [APP if c.lower() == "app_id" else f"old-{c}" for c in cols]
        sheet_tabs[t] = [cols, other, mine]
    sheet_tabs[m.TAB_REVIEW_LOG] = [list(m.REVIEW_LOG_COLUMNS)]
    sh = FakeSheet(sheet_tabs)

    def setc(tab, row_n, name, v):
        h = [str(x).lower() for x in sh.tabs[tab][0]]
        sh.tabs[tab][row_n - 1][h.index(name.lower())] = v
    setc(m.TAB_SCORE, 3, "Semaforo", "RED")
    setc(m.TAB_SCORE, 3, "Total_Normalized", "93.5")
    team = {"Status": "In review", "Status_Since": "2026-11-16 16:00 UTC", "Assigned_To": "Ana",
            "Final_Semaforo": "YELLOW", "Team_Comment": "C1 looks AI-generated", "Reviewed_By": "Ana"}
    for k, v in team.items():
        setc(m.TAB_PACKAGE, 3, k, v)
    old_link = m.drive_file_url(old_doc, google_doc=True)
    setc(m.TAB_PACKAGE, 3, "Eva_Assessment_Link", old_link)

    config = {"active_env": "test", "test": {}, "active": {"intake_sheet_id": "S", "intake_sheet_url": ""}}
    run = lambda **k: R.reprocess(m, sh, drive, config, APP, k.pop("run_id", "RP1"), cfg, {}, {}, **k)  # noqa: E731

    print("\n1. En seco no escribe nada")
    snap = copy.deepcopy(sh.tabs); n_items = len(drive.items)
    with contextlib.redirect_stdout(io.StringIO()):
        r = run(apply=False)
    check(sh.tabs == snap, "la hoja queda idéntica")
    check(len(drive.items) == n_items, "Drive sin archivos nuevos")
    NEW = r["after"]["Semaforo"]
    check(r["before"]["Semaforo"] == "RED" and NEW in ("GREEN", "YELLOW"),
          "muestra el antes (el de la hoja) y el después (reglas actuales)", (r["before"]["Semaforo"], NEW))
    check(r["before"]["Total_Normalized"] == "93.5" and r["after"]["Total_Normalized"] != "93.5",
          "y el puntaje antes y después", (r["before"]["Total_Normalized"], r["after"]["Total_Normalized"]))
    check("participant_count_mismatch" in r["after"]["Flags_Detail"], "y las banderas nuevas")

    print("\n2. Con --apply reemplaza solo su fila")
    with contextlib.redirect_stdout(io.StringIO()):
        r = run(apply=True, run_id="RP2", now="2026-11-16 17:00 UTC")
    check(r["applied"], "aplicado")
    for t in tabs:
        check(sh.tabs[t][1] == snap[t][1], f"{t}: la fila de la otra solicitud no se toca")
        check(col(sh, t, 3, "App_ID") == APP, f"{t}: la fila 3 sigue siendo {APP}")
        check(len(sh.tabs[t]) == 3, f"{t}: no agrega filas", len(sh.tabs[t]))
    check(col(sh, m.TAB_SCORE, 3, "Semaforo") == NEW, "Scorecard con el semáforo nuevo")
    check(col(sh, m.TAB_FLAGS, 3, "participant_count_mismatch") == "YES", "Flags con la bandera nueva")
    check(col(sh, m.TAB_PACKAGE, 3, "Semaforo") == NEW, "Review Package con el semáforo nuevo")

    print("\n3. Lo del equipo se conserva")
    for k, v in team.items():
        check(col(sh, m.TAB_PACKAGE, 3, k) == v, f"{k} intacto", col(sh, m.TAB_PACKAGE, 3, k))

    print("\n4. Documento nuevo, el anterior se queda")
    names = [it["name"] for it in drive.items.values() if folder in it["parents"]]
    check(f"{APP} · Eva assessment" in names, "el documento original sigue en la carpeta")
    new = [n for n in names if n.startswith(f"{APP} · Eva assessment · reprocessed RP2")]
    check(len(new) == 1, "hay un documento nuevo con 'reprocessed <run>'", names)
    link = col(sh, m.TAB_PACKAGE, 3, "Eva_Assessment_Link")
    check(link != old_link and link == r["assessment"], "el tablero apunta al documento nuevo")
    body = next(it["data"] for it in drive.items.values() if it["name"] in new).decode()
    check("Reprocessed on 2026-11-16 17:00 UTC" in body and "earlier assessment stays" in body,
          "el documento dice que es un reproceso y que el anterior se conserva")

    print("\n5. Review Log")
    logs = sh.tabs[m.TAB_REVIEW_LOG][1:]
    sem = [x for x in logs if x[2] == "reprocessed" and x[3] == "Semaforo"]
    check(len(sem) == 1 and sem[0][4] == "RED" and sem[0][5] == NEW,
          "registra el cambio de Semaforo", logs)
    check(any(x[3] == "Total_Normalized" and x[4] == "93.5" for x in logs), "y el cambio de puntaje")
    check(any(x[3] == "Eva_Assessment_Link" and x[4] == old_link and x[5] == link for x in logs),
          "y el enlace viejo y el nuevo")
    check(all(x[6] == "Eva" and x[7] == "RP2" for x in logs), "con autor Eva y el run")

    print("\n6. Lo que no toca y lo que rechaza")
    check(not list(tmp.glob("intake_watermark*")), "no crea ni mueve el watermark")
    check(json.loads((tmp / "grantee_registry.json").read_text()) == []
          and not (tmp / "grantee_registry.test.json").exists(), "no toca el registro de grantees")

    def refused(why, **kw):
        before = copy.deepcopy(sh.tabs)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                kw.pop("fn", run)(apply=True, run_id="RPX")
            check(False, why)
        except R.ReprocessError:
            check(sh.tabs == before, why)

    config["active_env"] = "production"
    refused("se niega en producción y no escribe")
    config["active_env"] = "test"

    sh.tabs[m.TAB_FLAGS].append(list(sh.tabs[m.TAB_FLAGS][2]))
    refused("con el App_ID repetido en una pestaña, no adivina")
    sh.tabs[m.TAB_FLAGS].pop()

    sh.tabs[m.TAB_SCORE][2][0] = "APP-2027-0099"
    refused("si falta la fila en una pestaña, no escribe en ninguna")
    sh.tabs[m.TAB_SCORE][2][0] = APP

    h = sh.tabs[m.TAB_FLAGS][0]
    j = h.index("stage_needs_review"); h[j] = "renamed"
    refused("si falta una columna, no escribe nada (misma guarda que una corrida)")
    h[j] = "stage_needs_review"

    other = lambda **k: R.reprocess(m, sh, drive, config, "APP-2027-0404", k.pop("run_id"), cfg, {}, {}, **k)  # noqa: E731
    refused("una solicitud que no está en ninguna ingesta", fn=other)

    print("\n" + "=" * 68)
    print(f"REPROCESO: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
