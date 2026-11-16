#!/usr/bin/env python3
"""
Reglas de revisión — 2026-11-16, a partir de APP-2027-0002 (caso de prueba
del equipo): salió VERDE con una imagen generada por IA como documento de
registro, con la etapa por encima de la meta del propio solicitante y con 60
participantes en E1 contra 18 en E5, sin que nada lo marcara.

  1. Si el nombre (B1) o la dirección (B4) no están en C1, el semáforo queda
     como máximo en AMARILLO ("verify documents"); no en rojo.
  2. Etapa inferida por encima de la meta (E12): bandera stage_needs_review
     y 0 puntos por "etapa inferida".
  3. Número de participantes en E1 distinto de E5: bandera.

Necesita el repositorio completo (lee questions.js con node).
  python3 test_reglas_revision.py
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


def main():
    print("=" * 68)
    print("REGLAS DE REVISIÓN")
    print("=" * 68)
    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    import test_form_options as T
    tmp = Path(tempfile.mkdtemp(prefix="reglas-"))
    m.CACHE_DIR, m.RUNS_DIR, m.NOTES_DIR = tmp, tmp / "intake_runs", tmp / "notes"
    m.download_ofac_sdn = lambda *a, **k: ([], {"source": "t", "download_date": "", "entry_count": 0,
                                                "cache_path": "", "cache_age_days": 0, "cache_fresh": True})
    cfg = json.loads((HERE / "data" / "scorecard_config.json").read_text())
    for r in ("cap", "addr", "gate", "pend"):
        (m.RUNS_DIR / r).mkdir(parents=True, exist_ok=True)
    F = T.form_fields()
    with contextlib.redirect_stdout(io.StringIO()):
        base = T.run(m, T.application(F), "base")
        trap = T.run(m, T.application(
            F,
            E1="Bitcoin Basics for Women Artisans. A nine-month program that teaches 60 women "
               "textile artisans to use a Bitcoin wallet safely; they will receive payments "
               "from two local buyers and shops.",
            E5="18",
            E12=T.opt(F, "E12", "Awareness"),
        ), "trap", app_id="APP-2027-9010")

    print("\n0. La solicitud base no cambia")
    check(base["score"]["Semaforo"] == base["score"]["Semaforo_By_Score"] and not base["score"]["Semaforo_Hold"],
          "sin banderas de documento ni de etapa, el semáforo es el del puntaje", base["score"]["Semaforo_Hold"])
    for k in ("participant_count_mismatch", "stage_needs_review"):
        check(base["flags"].get(k, "") != "YES", f"base sin {k}", base["flags"].get(k))
    check("stage inferred=" in base["score"]["Resilience_Fit_Reason"]
          and "(4pts)" in base["score"]["Resilience_Fit_Reason"].split("stage inferred=")[1][:60],
          "base conserva los 4 puntos de etapa")

    print("\n1. Documento que no coincide → máximo amarillo")
    cap = copy.deepcopy(base)
    check(cap["score"]["Semaforo_By_Score"] == "GREEN", "la base es verde por puntaje (premisa)",
          cap["score"]["Semaforo_By_Score"])
    cap["flags"]["name_mismatch"] = "YES"
    with contextlib.redirect_stdout(io.StringIO()):
        cap = m.step_score([cap], cfg, "cap")["applications"][0]
    check(cap["score"]["Semaforo"] == "YELLOW", "name_mismatch baja el verde a amarillo", cap["score"]["Semaforo"])
    check(cap["score"]["Semaforo_By_Score"] == "GREEN", "el color por puntaje queda a la vista")
    check(cap["score"]["Semaforo_Hold"] == "verify documents: name_mismatch",
          "el motivo queda en Semaforo_Hold", cap["score"]["Semaforo_Hold"])
    html = m.assessment_html(cap, board_url="")
    check("capped at yellow: verify documents" in html and "held red by" not in html,
          "el documento dice 'capped at yellow', no 'held red'")

    addr = copy.deepcopy(base); addr["flags"]["address_mismatch"] = "YES"
    with contextlib.redirect_stdout(io.StringIO()):
        addr = m.step_score([addr], cfg, "addr")["applications"][0]
    check(addr["score"]["Semaforo"] == "YELLOW", "address_mismatch también", addr["score"]["Semaforo"])

    gate = copy.deepcopy(base); gate["flags"]["name_mismatch"] = "YES"; gate["flags"]["ofac_flag"] = "YES"
    with contextlib.redirect_stdout(io.StringIO()):
        gate = m.step_score([gate], cfg, "gate")["applications"][0]
    check(gate["score"]["Semaforo"] == "RED" and gate["score"]["Semaforo_Hold"] == "ofac_flag",
          "un filtro duro sigue mandando: rojo", (gate["score"]["Semaforo"], gate["score"]["Semaforo_Hold"]))

    pend = copy.deepcopy(base); pend["flags"]["name_mismatch"] = "PENDING"
    with contextlib.redirect_stdout(io.StringIO()):
        pend = m.step_score([pend], cfg, "pend")["applications"][0]
    check(pend["score"]["Semaforo"] == "GREEN",
          "si no se pudo leer el documento (PENDING) no se castiga", pend["score"]["Semaforo"])

    print("\n2. Etapa por encima de la meta")
    c = trap["classified"]
    check(isinstance(c.get("Stage_Jump"), int) and c["Stage_Jump"] < 0,
          "premisa: la etapa inferida queda por encima de la meta", (c.get("Stage_Suggested"), c.get("Stage_Target")))
    check(trap["flags"].get("stage_needs_review") == "YES", "bandera stage_needs_review")
    rf = trap["score"]["Resilience_Fit_Reason"]
    check("needs review (0pts)" in rf, "0 puntos por la etapa inferida", rf)
    check(trap["score"]["Score_Resilience_Fit"] <= base["score"]["Score_Resilience_Fit"] - 4,
          "pierde los 4 puntos frente a la base",
          (trap["score"]["Score_Resilience_Fit"], base["score"]["Score_Resilience_Fit"]))
    check("stage_needs_review" in m.assessment_html(trap, board_url=""),
          "la bandera aparece explicada en el documento")

    print("\n3. Participantes E1 contra E5")
    check(trap["flags"].get("participant_count_mismatch") == "YES", "60 en E1 y 18 en E5 levanta la bandera")
    check("E1 says 60, E5 says 18" in trap["flags"].get("Flags_Detail", ""),
          "el detalle dice los dos números", trap["flags"].get("Flags_Detail"))
    pc = m.participant_counts_in_text
    check(pc("Capacitamos a 120 comerciantes de dos barrios") == [120], "español", pc("Capacitamos a 120 comerciantes"))
    check(pc("teaches 60 women textile artisans") == [60], "inglés con adjetivos en medio")
    check(pc("1,200 families in 3 towns") == [1200], "miles con coma; '3 towns' no cuenta")
    check(pc("A nine-month program in 2027") == [], "años y números sin personas no cuentan")
    check(trap["flags"]["Flags_Count"] >= 2 and trap["flags"]["Critical_Flags_Count"] == 0,
          "las dos banderas cuentan, ninguna es filtro duro")

    print("\n" + "=" * 68)
    print(f"REGLAS DE REVISIÓN: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
