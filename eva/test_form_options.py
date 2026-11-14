#!/usr/bin/env python3
"""
Las opciones del formulario, tal como las guarda, contra lo que Eva reconoce.

Por qué existe
──────────────
El 2026-11-13 se encontró que Eva no reconocía F1 ni E12 en ninguna
solicitud. El formulario muestra y guarda la opción con su descripción
("Commerce — number of merchants trading in the last 30 days") y el pipeline
comparaba contra el nombre solo ("Commerce"). Cada solicitud perdía 4 puntos
de Resilience fit y la etapa meta se ignoraba. Ninguna prueba falló porque
todas escribían a mano los valores cortos.

El mismo día se encontró que el filtro de elegibilidad (0.2) que los
parámetros de EVA describen como duro no existía en el código.

Esta prueba no escribe valores a mano: lee las etiquetas de
site/assets/questions.js (con node, el mismo archivo que usa el navegador),
arma una solicitud como la mandaría el formulario y la pasa por los pasos
REALES del pipeline — limpieza, clasificación, filtros y puntaje — con las
librerías de Google simuladas y la salida en un directorio temporal.

Solo corre donde está el repositorio completo (CI y desarrollo): necesita
questions.js y node.

Uso:
  python3 test_form_options.py
"""

import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
QUESTIONS_JS = HERE.parent / "site" / "assets" / "questions.js"
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


def form_fields():
    js = ("const w={};new Function('window',require('fs').readFileSync(process.argv[1],'utf8'))(w);"
          "console.log(JSON.stringify(w.GA27.FIELDS.map(f=>({id:f.id,type:f.type,options:f.options||null}))))")
    out = subprocess.run(["node", "-e", js, str(QUESTIONS_JS)],
                         capture_output=True, text=True, check=True).stdout
    return {f["id"]: f for f in json.loads(out)}


def opt(F, fid, start):
    """La etiqueta completa de la opción que empieza con `start`."""
    hits = [o for o in F[fid]["options"] if o.startswith(start)]
    assert len(hits) == 1, f"{fid}: {len(hits)} opciones empiezan con {start!r}"
    return hits[0]


