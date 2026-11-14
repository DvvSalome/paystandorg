#!/usr/bin/env python3
"""
Tablero de revisión — 2026-11-13.

  1. El documento "Eva assessment": el razonamiento completo de una solicitud
     real del formulario (pasada por los pasos reales), en inglés, citando la
     pregunta de cada punto, con los filtros duros y las banderas explicadas.
  2. Se crea en la carpeta del solicitante, una sola vez, y su enlace queda en
     la fila del tablero.
  3. El historial: cada cambio del equipo en el tablero queda en
     "9. Review Log"; las filas se buscan por App_ID (ordenar la hoja no rompe
     nada); un fallo al escribir no pierde cambios.

Necesita el repositorio completo (lee las etiquetas de questions.js con node).

Uso:
  python3 test_review_board.py
"""
import contextlib
import importlib
import io
import json
import shutil
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


def main():
    print("=" * 68)
    print("TABLERO DE REVISIÓN")
    print("=" * 68)
    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    import test_form_options as T
    import test_documentos as D
    from fake_google import FakeSheet
    tmp = Path(tempfile.mkdtemp(prefix="review-"))
    m.CACHE_DIR, m.RUNS_DIR, m.NOTES_DIR = tmp, tmp / "intake_runs", tmp / "notes"
    ofac_none = lambda *a, **k: ([], {"source": "t", "download_date": "", "entry_count": 0,  # noqa: E731
                                      "cache_path": "", "cache_age_days": 0, "cache_fresh": True})
    m.download_ofac_sdn = ofac_none
    try:
        F = T.form_fields()
        with contextlib.redirect_stdout(io.StringIO()):
            ok = T.run(m, T.application(F, E4="Barrera <b>alta</b> & comisiones para comerciantes del barrio "
                                              "que pierden ventas y pagan intermediarios cada mes."), "a1")
            m.download_ofac_sdn = lambda *a, **k: ([("FUNDACION SEMILLAS DIGITALES", "")], {
                "source": "t", "download_date": "", "entry_count": 1, "cache_path": "",
                "cache_age_days": 0, "cache_fresh": True})
            hit = T.run(m, T.application(F), "a2", app_id="APP-2027-9002")
            m.download_ofac_sdn = ofac_none

        print("\n1. El documento de razonamiento")
        html = m.assessment_html(ok, board_url="https://docs.google.com/spreadsheets/d/BOARD")
        for sec in ("1. Summary", "2. Hard gates", "3. Stage", "4. Pillars", "5. Scorecard",
                    "6. Flags", "7. Team review"):
            check(f"<h2>{sec}</h2>" in html, f"sección {sec}")
        for label, pts, why, mx in m.CRITERIA:
            check(f"{label}: {ok['score'][pts]} of {mx}" in html, f"criterio con su puntaje: {label}")
        check("F1 in expected set (4pts)" in html and "E7 result has number and date (4pts)" in html,
              "cada sub-punto con lo que sumó, citando la pregunta")
        check(ok["classified"]["Stage_Justification"].split(" (")[0] in html and "Signal counts" in html,
              "la etapa con las señales que la sostienen")
        check("not a decision" in html and "BOARD" in html, "dice que es pre-clasificación y enlaza el tablero")
        check("missing_nonprofit_proof" in html and "did not upload proof" in html,
              "las banderas explicadas en lenguaje claro")
        h2 = m.assessment_html(hit)
        check("<b>ofac_flag</b>: TRIGGERED" in h2 and "held red by: ofac_flag" in h2,
              "un filtro duro aparece activado y explica el rojo")
        check("<b>ofac_flag</b>: clear" in html, "y sin él, aparece despejado")
        risky = dict(ok, fields=dict(ok["fields"], B1="<script>x</script> Org"))
        rh = m.assessment_html(risky)
        check("<script" not in rh and "&lt;script&gt;" in rh, "el texto del solicitante va escapado")

        print("\n2. Se crea en la carpeta del solicitante, una sola vez")
        drive = D.FakeDrive()
        m.MediaIoBaseUpload = D.FakeMedia
        folder = drive.files().create(body={"name": "GR-2027-001 - Semillas", "parents": ["GA"],
                                            "mimeType": m.FOLDER_MIME}).execute()["id"]
        app = dict(ok, drive_folder_id=folder)
        rows = [{"app_id": app["app_id"], "Eva_Assessment_Link": ""}]
        errs = m.write_assessment_docs(drive, [app], rows, board_url="https://x")
        docs = [v for v in drive.items.values() if v["name"].endswith("Eva assessment")]
        check(not errs and len(docs) == 1 and folder in docs[0]["parents"],
              "un Google Doc en la carpeta del solicitante", errs)
        check(docs and docs[0]["mimeType"] == m.GOOGLE_DOC_MIME, "es un Google Doc (se puede comentar)")
        check(rows[0]["Eva_Assessment_Link"].startswith("https://docs.google.com/document/d/"),
              "el enlace queda en la fila del tablero", rows[0])
        n = len(drive.creates)
        m.write_assessment_docs(drive, [app], [{"app_id": app["app_id"]}])
        check(len(drive.creates) == n, "otra corrida no lo duplica ni lo reescribe")
        rows = [{"app_id": "APP-X"}]
        m.write_assessment_docs(drive, [dict(ok, app_id="APP-X", drive_folder_id="")], rows)
        check(rows[0]["Eva_Assessment_Link"].startswith("not created"), "sin carpeta lo dice en la fila", rows)

        print("\n3. Historial de revisión")
        cols = m.TAB_COLUMNS[m.TAB_PACKAGE]
        def row(app_id, **v):
            base = {c: "" for c in cols}
            base.update(App_ID=app_id, Status="New", Status_Since="2027-01-20 10:00 UTC", **v)
            return [base[c] for c in cols]
        sh = FakeSheet({m.TAB_PACKAGE: [list(cols), row("APP-1"), row("APP-2")],
                        m.TAB_REVIEW_LOG: [list(m.REVIEW_LOG_COLUMNS)]})
        def logs():
            return [dict(zip(m.REVIEW_LOG_COLUMNS, r)) for r in sh.tabs[m.TAB_REVIEW_LOG][1:]]
        r1 = m.review_sync(sh, "x", "test", "RUN1")
        check(r1["logged"] == 2 and all(l["Event"] == "added_to_board" for l in logs()),
              "primera vez: cada solicitud entra al historial", logs())

        # El equipo ordena la hoja (APP-2 arriba) y edita APP-2.
        body = sh.tabs[m.TAB_PACKAGE]
        body[1], body[2] = body[2], body[1]
        ci = {c: i for i, c in enumerate(cols)}
        body[1][ci["Status"]] = "In review"
        body[1][ci["Assigned_To"]] = "Marisa"
        body[1][ci["Reviewed_By"]] = "Marisa"
        r2 = m.review_sync(sh, "x", "test", "RUN2")
        new = logs()[2:]
        check(r2["logged"] == 3 and {l["Field"] for l in new} == {"Status", "Assigned_To", "Reviewed_By"},
              "cada campo cambiado es una fila del historial", new)
        st = [l for l in new if l["Field"] == "Status"]
        check(st and st[0]["App_ID"] == "APP-2" and st[0]["Old_Value"] == "New"
              and st[0]["New_Value"] == "In review" and st[0]["By"] == "Marisa",
              "con solicitud, valor anterior, valor nuevo y quién", st)
        check(body[1][ci["Status_Since"]] != "2027-01-20 10:00 UTC"
              and body[2][ci["Status_Since"]] == "2027-01-20 10:00 UTC",
              "Status_Since se actualiza en la fila correcta aunque la hoja esté ordenada distinto")
        check(m.review_sync(sh, "x", "test", "RUN3")["logged"] == 0, "sin cambios, nada nuevo en el historial")

        body[2][ci["Final_Stage"]] = "Awareness"
        sh.fail_append = True
        try:
            m.review_sync(sh, "x", "test", "RUN4")
            check(False, "un fallo al escribir el historial debe notarse")
        except RuntimeError:
            check(True, "un fallo al escribir el historial se nota")
        sh.fail_append = False
        r5 = m.review_sync(sh, "x", "test", "RUN5")
        check(r5["logged"] == 1 and logs()[-1]["Field"] == "Final_Stage" and logs()[-1]["App_ID"] == "APP-1",
              "y el cambio no se pierde: entra en la corrida siguiente", logs()[-1:])
        check((tmp / "review_snapshot.test.json").exists() and not (tmp / "review_snapshot.production.json").exists(),
              "la memoria del historial es por ambiente")
        before_vals = [list(r) for r in sh.tabs[m.TAB_PACKAGE]]
        m.review_sync(sh, "x", "test", "RUN6")
        team_idx = [ci[c] for c in m.REVIEW_TEAM_COLUMNS]
        check(all(r[i] == b[i] for r, b in zip(sh.tabs[m.TAB_PACKAGE], before_vals) for i in team_idx),
              "Eva nunca escribe en las columnas del equipo")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"TABLERO DE REVISIÓN: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
