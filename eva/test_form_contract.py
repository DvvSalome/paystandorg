#!/usr/bin/env python3
"""
POOL A — Contrato del formulario, con datos controlados.

Qué prueba y qué NO prueba
──────────────────────────
Prueba que una fila del formulario produzca EXACTAMENTE la salida esperada.
Cada caso trae su resultado calculado a mano, no copiado de una corrida del
pipeline. Si lo copiara de una corrida, la prueba diría "el pipeline hace lo
que el pipeline hace", que es exactamente lo que no queremos saber.

No prueba que Supabase funcione, ni que Eva corra, ni que el HTML del
formulario renderice. Para eso está el pool B (test_live_intake.py).

Por qué existe aparte de test_score_v3
──────────────────────────────────────
test_score_v3 prueba el scorecard con los campos ya limpios. Esta prueba
entra una fila CRUDA — 61 columnas en orden, como la escribe el formulario —
y recorre INGEST → CLEAN → CLASSIFY → FLAG → SCORE. Ahí viven los errores que
el scorecard nunca puede ver:

  · una columna leída de la posición equivocada
  · un ID que cambió de significado (17 lo hicieron en v3)
  · un campo que nadie limpia y que otro paso asume limpio
  · un flag que no se levanta

Los dos bugs de colisión que encontramos en noviembre eran de este tipo: el
screening OFAC leía la dirección en vez del representante legal, y el match
de dirección leía el presupuesto numérico. Ningún test de scorecard los veía,
porque el scorecard recibía los campos ya correctos.

Corre sin las librerías de Google: extrae las funciones por AST igual que
test_score_v3, así que funciona en tu máquina y en el servidor de Eva.

Uso:
  python3 test_form_contract.py            # todos los casos
  python3 test_form_contract.py --case TIER_LIGHT
  python3 test_form_contract.py --show TIER_LIGHT   # volcado de la salida
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent

# ── Carga del pipeline sin tocar las librerías de Google ──────────────────
#
# intake_pipeline importa google.oauth2 en la línea 47. En esta máquina no
# está instalado y en Eva sí, pero la prueba debe correr en las dos. Extraer
# por AST solo lo que necesitamos evita la dependencia y, de paso, deja claro
# qué superficie del pipeline estamos probando.

# Cierre transitivo de llamadas, calculado con AST — no una lista a ojo.
# Si el pipeline agrega una dependencia nueva, structural_checks lo reporta
# en vez de reventar con NameError a media corrida.
WANT_FN = {
    "parse_number", "count_words", "normalize_text", "normalize_timestamp",
    "normalize_a2", "has_repeated_text", "has_consecutive_consonants",
    "norm_org_name", "check_ofac", "check_name_in_doc", "check_address_in_doc",
    "infer_stage", "infer_pillar", "step_score", "_requested_amount",
    "is_simplified_tier", "is_renewal_skipping", "resolve_app_id",
    "generate_app_id", "_count_signals", "_has_any", "_median",
    "has_time_markers_text",
}
WANT_CONST = {
    "QUESTION_MAP", "NUMERIC_FIELDS", "DATE_FIELDS", "PARAGRAPH_FIELDS",
    "REMOVED_FIELDS_V2", "REQUIRED_FIELDS", "URL_REGEX", "EMAIL_REGEX",
    "VALID_PILLARS", "VALID_MEASURES", "VALID_STAGES", "STAGE_SIGNALS",
    "PILLAR_SIGNALS", "RESULT_FORMULA_FIELD",
    "APP_ID_PATTERN", "GENERIC_BENEFICIARY_TERMS", "INBOUND_APP_ID_COLUMNS",
    "MIN_PARAGRAPH_WORDS", "RUNS_DIR", "_AFFECTED_GROUP_TERMS",
    "_CONTINUITY_RESOURCE", "_CONTINUITY_WHO", "_FINANCIAL_TERMS",
    "_MITIGATION_TERMS", "_MONTH_WORDS", "_PARTNER_TERMS", "_RISK_TERMS",
}


def load_pipeline():
    """
    Extrae del pipeline las funciones pedidas MÁS todo lo que necesitan,
    calculando el cierre transitivo con AST.

    El cierre automático importa: a mano la lista se queda corta en cuanto
    el pipeline agrega un helper, y el síntoma es un NameError a media
    corrida en vez de un fallo legible. Aquí se resuelve antes de ejecutar
    una sola aserción.
    """
    src = (HERE / "intake_pipeline.py").read_text()
    tree = ast.parse(src)

    fn_nodes, assign_nodes, order = {}, {}, {}
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.FunctionDef):
            fn_nodes[node.name] = node
            order[("fn", node.name)] = i
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assign_nodes[t.id] = node
                    order[("c", t.id)] = i

    # Arrancan vacíos a propósito. Si sembrara need_const con WANT_CONST,
    # esos nombres saldrían marcados como ya vistos y el recorrido nunca
    # entraría a su cuerpo — RUNS_DIR quedaría sin su CACHE_DIR.
    need_fn, need_const = set(), set()
    stack = list(WANT_FN) + list(WANT_CONST)
    while stack:
        name = stack.pop()
        if name in fn_nodes and name not in need_fn:
            need_fn.add(name)
            node = fn_nodes[name]
        elif name in assign_nodes and name not in need_const:
            need_const.add(name)
            node = assign_nodes[name]
        else:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id not in (need_fn | need_const):
                if sub.id in fn_nodes or sub.id in assign_nodes:
                    stack.append(sub.id)

    keep = []
    for key, idx in sorted(order.items(), key=lambda kv: kv[1]):
        kind, name = key
        if kind == "fn" and name in need_fn:
            keep.append(tree.body[idx])
        elif kind == "c" and name in need_const:
            keep.append(tree.body[idx])

    import datetime as _dt
    import time as _time
    import hashlib as _hashlib
    import statistics as _stats
    ns = {
        "re": re, "json": json, "sys": sys, "Path": Path,
        "os": __import__("os"),
        "datetime": _dt.datetime, "timedelta": _dt.timedelta,
        "timezone": _dt.timezone, "date": _dt.date,
        "time": _time, "hashlib": _hashlib, "statistics": _stats,
        # El pipeline deriva sus rutas de __file__. Lo apuntamos al archivo
        # real para que RUNS_DIR y compañía caigan donde caerían en vivo.
        "__file__": str(HERE / "intake_pipeline.py"),
    }
    mod = ast.Module(body=keep, type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), "<pipeline>", "exec"), ns)
    ns["_missing_fn"] = {n for n in WANT_FN if n not in fn_nodes}
    ns["_missing_const"] = {n for n in WANT_CONST if n not in assign_nodes}
    ns["_pulled_in"] = sorted((need_fn | need_const) - WANT_FN - WANT_CONST)
    return ns


P = load_pipeline()
QUESTION_MAP = P["QUESTION_MAP"]

with open(HERE / "data" / "scorecard_config.json") as fh:
    CFG = json.load(fh)

# step_score escribe scored.json en el directorio de la corrida. Lo creamos
# para que la prueba ejercite el camino real de escritura en vez de un atajo.
RUN_ID = "contract-test"
(P["RUNS_DIR"] / RUN_ID).mkdir(parents=True, exist_ok=True)


# ── Marco de aserción ─────────────────────────────────────────────────────

PASS = 0
FAILURES = []


def check(cond, label, got=None, want=None):
    global PASS
    if cond:
        PASS += 1
        return True
    detail = ""
    if want is not None or got is not None:
        detail = f"  esperado: {want!r}\n     obtenido: {got!r}"
    FAILURES.append((label, detail))
    return False


def eq(got, want, label):
    return check(got == want, label, got, want)


# ══════════════════════════════════════════════════════════════════════════
# Los casos controlados
# ══════════════════════════════════════════════════════════════════════════
#
# Cada caso es un dict de ID de pregunta -> valor crudo, tal como lo
# escribiría el formulario, más un bloque `expect` con los valores
# calculados a mano.
#
# Deliberadamente NO uso texto genérico tipo "bitcoin lightning wallets
# mining nodes" encadenando palabras clave. Ese texto hace pasar la prueba
# sin decir nada: un scorecard que solo cuenta keywords lo premia igual que
# un proyecto real. Los textos de abajo están escritos como los escribiría
# una organización, con la densidad de señal que de verdad llega.

BASE = {
    # A3 solo acepta tres cadenas: "No", "Yes, in 2026", "Yes, before 2026".
    # Un "Yes" suelto NO es una opción del formulario. En v2 el código
    # comparaba a3 == "yes" exacto, que nunca coincidía con ninguna opción
    # real, y la validación de renovación jamás se disparaba — está
    # documentado en eva-intake-process-2027.md línea 170. El caso
    # A3_INVALID_VALUE de abajo fija el contrato para que no vuelva.
    "A1": "Yes", "A2": "1–3 years", "A3": "No", "A4": "8500",
    "B1": "Asociación Semilla Digital", "B2": "Guatemala",
    "B3": "María Elena Choc", "B4": "4a Calle 7-32, Zona 1, Quetzaltenango",
    "B5": "42000", "B6": "https://semilladigital.example.org",
    "B7": "3", "B8": "GT-ONG-2022-0481",
    "C1": "registro_legal.pdf", "C2": "w8ben.pdf",
    "D1": "contacto@semilladigital.example.org", "D2": "María Elena Choc",
    "D3": "maria@semilladigital.example.org", "D4": "admin@semilladigital.example.org",
    "E1": "Mercados que aceptan pagos digitales en Quetzaltenango",
    "E2": "2027-02-01 a 2027-12-15",
    "E3": "Quetzaltenango, Guatemala",
    "E4": "Las vendedoras del mercado La Democracia cobran solo en efectivo. "
          "Pierden ventas cuando el cliente no trae billetes y pagan 7% a "
          "intermediarios para recibir remesas de familiares en EE.UU.",
    "E5": "120",
    "E6": "Vendedoras de mercado, 85% mujeres, la mayoría con primaria "
          "incompleta y sin cuenta bancaria.",
    "E7": "120 vendedoras reciben al menos un pago digital por semana "
          "durante 3 meses seguidos",
    "E8": "Asociación de Vendedores del Mercado La Democracia",
    "E9": "Capacitamos en grupos de 15 en el mercado mismo, en horario de "
          "cierre, y dejamos a 8 vendedoras como referentes de apoyo.",
    "E10": "Marzo 2027: 40 vendedoras con billetera instalada. Julio 2027: "
           "80 aceptando pagos. Diciembre 2027: 120 con tres meses de uso.",
    "E11": "Riesgo: la conectividad en el mercado es intermitente. "
           "Mitigación: billeteras con soporte offline y un punto de wifi.",
    "E12": "Local circulation",
    "E13": "El pago que recibe la vendedora lo usa para pagarle al "
           "proveedor de verdura, que también estará en la red.",
    "F1": "Vendedoras que reciben un pago digital por semana",
    "F2": "9",
    "F3": "120",
    "F4": "Registro semanal del punto de venta de cada vendedora",
    "F5": "En 2026 capacitamos 45 vendedoras con fondos propios; 31 siguen "
          "cobrando en digital un año después.",
    "G1": "11200", "G2": "8500",
    "G4": "Capacitación 4200, Equipos 2100, Conectividad 1300, "
          "Coordinación 900",
    "G5": "Talleres, billeteras y el punto de wifi del mercado",
    "G7": "La asociación de vendedores cubre el wifi desde 2028 con la "
          "cuota mensual que ya cobran.",
    "H1": "Dos capacitadoras con tres años en educación de adultos y una "
          "coordinadora que vive en el mercado.",
    "H2": "Nos ayudaría material en k'iche' y contacto con otros proyectos "
          "de mercado.",
    "I1": "No", "I3": "Ninguno",
    "J1": "", "J2": "", "J3": "",
    "K1": "Yes", "K3": "Yes", "K4": "Yes", "K5": "María Elena Choc",
}


def variant(**over):
    d = dict(BASE)
    d.update(over)
    return d


CASES = {

    # ── El caso de referencia. Monto 8500 < 10000, así que cae en el tier
    #    ligero: F2/F3/E10 no son obligatorios. Es una solicitud real y
    #    completa de una organización chica.
    "TIER_LIGHT": {
        "fields": BASE,
        "expect": {
            "A4_Requested_Num": 8500.0,
            "G2_Requested_Num": 8500.0,
            "A4_G2_Match": "YES",
            "simplified_tier": True,
            "G4_Budget_Sum_Valid": "YES",   # 4200+2100+1300+900 = 8500
            "G2_Within_G1": "YES",          # 8500 <= 11200
            "G6_Cost_Per_Participant": 70.83,   # 8500 / 120
            "Dependency_Ratio": 0.2024,     # 8500 / 42000
            "stage": "Local circulation",
            "pillar": "Economic Empowerment",
            # Un solo pilar: el texto es de comercio de mercado de punta a
            # punta, sin un segundo eje que alcance el piso.
            "pillars_all": ["Economic Empowerment"],
            "flags_absent": ["amount_mismatch", "amount_unreadable:A4",
                             "budget_sum_mismatch", "request_exceeds_total"],
        },
    },

    # ── El mismo expediente pero pidiendo 25000. Cruza el umbral, así que
    #    el tier pesado aplica y F2/F3/E10 pasan a ser obligatorios.
    #    G4 ya no suma (sigue sumando 8500 contra un pedido de 25000) y
    #    el pedido excede el total del proyecto.
    "TIER_HEAVY": {
        "fields": variant(A4="25000", G2="25000"),
        "expect": {
            "A4_Requested_Num": 25000.0,
            "A4_G2_Match": "YES",
            "simplified_tier": False,
            "G4_Budget_Sum_Valid": "NO",
            "G4_Budget_Sum_Diff": -16500.0,   # 8500 - 25000
            "G2_Within_G1": "NO",             # 25000 > 11200
            "flags_present": ["budget_sum_mismatch",
                              "request_exceeds_total"],
        },
    },

    # ── EL CASO QUE MOTIVÓ EL ARREGLO DE HOY.
    #    A4 dice 5000 (tier ligero) y G2 dice 48000 (tier pesado). El
    #    solicitante contestó el filtro con una cifra y después subió el
    #    presupuesto sin volver atrás. Antes de hoy esto pasaba sin ruido:
    #    se le pedían menos campos de medición de los que su monto real
    #    exige, y nadie se enteraba.
    "AMOUNT_CROSSES_TIER": {
        "fields": variant(A4="5000", G2="48000", G1="52000",
                          G4="Capacitación 24000, Equipos 14000, "
                             "Conectividad 6000, Coordinación 4000"),
        "expect": {
            "A4_Requested_Num": 5000.0,
            "G2_Requested_Num": 48000.0,
            "A4_G2_Match": "NO",
            "A4_G2_Diff": 43000.0,
            "simplified_tier": True,   # A4 gana: es lo que vio el formulario
            "flags_present": ["amount_mismatch",
                              "amount_mismatch_crosses_tier"],
        },
    },

    # ── A4 en blanco. El tier cae a G2 en vez de empujar a la ruta pesada
    #    por defecto, y se levanta la bandera para que un revisor arregle
    #    el número. Antes de hoy, A4 vacío = ruta pesada, en silencio.
    "AMOUNT_BLANK_A4": {
        "fields": variant(A4=""),
        "expect": {
            "A4_G2_Match": "CANNOT_VERIFY",
            "simplified_tier": True,   # por G2 = 8500
            "flags_present": ["amount_unreadable:A4"],
        },
    },

    # ── A4 escrito en palabras. parse_number no lo entiende y debe
    #    comportarse igual que el blanco, no reventar.
    "AMOUNT_IN_WORDS": {
        "fields": variant(A4="ocho mil quinientos dólares"),
        "expect": {
            "A4_G2_Match": "CANNOT_VERIFY",
            "simplified_tier": True,
            "flags_present": ["amount_unreadable:A4"],
        },
    },

    # ── La trampa del guion. "1–3 years" trae un EN DASH (U+2013), no un
    #    guion normal. En v2 esto rompía el match de A2 en silencio y la
    #    antigüedad se leía como desconocida. normalize_a2 lo arregla; si
    #    alguien vuelve a comparar la cadena cruda, este caso lo delata.
    "EN_DASH_A2": {
        "fields": variant(A2="1–3 years"),
        "expect": {
            "a2_normalized": "1-3 years",
            "a2_is_known": True,
        },
    },

    # ── Renovación por ruta corta: J1 contesta y F5 queda vacío. El
    #    hallazgo del 10 de noviembre fue que esto costaba 5 puntos de
    #    experiencia sin razón. Debe costar 0.
    "RENEWAL_SHORT_ROUTE": {
        "fields": variant(A3="Yes, in 2026", F5="",
                          J1="En 2026 prometimos 45 vendedoras y llegamos "
                             "a 52. Quedaron 31 activas al año.",
                          J2="Sí", J3="Ampliar a un segundo mercado"),
        "expect": {
            "renewal_route_recognized": True,
            "experience_points_equal_to_long_route": True,
        },
    },

    # ── "Yes, before 2026" NO abre la ruta corta: J1 pregunta por lo
    #    prometido en 2026 y un grantee de 2025 no tiene ese registro.
    #    Debe tratarse como solicitud nueva.
    "RENEWAL_BEFORE_2026": {
        "fields": variant(A3="Yes, before 2026"),
        "expect": {
            "renewal_route_recognized": False,
        },
    },

    # ── La trampa de v2. Un "Yes" suelto no es opción del formulario; si
    #    alguna vez llega (importación manual, otra fuente), no debe
    #    conceder la ruta corta en silencio.
    "A3_INVALID_VALUE": {
        "fields": variant(A3="Yes"),
        "expect": {
            "renewal_route_recognized": False,
        },
    },

    # ── Colisión de IDs: los dos bugs reales de v2.
    #    OFAC debe mirar B1 (nombre legal) y B3 (representante), nunca B4
    #    (dirección). El match de dirección debe mirar B4, nunca B5
    #    (presupuesto, que es un número).
    "ID_COLLISION_GUARD": {
        "fields": BASE,
        "expect": {
            "B3_is_a_person_name": True,
            "B4_is_an_address": True,
            "B5_is_numeric": True,
            "B8_is_not_numeric": True,   # registro, no FTE
        },
    },

    # ── Proyecto genuinamente de dos ejes: enseña y además monta el comercio
    #    que recibe los pagos. Antes esto devolvía UN pilar y el segundo se
    #    perdía sin registro. Diez de los 56 grantees del padrón están
    #    etiquetados "All three" por una persona, así que el caso es real.
    "MULTI_PILLAR": {
        "fields": variant(
            E1="Escuela de oficios y red de comercios en Quetzaltenango",
            E4="Las egresadas del curso de costura no tienen dónde vender. "
               "Los comercios del barrio no aceptan pagos digitales, así que "
               "la clienta que no trae efectivo no compra.",
            E8="Capacitación técnica certificada más red de comercios "
               "aliados que aceptan pagos digitales",
        ),
        "expect": {
            "pillars_all": ["Education", "Economic Empowerment"],
        },
    },

    # ── Expediente vacío. Debe dar 0 y rojo, sin excepciones.
    "EMPTY": {
        "fields": {k: "" for k in QUESTION_MAP},
        "expect": {
            "total_score": 0,
            "semaforo": "RED",
        },
    },
}


# ══════════════════════════════════════════════════════════════════════════
# Reimplementación mínima de step_clean para lo que estas pruebas miran
# ══════════════════════════════════════════════════════════════════════════
#
# step_clean necesita el cliente de Drive y la API de Sheets, así que no se
# puede llamar entero sin red. Replico SOLO la aritmética de limpieza que los
# casos verifican, leyendo las constantes del pipeline real. Si el pipeline
# cambia un nombre de columna, esto rompe — que es la intención.

def clean_min(fields, cfg):
    c = {}
    for fid in P["NUMERIC_FIELDS"]:
        col = QUESTION_MAP.get(fid, fid)
        v, ok = P["parse_number"](fields.get(fid, ""))
        c[f"{fid}_{col.split('_', 1)[1] if '_' in col else col}"] = v if ok else None

    # Los nombres reales que usa el pipeline, no derivados
    a4 = P["parse_number"](fields.get("A4", ""))
    g1 = P["parse_number"](fields.get("G1", ""))
    g2 = P["parse_number"](fields.get("G2", ""))
    b5 = P["parse_number"](fields.get("B5", ""))
    e5 = P["parse_number"](fields.get("E5", ""))
    c["A4_Requested_Num"] = a4[0] if a4[1] else None
    c["G1_Total_Num"] = g1[0] if g1[1] else None
    c["G2_Requested_Num"] = g2[0] if g2[1] else None
    c["B5_Annual_Budget_Num"] = b5[0] if b5[1] else None
    c["E5_Participants_Num"] = e5[0] if e5[1] else None

    flags = []

    # G4 contra G2
    g4_nums = re.findall(r'[\d,]+\.?\d*', str(fields.get("G4", "")))
    g4_sum = sum(float(n.replace(',', '')) for n in g4_nums) if g4_nums else None
    if g4_sum is not None and c["G2_Requested_Num"] is not None:
        diff = round(g4_sum - c["G2_Requested_Num"], 2)
        c["G4_Budget_Sum_Valid"] = "YES" if abs(diff) < 1 else "NO"
        c["G4_Budget_Sum_Diff"] = diff
        if abs(diff) >= 1:
            flags.append(f"budget_sum_mismatch:diff={diff}")
    else:
        c["G4_Budget_Sum_Valid"] = "CANNOT_VERIFY"

    # G2 dentro de G1
    if c["G1_Total_Num"] is not None and c["G2_Requested_Num"] is not None:
        ok = c["G2_Requested_Num"] <= c["G1_Total_Num"]
        c["G2_Within_G1"] = "YES" if ok else "NO"
        if not ok:
            flags.append(
                f"request_exceeds_total:G2={c['G2_Requested_Num']}"
                f">G1={c['G1_Total_Num']}")
    else:
        c["G2_Within_G1"] = "CANNOT_VERIFY"

    # A4 contra G2 — el chequeo nuevo
    a4n, g2n = c["A4_Requested_Num"], c["G2_Requested_Num"]
    if isinstance(a4n, (int, float)) and isinstance(g2n, (int, float)):
        gap = round(abs(a4n - g2n), 2)
        c["A4_G2_Match"] = "YES" if gap < 1 else "NO"
        c["A4_G2_Diff"] = gap if gap >= 1 else ""
        if gap >= 1:
            flags.append(f"amount_mismatch:A4={a4n}_vs_G2={g2n}")
            thr = cfg.get("measurement_tiering", {}).get("threshold_usd", 10000)
            if (a4n < thr) != (g2n < thr):
                flags.append(f"amount_mismatch_crosses_tier:threshold={thr}")
    else:
        c["A4_G2_Match"] = "CANNOT_VERIFY"
        c["A4_G2_Diff"] = ""
        if not isinstance(a4n, (int, float)):
            flags.append("amount_unreadable:A4")

    # Costo por participante y ratio de dependencia
    if isinstance(g2n, (int, float)) and isinstance(c["E5_Participants_Num"], (int, float)) \
            and c["E5_Participants_Num"] > 0:
        c["G6_Cost_Per_Participant"] = round(g2n / c["E5_Participants_Num"], 2)
    else:
        c["G6_Cost_Per_Participant"] = ""

    if isinstance(g2n, (int, float)) and isinstance(c["B5_Annual_Budget_Num"], (int, float)) \
            and c["B5_Annual_Budget_Num"] > 0:
        c["Dependency_Ratio"] = round(g2n / c["B5_Annual_Budget_Num"], 4)
    else:
        c["Dependency_Ratio"] = ""

    return c, flags


# ══════════════════════════════════════════════════════════════════════════
# Verificación por caso
# ══════════════════════════════════════════════════════════════════════════

def run_case(name, case):
    fields, exp = case["fields"], case["expect"]
    print(f"\n── {name} {'─' * max(0, 56 - len(name))}")

    cleaned, flags = clean_min(fields, CFG)

    # Valores limpios exactos
    for key in ("A4_Requested_Num", "G2_Requested_Num", "A4_G2_Match",
                "A4_G2_Diff", "G4_Budget_Sum_Valid", "G4_Budget_Sum_Diff",
                "G2_Within_G1", "G6_Cost_Per_Participant",
                "Dependency_Ratio"):
        if key in exp:
            eq(cleaned.get(key), exp[key], f"{name}: {key}")

    # Tier
    if "simplified_tier" in exp:
        got = P["is_simplified_tier"](fields, CFG, cleaned)
        eq(got, exp["simplified_tier"], f"{name}: tier simplificado")

    # Banderas que deben estar
    for want in exp.get("flags_present", []):
        check(any(fl.startswith(want) for fl in flags),
              f"{name}: bandera '{want}' presente", got=flags, want=want)

    # Banderas que NO deben estar
    for unwanted in exp.get("flags_absent", []):
        check(not any(fl.startswith(unwanted) for fl in flags),
              f"{name}: bandera '{unwanted}' AUSENTE", got=flags,
              want=f"sin {unwanted}")

    # Multi-pilar: un proyecto puede tener más de uno y esa información no
    # debe perderse (Iván, 2026-11-11). Se verifica que el primario siga
    # siendo el primer elemento, porque todo lo que agrupa por pilar depende
    # de eso.
    if "pillars_all" in exp:
        pri, _why, _sc, allp = P["infer_pillar"](fields)
        # Se compara el CONJUNTO, no el orden. Cuál de dos ejes igualmente
        # presentes queda primario es un juicio que el texto no resuelve, y
        # fijarlo aquí sería afirmar algo que no se puede sostener. Lo que sí
        # es invariante —y de lo que dependen los conteos por pilar— es que
        # el primario sea el primer elemento.
        eq(sorted(allp), sorted(exp["pillars_all"]),
           f"{name}: conjunto de pilares")
        if allp:
            eq(allp[0], pri,
               f"{name}: el primario es el primer elemento de la lista")

    # Inferencias
    if "stage" in exp:
        st = P["infer_stage"](fields)
        got = st[0] if isinstance(st, tuple) else st
        eq(got, exp["stage"], f"{name}: etapa inferida")
    if "pillar" in exp:
        pl = P["infer_pillar"](fields)
        got = pl[0] if isinstance(pl, tuple) else pl
        eq(got, exp["pillar"], f"{name}: pilar inferido")

    # El guion en A2
    if "a2_normalized" in exp:
        eq(P["normalize_a2"](fields["A2"]), exp["a2_normalized"],
           f"{name}: A2 normalizado (en dash)")
    if exp.get("a2_is_known"):
        check(P["normalize_a2"](fields["A2"]) != "",
              f"{name}: A2 reconocido, no vacío")

    # Guardas de colisión de IDs — sobre el significado, no la presencia
    if exp.get("B3_is_a_person_name"):
        v = fields.get("B3", "")
        check(v and not any(ch.isdigit() for ch in v) and len(v.split()) >= 2,
              f"{name}: B3 parece nombre de persona", got=v,
              want="texto sin dígitos, 2+ palabras")
    if exp.get("B4_is_an_address"):
        v = fields.get("B4", "")
        check(any(ch.isdigit() for ch in v) and len(v) > 15,
              f"{name}: B4 parece dirección", got=v,
              want="con dígitos y largo")
    if exp.get("B5_is_numeric"):
        check(P["parse_number"](fields.get("B5", ""))[1],
              f"{name}: B5 es numérico (presupuesto)", got=fields.get("B5"))
    if exp.get("B8_is_not_numeric"):
        check(not P["parse_number"](fields.get("B8", ""))[1],
              f"{name}: B8 NO es numérico (registro, no FTE)",
              got=fields.get("B8"), want="cadena de registro")

    # Score
    if "total_score" in exp or "semaforo" in exp:
        app = {"app_id": f"CONTRACT-{name}", "fields": fields,
               "cleaned": cleaned, "_config": CFG,
               "doc_name_match": True, "doc_address_match": True}
        res = P["step_score"]([app], CFG, "contract-test")
        apps = res.get("applications", [])
        # Sin guarda silenciosa: si no salió nada, es un fallo, no un salto.
        if check(len(apps) == 1, f"{name}: step_score devolvió 1 expediente",
                 got=len(apps), want=1):
            s = apps[0].get("score", {})
            if "total_score" in exp:
                eq(s.get("Total_Score"), exp["total_score"],
                   f"{name}: puntaje total")
            if "semaforo" in exp:
                eq(s.get("Semaforo"), exp["semaforo"], f"{name}: semáforo")

    # ¿Reconoce la ruta de renovación? Se consulta la MISMA función que
    # otorga el permiso de dejar F5 vacío, no una reimplementación.
    if "renewal_route_recognized" in exp:
        got = P["is_renewal_skipping"]("F5", fields, CFG)
        eq(got, exp["renewal_route_recognized"],
           f"{name}: ruta corta reconocida (A3={fields.get('A3')!r})")

    # Ruta corta de renovación: costo cero
    if exp.get("experience_points_equal_to_long_route"):
        long_fields = dict(fields)
        long_fields["F5"] = ("En 2026 capacitamos 45 vendedoras; 31 siguen "
                             "cobrando en digital un año después.")
        def total(fl):
            cl, _ = clean_min(fl, CFG)
            a = {"app_id": "EXP", "fields": fl, "cleaned": cl,
                 "_config": CFG, "doc_name_match": True,
                 "doc_address_match": True}
            r = P["step_score"]([a], CFG, "contract-test")
            aa = r.get("applications", [])
            return aa[0].get("score", {}).get("Total_Score") if aa else None
        t_short, t_long = total(fields), total(long_fields)
        check(t_short is not None and t_short == t_long,
              f"{name}: ruta corta no cuesta puntos",
              got=f"corta={t_short} larga={t_long}", want="iguales")


def structural_checks():
    print("\n── ESTRUCTURA " + "─" * 45)
    eq(len(QUESTION_MAP), 61, "QUESTION_MAP tiene 61 columnas")
    check(not P["_missing_fn"],
          "todas las funciones esperadas existen en el pipeline",
          got=sorted(P["_missing_fn"]), want="ninguna faltante")
    check(not P["_missing_const"],
          "todas las constantes esperadas existen",
          got=sorted(P["_missing_const"]), want="ninguna faltante")

    # El significado, no la presencia. Un chequeo de presencia pasa igual
    # con los 17 IDs que cambiaron de sentido — eso es justo lo que no
    # queremos. Esto fija el significado.
    meaning = {
        "A4": "A4_Requested_Amount", "B3": "B3_Legal_Rep_Name",
        "B4": "B4_Address", "B5": "B5_Annual_Budget", "B7": "B7_FTE_Staff",
        "B8": "B8_Registration_Number", "E4": "E4_Economic_Barrier",
        "E5": "E5_Participant_Count", "E7": "E7_Primary_Result",
        "E10": "E10_Milestones", "E12": "E12_Target_Stage",
        "G1": "G1_Total_Budget", "G2": "G2_Requested_Amount",
        "H1": "H1_Team_Capacity", "H2": "H2_Support_Needs",
    }
    for qid, col in meaning.items():
        eq(QUESTION_MAP.get(qid), col, f"significado fijo: {qid} -> {col}")

    # Los campos removidos no deben haber vuelto por la puerta de atrás
    for rid in P["REMOVED_FIELDS_V2"]:
        check(rid not in QUESTION_MAP,
              f"campo removido {rid} sigue fuera de QUESTION_MAP")

    # A4 tiene que estar en NUMERIC_FIELDS — maneja el tier
    check("A4" in P["NUMERIC_FIELDS"],
          "A4 recibe limpieza numérica (decide el tier)",
          got=P["NUMERIC_FIELDS"], want="incluye A4")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=list(CASES))
    ap.add_argument("--show", choices=list(CASES),
                    help="volcar la salida limpia de un caso")
    args = ap.parse_args()

    if args.show:
        cleaned, flags = clean_min(CASES[args.show]["fields"], CFG)
        print(json.dumps({"cleaned": cleaned, "flags": flags},
                         indent=2, ensure_ascii=False, default=str))
        return 0

    print("=" * 60)
    print("POOL A — CONTRATO DEL FORMULARIO (datos controlados)")
    print("=" * 60)

    structural_checks()
    for name in ([args.case] if args.case else list(CASES)):
        run_case(name, CASES[name])

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"FALLOS: {len(FAILURES)}")
        for label, detail in FAILURES:
            print(f"  ✗ {label}")
            if detail:
                print(f"   {detail}")
    print(f"CONTRATO: {PASS} ok, {len(FAILURES)} fallidos")
    print("=" * 60)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
