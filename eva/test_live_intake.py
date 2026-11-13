#!/usr/bin/env python3
"""
POOL B — Datos reales de grantees y el circuito en vivo.

Dos capas, porque prueban cosas distintas y una corre hoy y la otra no.

  B1  OFFLINE — texto real de los 56 grantees del registro contra la
      pre-clasificación. Corre en cualquier máquina, sin red. Responde:
      ¿Eva clasifica prosa real de forma defendible, o solo mi texto
      inventado con palabras clave?

  B2  EN VIVO — ida y vuelta por Supabase. Corre solo en Eva, con la llave.
      Responde: ¿lo que escribe el formulario es lo que lee Eva, y lo que
      Eva calcula queda guardado?

Por qué separadas: B1 mide criterio, B2 mide cableado. Un pipeline puede
tener el cableado perfecto y clasificar mal, o clasificar bien y perder
filas. Mezclarlas haría que un fallo no dijera cuál de las dos falló.

LÍMITE QUE HAY QUE TENER PRESENTE EN B1
───────────────────────────────────────
El registro guarda scope / purpose / impact / program_type, no las 61
preguntas del formulario 2027. Para pasar ese texto por la inferencia hay
que mapearlo a campos del formulario, y ese mapeo lo decidí yo (ver
REGISTRY_TO_FORM). Entonces un desacuerdo puede venir de la inferencia o de
mi mapeo, y la prueba no puede distinguirlos sola. Por eso B1 no "pasa" ni
"falla" la clasificación: imprime una hoja para que un humano la juzgue, y
solo falla en invariantes que no dependen del mapeo (que no truene, que la
justificación cite campos reales, que sea determinista).

Uso:
  python3 test_live_intake.py --b1               # offline, hoy
  python3 test_live_intake.py --b1 --sheet       # + hoja de revisión TSV
  python3 test_live_intake.py --b2               # en vivo, en Eva
  python3 test_live_intake.py --b2 --check-only  # solo valida credenciales
"""

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# Reutilizamos el cargador por AST del pool A en vez de duplicarlo. Si el
# pipeline cambia una dependencia, los dos pools lo ven igual.
from test_form_contract import load_pipeline, CFG  # noqa: E402

P = load_pipeline()
QUESTION_MAP = P["QUESTION_MAP"]

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


# ══════════════════════════════════════════════════════════════════════════
# B1 — Texto real de grantees contra la pre-clasificación
# ══════════════════════════════════════════════════════════════════════════

# Mapeo registro -> formulario. Decisión mía, no dato del registro.
# La inferencia de pilar lee E1+E4+E8; la de etapa lee E1+E4+E8+E9+F1+F2+F3.
REGISTRY_TO_FORM = {
    "E1": ("legal_name", "scope"),      # título + resumen del proyecto
    "E4": ("purpose",),                 # el porqué, lo más cercano a la barrera
    "E8": ("program_type",),            # cómo se aplica / con quién
    "E9": ("impact",),                  # cómo llega a la gente
    "F1": ("reporting",),               # qué mide
}


def registry_to_fields(g):
    f = {k: "" for k in QUESTION_MAP}
    for fid, keys in REGISTRY_TO_FORM.items():
        f[fid] = " ".join(str(g.get(k, "") or "").strip() for k in keys).strip()
    f["B1"] = str(g.get("legal_name", "") or "")
    f["B2"] = str(g.get("country", "") or "")
    return f


def load_registry():
    """
    El padrón trae nombres, contactos y correos de organizaciones reales, así
    que NO se versiona en el repo: vive solo en el servidor de Eva y en la
    máquina de Iván. Si falta, se dice por qué en vez de reventar con un
    FileNotFoundError que no explica nada.
    """
    path = HERE / "data" / "grantee_registry.json"
    if not path.exists():
        return None
    with open(path) as fh:
        return json.load(fh)