def application(F, **over):
    """Una solicitud completa con los valores tal como los guarda el formulario
    y los entrega la vista intake_rows (casillas unidas con '; ')."""
    j = "; ".join
    f = {
        "timestamp": "2027-01-20T15:00:00Z",
        "0.1": j(F["0.1"]["options"]), "0.2": j(F["0.2"]["options"]),
        "A1": opt(F, "A1", "Organization"), "A1b": opt(F, "A1b", "Nonprofit"),
        "A2": opt(F, "A2", "1"), "A3": opt(F, "A3", "No"),
        "B1": "Fundación Semillas Digitales (DEMO)", "B2": "Colombia",
        "B3": "Camila Ejemplo Rojas", "B4": "Calle 00 # 00-00, Ciudad Ejemplo, 000000",
        "B5": "85000", "B6": "https://example.org/semillas-demo", "B7": "4", "B8": "DEMO-000000-0",
        "C1": "", "C2": "", "C3": "",
        "D1": "Camila Ejemplo Rojas; Directora; camila@example.org; +57 300 000 0000",
        "D2": "Yes", "D3": "", "D4": "finanzas@example.org",
        "E1": "Bitcoin para comercios de barrio. Capacitamos a 120 comerciantes de dos barrios "
              "para recibir pagos en Bitcoin por Lightning y mantener un registro simple de ventas.",
        "E2": "2027-02-01 → 2027-12-15",
        "E3": "Colombia, Ciudad Ejemplo, barrios Norte y Sur",
        "E4": "Los pequeños comercios pagan comisiones altas por cobrar con tarjeta y muchos no "
              "tienen acceso a cuentas bancarias. Afecta a dueños de tiendas de barrio, mayormente "
              "mujeres, que pierden ingresos y ventas cada mes.",
        "E5": "120",
        "E6": "Son dueños de tiendas de barrio y vendedores ambulantes. Los seleccionamos por "
              "convocatoria abierta en las juntas de acción comunal con las que trabajamos.",
        "E7": "By December 2027, 80% of 120 trained merchants will have accepted at least 10 Bitcoin payments.",
        "E8": "Los comerciantes cobran con QR Lightning en su propio negocio. La cooperativa de "
              "tenderos Ejemplo, nuestro aliado, promueve la aceptación entre sus 300 socios.",
        "E9": j([opt(F, "E9", "Receiving payments"), opt(F, "E9", "Paying")]),
        "E10": "Primer taller con 40 comerciantes | 2027-04-30 | Listas de asistencia; "
               "60 comercios cobrando | 2027-08-15 | Registro de transacciones; "
               "120 comercios con 10 pagos | 2027-12-01 | Reporte de pagos",
        "E11": "El mayor riesgo es que los comerciantes dejen de usar la billetera. Lo reducimos "
               "con acompañamiento semanal y un grupo de soporte.",
        "E12": opt(F, "E12", "Local circulation"),
        "E13": "El dinero circula cuando un comercio recibe un pago en Bitcoin y lo usa para pagar "
               "a su proveedor del barrio, sin salir de la comunidad.",
        "F1": opt(F, "F1", "Commerce"),
        "F2": "0 merchants (2027-01-15)", "F3": "96 merchants (2027-12-15)",
        "F4": opt(F, "F4", "Partner or transaction records"),
        "F5": "En 2025 capacitamos a 60 personas; 35 hicieron al menos una transacción propia.",
        "G1": "32000", "G2": "20000", "G3": "No",
        "G4": "Program delivery 9000; People and training 6000; Technology 2500; "
              "Monitoring 1500; Administration 1000",
        "G5": "", "G7": "Los comercios seguirán cobrando con Lightning porque ya tienen la billetera "
                        "y los clientes; la cooperativa sostiene el soporte con una cuota mínima.",
        "G8": opt(F, "G8", "Bitcoin"), "H1": opt(F, "H1", "2."),
        "H2": "Un técnico para configurar billeteras y voluntarios para la capacitación.",
        "I1": opt(F, "I1", "No"), "I2": "",
        "I3": "Nombre, teléfono y ventas con consentimiento; hoja protegida; se borran a los dos años.",
        "J1": "", "J2": "", "J3": "",
        "K1": opt(F, "K1", "None"), "K2": "", "K3": j(F["K3"]["options"]),
        "K4": j(F["K4"]["options"]), "K5": "Camila Ejemplo Rojas",
    }
    f.update(over)
    return f


def run(m, fields, run_id):
    """La solicitud por los pasos reales, desde la normalización de la ingesta."""
    fields = dict(fields)   # sin normalizar: eso lo tiene que hacer el pipeline
    app = {"app_id": "APP-2027-9001", "timestamp": fields["timestamp"],
           "timestamp_raw": fields["timestamp"], "fields": fields, "row_index": 2,
           "grantee_id": None, "grantee_match_status": "NEW", "grantee_matched_name": fields["B1"],
           "is_renewal": False, "grantee_registry_data": {}, "seg_2027_data": None}
    (m.RUNS_DIR / run_id).mkdir(parents=True, exist_ok=True)
    cfg = json.loads((HERE / "data" / "scorecard_config.json").read_text())
    apps = m.step_clean([app], {}, run_id)["applications"]
    apps = m.step_classify(apps, cfg, {}, {}, run_id)["applications"]
    apps = m.step_flag(apps, run_id)["applications"]
    apps = m.step_score(apps, cfg, run_id)["applications"]
    return apps[0]


