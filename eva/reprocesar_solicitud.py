#!/usr/bin/env python3
"""
Reprocesa UNA solicitud ya procesada, con las reglas actuales. Solo en TEST.

Para calibrar: después de cambiar una regla hay que poder volver a pasar los
mismos casos. Una corrida normal no puede: la hoja salta los App_ID que ya
tiene y el documento de evaluación se escribe una sola vez.

Qué hace (con --apply):
  - toma la solicitud tal como se ingirió (cache/intake_runs/<run>/ingest.json,
    la más reciente que la contenga) y la pasa por limpieza → clasificación →
    banderas → puntaje → paquete;
  - reemplaza SU fila en "2. Cleaned" … "6. Review Package", buscándola por
    App_ID (no por posición);
  - en "6. Review Package" conserva todo lo del equipo: Status, Status_Since
    y las columnas de revisión. Nunca borra una decisión;
  - crea un documento NUEVO "<APP> · Eva assessment · reprocessed <run>" en la
    carpeta del solicitante; el anterior se queda, es el registro de lo que
    Eva dijo antes;
  - deja en "9. Review Log" el cambio de semáforo, de puntaje y el enlace nuevo.

Qué NO toca: watermark, registro de grantees, carpetas, documentos del
solicitante, Process Log, Slack.

Sin --apply solo muestra el antes y el después.

Uso:
  python3 reprocesar_solicitud.py --app APP-2027-0002            # en seco
  python3 reprocesar_solicitud.py --app APP-2027-0002 --apply
"""
import argparse
import copy
import json
import sys
from datetime import datetime, timezone

RESULT_TABS = None   # se llena con los nombres del módulo


class ReprocessError(Exception):
    pass


def find_ingested(m, app_id):
    """La solicitud tal como quedó en la ingesta más reciente que la contiene."""
    if not m.RUNS_DIR.exists():
        raise ReprocessError(f"no existe {m.RUNS_DIR}")
    for d in sorted((p for p in m.RUNS_DIR.iterdir() if p.is_dir()), reverse=True):
        f = d / "ingest.json"
        if not f.exists():
            continue
        try:
            apps = json.loads(f.read_text()).get("applications", [])
        except Exception:
            continue
        for a in apps:
            if a.get("app_id") == app_id:
                return copy.deepcopy(a), d.name
    raise ReprocessError(f"{app_id} no aparece en ninguna ingesta de {m.RUNS_DIR}")


def _locate(data, app_id):
    """(headers, número de fila en la hoja, valores) de la fila de app_id."""
    if not data:
        return None, None, None
    headers = data[0]
    lower = [str(h).strip().lower() for h in headers]
    if "app_id" not in lower:
        return headers, None, None
    i = lower.index("app_id")
    hits = [(n, r) for n, r in enumerate(data[1:], start=2)
            if i < len(r) and str(r[i]).strip() == app_id]
    if len(hits) > 1:
        raise ReprocessError(f"{app_id} aparece {len(hits)} veces en una pestaña; no sé cuál reemplazar")
    if not hits:
        return headers, None, None
    return headers, hits[0][0], hits[0][1]


def _get(headers, row, col):
    lower = [str(h).strip().lower() for h in headers]
    c = col.lower()
    if c in lower:
        j = lower.index(c)
        return row[j] if j < len(row) else ""
    return ""


def _to_list(d, headers):
    ci = {k.lower(): v for k, v in d.items()}
    out = []
    for h in headers:
        v = d.get(h)
        if v is None:
            v = ci.get(str(h).lower(), "")
        out.append(v)
    return out