def b1_offline(emit_sheet=False):
    print("=" * 74)
    print("B1 — PRE-CLASIFICACIÓN SOBRE TEXTO REAL DE GRANTEES (offline)")
    print("=" * 74)

    registry = load_registry()
    if registry is None:
        print("\n  data/grantee_registry.json no está presente.")
        print("  Contiene nombres y contactos de organizaciones reales, así")
        print("  que no se versiona. B1 necesita ese archivo porque su punto")
        print("  entero es medir la clasificación contra PROSA REAL — con")
        print("  datos sintéticos mediría mi propia redacción, no la de los")
        print("  solicitantes. Para esto está el pool A (test_form_contract).")
        print("\n  Cópialo desde el servidor de Eva (scripts/data/) o desde")
        print("  la máquina de Iván para correr B1.")
        return []

    narrative_keys = ("scope", "impact", "program_type", "purpose", "reporting")

    usable = [g for g in registry
              if sum(1 for k in narrative_keys if str(g.get(k, "") or "").strip()) >= 2]
    print(f"\nRegistro: {len(registry)} grantees | con 2+ campos narrativos: "
          f"{len(usable)}")

    rows = []
    no_pillar, no_stage = [], []

    for g in usable:
        f = registry_to_fields(g)
        gid = g.get("grantee_id", "?")
        name = str(g.get("legal_name", "") or "")[:38]

        pil = P["infer_pillar"](f)
        stg = P["infer_stage"](f)
        pil_v, pil_why = (pil[0], pil[1]) if isinstance(pil, tuple) else (pil, "")
        stg_v, stg_why = (stg[0], stg[1]) if isinstance(stg, tuple) else (stg, "")

        declared = str(g.get("pillar", "") or "").strip()

        rows.append({
            "grantee_id": gid, "legal_name": name,
            "country": g.get("country", ""),
            "declared_pillar": declared or "(sin declarar)",
            "inferred_pillar": pil_v or "(ninguno)",
            "pillar_why": pil_why,
            "inferred_stage": stg_v or "(ninguno)",
            "stage_why": stg_why,
        })

        if not pil_v:
            no_pillar.append((gid, name))
        if not stg_v:
            no_stage.append((gid, name))

    # ── Invariantes que NO dependen de mi mapeo ──────────────────────────

    # 1. Nada truena y todo sale con justificación.
    for r in rows:
        check(bool(r["pillar_why"]),
              f"B1 {r['grantee_id']}: el pilar trae justificación")
        check(bool(r["stage_why"]),
              f"B1 {r['grantee_id']}: la etapa trae justificación")

    # 2. La justificación tiene que citar campos que existan. Una inferencia
    #    que no dice de dónde salió no es auditable, y una que cita un campo
    #    inexistente delata que la lista de campos se movió.
    cited = re.compile(r'\b([A-K]\d{1,2})\b')
    for r in rows:
        for why in (r["pillar_why"], r["stage_why"]):
            for qid in set(cited.findall(why)):
                check(qid in QUESTION_MAP,
                      f"B1 {r['grantee_id']}: justificación cita {qid}, que existe",
                      got=qid, want="ID en QUESTION_MAP")

    # 3. Determinismo: la misma entrada da la misma salida. Si algún día
    #    entra un LLM o algo con reloj, esto lo caza.
    for g in usable[:12]:
        f = registry_to_fields(g)
        a, b = P["infer_pillar"](f), P["infer_pillar"](f)
        c, d = P["infer_stage"](f), P["infer_stage"](f)
        check(a == b and c == d,
              f"B1 {g.get('grantee_id')}: inferencia determinista")

    # ── Acuerdo con la etiqueta humana, donde existe ─────────────────────
    #
    # 9 grantees traen pilar decidido por una persona. Nueve casos no dan
    # para hablar de un porcentaje de acierto; sirven para mirar los
    # desacuerdos uno por uno. Eso se reporta, no se convierte en aserción.

    comparable = [r for r in rows
                  if r["declared_pillar"] in P["VALID_PILLARS"]]
    agree = [r for r in comparable if r["inferred_pillar"] == r["declared_pillar"]]
    disagree = [r for r in comparable if r["inferred_pillar"] != r["declared_pillar"]]

    print(f"\n── Acuerdo con el pilar declarado por un humano "
          f"({len(comparable)} casos) " + "─" * 12)
    if comparable:
        print(f"   coincide:    {len(agree)}")
        print(f"   discrepa:    {len(disagree)}")
        print("\n   Nueve casos no son una tasa de acierto. Son nueve casos "
              "para mirar.")
        for r in disagree:
            print(f"\n   ✗ {r['grantee_id']} {r['legal_name']}")
            print(f"       humano:    {r['declared_pillar']}")
            print(f"       inferido:  {r['inferred_pillar']}")
            print(f"       porqué:    {r['pillar_why'][:120]}")

    # "All three" no es representable: la inferencia elige UNO.
    all_three = [r for r in rows if r["declared_pillar"].lower() == "all three"]
    if all_three:
        print(f"\n── Brecha de metodología " + "─" * 46)
        print(f"   {len(all_three)} grantees están etiquetados 'All three' por "
              "un humano.")
        print("   infer_pillar devuelve UN pilar, nunca varios, así que esa")
        print("   etiqueta no se puede reproducir. Si los solicitantes 2027 se")
        print("   parecen al padrón actual, forzar un pilar pierde información")
        print("   que alguien decidió registrar. Es decisión de Marisa, no del")
        print("   código: o el pilar admite múltiples, o se acepta que es solo")
        print("   la etiqueta dominante.")

    # ── Cobertura ────────────────────────────────────────────────────────
    print(f"\n── Cobertura de la inferencia " + "─" * 41)
    print(f"   sin pilar inferido:  {len(no_pillar)}/{len(usable)}")
    print(f"   sin etapa inferida:  {len(no_stage)}/{len(usable)}")
    for gid, nm in no_pillar[:6]:
        print(f"      · {gid} {nm}")

    print(f"\n   distribución de pilar inferido: "
          f"{dict(Counter(r['inferred_pillar'] for r in rows))}")
    print(f"   distribución de etapa inferida: "
          f"{dict(Counter(r['inferred_stage'] for r in rows))}")

    # Una inferencia que manda todo al mismo cajón no está clasificando.
    stages = Counter(r["inferred_stage"] for r in rows)
    if rows:
        top_share = stages.most_common(1)[0][1] / len(rows)
        check(top_share < 0.85,
              "B1: la etapa inferida no colapsa a un solo valor",
              got=f"{stages.most_common(1)[0][0]} en {top_share:.0%}",
              want="< 85% en una sola etapa")

    if emit_sheet:
        out = HERE / "b1_review_sheet.tsv"
        cols = ["grantee_id", "legal_name", "country", "declared_pillar",
                "inferred_pillar", "inferred_stage", "pillar_why", "stage_why"]
        with open(out, "w") as fh:
            fh.write("\t".join(cols) + "\n")
            for r in rows:
                fh.write("\t".join(
                    str(r.get(c, "")).replace("\t", " ").replace("\n", " ")
                    for c in cols) + "\n")
        print(f"\n   hoja de revisión: {out}")
        print("   (ábrela y juzga los desacuerdos; eso no lo puede hacer "
              "una aserción)")

    return rows


