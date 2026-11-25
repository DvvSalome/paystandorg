#!/usr/bin/env python3
"""
Vuelve a evaluar solicitudes ya ingeridas con el código actual, SIN escribir
nada: ni hoja, ni Drive, ni watermark, ni registro, ni Slack. Lee
cache/intake_runs/<run_id>/ingest.json y corre limpieza → clasificación →
banderas → puntaje en memoria. El documento C1 se descarga (solo lectura)
de Storage para comparar nombre y dirección, igual que en una corrida.

Uso:
  python3 reevaluar_solicitud.py --run-id 20261116-153007 [--app APP-2027-0002]
"""
import argparse
import json
import sys
import tempfile
from pathlib import Path

import intake_pipeline as m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--app", default=None)
    a = ap.parse_args()

    src = m.RUNS_DIR / a.run_id / "ingest.json"
    if not src.exists():
        print(f"no existe {src}")
        return 1
    apps = json.loads(src.read_text())["applications"]
    if a.app:
        apps = [x for x in apps if x.get("app_id") == a.app]
    if not apps:
        print("ninguna solicitud con ese App_ID en ese run")
        return 1

    # Todo lo que los pasos escriben va a una carpeta temporal.
    m.RUNS_DIR = Path(tempfile.mkdtemp(prefix="reevaluar-"))
    m.NOTES_DIR = m.RUNS_DIR / "notes"
    m.send_slack_notification = lambda *x, **k: None
    rid = "reevaluar"
    (m.RUNS_DIR / rid).mkdir(parents=True)

    cfg = m.load_scorecard_config()
    country, region = m.load_country_mapping(), m.load_region_mapping()
    drive = m.get_drive_service()
    apps = m.step_clean(apps, country, rid)["applications"]
    apps = m.step_classify(apps, cfg, country, region, rid)["applications"]
    for x in apps:
        x["_config"] = cfg
    apps = m.step_flag(apps, rid, drive_api=drive)["applications"]
    apps = m.step_score(apps, cfg, rid)["applications"]

    for x in apps:
        c, fl, sc = x["classified"], x["flags"], x["score"]
        print("\n" + "=" * 60)
        print(f"{x['app_id']} · {x['fields'].get('B1', '')}")
        print("=" * 60)
        print(f"Semaforo:          {sc['Semaforo']}   (por puntaje: {sc['Semaforo_By_Score']})")
        print(f"Semaforo_Hold:     {sc.get('Semaforo_Hold', '')}")
        print(f"Total:             {sc['Total_Score']}/{sc['Score_Max_Available']} → {sc['Total_Normalized']}")
        for _, col, why, mx in m.CRITERIA:
            print(f"  {col}: {sc[col]}/{mx}")
        print(f"Etapa:             {c.get('Stage_Suggested')} → meta {c.get('Stage_Target')} (salto {c.get('Stage_Jump')})")
        print(f"Resilience_Fit:    {sc.get('Resilience_Fit_Reason', '')}")
        print(f"Flags ({fl['Flags_Count']}, críticas {fl['Critical_Flags_Count']}): {fl['Flags_Detail']}")
    print("\nNada se escribió en la hoja ni en Drive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