def reprocess(m, sheets, drive, config, app_id, run_id, scorecard_cfg,
              country_map, region_map, apply=False, now=None):
    if config.get("active_env") != "test":
        raise ReprocessError("solo se reprocesa en test")
    sid = config["active"]["intake_sheet_id"]
    tabs = [m.TAB_CLEAN, m.TAB_CLASSIFY, m.TAB_FLAGS, m.TAB_SCORE, m.TAB_PACKAGE]
    now = now or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    app, source_run = find_ingested(m, app_id)
    (m.RUNS_DIR / run_id).mkdir(parents=True, exist_ok=True)

    # La hoja primero: si la fila no está, no hay nada que reprocesar.
    current = {}
    for t in tabs:
        headers, rown, row = _locate(m.read_sheet(sheets, sid, t), app_id)
        if rown is None:
            raise ReprocessError(f"{app_id} no tiene fila en '{t}'")
        current[t] = (headers, rown, row)

    apps = m.step_clean([app], country_map, run_id)["applications"]
    apps = m.step_classify(apps, scorecard_cfg, country_map, region_map, run_id)["applications"]
    for a in apps:
        a["_config"] = scorecard_cfg
    apps = m.step_flag(apps, run_id, drive_api=drive)["applications"]
    apps = m.step_score(apps, scorecard_cfg, run_id)["applications"]
    pkg = m.step_package(apps, run_id)["package_rows"][0]
    a = apps[0]

    # Lo del equipo no se toca.
    ph, _, prow = current[m.TAB_PACKAGE]
    keep = list(m.REVIEW_TRACKED_COLUMNS) + ["Status_Since"]
    for col in keep:
        pkg[col] = _get(ph, prow, col)
    old_link = _get(ph, prow, "Eva_Assessment_Link")

    new_rows = {m.TAB_CLEAN: a["cleaned"], m.TAB_CLASSIFY: a["classified"],
                m.TAB_FLAGS: a["flags"], m.TAB_SCORE: a["score"], m.TAB_PACKAGE: pkg}

    # Misma guarda que una corrida: ningún valor sin columna.
    missing = {}
    for t, d in new_rows.items():
        have = {str(h).strip().lower() for h in current[t][0]}
        lack = [k for k in d if not k.startswith("_") and k.lower() not in have]
        if lack:
            missing[t] = lack
    if missing:
        raise ReprocessError("faltan columnas (corre sync_sheet_headers.py --apply): "
                             + "; ".join(f"{t}: {', '.join(v)}" for t, v in missing.items()))

    sh, _, srow = current[m.TAB_SCORE]
    before = {
        "Semaforo": _get(sh, srow, "Semaforo"),
        "Semaforo_Hold": _get(sh, srow, "Semaforo_Hold"),
        "Total_Normalized": str(_get(sh, srow, "Total_Normalized")),
        "Flags_Detail": _get(current[m.TAB_FLAGS][0], current[m.TAB_FLAGS][2], "Flags_Detail"),
        "Stage_Suggested": _get(current[m.TAB_CLASSIFY][0], current[m.TAB_CLASSIFY][2], "Stage_Suggested"),
    }
    after = {
        "Semaforo": a["score"].get("Semaforo", ""),
        "Semaforo_Hold": a["score"].get("Semaforo_Hold", ""),
        "Total_Normalized": str(a["score"].get("Total_Normalized", "")),
        "Flags_Detail": a["flags"].get("Flags_Detail", ""),
        "Stage_Suggested": a["classified"].get("Stage_Suggested", ""),
    }
    report = {"app_id": app_id, "run_id": run_id, "source_run": source_run,
              "team_status": pkg.get("Status", ""), "before": before, "after": after,
              "applied": False, "assessment": ""}
    if not apply:
        return report

    # Documento nuevo; el anterior se queda.
    folder = a.get("drive_folder_id", "")
    if drive and folder:
        name = f"{app_id} · {m.ASSESSMENT_SUFFIX} · reprocessed {run_id}"
        html = m.assessment_html(a, config["active"].get("intake_sheet_url", ""))
        note = (f"<p><b>Reprocessed on {now} (run {run_id}) with the current rules. "
                f"The earlier assessment stays in this folder as the record of what Eva said then.</b></p>")
        html = html.replace("</h1>", "</h1>" + note, 1)
        fid = m._upload(drive, folder, name, html.encode("utf-8"), "text/html", as_google_doc=True)
        pkg["Eva_Assessment_Link"] = m.drive_file_url(fid, google_doc=True)
    else:
        pkg["Eva_Assessment_Link"] = old_link or "not created: no applicant folder"
    report["assessment"] = pkg["Eva_Assessment_Link"]

    writes = [(t, [_to_list(new_rows[t], current[t][0])], current[t][1]) for t in tabs]
    ok, errs = m.atomic_batch_write(sheets, sid, writes)
    if errs:
        raise ReprocessError(f"escritura incompleta ({ok}/{len(writes)}): {'; '.join(errs)[:300]}")

    log = []
    for field in ("Semaforo", "Total_Normalized"):
        log.append([now, app_id, "reprocessed", field, before[field], after[field], "Eva", run_id])
    log.append([now, app_id, "reprocessed", "Eva_Assessment_Link", old_link,
                pkg["Eva_Assessment_Link"], "Eva", run_id])
    try:
        m.append_sheet(sheets, sid, m.TAB_REVIEW_LOG, log)
    except Exception as e:
        report["review_log_error"] = f"{type(e).__name__}: {str(e)[:120]}"
    report["applied"] = True
    (m.RUNS_DIR / run_id / "reprocess.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report


def print_report(r):
    print("\n" + "=" * 60)
    print(f"{r['app_id']}  (ingesta {r['source_run']} → run {r['run_id']})")
    print("=" * 60)
    if r["team_status"] in ("Decided", "Closed"):
        print(f"⚠️  El equipo ya marcó este caso como {r['team_status']}; su decisión no se toca.")
    for k in ("Semaforo", "Semaforo_Hold", "Total_Normalized", "Stage_Suggested", "Flags_Detail"):
        b, a = r["before"][k], r["after"][k]
        mark = "  " if b == a else "→ "
        print(f"{mark}{k}:\n     antes:   {b}\n     después: {a}")
    if r["applied"]:
        print(f"\nAplicado. Documento nuevo: {r['assessment']}")
        if r.get("review_log_error"):
            print(f"⚠️  No se pudo escribir el Review Log: {r['review_log_error']}")
    else:
        print("\nEn seco: nada se escribió. Agrega --apply para reemplazar las filas.")


def main():
    import intake_pipeline as m
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--environment", default="test")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.environment != "test":
        print("Solo se reprocesa en test.")
        return 2
    try:
        lock = m.acquire_run_lock(info={"by": "reprocesar_solicitud", "app": a.app})  # noqa: F841
    except m.PipelineLocked as e:
        print(f"Otra corrida tiene el candado: {e}")
        return m.EXIT_LOCKED
    config = m.load_config()
    config["active"], config["active_env"] = config["test"], "test"
    m.send_slack_notification = lambda *x, **k: None
    try:
        r = reprocess(m, m.get_sheets_service(), m.get_drive_service(), config, a.app,
                      m.generate_run_id(), m.load_scorecard_config(),
                      m.load_country_mapping(), m.load_region_mapping(), apply=a.apply)
    except ReprocessError as e:
        print(f"✗ {e}")
        return 1
    print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