# ══════════════════════════════════════════════════════════════════════════
# B2 — Ida y vuelta por Supabase, en vivo
# ══════════════════════════════════════════════════════════════════════════

def b2_live(check_only=False):
    print("=" * 74)
    print("B2 — CIRCUITO EN VIVO POR SUPABASE")
    print("=" * 74)

    cfg_path = HERE / "data" / "intake_sheets_config.json"
    with open(cfg_path) as fh:
        sheets_cfg = json.load(fh)

    ing = sheets_cfg.get("ingest", {})
    sb = ing.get("supabase", {})

    pend = [k for k in ("url", "table") if str(sb.get(k, "")).strip()
            in ("", "PENDIENTE")]
    if not str(sb.get("timestamp_column", "")).strip():
        pend.append("timestamp_column")

    if pend:
        print(f"\n   Faltan datos de Salomé: {', '.join(pend)}")
        print(f"   Archivo: {cfg_path}")
        print("\n   B2 no puede correr sin eso. B1 sí corre hoy:")
        print("      python3 test_live_intake.py --b1 --sheet")
        return False

    # ── Guarda de entorno. Datos reales de grantees no tocan producción. ──
    table = str(sb.get("table", ""))
    url = str(sb.get("url", ""))
    is_test = any(m in (table + url).lower()
                  for m in ("test", "staging", "dev", "sandbox", "qa"))
    if not is_test:
        print(f"\n   NEGADO: la tabla '{table}' no se identifica como de "
              "pruebas.")
        print("   B2 inserta expedientes de prueba con texto de grantees")
        print("   reales. Eso no va a producción. Renombra la tabla de")
        print("   pruebas con 'test' en el nombre, o corre B2 apuntando a")
        print("   un proyecto Supabase de staging.")
        return False

    key_path = Path(sb.get("key_path",
                           "~/.openclaw/secrets/supabase_service_key.txt")
                    ).expanduser()
    if not key_path.exists():
        print(f"\n   Falta la llave: {key_path}")
        print("   Ponla con chmod 600 (ver INSTRUCCIONES-EVA.md, paso 5).")
        return False

    mode = oct(key_path.stat().st_mode & 0o777)
    check(mode == "0o600", f"B2: la llave está en 600 (está en {mode})",
          got=mode, want="0o600")

    print(f"\n   tabla:  {table}")
    print(f"   url:    {url}")
    print(f"   llave:  {key_path} ({mode})")

    if check_only:
        print("\n   --check-only: credenciales y entorno validados, sin "
              "tocar la red.")
        return True

    print("\n   Lo que B2 verifica cuando corre completo:")
    for i, line in enumerate([
        "las 61 columnas vuelven de Supabase con el MISMO nombre y orden "
        "que escribió el formulario",
        "el en dash de \"1–3 years\" sobrevive el viaje (es el carácter "
        "exacto que rompió A2 en v2)",
        "N filas insertadas = N expedientes puntuados, sin pérdidas "
        "silenciosas",
        "correr dos veces da salida idéntica (determinismo sobre datos "
        "reales, no solo fixtures)",
        "reprocesar no duplica ni vuelve a puntuar (idempotencia por "
        "App_ID)",
        "lo puntuado se puede leer de vuelta de Supabase",
        "ningún campo guardado contiene identificadores de participantes "
        "(el config dice aggregate_only)",
    ], 1):
        print(f"      {i}. {line}")

    print("\n   Implementación pendiente del esquema real de la tabla.")
    print("   Sin saber los nombres de columna que usó Salomé, cualquier")
    print("   inserción que escriba ahora sería una suposición, y una")
    print("   prueba que adivina el esquema falla por el motivo equivocado.")
    return True


# ══════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--b1", action="store_true", help="offline, corre hoy")
    ap.add_argument("--b2", action="store_true", help="en vivo, en Eva")
    ap.add_argument("--sheet", action="store_true",
                    help="B1: escribir hoja de revisión TSV")
    ap.add_argument("--check-only", action="store_true",
                    help="B2: solo validar credenciales")
    args = ap.parse_args()

    if not (args.b1 or args.b2):
        ap.print_help()
        return 0

    if args.b1:
        b1_offline(emit_sheet=args.sheet)
    if args.b2:
        b2_live(check_only=args.check_only)

    print("\n" + "=" * 74)
    if FAILURES:
        print(f"FALLOS: {len(FAILURES)}")
        for label, detail in FAILURES:
            print(f"  ✗ {label}")
            if detail:
                print(f"   {detail}")
    print(f"POOL B: {PASS} ok, {len(FAILURES)} fallidos")
    print("=" * 74)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