def main():
    print("=" * 68)
    print("OPCIONES DEL FORMULARIO CONTRA EVA")
    print("=" * 68)
    if not QUESTIONS_JS.exists() or not shutil.which("node"):
        print("  ✗ falta site/assets/questions.js o node: esta prueba corre en el repositorio")
        return 1
    F = form_fields()

    install_google_stubs()
    m = importlib.import_module("intake_pipeline")
    tmp = Path(tempfile.mkdtemp(prefix="form-options-"))
    m.CACHE_DIR, m.RUNS_DIR = tmp, tmp / "intake_runs"
    m.download_ofac_sdn = lambda *a, **k: ([], {
        "source": "test", "download_date": "", "entry_count": 0,
        "cache_path": "", "cache_age_days": 0, "cache_fresh": True})

    try:
        print("\n1. Cada opción de F1, E12 y J2 se reconoce")
        for fid, valid in m.OPTION_FIELDS.items():
            for o in F[fid]["options"]:
                c = m.canonical_option(o, valid)
                check(c in valid, f"{fid}: {o[:55]!r} → {c!r}", got=c)
        check(m.canonical_option("Something else", m.VALID_MEASURES) == "Something else",
              "un valor desconocido no se fuerza a una opción: sigue apareciendo como desconocido")

        print("\n2. Las demás opciones que Eva interpreta")
        for o in F["A2"]["options"]:
            check(m.normalize_a2(o) != "", f"A2: {o!r} se reconoce", got=m.normalize_a2(o))
        for phrase in [p for _, p in m.ELIGIBILITY_STATEMENTS]:
            hits = [o for o in F["0.2"]["options"] if phrase in o.lower()]
            check(len(hits) == 1, f"0.2: la frase {phrase!r} identifica exactamente una casilla", got=hits)

        print("\n3. Toda bandera que el pipeline levanta se cuenta")
        import re as _re
        src = (HERE / "intake_pipeline.py").read_text(encoding="utf-8")
        raised = set(_re.findall(r'flags\["([a-z_]+)"\] = "YES"', src))
        i = src.index("all_flag_keys = ["); listed = set(_re.findall(r'"([a-z_]+)"', src[i:src.index("]", i)]))
        check(raised <= listed, "cada flags[...] = \"YES\" está en all_flag_keys", got=sorted(raised - listed))

        print("\n4. Una solicitud completa, como la manda el formulario")
        a = run(m, application(F), "complete")
        cl, sc, fl = a["classified"], a["score"], a["flags"]
        base_critical = fl.get("Critical_Flags_Count", 0)
        check(cl.get("Measure_Matches_Stage") == "YES",
              "F1 = Commerce cae en lo esperado para la meta Local circulation",
              got=(cl.get("Measure_Matches_Stage"), cl.get("Expected_Measures")))
        check(cl.get("Measure_Basis") == "target", "la medida se evalúa contra la etapa META (E12)",
              got=cl.get("Measure_Basis"))
        check(cl.get("Stage_Target") == "Local circulation", "E12 se guarda con su nombre canónico",
              got=cl.get("Stage_Target"))
        notes = json.dumps(cl, ensure_ascii=False)
        check("unrecognized_measure" not in notes, "sin nota de medida no reconocida")
        check("F1 in expected set (4pts)" in sc.get("Resilience_Fit_Reason", "") or
              "F1 in expected set" in json.dumps(sc),
              "el puntaje acredita los 4 puntos de F1", got=sc.get("Resilience_Fit_Reason"))
        check("option 2" in json.dumps(sc), "H1 se reconoce como opción 2",
              got=[v for k, v in sc.items() if "Deliver" in k or "deliver" in k])
        check("eligibility_incomplete" not in fl.get("Flags_Detail", ""),
              "con las cuatro casillas de 0.2 no hay bandera de elegibilidad",
              got=fl.get("Flags_Detail"))

        print("\n5. Filtro de elegibilidad")
        three = "; ".join(o for o in F["0.2"]["options"] if "price gain" not in o.lower())
        a = run(m, application(F, **{"0.2": three, "K2": "Usamos Bitcoin como ahorro; lo explicamos."}), "elig3")
        fl = a["flags"]
        check("eligibility_missing:no_price_gains" in fl.get("Flags_Detail", ""),
              "tres de cuatro → bandera que dice cuál falta", got=fl.get("Flags_Detail"))
        check(fl.get("Critical_Flags_Count", 0) == base_critical + 1,
              "y cuenta como crítica: una más que la solicitud completa",
              got=(base_critical, fl.get("Critical_Flags_Count")))
        a = run(m, application(F, **{"0.2": ""}), "elig0")
        check("no_K2_explanation" in a["flags"].get("Flags_Detail", ""),
              "0.2 vacío y sin K2 → bandera, y lo dice", got=a["flags"].get("Flags_Detail"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 68)
    print(f"OPCIONES DEL FORMULARIO: {PASSED} ok, {len(FAILS)} fallidos")
    print("=" * 68)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
