#!/usr/bin/env python3
"""
intake_pipeline.py — PayStand Foundation 2027 Grant Intake Pipeline

Orchestrates 7 steps:
  1. INGEST     — Read new form responses from Google Sheet
  2. CLEAN      — Normalize, validate, flag data quality
  3. CLASSIFY   — Profile, pillar, region, renewal cross-ref
  4. FLAG       — Nonsense detection + compliance flags
  5. SCORE      — 100-point scorecard + semáforo
  6. PACKAGE    — Review package + dashboard metrics
  7. WRITE      — Write results to sheet tabs + process log

Usage:
  .venv/bin/python3 scripts/intake_pipeline.py --run-all
  .venv/bin/python3 scripts/intake_pipeline.py --step ingest
  .venv/bin/python3 scripts/intake_pipeline.py --step clean --run-id <run_id>
  ...

Configuration:
  scripts/data/intake_sheets_config.json  — Sheet IDs, tab names
  scripts/data/scorecard_config.json      — Weights, thresholds
  scripts/data/country_mapping.json       — Country normalization
  scripts/data/region_mapping.json        — Region mapping
"""

import argparse
import fcntl
import csv
import io
import json
import os
import re
import sys
import time
import traceback
import unicodedata
import urllib.request
import urllib.parse
import functools
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Slack notification (P0 guardrail)
import subprocess

# Google API
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

# ─── P1.1: Google API retry with exponential backoff ────────────────────────
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0  # seconds

def with_retry(func):
    """Decorator: retry Google API calls with exponential backoff.
    Retries on HttpError 429/5xx and ConnectionError. Raises after MAX_RETRIES."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, TimeoutError) as e:
                last_exc = e
                if attempt < MAX_RETRIES:
                    backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    print(f"  [RETRY] {func.__name__} attempt {attempt}/{MAX_RETRIES} failed ({type(e).__name__}), retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    raise
            except HttpError as e:
                status = e.resp.status if hasattr(e, 'resp') else None
                if status and (status == 429 or 500 <= status < 600):
                    last_exc = e
                    if attempt < MAX_RETRIES:
                        backoff = INITIAL_BACKOFF * (2 ** (attempt - 1))
                        print(f"  [RETRY] {func.__name__} attempt {attempt}/{MAX_RETRIES} failed (HTTP {status}), retrying in {backoff}s...")
                        time.sleep(backoff)
                    else:
                        raise
                else:
                    raise
        raise last_exc
    return wrapper

# ─── Constants ─────────────────────────────────────────────────────────────

WORKSPACE = Path(__file__).parent.parent
CONFIG_DIR = WORKSPACE / "scripts" / "data"
CACHE_DIR = WORKSPACE / "cache"
RUNS_DIR = CACHE_DIR / "intake_runs"
NOTES_DIR = WORKSPACE / "notes" / "intake"   # a constant so tests can point it elsewhere
SECRETS_PATH = Path(os.path.expanduser("~/.openclaw/secrets/google_token.json"))

# Tab names
TAB_FORM = "1. Form Responses"
TAB_CLEAN = "2. Cleaned"
TAB_CLASSIFY = "3. Classified"
TAB_FLAGS = "4. Flags"
TAB_SCORE = "5. Scorecard"
TAB_PACKAGE = "6. Review Package"
TAB_DASH = "7. Dashboard"
TAB_LOG = "8. Process Log"
TAB_REGISTRY = "0. Grantee Registry"
TAB_REVIEW_LOG = "9. Review Log"

ALL_TABS = [TAB_REGISTRY, TAB_FORM, TAB_CLEAN, TAB_CLASSIFY, TAB_FLAGS, TAB_SCORE, TAB_PACKAGE, TAB_DASH, TAB_LOG]

# Question map: field ID → column name in Form Responses tab
#  ═══════════════════════════════════════════════════════════════════════════
#  FIELD MAP v3 — FROZEN 2026-11-09
#  Authoritative spec: eva/eva-form-field-map-v3-FROZEN.md
#
#  ⚠️  IDs were RENUMBERED after Marisa's 18 removals. Thirteen IDs changed
#      MEANING and every one of them also exists in the old numbering, so a
#      half-migrated system reads plausible values from the wrong field and
#      fails silently. Notable reversals:
#        B4  was legal rep        → now ADDRESS
#        B5  was address          → now ANNUAL BUDGET (numeric)
#        E7  was economic barrier → now PRIMARY RESULT sentence
#        E8  was participant count→ now APPLICATION + PARTNER
#        E10 was result sentence  → now THREE MILESTONES
#      Do not implement from `Intake Skill Design Notes.md` (SUPERSEDED).
#
#  Pillar and stage are NO LONGER COLLECTED. Eva infers both from the
#  narrative — an applicant will declare whatever sounds right, so the
#  classification rests on the substance of what they describe doing.
#  ═══════════════════════════════════════════════════════════════════════════

QUESTION_MAP = {
    "timestamp": "Timestamp",
    # ── 0. Before you apply ──
    "0.1": "Q01_Readiness_Checklist",
    "0.2": "Q02_Eligibility_Checklist",
    # ── A. Filter questions ──
    "A1": "A1_Applicant_Type",          # Organization | Individual
    "A1b": "A1b_Org_Type",              # Nonprofit/NGO | Social enterprise
    "A2": "A2_Time_Operating",
    "A3": "A3_Prior_Grant",             # No | Yes, in 2026 | Yes, before 2026
    # A4 (requested amount) removed 2026-11-13, Iván: it asked the same
    # number as G2, out of the budget's context, and existed only to decide
    # a measurement tier that the form never applied. G2 is the one amount.
    # ── B. Organization ──
    "B1": "B1_Legal_Name",
    "B2": "B2_Country",
    "B3": "B3_Legal_Rep_Name",          # was B4
    "B4": "B4_Address",                 # was B5
    "B5": "B5_Annual_Budget",           # was B8 — NUMERIC
    "B6": "B6_Website",                 # was B10
    "B7": "B7_FTE_Staff",               # restaurada — mismo significado original
    "B8": "B8_Registration_Number",     # restaurada — era B3 en el borrador
    # ── C. Documents ──
    "C1": "C1_Registration_Doc",
    "C2": "C2_Tax_Form",
    "C3": "C3_Person_Registration_Info",
    # ── D. Contact ──
    "D1": "D1_Primary_Contact",
    "D2": "D2_Contact_Authorized",
    "D3": "D3_Signer",
    "D4": "D4_Copy_Email",
    # ── E. Project ──
    "E1": "E1_Project_Title_Summary",
    "E2": "E2_Dates",                   # start + end, DATE pair (not numeric)
    "E3": "E3_Location",
    "E4": "E4_Economic_Barrier",        # was E7
    "E5": "E5_Participant_Count",       # was E8 — NUMERIC
    "E6": "E6_Participant_Profile",     # was E9
    "E7": "E7_Primary_Result",          # was E10 — short text, formula-shaped
    "E8": "E8_Application_Partner",     # was E11
    "E9": "E9_Bitcoin_Uses",            # was E12 — checkboxes
    "E10": "E10_Milestones",            # was E14 — 3-row table
    "E11": "E11_Risks",                 # was E15
    "E12": "E12_Target_Stage",          # restaurada — era E6. DECLARADA por el
                                        # aplicante; la etapa actual se infiere.
    "E13": "E13_Value_Circulation",     # restaurada — mismo ID original
    # ── F. Measurement ──
    "F1": "F1_Main_Measure",            # Skills|Access|Commerce|Remittances|Recovery
    "F2": "F2_Baseline",
    "F3": "F3_Target_12mo",
    "F4": "F4_Verification",
    "F5": "F5_Prior_Results",
    # ── G. Budget ──
    "G1": "G1_Total_Budget",            # TOTAL project budget
    "G2": "G2_Requested_Amount",        # amount requested from Paystand.org
    "G3": "G3_Other_Funders",
    "G4": "G4_Budget_By_Category",
    "G5": "G5_Fund_Uses",
    "G7": "G7_Continuity",
    "G8": "G8_Payment_Method",          # restaurada — mismo ID original
    # ── H. Experience ──
    "H1": "H1_Team_Capacity",           # was H3
    "H2": "H2_Support_Needs",           # restaurada — era H4
    # ── I. Participant protection ──
    "I1": "I1_Children_Involved",
    "I2": "I2_Safeguarding_Policy",
    "I3": "I3_Participant_Data",        # restaurada — mismo ID original
    # ── J. Renewal ──
    "J1": "J1_Renewal_Results",
    "J2": "J2_Stage_Reached_2026",      # restaurada — mismo ID original
    "J3": "J3_Report_2026",             # restaurada — mismo ID original
    # ── K. Disclosures ──
    "K1": "K1_Disclosures",
    "K2": "K2_Disclosure_Details",
    "K3": "K3_Certification",
    "K4": "K4_Data_Consent",
    "K5": "K5_Submitter",
}

# IDs that exist in the November 5 draft but have NO meaning in v3. A value
# arriving under one of these means a v2-shaped payload reached a v3 pipeline,
# which is the failure the renumbering makes silent — so it is flagged.
#
# This list is NOT "what Marisa removed". Nine of her removals were restored
# on 2026-11-10 and are live v3 fields again (B7, B8, E12, E13, G8, H2, I3,
# J2, J3). Listing those here would have flagged every legitimate submission.
REMOVED_FIELDS_V2 = [
    "B9",    # "who funds your work today" — G3 covers project funders
    "B10",   # website — now B6
    "B11",   # countries where you operate — E3 covers it
    "D5",    # English fluency — explicitly not a requirement
    "E14",   # three milestones — now E10
    "E15",   # risks — now E11
    "H3",    # team capacity — now H1
    "H4",    # technical support — now H2
]

# Always required (non-empty). Conditionals live in CONDITIONAL_REQUIRED.
REQUIRED_FIELDS = [
    "A1", "A2", "A3",
    "B1", "B2", "B3", "B4",
    "D1", "D2",
    "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10", "E11",
    "F1", "F2", "F3", "F4",
    "G1", "G2", "G3", "G7",
    "H1",
    "I1",
    "K1", "K3", "K4", "K5",
]

def is_renewal_skipping(field_id, fields, cfg):
    """
    True when a renewal may leave this field blank under the short route.

    Decision 4, Iván 2026-11-10. J1 covers the same ground as F5 for a 2026
    grantee, and we hold that record ourselves. Verified to cost no points.
    """
    r = (cfg or {}).get("renewal_short_route", {})
    if not r.get("enabled"):
        return False
    a3 = fields.get("A3", "")
    is_renewal = a3.lower().startswith("yes") and "2026" in a3 and "before" not in a3.lower()
    return is_renewal and field_id in r.get("skips", [])


# field -> callable(fields, profile) -> is it required for this applicant?
# Signature takes cfg too where the answer depends on configuration.
CONDITIONAL_REQUIRED = {
    "A1b": lambda f, p: f.get("A1", "").strip().lower().startswith("organization"),
    "B5":  lambda f, p: p == "Establecida",
    "B7":  lambda f, p: f.get("A1", "").strip().lower().startswith("organization"),
    "B8":  lambda f, p: f.get("A1", "").strip().lower().startswith("organization"),
    "C1":  lambda f, p: True,   # every applicant type owes a legal identity doc
    "D3":  lambda f, p: f.get("D2", "").strip().lower() in ("no", "false"),
    "G4":  lambda f, p: p == "Establecida",
    "G5":  lambda f, p: p == "Inicial",
    "I2":  lambda f, p: f.get("I1", "").strip().lower() not in ("", "no"),
    "J1":  lambda f, p: "2026" in f.get("A3", "") and "yes" in f.get("A3", "").lower(),
    "J2":  lambda f, p: "2026" in f.get("A3", "") and "yes" in f.get("A3", "").lower(),
}

# Measurement fields, required of every applicant. Until 2026-11-13 they
# were required only above a $10,000 request (decision 2, "measurement
# tiering"); Iván retired that: the form never applied it — it always asked
# all three — so the tier only changed what Eva expected, not what people
# were asked. Kept as a named list because the baseline, the 12-month target
# and the milestones are what the follow-up instrument measures against.
MEASUREMENT_REQUIRED = ["F2", "F3", "E10"]

# Paragraph fields with word-count limits: (field, max_words) — v3 IDs.
# E7 is deliberately absent: it is SHORT TEXT (a one-sentence formula), not a
# paragraph. The v2 code word-counted it at 150, which the form spec contradicts.
PARAGRAPH_FIELDS = [
    ("E1", 60),    # Project title + 2-3 sentence summary
    ("E4", 150),   # Economic barrier                     (was E7)
    ("E6", 150),   # Who participants are + selection     (was E9)
    ("E8", 150),   # How they apply it + which partner    (was E11)
    ("E11", 150),  # Risks + mitigation                   (was E15)
    ("F5", 150),   # Prior BTC / financial-inclusion results
    ("G5", 100),   # Main uses of funds (Inicial)
    ("G7", 150),   # Continuity after the grant
    ("J1", 200),   # 2026 promises vs achievements
]

# Numeric fields — v3. B9 and A4 are gone; E2 moved to DATE_FIELDS.
NUMERIC_FIELDS = ["B5", "E5", "G1", "G2"]

# E2 is a start/end date PAIR. Project duration is DERIVED from it, which is
# what the "more than one stage in <=12 months" check needs. The v2 code had
# E2 in NUMERIC_FIELDS parsing it as a month count.
DATE_FIELDS = ["E2"]

# Short-text field validated for the result formula rather than word count.
RESULT_FORMULA_FIELD = "E7"

# ── Classification vocabularies ──
VALID_PILLARS = ["Education", "Technology Adoption", "Economic Empowerment"]
VALID_MEASURES = ["Skills", "Access", "Commerce", "Remittances", "Recovery"]
VALID_STAGES = ["Awareness", "Useful adoption", "Local circulation", "Resilience"]

# The form shows F1 and E12 with a description after the name:
#   "Commerce — number of merchants trading in the last 30 days"
# and stores the whole label. Every comparison here is against the bare name,
# so until 2026-11-13 F1 never matched (4 Resilience-fit points lost on every
# application, plus an "unrecognized_measure" note) and E12 was ignored (the
# target stage fell back to the inferred one, and the ambitious-target rule
# never ran). The test fixtures used the bare names, so nothing failed.
# Normalized once, at the start of step_clean; test_form_options.py feeds the
# form's own labels through the real steps.
OPTION_FIELDS = {"F1": VALID_MEASURES, "E12": VALID_STAGES, "J2": VALID_STAGES}


def canonical_option(value, valid):
    """
    Map a stored option label onto its canonical name: exact match first, then
    the text before a spaced dash ("Commerce — ..."), case-insensitively.
    Anything unrecognized is returned unchanged, so it still shows up as
    unrecognized downstream instead of being silently coerced.
    """
    v = "" if value is None else str(value).strip()
    if not v or v in valid:
        return v
    head = re.split(r"\s+[\u2014\u2013-]\s+", v, maxsplit=1)[0].strip().lower()
    for c in valid:
        if head == c.lower():
            return c
    return v


def normalize_option_fields(fields):
    for fid, valid in OPTION_FIELDS.items():
        if fid in fields:
            fields[fid] = canonical_option(fields[fid], valid)
    return fields


# Hard gates (EVA parameters, Paso 2; decided by Iván 2026-11-13). Any of
# these keeps the semáforo RED until a person releases it, and counts as a
# critical flag (manual review before committee). Until 2026-11-13 the code
# treated a different set as critical (name mismatch and missing nonprofit
# proof, which the parameters call soft) and never let a flag touch the
# semáforo, so an application on the OFAC list could come out GREEN.
HARD_GATE_FLAGS = [
    "ofac_flag", "eligibility_incomplete", "child_protection_missing",
    "disclosure_present", "missing_legal_name",
]

# Eligibility checklist (0.2). Four statements; the form lets an applicant
# continue with fewer if they explain in K2 (decision 2026-11-13), on the
# understanding that Eva sends any incomplete checklist to manual review. That
# gate did not exist until 2026-11-13. Matched by a phrase from each statement
# rather than by the full text, so a copy edit on the form does not silently
# disable it; test_form_options.py checks every phrase against the form.
ELIGIBILITY_STATEMENTS = [
    ("economic_barriers", "economic barrier"),
    ("charitable_purpose", "charitable purpose"),
    ("outcome_reporting", "outcome reporting"),
    ("no_price_gains", "price gain"),
]

# Resilience-path signals for STAGE INFERENCE (methodology Paso 3).
# Searched across E1 + E4 + E8 + E9 + F1 + F2 + F3.
STAGE_SIGNALS = {
    # Español ampliado el 2026-11-11. "Useful adoption" tenía UN solo término
    # en español (billetera activa) contra quince en inglés, y es justo la
    # etapa bisagra de la metodología. Un proyecto que ya describe gente
    # cobrando en bitcoin, escrito en español, no podía alcanzarla: caía a
    # Awareness o a Local circulation, las únicas con vocabulario. Las cuatro
    # quedan parejas (22 / 25 / 27 / 25) porque el empate se resuelve hacia la
    # etapa más avanzada y el tamaño de la lista sesga el max().
    "Awareness": [
        "workshop", "class", "classes", "curriculum", "training", "diploma",
        "course", "teach", "teaching", "literacy", "first wallet", "seminar",
        "taller", "capacitacion", "capacitación", "formacion", "formación",
        # español
        "clase", "seminario", "diplomado", "primera billetera",
        "alfabetizaci",
    ],
    "Useful adoption": [
        "active wallet", "wallets active", "paying", "pays", "receiving payment",
        "receive payments", "paid in bitcoin", "salary", "wages", "stipend",
        "spend", "spending", "transacting", "transaction", "billetera activa",
        # español
        "billeteras activas", "recibe pago", "recibir pago", "reciben pago",
        "cobra en bitcoin", "cobrar en bitcoin", "cobran en bitcoin",
        "pagado en bitcoin", "salario", "sueldo", "transacci",
    ],
    "Local circulation": [
        "merchant", "merchants", "vendor", "shop", "store", "accept bitcoin",
        "accepts bitcoin", "btc map", "btcmap", "between members",
        "community members", "remittance", "remittances", "local trade",
        "comercio", "comerciante", "remesa", "remesas",
        # español
        "acepta bitcoin", "aceptan bitcoin", "acepta pago", "aceptan pago",
        "entre miembros", "comercio local", "proveedor", "tienda",
        "mercado local",
    ],
    "Resilience": [
        "emergency fund", "savings fund", "reserve fund", "without subsidy",
        "self-sustaining", "self sustaining", "sustains itself", "recovery",
        "after a shock", "resilient", "local leaders train", "train others",
        "fondo de emergencia", "sin subsidio", "autosostenible",
        # español
        "fondo de ahorro", "fondo de reserva", "se sostiene",
        "autosuficiente", "recuperaci", "lideres locales", "líderes locales",
        "capacitar a otros", "forma a otros", "sin donaciones",
    ],
}

EXPECTED_MEASURES_BY_STAGE = {
    "Awareness": ["Skills"],
    "Useful adoption": ["Access", "Skills"],
    "Local circulation": ["Commerce", "Remittances"],
    "Resilience": ["Recovery"],
}

# Pillar inference — searched across E1 + E4 + E8.
# El pilar se elige con max(scores), así que el TAMAÑO de cada lista influye
# en el resultado, no solo su contenido. Las tres se mantienen parejas a
# propósito (26 / 27 / 24) y se evitan términos genéricos: agregar "red" o
# "programa" a Technology inflaría sus aciertos sin aportar discriminación.
#
# El match es por subcadena (_count_signals), así que se usan raíces:
# "mercado" cubre mercados, "transacci" cubre transacción y transacciones,
# "vendedor" cubre vendedora y vendedores.
#
# Español ampliado el 2026-11-11. La versión anterior tenía 22% de términos
# en español, lo que daba a una solicitud en inglés cerca de cuatro veces más
# probabilidad de coincidir que a su equivalente en español. Con el padrón de
# grantees concentrado en Centroamérica y Sudamérica, eso era un sesgo
# sistemático contra quienes escriben en su idioma. Portugués sigue sin
# cubrir — hay grantees en Madeira y Brasil, queda pendiente.
PILLAR_SIGNALS = {
    "Education": [
        "education", "training", "curriculum", "course", "diploma", "students",
        "school", "teach", "learning", "workshop", "literacy", "instructor",
        "certification", "educacion", "educación", "escuela", "estudiantes",
        # español
        "alfabetizaci", "enseña", "aprendizaje", "curso", "diplomado",
        "docente", "certificaci", "estudiante", "mentor",
        # el nombre del pilar y sus sinónimos directos
        "financial literacy", "educativ", "pedagog", "tutor", "educar",
        "alfabetización financiera",
    ],
    "Economic Empowerment": [
        "trade", "commerce", "business", "merchant", "trader", "income",
        "revenue", "employment", "entrepreneur", "market", "savings",
        "cross-border", "remittance", "payment", "comercio", "ingreso",
        "emprendedor", "ahorro",
        # español — "pago" queda fuera a propósito: es señal de ETAPA y es
        # demasiado común, empujaría a Economic cualquier proyecto educativo
        # que mencione cobrar.
        "mercado", "vendedor", "negocio", "remesa", "ventas",
        "microempresa", "empleo", "tienda",
        # "client" en vez de "cliente": cubre clienta, clientes, clientas y
        # el client inglés. "cliente" no coincide con "clienta", que es la
        # forma que usa cualquier proyecto de vendedoras.
        "client", "vender",
        # "pago" suelto queda fuera por genérico, pero "pagos digitales" es
        # comercio sin ambigüedad. Hacen falta las dos formas: el match es
        # por subcadena y "pago digital" no está dentro de "pagos digitales".
        "pago digital", "pagos digitales",
        # El nombre del propio pilar faltaba. "Empower women through financial
        # education to foster economic independence" marcaba 0 aquí y 1 en
        # Education, así que se clasificaba como Education — un humano lo
        # había puesto en Economic Empowerment. Encontrado por B1 sobre
        # BTC Media (GR-2025-011), 2026-11-11.
        "economic", "económ", "empower", "livelihood",
        "financial inclusion", "empoderamiento", "inclusi",
    ],
    "Technology Adoption": [
        "node", "lightning", "infrastructure", "wallet", "software", "api",
        "platform", "system", "open-source", "network", "protocol", "mining",
        "nodo", "infraestructura", "plataforma",
        # español
        "billetera", "monedero", "código abierto", "codigo abierto",
        "servidor", "protocolo", "mineria", "minería", "aplicaci",
        # el nombre del pilar y sus sinónimos directos. "digital" queda
        # fuera a propósito: "pagos digitales" es comercio, no tecnología.
        "technology", "technical", "tecnolog", "hardware",
        "self-custody", "autocustodia",
    ],
}

# Bitcoin rule (methodology): flag when these appear as the RESULT or GOAL.
BITCOIN_RULE_KEYWORDS = [
    "price appreciation", "price increase", "value will go up", "hodl",
    "store of value gains", "number of downloads", "wallets created",
    "transaction volume", "sats distributed",
    "subida del precio", "plusvalía", "plusvalia", "ganancias por precio",
    "descargas", "wallets creadas", "valorização", "valorizacao",
    "aumento de preço", "aumento de preco",
]

# Generic beneficiary terms that do not count as specificity (E6).
GENERIC_BENEFICIARY_TERMS = [
    "people", "community", "communities", "individuals", "population",
    "everyone", "all", "public", "users", "gente", "comunidad", "personas",
]

# Email / URL
EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
URL_REGEX = re.compile(r'^https?://[^\s]+$')

# OFAC SDN list URL and cache
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_CACHE_PATH = CACHE_DIR / "ofac_sdn.csv"
OFAC_CACHE_TTL = 604800  # 7 days in seconds (weekly refresh)


# ─── Google API helpers ────────────────────────────────────────────────────

# ── Autenticación con Google ──────────────────────────────────────────────
#
# Vive en scripts/google_auth.py, no aquí. Eva lo centralizó el 2026-11-13
# porque nueve scripts tenían cada uno su propia copia de get_credentials, y
# una copia divergente de la lógica de credenciales es como se llega a un
# token que nunca se refresca.
#
# Ese módulo fija los scopes (drive + spreadsheets completos) y decide el
# refresh con una cadena OR que NO depende de `creds.expired`:
#
#     needs_refresh = (not creds.token or creds.expired
#                      or stored_expiry is None or _is_expired(stored_expiry))
#
# Es más defensivo que confiar en la propiedad de la librería: `expired`
# devuelve False cuando el objeto se construyó sin `expiry`, y entonces
# nunca refresca. Aquí ese término puede ser False sin consecuencia porque
# _is_expired() parsea el string guardado y cubre el caso.
#
# Pendiente de una línea en google_auth.py, no aquí: pasarle `expiry=` al
# constructor de Credentials. Sin eso, `creds.expired` queda en False de
# forma permanente y google-auth tampoco auto-refresca a media corrida —
# `valid` es `token and not expired`, así que la librería cree que el token
# sirve hasta que Google responde 401. El arranque ya está cubierto; lo que
# falta es que el token venza DURANTE un lote largo.
from google_auth import (          # noqa: E402
    get_credentials,
    get_sheets_service,
    get_drive_service,
)


@with_retry
def read_sheet(sheets_api, spreadsheet_id, tab_name, range_str=None):
    """Read all data from a tab."""
    if range_str is None:
        range_str = f"'{tab_name}'"
    result = sheets_api.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=range_str
    ).execute()
    return result.get('values', [])


GRID_HEADROOM_ROWS = 500


def ensure_grid(sheets_api, spreadsheet_id, tab_name, last_row, last_col):
    """
    Grow a tab so that (last_row, last_col) exists before writing there.

    values().update fails with "exceeds grid limits" outside the tab's size;
    only values().append grows it. Found 2026-11-13 when the result tabs got
    their v3 columns. The Process Log gets at least one row per run, so with a
    30-minute cron the default 1000 rows would run out in about three weeks and
    every later log write would fail. Rows grow with headroom to keep this to
    an occasional call.
    """
    meta = sheets_api.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets(properties(sheetId,title,gridProperties(rowCount,columnCount)))",
    ).execute()
    for sh in meta.get("sheets", []):
        props = sh.get("properties", {})
        if props.get("title") != tab_name:
            continue
        grid = props.get("gridProperties", {})
        reqs = []
        if grid.get("rowCount", 0) < last_row:
            reqs.append({"appendDimension": {
                "sheetId": props["sheetId"], "dimension": "ROWS",
                "length": last_row - grid.get("rowCount", 0) + GRID_HEADROOM_ROWS}})
        if grid.get("columnCount", 0) < last_col:
            reqs.append({"appendDimension": {
                "sheetId": props["sheetId"], "dimension": "COLUMNS",
                "length": last_col - grid.get("columnCount", 0)}})
        if reqs:
            sheets_api.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id, body={"requests": reqs}).execute()
            print(f"  [{tab_name}] grid grown to fit row {last_row}, column {last_col}")
        return
    raise ValueError(f"tab not found: {tab_name}")


@with_retry
def write_sheet(sheets_api, spreadsheet_id, tab_name, values, start_row=2):
    """Write rows to a tab (append style — starts at given row)."""
    if not values:
        return
    ensure_grid(sheets_api, spreadsheet_id, tab_name,
                start_row + len(values) - 1, max(len(r) for r in values))
    num_cols = len(values[0]) if values else 1
    def col_letter(n):
        r = ""
        while n > 0:
            n, rem = divmod(n - 1, 26)
            r = chr(65 + rem) + r
        return r
    end_col = col_letter(num_cols)
    range_str = f"'{tab_name}'!A{start_row}:{end_col}"
    body = {"values": values}
    sheets_api.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_str,
        valueInputOption='RAW',
        body=body
    ).execute()


@with_retry
def append_sheet(sheets_api, spreadsheet_id, tab_name, values):
    """Append rows to a tab."""
    if not values:
        return
    num_cols = len(values[0]) if values else 1
    def col_letter(n):
        r = ""
        while n > 0:
            n, rem = divmod(n - 1, 26)
            r = chr(65 + rem) + r
        return r
    end_col = col_letter(num_cols)
    range_str = f"'{tab_name}'!A1:{end_col}"
    body = {"values": values}
    sheets_api.spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=range_str,
        valueInputOption='RAW',
        insertDataOption='INSERT_ROWS',
        body=body
    ).execute()


@with_retry
def clear_tab(sheets_api, spreadsheet_id, tab_name, start_row=2):
    """Clear data rows from a tab (keep headers)."""
    range_str = f"'{tab_name}'!A{start_row}:Z"
    sheets_api.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=range_str
    ).execute()


# ─── Config loaders ────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_DIR / "intake_sheets_config.json") as f:
        return json.load(f)


def load_scorecard_config():
    with open(CONFIG_DIR / "scorecard_config.json") as f:
        return json.load(f)


def load_country_mapping():
    with open(CONFIG_DIR / "country_mapping.json") as f:
        return json.load(f)


def load_region_mapping():
    with open(CONFIG_DIR / "region_mapping.json") as f:
        return json.load(f)


# One watermark per environment. Until 2026-11-13 test and production shared
# cache/intake_watermark.json while reading the same Supabase table, so a test
# run moved the mark past real applications and production then never saw
# them. Each environment now keeps its own file.
ENVIRONMENTS = ("test", "production")
WATERMARK_LEGACY = CACHE_DIR / "intake_watermark.json"


def watermark_path(env):
    if env not in ENVIRONMENTS:
        # No default on purpose: a missing env must not fall back to a shared file.
        raise ValueError(f"unknown environment for watermark: {env!r}")
    return CACHE_DIR / f"intake_watermark.{env}.json"


def _empty_watermark():
    return {
        "last_timestamp": None,
        "last_row": 0,
        "total_processed": 0,
        "last_run_id": None
    }


def load_watermark(env):
    wm_path = watermark_path(env)
    if wm_path.exists():
        with open(wm_path) as f:
            return json.load(f)
    # The shared file was only ever advanced by test runs (production has not
    # run), so test inherits it. Production deliberately does NOT: inheriting
    # it would skip every application a test run had already touched.
    if env == "test" and WATERMARK_LEGACY.exists():
        with open(WATERMARK_LEGACY) as f:
            wm = json.load(f)
        print(f"  Watermark: test inherits legacy {WATERMARK_LEGACY.name} "
              f"(last_timestamp={wm.get('last_timestamp')})")
        return wm
    return _empty_watermark()


def save_watermark(env, wm):
    wm_path = watermark_path(env)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Write then rename, so a crash mid-write cannot leave a truncated file
    # that the next run would fail to parse.
    tmp = wm_path.with_name(wm_path.name + ".tmp")
    with open(tmp, 'w') as f:
        json.dump(wm, f, indent=2)
    os.replace(tmp, wm_path)


# ─── Run lock ──────────────────────────────────────────────────────────────
# Two overlapping runs (cron firing while a manual run is still going, or two
# cron ticks when a run is slow) would both read the same watermark, mint
# the same IDs and write the same rows twice. One lock for both environments:
# they share the grantee registry and the Drive folders.

RUN_LOCK_PATH = CACHE_DIR / "intake_pipeline.lock"
EXIT_LOCKED = 75  # EX_TEMPFAIL: "try again later", not a failure


class PipelineLocked(Exception):
    pass


def acquire_run_lock(path=None, info=None):
    """
    Take the run lock or raise PipelineLocked with who holds it.

    flock is released by the kernel when the process exits, crashes or is
    killed, so there is no stale lock to clean up by hand. The caller must
    keep the returned file object alive for the whole run.
    """
    path = Path(path or RUN_LOCK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        holder = fh.read().strip() or "unknown holder"
        fh.close()
        raise PipelineLocked(holder)
    fh.seek(0)
    fh.truncate()
    fh.write(json.dumps({
        "pid": os.getpid(),
        "started": datetime.now(timezone.utc).isoformat(),
        **(info or {}),
    }))
    fh.flush()
    return fh


# ─── P0 Guardrails: Slack notification + Idempotency ───────────────────────

def send_slack_notification(message, is_error=False):
    """
    Send a notification to Eva's Slack channel.
    Uses the openclaw message tool via CLI if available, otherwise logs to stderr.
    Never raises — notification failures must not break the pipeline.
    """
    try:
        prefix = "🔴 INTAKE ERROR" if is_error else "✅ INTAKE COMPLETE"
        full_msg = f"{prefix}: {message}"

        # Try openclaw CLI (works when running under gateway)
        result = subprocess.run(
            ["openclaw", "message", "send", "--channel", "#foundation-ops", full_msg],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            # Fallback: log to stderr (will appear in cron logs / systemd journal)
            print(f"[NOTIFY] {full_msg}", file=sys.stderr)
    except Exception:
        # Never let notification failure break the pipeline
        print(f"[NOTIFY FAILED] {message}", file=sys.stderr)


def get_existing_app_ids(sheets_api, spreadsheet_id):
    """
    Read the Cleaned tab to find App_IDs that have already been processed.
    Returns a set of App_ID strings. Used for idempotency — if an App_ID
    is already in the Cleaned tab, we skip it to prevent duplicates.
    """
    try:
        data = read_sheet(sheets_api, spreadsheet_id, TAB_CLEAN)
        if not data or len(data) < 2:
            return set()
        headers = data[0]
        app_id_col = None
        for i, h in enumerate(headers):
            if h and "app_id" in str(h).lower():
                app_id_col = i
                break
        if app_id_col is None:
            return set()
        existing = set()
        for row in data[1:]:
            if app_id_col < len(row) and row[app_id_col]:
                existing.add(row[app_id_col])
        return existing
    except Exception as e:
        print(f"  WARNING: Could not read existing App_IDs for idempotency check: {e}")
        return set()

# ─── Grantee Registry ──────────────────────────────────────────────────────

def load_grantee_registry():
    """Load the grantee registry JSON (pre-populated from Master Tracker)."""
    registry_path = CONFIG_DIR / "grantee_registry.json"
    if registry_path.exists():
        with open(registry_path) as f:
            return json.load(f)
    return []


def load_seguimiento_2027():
    """Load the 2027 pipeline tracking data from Master Tracker."""
    seg_path = CONFIG_DIR / "seguimiento_2027.json"
    if seg_path.exists():
        with open(seg_path) as f:
            return json.load(f)
    return []


def load_tracker_listas():
    """Load dropdown values from Master Tracker Listas sheet."""
    listas_path = CONFIG_DIR / "tracker_listas.json"
    if listas_path.exists():
        with open(listas_path) as f:
            return json.load(f)
    return {}


def norm_org_name(name):
    """Normalize organization name for fuzzy matching."""
    if not name:
        return ""
    n = name.lower().strip()
    # Remove common legal suffixes
    for suffix in [" inc.", " inc", " llc", " ltd", " corp.", " corp",
                   " foundation", " fundacion", " asociacion civil",
                   " a.c.", " ac", " ngo", " org"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)]
    # Remove everything except alphanumerics
    n = re.sub(r'[^a-z0-9]', '', n)
    return n


def _name_tokens(s):
    """
    Lower-case, strip accents, split on non-alphanumerics, drop tokens under
    3 characters.

    El regex anterior, `re.findall(r'[a-z0-9]+', nombre.lower())`, partía en
    cada letra acentuada: "Fundación" -> "fundaci" + "n", "Asociación" ->
    "asociaci" + "n", "Medellín" -> "medell" + "n". `domain_common` contiene
    "fundacion" pero no "fundaci" ni "n", así que dos organizaciones del mismo
    país con una palabra acentuada compartían los 2 tokens {"fundaci", "n"},
    justo el mínimo del nivel 4 — y una organización NUEVA se trataba como
    grantee existente: reusaba su GR-id, no se creaba su carpeta en Drive y
    heredaba los datos del registro de otra.

    Explica por qué las dos solicitudes demo se emparejaron con GR-2026-015.

    Diagnóstico y arreglo del equipo de Salomé, 2026-11-13
    (`supabase/eva_patches/match_grantee_accents.py` en DvvSalome/paystandorg).
    Mismo origen que el sesgo del vocabulario: tratamiento inglés de texto en
    español.
    """
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {t for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 3}


def match_grantee(legal_name, country, registry):
    """
    Match an applicant to existing grantee registry.
    Returns (grantee_id, matched_name, is_renewal) or (None, None, False).
    """
    if not legal_name:
        return None, None, False

    applicant_key = norm_org_name(legal_name)

    # 1. Exact normalized match
    for g in registry:
        if norm_org_name(g["legal_name"]) == applicant_key:
            return g["grantee_id"], g["legal_name"], True

    # 2. Partial match (one contains the other)
    for g in registry:
        reg_key = norm_org_name(g["legal_name"])
        if len(applicant_key) > 5 and len(reg_key) > 5:
            if applicant_key in reg_key or reg_key in applicant_key:
                return g["grantee_id"], g["legal_name"], True

    # 3. Match without country suffixes (e.g., "Motiv" vs "Motiv Peru")
    # Only apply if the cleaned result is still substantial (8+ chars)
    # to avoid "bitcoin" matching "bitcoinaccra" etc.
    clean_applicant = re.sub(r'(peru|brasil|brazil|elsalvador|costarica|colombia|mexico|guatemala|argentina)', '', applicant_key)
    if clean_applicant and len(clean_applicant) >= 8:
        for g in registry:
            clean_reg = re.sub(r'(peru|brasil|brazil|elsalvador|costarica|colombia|mexico|guatemala|argentina)', '', norm_org_name(g["legal_name"]))
            if clean_reg and len(clean_reg) >= 8:
                if clean_applicant == clean_reg:
                    return g["grantee_id"], g["legal_name"], True
                # Only match if the shorter string is at least 60% of the longer
                shorter = min(len(clean_applicant), len(clean_reg))
                longer = max(len(clean_applicant), len(clean_reg))
                if shorter >= longer * 0.6:
                    if clean_applicant in clean_reg or clean_reg in clean_applicant:
                        return g["grantee_id"], g["legal_name"], True

    # 4. Country-boosted match: if country matches, require 2+ significant token overlaps
    # Exclude ultra-common tokens in this domain (bitcoin, btc, crypto, foundation, etc.)
    if country:
        country_lower = country.lower().strip()
        domain_common = {"bitcoin", "btc", "crypto", "foundation", "fundacion", "initiative",
                         "project", "program", "org", "organization", "the", "of", "and",
                         "for", "in", "de", "la", "el", "los", "las", "en", "inc", "llc"}
        app_tokens = _name_tokens(legal_name) - domain_common
        for g in registry:
            g_country = str(g.get("country", "")).lower().strip()
            if g_country and country_lower in g_country:
                reg_tokens = _name_tokens(g["legal_name"]) - domain_common
                if app_tokens and reg_tokens:
                    overlap = app_tokens & reg_tokens
                    # Require at least 2 significant tokens to match, or all tokens if < 3
                    min_overlap = max(2, min(len(app_tokens), len(reg_tokens)) // 2)
                    if len(overlap) >= min_overlap:
                        return g["grantee_id"], g["legal_name"], True

    return None, None, False


def generate_grantee_id(year, existing_registry):
    """Generate next sequential Grantee_ID for a given year."""
    year_prefix = f"GR-{year}-"
    max_num = 0
    for g in existing_registry:
        gid = g.get("grantee_id", "")
        if gid.startswith(year_prefix):
            try:
                num = int(gid.split("-")[-1])
                if num > max_num:
                    max_num = num
            except ValueError:
                pass
    return f"GR-{year}-{max_num + 1:03d}"


# ─── Applicant folders and documents in Drive ──────────────────────────────
#
# Decided 2026-11-13 (Iván, with the Drive rules Marisa set out in
# skills/busqueda-inventario/SKILL.md):
#   - One folder per organization per year, inside "Grant Application 2027":
#     "GR-id - Legal name". Renewals too: a 2026 grantee keeps its GR-id and
#     gets a 2027 folder. Earlier years' folders are never written to.
#   - In it, a copy of the whole application as a Google Doc and every file the
#     applicant uploaded (C1, C2, I2, J3), each prefixed with the application ID.
#   - Eva never writes to 1.1 Administration (legal evidence, assembled by the
#     team after approval), Drafts/, or anything outside the 2027 folder.
#   - Re-running does not duplicate anything: every write checks first.
# Until then the pipeline only created folders for NEW organizations and never
# stored a document: C1 was read in memory for the name check and discarded.

SHARED_DRIVE_ID = "0AI7r3Td00baEUk9PVA"   # Paystand Impact Foundation
FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
APPLICATION_COPY_SUFFIX = "Solicitud"


def drive_q_escape(s):
    """
    Quote a value for a Drive query string. Without this a legal name with an
    apostrophe ("Women's Bitcoin Fund") made the query invalid; the error was
    caught and the organization silently got no folder.
    """
    return str(s).replace("\\", "\\\\").replace("'", "\\'")


def drive_find_child(drive_service, parent_id, name, folders_only=False):
    """Return the id of a non-trashed child called `name`, or None."""
    q = (f"name='{drive_q_escape(name)}' and '{drive_q_escape(parent_id)}' in parents "
         f"and trashed=false")
    if folders_only:
        q += f" and mimeType='{FOLDER_MIME}'"
    res = drive_service.files().list(
        q=q, corpora="drive", driveId=SHARED_DRIVE_ID,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields="files(id, name)",
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def drive_folder_url(folder_id):
    return f"https://drive.google.com/drive/folders/{folder_id}" if folder_id else ""


def drive_file_url(file_id, google_doc=False):
    if not file_id:
        return ""
    if google_doc:
        return f"https://docs.google.com/document/d/{file_id}/edit"
    return f"https://drive.google.com/file/d/{file_id}/view"


def applicant_folder_root(config):
    """
    Where applicant folders go for the active environment.

    Production: the real "Grant Application 2027" (top-level
    grant_application_2027_folder). Test: only a folder configured for test
    (config["test"]["grant_application_2027_folder"]). A test run never falls
    back to the real folder: until 2026-11-13 both environments shared it, and
    the 2 Nov rehearsal left four junk grantee folders in the real Drive.
    Returns None when nothing is configured, which ensure_grantee_folder
    reports and step_flag turns into documents_not_stored.
    """
    env = config.get("active_env")
    own = ((config.get("active") or {}).get("grant_application_2027_folder") or {}).get("id")
    if own:
        return own
    if env == "production":
        return (config.get("grant_application_2027_folder") or {}).get("id")
    return None


def ensure_grantee_folder(drive_service, grantee_id, legal_name, parent_folder_id):
    """
    The organization's folder for this year, created if missing.
    Returns (folder_id, error). Never raises: a Drive failure must not stop
    the application from being processed, but it must not be silent either.
    """
    if not drive_service:
        return None, "no Drive connection"
    if not parent_folder_id:
        return None, ("no applicant folder configured for this environment "
                      "(test needs its own grant_application_2027_folder)")
    if not grantee_id or not (legal_name or "").strip():
        return None, "no grantee ID or legal name"
    folder_name = f"{grantee_id} - {legal_name.strip()}"
    try:
        existing = drive_find_child(drive_service, parent_folder_id, folder_name,
                                    folders_only=True)
        if existing:
            return existing, None
        folder = drive_service.files().create(
            body={"name": folder_name, "mimeType": FOLDER_MIME,
                  "parents": [parent_folder_id]},
            supportsAllDrives=True, fields="id, name",
        ).execute()
        return folder["id"], None
    except Exception as e:
        print(f"  WARNING: Could not create folder for {grantee_id}: {e}")
        return None, f"folder: {type(e).__name__}: {str(e)[:120]}"


def create_grantee_folder(drive_service, grantee_id, legal_name, parent_folder_id):
    """Kept for callers outside the pipeline. Returns folder_id or None."""
    return ensure_grantee_folder(drive_service, grantee_id, legal_name, parent_folder_id)[0]


@with_retry
def fetch_application_files(app_id, supabase_cfg):
    """
    The files an application uploaded, from Supabase table application_files
    (question, storage_path, file_name, mime_type, size_bytes). Read-only, with
    the same key the ingest uses. The intake_rows view only carries C1, C2 and
    J3, and I2 (the safeguarding policy) never reached Eva; this table has all.
    """
    url = (supabase_cfg.get("url") or "").rstrip("/")
    key = load_supabase_key(supabase_cfg)
    if not url or not key:
        raise ValueError("supabase url or key not configured")
    query = (f"{url}/rest/v1/application_files"
             f"?application_id=eq.{urllib.parse.quote(app_id)}"
             f"&select=question,storage_path,file_name,mime_type,size_bytes"
             f"&order=question.asc")
    req = urllib.request.Request(query, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"unexpected Supabase response: {type(payload).__name__}")
    return payload


def document_file_name(app_id, question, file_name):
    base = re.sub(r"[\\/\x00-\x1f]", "_", os.path.basename(str(file_name or "file")))
    return f"{app_id} · {question} · {base[:120]}"


def load_question_labels():
    """Question text in form order, generated from questions.js."""
    try:
        with open(CONFIG_DIR / "question_labels.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"  ⚠️  question_labels.json not loaded ({type(e).__name__}); "
              f"the application copy will use column names")
        return None


def _html(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def application_copy_html(app_id, fields, labels, attachments):
    """
    The whole application as the applicant answered it, for the committee and
    for item 4 of Marisa's Grant Completeness Checklist ("proposal of the
    cycle"). Answers are escaped: they are applicant text, never markup.
    """
    title = f"{app_id} · {fields.get('B1', '').strip() or '(no legal name)'}"
    out = [f"<html><head><meta charset='utf-8'><title>{_html(title)}</title></head><body>",
           f"<h1>{_html(title)}</h1>",
           f"<p>Submitted: {_html(fields.get('timestamp', ''))}</p>"]
    if labels:
        sections = {s["id"]: s["title"] for s in labels.get("sections", [])}
        order = [(f["id"], f["section"], f["label"]) for f in labels.get("fields", [])]
    else:
        sections, order = {}, [(fid, "", col) for fid, col in QUESTION_MAP.items()
                               if fid != "timestamp"]
    current = None
    for fid, sec, label in order:
        raw = str(fields.get(fid, "") or "").strip()
        if fid in attachments:
            # The file, plus any text answer the same question carries (I2 is
            # a policy file OR a commitment, and always a named person).
            link, name = attachments[fid]
            parts = [f"<a href='{_html(link)}'>{_html(name)}</a>" if link else _html(name)]
            if raw and not raw.startswith(SUPABASE_DOC_PREFIX):
                parts.append(_html(raw).replace("\n", "<br>"))
            value = "<br>".join(parts)
        elif raw and not raw.startswith(SUPABASE_DOC_PREFIX):
            value = _html(raw).replace("\n", "<br>")
        else:
            continue
        if sec and sec != current:
            current = sec
            out.append(f"<h2>{_html(sec)}. {_html(sections.get(sec, ''))}</h2>")
        out.append(f"<p><b>{_html(fid)}. {_html(label)}</b><br>{value}</p>")
    out.append("</body></html>")
    return "\n".join(out)


def _upload(drive_service, parent_id, name, data, mime, as_google_doc=False):
    body = {"name": name, "parents": [parent_id]}
    if as_google_doc:
        body["mimeType"] = GOOGLE_DOC_MIME
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
    created = drive_service.files().create(
        body=body, media_body=media, supportsAllDrives=True, fields="id",
    ).execute()
    return created["id"]


# ─── Eva assessment: the reasoning, one Google Doc per application ──────────
ASSESSMENT_SUFFIX = "Eva assessment"
CRITERIA = [
    ("Resilience fit", "Score_Resilience_Fit", "Resilience_Fit_Reason", 30),
    ("Measurable result", "Score_Measurable_Result", "Measurable_Result_Reason", 25),
    ("Ability to deliver", "Score_Ability_To_Deliver", "Ability_To_Deliver_Reason", 20),
    ("Value and sustainability", "Score_Value_Sustainability", "Value_Sustainability_Reason", 25),
]
FLAG_EXPLANATIONS = {
    "ofac_flag": "The legal name (B1) or the legal representative (B3) matches an entry on the OFAC sanctions list.",
    "eligibility_incomplete": "At least one eligibility statement (0.2) was left unchecked; K2 should explain why.",
    "child_protection_missing": "The project involves children (I1) but there is no safeguarding policy or commitment (I2).",
    "disclosure_present": "The applicant disclosed legal, financial, media or conflict-of-interest issues (K1).",
    "missing_legal_name": "The application has no legal name (B1); no grantee record or folder was created.",
    "name_mismatch": "The legal name (B1) does not match the registration document (C1).",
    "address_mismatch": "The address (B4) does not match the registration document (C1).",
    "missing_nonprofit_proof": "An NGO did not upload proof of nonprofit status, or no registration document was found.",
    "bitcoin_rule_violation": "The impact appears to rest on price gains, downloads, wallets created, raw volume or sats given away.",
    "budget_invalid": "The budget does not hold together (G2 is zero, larger than G1, or G4 does not add up to G2).",
    "high_dependency": "The request is 75% or more of the organization's annual budget (context, not scored).",
    "suspected_participant_identifiers": "A paragraph looks like it contains a participant list; only aggregate figures should be sent.",
    "duplicate_application": "Another application in this batch has the same legal name or contact email.",
    "documents_not_stored": "Some uploaded documents could not be copied to the applicant's folder.",
    "nonsense_empty_required": "A required answer is empty.",
    "nonsense_short_answer": "A paragraph answer is shorter than the 15-word minimum.",
    "nonsense_one_word": "A paragraph question was answered with one word.",
    "nonsense_repeated_text": "An answer repeats the same phrase several times.",
    "nonsense_random_chars": "An answer looks like random characters.",
    "nonsense_copy_paste": "Two different questions have the same answer.",
    "nonsense_text_in_number": "A number field contains text.",
    "nonsense_invalid_email": "An email address is not valid.",
}


def _reason_html(reason):
    """'Group: item; item | Group: item' -> one list per group."""
    out = []
    for group in [g.strip() for g in str(reason or "").split(" | ") if g.strip()]:
        label, _, rest = group.partition(": ")
        items = [i.strip() for i in rest.split("; ") if i.strip()] if rest else []
        if items:
            out.append(f"<p><b>{_html(label)}</b></p><ul>"
                       + "".join(f"<li>{_html(i)}</li>" for i in items) + "</ul>")
        else:
            out.append(f"<p>{_html(group)}</p>")
    return "".join(out) or "<p>(no detail recorded)</p>"


def assessment_html(app, board_url=""):
    """
    Eva's pre-classification of one application, written for the team to read
    and dispute line by line (comments in Google Docs). Every statement comes
    from the deterministic rules and cites the question it read. Applicant text
    is escaped; this document never carries markup from the application.
    """
    f = app.get("fields", {}) or {}
    c, sc, fl = app.get("classified", {}) or {}, app.get("score", {}) or {}, app.get("flags", {}) or {}
    app_id = app.get("app_id", "")
    name = f.get("B1", "").strip() or "(no legal name)"
    h = [f"<html><head><meta charset='utf-8'><title>{_html(app_id)} · {ASSESSMENT_SUFFIX}</title></head><body>",
         f"<h1>{_html(app_id)} · {_html(name)}</h1>",
         "<p><i>Eva's pre-classification. It is a starting point for the team, not a decision: "
         "comment on any line you support or dispute, and record the team's decision in the review board"
         + (f" (<a href='{_html(board_url)}'>open the board</a>)" if board_url else "") + ".</i></p>"]

    hold = sc.get("Semaforo_Hold", "")
    h.append("<h2>1. Summary</h2><ul>")
    h.append(f"<li><b>Traffic light: {_html(sc.get('Semaforo', ''))}</b>"
             + (f" — held red by: {_html(hold)}" if hold else "") + "</li>")
    h.append(f"<li>By score alone: {_html(sc.get('Semaforo_By_Score', ''))}, "
             f"{_html(sc.get('Total_Normalized', ''))} / 100"
             f" (raw {_html(sc.get('Total_Score', ''))} of {_html(sc.get('Score_Max_Available', ''))} available)</li>")
    h.append(f"<li>Profile: {_html(c.get('Profile', ''))} · Route: {_html(c.get('Route', ''))}"
             f" · Region: {_html(c.get('Region', ''))}</li>")
    h.append(f"<li>Stage suggested: {_html(c.get('Stage_Suggested', '') or 'not inferable')}"
             f" · Target declared (E12): {_html(c.get('Stage_Target', '') or 'none')}</li>")
    h.append(f"<li>Pillars: {_html(c.get('Pillars_All', '') or c.get('Pillar', ''))}</li></ul>")

    h.append("<h2>2. Hard gates</h2><ul>")
    for g in HARD_GATE_FLAGS:
        state = "TRIGGERED" if fl.get(g) == "YES" else "clear"
        h.append(f"<li><b>{_html(g)}</b>: {state}"
                 + (f" — {_html(FLAG_EXPLANATIONS.get(g, ''))}" if state == "TRIGGERED" else "") + "</li>")
    h.append("</ul>")

    h.append("<h2>3. Stage</h2>")
    h.append(f"<p><b>Suggested current stage:</b> {_html(c.get('Stage_Suggested', '') or 'not inferable')}</p>")
    h.append(f"<p><b>Why:</b> {_html(c.get('Stage_Justification', ''))}</p>")
    h.append(f"<p><b>Target stage declared by the applicant (E12):</b> {_html(c.get('Stage_Target', '') or 'none')}"
             f"{' · jump: ' + _html(c.get('Stage_Jump')) if c.get('Stage_Jump') else ''}</p>")
    h.append(f"<p><b>Main measure (F1):</b> {_html(c.get('F1_Main_Measure', ''))} — "
             f"matches the {_html(c.get('Measure_Basis', ''))} stage: {_html(c.get('Measure_Matches_Stage', ''))}"
             f" (expected: {_html(c.get('Expected_Measures', ''))})</p>")
    if c.get("Stage_Reached_2026"):
        h.append(f"<p><b>Stage reached in 2026 (J2):</b> {_html(c.get('Stage_Reached_2026'))}</p>")
    notes = [n for n in str(c.get("Classification_Notes", "")).split("; ") if n.strip()]
    if notes:
        h.append("<p><b>Classification notes:</b></p><ul>" + "".join(f"<li>{_html(n)}</li>" for n in notes) + "</ul>")

    h.append("<h2>4. Pillars</h2>")
    h.append(f"<p><b>{_html(c.get('Pillars_All', '') or c.get('Pillar', ''))}</b></p>")
    h.append(f"<p><b>Why:</b> {_html(c.get('Pillar_Justification', ''))}</p>")

    h.append("<h2>5. Scorecard</h2>")
    for i, (label, pts_key, why_key, mx) in enumerate(CRITERIA, 1):
        h.append(f"<h3>5.{i} {label}: {_html(sc.get(pts_key, ''))} of {mx}</h3>")
        h.append(_reason_html(sc.get(why_key, "")))
    if sc.get("Dependency_Note"):
        h.append(f"<p><b>Dependency (context, not scored):</b> {_html(sc.get('Dependency_Note'))}</p>")
    if sc.get("Scoring_Notes"):
        h.append(f"<p><i>{_html(sc.get('Scoring_Notes'))}</i></p>")

    h.append("<h2>6. Flags</h2>")
    raised = [k for k, v in fl.items() if v == "YES" and k in FLAG_EXPLANATIONS]
    if raised:
        h.append("<ul>" + "".join(
            f"<li><b>{_html(k)}</b>{' (hard gate)' if k in HARD_GATE_FLAGS else ''}: "
            f"{_html(FLAG_EXPLANATIONS[k])}</li>" for k in raised) + "</ul>")
        h.append(f"<p><b>Detail:</b> {_html(fl.get('Flags_Detail', ''))}</p>")
    else:
        h.append("<p>No flags.</p>")

    h.append("<h2>7. Team review</h2>")
    h.append("<p>The team's decision is recorded in the review board and every change is logged in "
             "'9. Review Log'. When the case is closed, the final classification is added here.</p>")
    h.append("</body></html>")
    return "\n".join(h)


def write_assessment_docs(drive_service, applications, package_rows, board_url=""):
    """
    Create "<APP-ID> · Eva assessment" in each applicant's folder and put its
    link in the package row. Never overwrites: the assessment is the record of
    what Eva said at intake. Returns a list of error strings; never raises.
    """
    rows = {r.get("app_id"): r for r in package_rows}
    errors = []
    for app in applications:
        app_id = app.get("app_id", "")
        row = rows.get(app_id)
        folder = app.get("drive_folder_id", "")
        if row is None:
            continue
        if not drive_service or not folder:
            row["Eva_Assessment_Link"] = "not created: no applicant folder"
            errors.append(f"{app_id}: no applicant folder")
            continue
        name = f"{app_id} · {ASSESSMENT_SUFFIX}"
        try:
            existing = drive_find_child(drive_service, folder, name)
            if existing:
                fid = existing
            else:
                fid = _upload(drive_service, folder, name,
                              assessment_html(app, board_url).encode("utf-8"),
                              "text/html", as_google_doc=True)
            row["Eva_Assessment_Link"] = drive_file_url(fid, google_doc=True)
        except Exception as e:
            row["Eva_Assessment_Link"] = f"not created: {type(e).__name__}"
            errors.append(f"{app_id}: {type(e).__name__}: {str(e)[:120]}")
    return errors


def _col_letter(n):
    r = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        r = chr(65 + rem) + r
    return r


def review_snapshot_path(env):
    if env not in ENVIRONMENTS:
        raise ValueError(f"unknown environment for review snapshot: {env!r}")
    return CACHE_DIR / f"review_snapshot.{env}.json"


def review_sync(sheets_api, sheet_id, env, run_id):
    """
    Turn the team's edits on the board into the formal record.

    Compares the tracked columns of every row in "6. Review Package" with the
    snapshot taken on the previous run and appends one row per change to
    "9. Review Log" (time, application, field, old value, new value, who).
    When Status changes, Status_Since is updated on that application's row.
    Rows are found by App_ID, never by position, so the team can sort and
    filter the board freely.

    Limits, stated so nobody reads more into the log than it holds: changes are
    seen at run time, so two edits to one cell between runs appear as one;
    "By" is the Reviewed_By column at that moment, because the Sheets API does
    not say who edited a cell.

    The snapshot is saved only after the log rows are written, so a failed
    write is retried on the next run instead of losing the changes.
    Returns {"logged": n, "status_changes": n}.
    """
    data = read_sheet(sheets_api, sheet_id, TAB_PACKAGE) or []
    if not data:
        return {"logged": 0, "status_changes": 0}
    headers = [str(x).strip() for x in data[0]]
    idx = {hname.lower(): i for i, hname in enumerate(headers)}
    if "app_id" not in idx:
        raise ValueError(f"'{TAB_PACKAGE}' has no App_ID column")

    def cell(row, col):
        i = idx.get(col.lower())
        return str(row[i]).strip() if i is not None and i < len(row) else ""

    path = review_snapshot_path(env)
    try:
        before = json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        before = {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    after, log_rows, status_rows = {}, [], []
    for r_i, row in enumerate(data[1:], start=2):
        app_id = cell(row, "App_ID")
        if not app_id:
            continue
        current = {col: cell(row, col) for col in REVIEW_TRACKED_COLUMNS}
        after[app_id] = current
        by = current.get("Reviewed_By", "")
        old = before.get(app_id)
        if old is None:
            log_rows.append([now, app_id, "added_to_board", "Status", "",
                             current.get("Status", ""), "Eva", run_id])
            continue
        for col in REVIEW_TRACKED_COLUMNS:
            if old.get(col, "") != current[col]:
                log_rows.append([now, app_id, "changed", col, old.get(col, ""),
                                 current[col], by, run_id])
                if col == "Status":
                    status_rows.append(r_i)
    for app_id in before:
        if app_id not in after:
            log_rows.append([now, app_id, "removed_from_board", "", "", "", "", run_id])

    if log_rows:
        append_sheet(sheets_api, sheet_id, TAB_REVIEW_LOG, log_rows)
    if status_rows and "status_since" in idx:
        letter = _col_letter(idx["status_since"] + 1)
        for r_i in status_rows:
            sheets_api.spreadsheets().values().update(
                spreadsheetId=sheet_id, range=f"'{TAB_PACKAGE}'!{letter}{r_i}",
                valueInputOption="RAW", body={"values": [[now]]}).execute()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(after, ensure_ascii=False, indent=1))
    os.replace(tmp, path)
    return {"logged": len(log_rows), "status_changes": len(status_rows)}


def store_application_documents(drive_service, folder_id, app_id, fields,
                                supabase_cfg, labels=None):
    """
    Put every uploaded file and a copy of the application in the folder.
    Returns {"stored": [...], "existing": [...], "errors": [...],
             "copy_url": str}. Never raises.
    """
    result = {"stored": [], "existing": [], "errors": [], "copy_url": ""}
    if not drive_service or not folder_id:
        result["errors"].append("no folder to store documents in")
        return result

    attachments = {}   # question -> (url, display name), for the copy
    try:
        files = fetch_application_files(app_id, supabase_cfg)
    except Exception as e:
        files = []
        result["errors"].append(f"file list: {type(e).__name__}: {str(e)[:120]}")

    for rec in files:
        q = rec.get("question", "?")
        name = document_file_name(app_id, q, rec.get("file_name"))
        try:
            existing = drive_find_child(drive_service, folder_id, name)
            if existing:
                result["existing"].append(q)
                attachments[q] = (drive_file_url(existing), name)
                continue
            data, mime = download_supabase_doc(
                SUPABASE_DOC_PREFIX + str(rec.get("storage_path", "")), supabase_cfg)
            if data is None:
                result["errors"].append(f"{q}: download failed")
                attachments[q] = ("", f"{name} (not stored: download failed)")
                continue
            fid = _upload(drive_service, folder_id, name, data,
                          rec.get("mime_type") or mime)
            result["stored"].append(q)
            attachments[q] = (drive_file_url(fid), name)
        except Exception as e:
            result["errors"].append(f"{q}: {type(e).__name__}: {str(e)[:120]}")

    copy_name = f"{app_id} · {APPLICATION_COPY_SUFFIX}"
    try:
        existing = drive_find_child(drive_service, folder_id, copy_name)
        if existing:
            result["existing"].append(APPLICATION_COPY_SUFFIX)
            result["copy_url"] = drive_file_url(existing, google_doc=True)
        else:
            html = application_copy_html(app_id, fields, labels, attachments)
            fid = _upload(drive_service, folder_id, copy_name, html.encode("utf-8"),
                          "text/html", as_google_doc=True)
            result["stored"].append(APPLICATION_COPY_SUFFIX)
            result["copy_url"] = drive_file_url(fid, google_doc=True)
    except Exception as e:
        result["errors"].append(f"application copy: {type(e).__name__}: {str(e)[:120]}")
    return result


def add_grantee_to_registry_tab(sheets_api, spreadsheet_id, grantee_data):
    """Append a new grantee to the Grantee Registry tab."""
    row = [
        grantee_data.get("grantee_id", ""),
        grantee_data.get("legal_name", ""),
        grantee_data.get("country", ""),
        grantee_data.get("first_year", ""),
        0,  # prior_apps_count
        "",  # total_awarded
        "",  # pillar
        "",  # status
        "",  # relationship_owner
        "",  # contact_person
        "",  # contact_info
        "",  # web_social
        "",  # scope_of_work
        "",  # program_type
        "",  # reporting_schedule
        drive_folder_url(grantee_data.get("folder_2027", "")),  # folder_link
        "Yes",  # in_2027_pipeline
        "",  # 2027_pipeline_status
        "New (form submission)",  # 2027_pipeline_tipo
        "",  # 2027_owner
        ""  # notes
    ]
    append_sheet(sheets_api, spreadsheet_id, TAB_REGISTRY, [row])


def update_grantee_registry_match(sheets_api, spreadsheet_id, grantee_id, app_id):
    """Update the In_2027_Pipeline column for a matched grantee."""
    # Read registry to find the row
    data = read_sheet(sheets_api, spreadsheet_id, TAB_REGISTRY)
    if not data:
        return
    headers = data[0]
    gid_col = None
    for i, h in enumerate(headers):
        if h and "Grantee_ID" in str(h):
            gid_col = i
            break
    if gid_col is None:
        return

    for row_idx, row in enumerate(data[1:], 2):
        if gid_col < len(row) and row[gid_col] == grantee_id:
            # Update the In_2027_Pipeline column (col Q = index 16)
            pipeline_col = 16
            if pipeline_col < len(headers):
                col_letter = chr(ord('A') + pipeline_col)
                sheets_api.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"'{TAB_REGISTRY}'!{col_letter}{row_idx}",
                    valueInputOption='RAW',
                    body={"values": [["Yes"]]}
                ).execute()
            break


# ─── Utilities ─────────────────────────────────────────────────────────────

def generate_run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


APP_ID_PATTERN = re.compile(r'^[A-Z]{2,6}-\d{4}-\d{3,6}$')

# Column names the form may use to pass its own application ID through.
INBOUND_APP_ID_COLUMNS = ("App_ID", "Application_ID", "app_id", "application_id")


#  ═══════════════════════════════════════════════════════════════════════════
#  INGEST SOURCES — Supabase primary, Google Sheets as plan B
#
#  Decision: Iván 2026-11-11. The 2027 form writes to Supabase; Apps Script
#  and Sheets are the fallback.
#
#  Both readers return the SAME shape — (headers, rows) where headers is a
#  list of column names and rows is a list of lists. That keeps every step
#  after INGEST untouched: they already consume that shape from Sheets.
#
#  Deliberately uses urllib from the standard library rather than supabase-py.
#  Installing a package on Eva is friction we do not need for three HTTP GETs,
#  and PostgREST is a plain REST interface.
#  ═══════════════════════════════════════════════════════════════════════════

DEFAULT_SUPABASE_KEY_PATH = "~/.openclaw/secrets/supabase_service_key.txt"


# ── Descarga de documentos desde Supabase Storage ──
# La vista `intake_rows` entrega C1/C2/J3 como "storage:<ruta>" apuntando al
# bucket privado. Porteado del parche probado del equipo de Salomé
# (supabase/eva_patches/pipeline_c1_storage.py en DvvSalome/paystandorg),
# aplicado a mano en el servidor de Eva el 2026-11-12. Va aquí para que una
# reinstalación del pipeline no lo borre.
SUPABASE_DOC_PREFIX = "storage:"
SUPABASE_DOC_BUCKET = "applications"
SUPABASE_DOC_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".png": "image/png"}


def download_supabase_doc(value, supabase_cfg=None, timeout=60):
    """
    C1/C2/J3 values starting with "storage:" are files in the private bucket.

    Same contract as download_drive_file: returns (bytes, mime), or
    (None, None) on any failure, so the caller flags it for manual review
    instead of crashing the step.
    """
    try:
        path = value[len(SUPABASE_DOC_PREFIX):].strip()
        if not path or path.startswith("/") or ".." in path.split("/"):
            raise ValueError("unsafe storage path: %r" % path[:80])
        if supabase_cfg is None:
            cfg_file = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "data", "intake_sheets_config.json")
            with open(cfg_file, encoding="utf-8") as fh:
                supabase_cfg = (json.load(fh).get("ingest") or {}).get(
                    "supabase", {})
        url = (supabase_cfg.get("url") or "").rstrip("/")
        key = load_supabase_key(supabase_cfg)
        if not url or not key:
            raise ValueError("supabase url or key not configured")
        req = urllib.request.Request(
            "%s/storage/v1/object/authenticated/%s/%s" % (
                url, SUPABASE_DOC_BUCKET, urllib.parse.quote(path)),
            headers={"apikey": key, "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(11 * 1024 * 1024 + 1)
        if len(data) > 11 * 1024 * 1024:
            raise ValueError("document larger than the 10 MB bucket limit")
        return data, SUPABASE_DOC_MIME.get(
            os.path.splitext(path)[1].lower(), "application/octet-stream")
    except Exception as e:
        print("  ⚠️  supabase document download failed: %s: %s"
              % (type(e).__name__, e))
        return None, None


def load_supabase_key(cfg):
    """
    Read the Supabase key from a file under secrets/.

    Never from config and never from code: the config travels between machines
    and lands in git, a service-role key must not. Returns None when absent,
    which the caller reports as a configuration error rather than crashing.
    """
    path = Path(os.path.expanduser(
        (cfg or {}).get("key_file", DEFAULT_SUPABASE_KEY_PATH)
    ))
    try:
        key = path.read_text().strip()
        return key or None
    except Exception:
        return None


def _normalize_source_headers(raw_headers):
    """
    Accept either the full column names or the bare question IDs.

    Salomé asked for the header row so she could shape the Supabase table, so
    it will probably arrive as A1_Applicant_Type. But a table built from the
    spec's ID column would arrive as plain A1, and both should work rather
    than failing on a naming preference.
    """
    by_id = {fid: col for fid, col in QUESTION_MAP.items()}
    canonical = set(QUESTION_MAP.values())
    out = []
    for h in raw_headers:
        h = (h or "").strip()
        if h in canonical:
            out.append(h)
        elif h in by_id:
            out.append(by_id[h])
        else:
            # Unknown column: keep it. step_flag reports stale v2 columns, and
            # dropping something silently is worse than carrying it along.
            out.append(h)
    return out


# with_retry no acepta argumentos: envuelve directo y usa MAX_RETRIES. La
# versión con @with_retry(max_attempts=3) lanzaba TypeError AL IMPORTAR, así
# que el pipeline entero no arrancaba. Parchado en el servidor de Eva el
# 2026-11-12; corregido aquí el 2026-11-13 para no reintroducirlo.
@with_retry
def fetch_supabase_rows(cfg, since_ts=None):
    """
    Read new submissions from Supabase via PostgREST.

    Filters server-side on the timestamp column so a growing table does not
    mean a growing download. Returns (headers, rows).
    """
    url = (cfg.get("url") or "").rstrip("/")
    table = cfg.get("table")
    ts_col = cfg.get("timestamp_column", "created_at")
    page = int(cfg.get("page_size", 500))

    if not url or not table:
        raise ValueError(
            "supabase ingest needs 'url' and 'table' in "
            "intake_sheets_config.json under ingest.supabase"
        )
    key = load_supabase_key(cfg)
    if not key:
        raise ValueError(
            "supabase key not found. Write it to "
            f"{cfg.get('key_file', DEFAULT_SUPABASE_KEY_PATH)} (chmod 600) — "
            "it must not live in config or in code."
        )

    query = f"{url}/rest/v1/{table}?select=*&order={ts_col}.asc&limit={page}"
    if since_ts:
        query += f"&{ts_col}=gt.{urllib.parse.quote(str(since_ts))}"

    req = urllib.request.Request(query, headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    if not isinstance(payload, list):
        raise ValueError(f"unexpected Supabase response: {type(payload).__name__}")
    if not payload:
        return [], []

    # Union of keys across rows, so a column that is null in the first record
    # is not lost. Order follows QUESTION_MAP where possible, so downstream
    # column positions stay predictable.
    seen = set()
    for rec in payload:
        seen.update(rec.keys())
    normalized = {}
    for k in seen:
        nk = _normalize_source_headers([k])[0]
        normalized.setdefault(nk, k)

    ordered = [c for c in QUESTION_MAP.values() if c in normalized]
    ordered += sorted(c for c in normalized if c not in set(ordered))

    rows = []
    for rec in payload:
        row = []
        for col in ordered:
            v = rec.get(normalized[col])
            if v is None:
                row.append("")
            elif isinstance(v, (dict, list)):
                row.append(json.dumps(v, ensure_ascii=False))
            elif isinstance(v, bool):
                row.append("Yes" if v else "No")
            else:
                row.append(str(v))
        rows.append(row)

    return ordered, rows


def fetch_source_rows(sheets_api, sheet_id, config, since_ts=None):
    """
    Read new submissions from whichever source is configured.

    Returns (headers, rows, source_name). Falls back to Sheets when Supabase
    is configured but unreachable, and says so loudly — a silent fallback
    would mean scoring yesterday's data while believing it was today's.
    """
    ing = (config or {}).get("ingest", {})
    source = (ing.get("source") or "sheets").lower()

    if source == "supabase":
        try:
            headers, rows = fetch_supabase_rows(ing.get("supabase", {}), since_ts)
            print(f"  Source: Supabase — {len(rows)} new rows")
            return headers, rows, "supabase"
        except Exception as e:
            if not ing.get("fallback_to_sheets", True):
                raise
            print(f"  🔴 Supabase read FAILED: {e}")
            print(f"  🔴 Falling back to Google Sheets (plan B). The data may be stale.")
            send_slack_notification(
                f"Supabase ingest failed, fell back to Sheets: {e}", is_error=True
            )

    all_data = read_sheet(sheets_api, sheet_id, TAB_FORM)
    if not all_data:
        return [], [], "sheets"
    print(f"  Source: Google Sheets — {len(all_data) - 1} rows in tab")
    return _normalize_source_headers(all_data[0]), all_data[1:], "sheets"


def get_existing_app_timestamps(sheets_api, spreadsheet_id):
    """
    App_ID -> Timestamp for everything already in the Cleaned tab.

    Lets resolve_app_id distinguish a replay of the same submission from an ID
    reused across two different ones. Returns {} on any failure, which makes
    reuse look like reuse — the safe direction, since that path flags and
    processes rather than skipping.
    """
    try:
        data = read_sheet(sheets_api, spreadsheet_id, TAB_CLEAN)
        if not data or len(data) < 2:
            return {}
        headers = data[0]
        id_col = ts_col = None
        for i, h in enumerate(headers):
            low = str(h or "").lower()
            if id_col is None and "app_id" in low:
                id_col = i
            if ts_col is None and low.startswith("timestamp"):
                ts_col = i
        if id_col is None:
            return {}
        out = {}
        for row in data[1:]:
            if id_col >= len(row):
                continue
            aid = (row[id_col] or "").strip()
            if not aid:
                continue
            ts = (row[ts_col] or "").strip() if ts_col is not None and ts_col < len(row) else ""
            out[aid] = ts
        return out
    except Exception as e:
        print(f"  ⚠️  could not read existing timestamps: {e}")
        return {}


def generate_app_id(seq):
    return f"APP-2027-{seq:04d}"


def resolve_app_id(row, col_map, existing_ids, existing_timestamps, seq, row_timestamp):
    """
    Use the application ID the form already showed the applicant, when it sends
    one. Falls back to generating one.

    Requested by Salomé 2026-11-11: the confirmation email gives the applicant
    an ID, and if EVA mints a different one there are two numbers for one
    application — which breaks support conversations, the per-applicant Drive
    folder name, and the Proposal link in the consolidated sheet.

    Returns (app_id, source, flags).

    ── The risk this closes at the same time ────────────────────────────────
    Idempotency skips any ID already in the Cleaned tab. With generated IDs
    that is safe, because they are monotonic and never repeat. With an ID from
    outside, a repeat can mean two different things:

      * the same submission arriving twice — a retry, a replay — where
        skipping is exactly right; or
      * two genuinely different submissions sharing an ID, from a form bug or
        a reset counter, where skipping silently drops a real application.

    Those are distinguished by the timestamp. Same ID and same timestamp is a
    replay: skip. Same ID, different timestamp is ID reuse: process it under a
    suffixed ID and flag it, because dropping an application without telling
    anyone is the worse failure.
    """
    flags = []

    raw = ""
    for name in INBOUND_APP_ID_COLUMNS:
        idx = col_map.get(name)
        if idx is not None and idx < len(row):
            raw = (row[idx] or "").strip()
            if raw:
                break

    if not raw:
        return generate_app_id(seq), "generated", flags

    if not APP_ID_PATTERN.match(raw):
        # Untrusted input: this value ends up in a Drive folder name and as a
        # sheet key, so a malformed one is replaced rather than passed through.
        flags.append(f"malformed_inbound_app_id:{raw[:40]}")
        return generate_app_id(seq), "generated_after_malformed", flags

    if raw in existing_ids:
        prior_ts = existing_timestamps.get(raw)
        if prior_ts and row_timestamp and prior_ts == row_timestamp:
            # Same submission seen again — the caller's idempotency check will
            # skip it, which is correct.
            return raw, "form_replay", flags
        flags.append(f"reused_app_id:{raw}_already_used_for_{prior_ts or 'unknown'}")
        return f"{raw}-R{seq:02d}", "form_reused_suffixed", flags

    return raw, "form", flags

# Google Sheets epoch for serial number conversion
SHEETS_EPOCH = datetime(1899, 12, 30, tzinfo=timezone.utc)

def normalize_timestamp(ts):
    """
    Convert any timestamp format to ISO 8601: YYYY-MM-DDTHH:MM:SSZ
    
    Handles: ISO 8601, Google Sheets serial numbers, US format (M/D/YYYY),
    WordPress format ("Month D, YYYY at H:MM AM/PM"), SQL-like, date-only.
    
    Returns: (iso_string, warning_or_None)
    """
    if not ts or str(ts).strip() == "":
        return "", "empty timestamp"
    
    ts = str(ts).strip()
    
    # 1. Already ISO 8601
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), None
        except:
            return ts + ("Z" if not ts.endswith("Z") else ""), None
    
    # 2. Google Sheets serial number (float days since 1899-12-30)
    try:
        serial = float(ts)
        if 1 < serial < 60000:
            dt = SHEETS_EPOCH + timedelta(days=serial)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
    except (ValueError, TypeError):
        pass
    
    # 3. US format: M/D/YYYY H:M:S or M/D/YYYY
    us_patterns = [
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})$", 6),
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})$", 5),
        (r"^(\d{1,2})/(\d{1,2})/(\d{4})$", 3),
    ]
    for pat, ngroups in us_patterns:
        m = re.match(pat, ts)
        if m:
            g = m.groups()
            month, day, year = int(g[0]), int(g[1]), int(g[2])
            hour = int(g[3]) if ngroups > 3 else 0
            minute = int(g[4]) if ngroups > 4 else 0
            second = int(g[5]) if ngroups > 5 else 0
            try:
                dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
            except ValueError:
                break
    
    # 4. WordPress format: "Month D, YYYY at H:MM AM/PM"
    months_map = {
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
        "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    wp_patterns = [
        r"^(\w+)\s+(\d{1,2}),\s+(\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*(AM|PM)$",
        r"^(\w+)\s+(\d{1,2}),\s+(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})$",
        r"^(\w+)\s+(\d{1,2}),\s+(\d{4})$",
    ]
    for pat in wp_patterns:
        m = re.match(pat, ts, re.IGNORECASE)
        if m:
            g = m.groups()
            month = months_map.get(g[0].lower())
            if not month:
                break
            day, year = int(g[1]), int(g[2])
            if len(g) >= 6:
                hour = int(g[3])
                minute = int(g[4])
                second = int(g[5]) if len(g) >= 7 else 0
                if g[-1].upper() == "PM" and hour < 12:
                    hour += 12
                elif g[-1].upper() == "AM" and hour == 12:
                    hour = 0
            else:
                hour, minute, second = 0, 0, 0
            try:
                dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
                return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
            except ValueError:
                break
    
    # 5. Alternative common formats
    for pat in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y"]:
        try:
            dt = datetime.strptime(ts, pat).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), None
        except ValueError:
            continue
    
    # 6. Fallback
    return ts, f"unrecognized timestamp format: '{ts[:50]}'"



def normalize_text(text):
    """Normalize text for comparison: strip, lowercase, remove punctuation."""
    if not text:
        return ""
    text = str(text).strip().lower()
    text = text.replace(',', ' ').replace('.', ' ')
    text = ' '.join(text.split())  # collapse whitespace
    return text


def count_words(text):
    if not text:
        return 0
    return len(str(text).split())


def parse_number(value):
    """Try to parse a value as float. Return (number, is_valid)."""
    if value is None or value == "":
        return None, False
    try:
        # Remove currency symbols, commas, spaces
        cleaned = re.sub(r'[$,\s]', '', str(value))
        return float(cleaned), True
    except (ValueError, TypeError):
        return None, False


# Minimum words before a paragraph answer is flagged as nonsense.
# Frozen spec §4: [15], confirmed by Iván. v2 hardcoded 20.
MIN_PARAGRAPH_WORDS = 15

# Date formats accepted in E2 (start/end pair).
_DATE_FORMATS = [
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d",
    "%d %B %Y", "%B %d %Y", "%b %d %Y", "%d %b %Y", "%Y-%m",
]

_MONTH_WORDS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
    "noviembre|diciembre"
)


def _parse_one_date(token):
    """Parse a single date token. Returns a date or None."""
    token = token.strip().strip(',').strip()
    if not token:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            continue
    return None


def parse_date_pair(value):
    """
    v3: E2 holds a start and end date. Returns (start_iso, end_iso, months).

    Project duration is DERIVED here rather than collected, which is what the
    methodology's "more than one stage in <=12 months" check needs. The v2 code
    treated E2 as a numeric month count.

    Accepts "2027-01-15 to 2027-12-31", "15/01/2027 - 31/12/2027",
    "January 15 2027 to December 31 2027", and a JSON-ish pair.
    Returns (None, None, None) when it cannot parse two dates.
    """
    if not value:
        return None, None, None
    text = str(value).strip()

    # ISO dates first — least ambiguous
    iso = re.findall(r'\d{4}-\d{2}-\d{2}', text)
    candidates = list(iso)

    if len(candidates) < 2:
        numeric = re.findall(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b', text)
        candidates.extend(n for n in numeric if n not in candidates)

    if len(candidates) < 2:
        worded = re.findall(
            r'\b(?:' + _MONTH_WORDS + r')\s+\d{1,2},?\s+\d{4}\b'
            r'|\b\d{1,2}\s+(?:' + _MONTH_WORDS + r')\s+\d{4}\b',
            text, re.IGNORECASE,
        )
        candidates.extend(w for w in worded if w not in candidates)

    parsed = []
    for c in candidates:
        d = _parse_one_date(c)
        if d:
            parsed.append(d)
        if len(parsed) == 2:
            break

    if len(parsed) < 2:
        return None, None, None

    start, end = parsed[0], parsed[1]
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return start.isoformat(), end.isoformat(), months


def result_formula_parts(value):
    """
    v3: E7 is the primary-result sentence, validated against the methodology
    formula "By [date], [number or %] of [participants] will [result]."

    Returns (has_quantity, has_date). E7 is short text, not a paragraph — the
    v2 code word-counted it at 150 words, which the form spec contradicts.
    """
    if not value:
        return False, False
    text = str(value)

    has_quantity = bool(re.search(r'\d+\s*%|\b\d[\d,.]*\b', text))

    has_date = bool(
        re.search(r'\b(19|20)\d{2}\b', text)
        or re.search(r'\bQ[1-4]\b', text, re.IGNORECASE)
        or re.search(r'\b(?:' + _MONTH_WORDS + r')\b', text, re.IGNORECASE)
        or re.search(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', text)
    )
    return has_quantity, has_date


def has_time_markers_text(text):
    """True when text carries a recognizable time marker (year, quarter, month…)."""
    if not text:
        return False
    patterns = [
        r'\b(19|20)\d{2}\b',
        r'\bQ[1-4]\b',
        r'\bmonth\s*\d+', r'\bphase\s*\d+', r'\bweek\s*\d+',
        r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
        r'\b(?:' + _MONTH_WORDS + r')\b',
        r'\bwithin \d+', r'\bby \w+',
        r'\bfirst quarter\b|\bsecond quarter\b|\bthird quarter\b|\bfourth quarter\b',
    ]
    return any(re.search(p, str(text), re.IGNORECASE) for p in patterns)


def normalize_a2(value):
    """
    Map an A2 answer onto a canonical range label.

    The form's middle option is "1–3 years" with an EN DASH (U+2013). The v2
    config stored "1 to 3 years" and tested `"1-3" in a2` with a HYPHEN, so the
    match always failed and the Track Record points were never awarded.
    """
    if not value:
        return ""
    v = str(value).strip().lower().replace("–", "-").replace("—", "-")
    v = re.sub(r'\s+', ' ', v)
    if "less than 1" in v or v.startswith("<1") or "menos de 1" in v:
        return "Less than 1 year"
    if "more than 3" in v or "3+" in v or v.startswith(">3") or "mas de 3" in v or "más de 3" in v:
        return "More than 3 years"
    if "1-3" in v or "1 to 3" in v or "1 a 3" in v:
        return "1-3 years"
    return ""


def match_a2_range(value, accepted):
    """True when A2 falls in one of `accepted` (compared after normalization)."""
    norm = normalize_a2(value)
    if not norm:
        return False
    for a in accepted:
        if normalize_a2(a) == norm:
            return True
    return False


def _count_signals(text, signals):
    """
    Return (hit_count, matched_terms) for signal terms present in text.

    Overlapping terms are collapsed: if a matched term is a substring of
    another matched term, only the longer one counts.

    Without that, one occurrence of a phrase scores once per nested term in
    the same vocabulary. "financial inclusion" also matched "inclusi" and
    counted 2; "remittances" also matched "remittance"; "classes" also
    matched "class"; "remesas" also matched "remesa". Since the pillar is
    chosen with max(scores) and stage ties resolve to the furthest-along
    stage, that inflation decided classifications — it flipped one real
    case from a
    Technology/Economic tie into Economic on a single phrase.

    The dedup is on the term list, not on occurrences: a vocabulary term that
    genuinely appears three times still counts once, which is the existing
    behaviour and the intended one (breadth of signal, not repetition).

    Found by B1 over the real grantee registry, 2026-11-11.
    """
    low = (text or "").lower()
    hits = [s for s in signals if s in low]
    maximal = [s for s in hits
               if not any(s != other and s in other for other in hits)]
    return len(maximal), maximal


def infer_pillar(fields):
    """
    Infer the pillars from narrative content. A project may have more than one.

    E4 (declared pillar) was removed 2026-11-09. The methodology keeps pillars
    as a comparison tag against 2026, so Eva derives them from E1 + E4
    (economic barrier) + E8 (how participants apply it + partner).

    Returns (primary_or_None, justification, per_pillar_scores, all_pillars).

    ── Por qué devuelve varios (Iván, 2026-11-11) ──
    Un proyecto puede pertenecer a más de un pilar, y esa información no debe
    perderse. El registro ya lo demuestra: 10 de los 56 grantees están
    etiquetados "All three" por una persona, y la versión anterior de esta
    función no podía reproducir esa etiqueta — devolvía uno y descartaba el
    resto en silencio.

    El PRIMARIO se sigue devolviendo primero y sigue siendo el argmax, así que
    todo lo que agrupa o cuenta por pilar sigue funcionando igual. Lo que se
    agrega es la lista completa; nada se reemplaza.

    ── Cuándo cuenta un pilar secundario ──
    No basta con tener una coincidencia: los vocabularios se traslapan y
    "≥1 señal" etiquetaría casi todo como multi-pilar, que es tan poco
    informativo como forzar uno solo. Un secundario entra si alcanza
    max(2, mitad del primario): tiene que mostrar un patrón, no una palabra
    suelta.

    Contra los datos reales del registro eso da, por ejemplo:
      · caso real A  Ec 5, Ed 1, T 1  -> solo Economic ("mentor" y "system"
                                         son incidentales, no un segundo eje)
      · caso real B  Ec 2, T 2, Ed 1  -> Economic + Technology (es una
                                         plataforma de financiamiento: los dos
                                         ejes son reales)
    """
    corpus = " ".join([
        fields.get("E1", "") or "",
        fields.get("E4", "") or "",
        fields.get("E8", "") or "",
    ])

    scores = {}
    matched = {}
    for pillar, signals in PILLAR_SIGNALS.items():
        n, hits = _count_signals(corpus, signals)
        scores[pillar] = n
        matched[pillar] = hits

    best = max(scores, key=lambda p: scores[p]) if scores else None
    if not best or scores[best] == 0:
        return None, "No pillar signals found in E1/E4/E8", scores, []

    # Un secundario necesita patrón, no una palabra suelta. El primario
    # siempre entra, incluso si su propio puntaje no alcanza el piso.
    floor = max(2, (scores[best] + 1) // 2)
    all_pillars = [p for p, n in scores.items() if n >= floor]
    if best not in all_pillars:
        all_pillars.append(best)
    # Orden por fuerza de señal, el primario primero.
    all_pillars.sort(key=lambda p: (p != best, -scores[p], p))

    def _terms(p):
        return ", ".join(matched[p][:4])

    multi_note = ""
    if len(all_pillars) > 1:
        detail = "; ".join(
            f"{p} {scores[p]} ({_terms(p)})" for p in all_pillars)
        multi_note = (f" MULTI-PILLAR ({len(all_pillars)}): {detail}. "
                      f"Primary reported as {best}.")

    # A tie is reported rather than silently resolved — a reviewer decides.
    tied = [p for p, n in scores.items() if n == scores[best]]
    if len(tied) > 1:
        return (
            best,
            f"Tie between {' and '.join(tied)} ({scores[best]} signals each) — "
            f"reported as {best}; reviewer should confirm. "
            f"Terms: {_terms(best)}.{multi_note}",
            scores,
            all_pillars,
        )

    # ── Margen delgado = baja confianza, dicho en voz alta.
    #
    #    max(scores) con 1 contra 0 devolvía un pilar con la misma seguridad
    #    que uno con 9 contra 1. No son lo mismo: una sola palabra que
    #    aparece una vez decide igual que un patrón. El pilar asignado no
    #    cambia — esa elección es de Marisa, no del código — pero la
    #    justificación ahora dice cuándo apoyarse en ella es riesgoso.
    #
    #    Visto en BTC Media: "financial education ... economic independence"
    #    daba Education 1 / Economic 0 y se reportaba sin reserva. 2026-11-11.
    runner_up = max((n for p, n in scores.items() if p != best), default=0)
    margin = scores[best] - runner_up
    if scores[best] <= 1 or margin <= 1:
        return (
            best,
            f"LOW CONFIDENCE — {best} by {scores[best]} signal(s) vs "
            f"{runner_up} for the next pillar (margin {margin}). "
            f"Terms: {_terms(best)}. "
            f"Reviewer should confirm the pillar.{multi_note}",
            scores,
            all_pillars,
        )

    return (
        best,
        f"{best}: {scores[best]} signals in E1/E4/E8 ({_terms(best)})"
        f"{multi_note}",
        scores,
        all_pillars,
    )


def infer_stage(fields):
    """
    Infer the community's position on the resilience path.

    E5 (stage today) and E6 (target stage) were removed 2026-11-09 because a
    self-declared stage is gameable. Eva reads the evidence instead, across
    E1 + E4 + E8 + E9 + F1 + F2 + F3.

    Later stages win ties: a project describing merchants accepting Bitcoin
    will also mention workshops, and the furthest-along evidence is the
    better description of where the community actually is.

    Returns (stage_or_None, justification, per_stage_scores).
    """
    corpus = " ".join([
        fields.get("E1", "") or "",
        fields.get("E4", "") or "",
        fields.get("E8", "") or "",
        fields.get("E9", "") or "",
        fields.get("F1", "") or "",
        fields.get("F2", "") or "",
        fields.get("F3", "") or "",
    ])

    scores = {}
    matched = {}
    for stage, signals in STAGE_SIGNALS.items():
        n, hits = _count_signals(corpus, signals)
        scores[stage] = n
        matched[stage] = hits

    present = [s for s in VALID_STAGES if scores.get(s, 0) > 0]
    if not present:
        return None, "No resilience-path signals found in E1/E4/E8/E9/F1-F3", scores

    top = max(scores[s] for s in present)
    # VALID_STAGES is ordered Awareness → Resilience; take the furthest along
    # among those tied at the top.
    best = [s for s in VALID_STAGES if scores.get(s, 0) == top][-1]

    detail = ", ".join(f"{s}={scores[s]}" for s in VALID_STAGES)
    return (
        best,
        f"{best} ({scores[best]} signals: {', '.join(matched[best][:5])}). "
        f"Signal counts — {detail}",
        scores,
    )


def has_consecutive_consonants(text, min_count=8):
    """Check for random characters: 8+ consecutive consonants without vowels."""
    if not text:
        return False
    vowels = set('aeiouAEIOU')
    consecutive = 0
    for char in str(text):
        if char.isalpha() and char not in vowels:
            consecutive += 1
            if consecutive >= min_count:
                return True
        else:
            consecutive = 0
    return False


def has_repeated_text(text, min_repeats=3):
    """Check if same string segment is repeated 3+ times."""
    if not text:
        return False
    text = str(text).lower()
    words = text.split()
    if len(words) < 6:
        return False
    # Check for repeated phrases (3+ words repeated 3+ times)
    for i in range(len(words) - 2):
        phrase = ' '.join(words[i:i+3])
        if text.count(phrase) >= min_repeats:
            return True
    return False


# ─── OFAC SDN Check ────────────────────────────────────────────────────────

def download_ofac_sdn():
    """Download OFAC SDN list and cache locally.
    Returns tuple: (entries list, metadata dict).
    entries = [(name, country), ...]
    metadata = {source, download_date, entry_count, cache_path, cache_age_days}
    """
    metadata = {
        "source": OFAC_SDN_URL,
        "download_date": "",
        "entry_count": 0,
        "cache_path": str(OFAC_CACHE_PATH),
        "cache_age_days": 0,
        "cache_fresh": False
    }

    # Check cache freshness
    if OFAC_CACHE_PATH.exists():
        cache_mtime = OFAC_CACHE_PATH.stat().st_mtime
        age = time.time() - cache_mtime
        metadata["cache_age_days"] = round(age / 86400, 1)

        if age < OFAC_CACHE_TTL:
            # Use cached file
            metadata["cache_fresh"] = True
            metadata["download_date"] = datetime.fromtimestamp(cache_mtime).strftime("%Y-%m-%d")
            with open(OFAC_CACHE_PATH, 'r', encoding='utf-8', errors='replace') as f:
                reader = csv.reader(f)
                entries = [(row[1].strip(), row[3].strip() if len(row) > 3 else "")
                           for row in reader if len(row) > 1 and row[1] and row[1] != "-0- "]
            metadata["entry_count"] = len(entries)
            print(f"  [OFAC] Using cached SDN list ({len(entries)} entries, {metadata['cache_age_days']}d old, downloaded {metadata['download_date']})")
            return entries, metadata

    # Download fresh copy
    print("  [OFAC] Downloading SDN list...")
    download_dt = datetime.now()
    req = urllib.request.Request(OFAC_SDN_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()

    # Save to cache
    OFAC_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OFAC_CACHE_PATH, 'wb') as f:
        f.write(data)

    # Parse and return
    reader = csv.reader(io.StringIO(data.decode('utf-8', errors='replace')))
    entries = [(row[1].strip(), row[3].strip() if len(row) > 3 else "")
               for row in reader if len(row) > 1 and row[1] and row[1] != "-0- "]

    metadata["download_date"] = download_dt.strftime("%Y-%m-%d")
    metadata["entry_count"] = len(entries)
    metadata["cache_fresh"] = True
    metadata["cache_age_days"] = 0
    print(f"  [OFAC] Downloaded {len(entries)} SDN entries (fresh, {metadata['download_date']})")
    return entries, metadata


def _ofac_norm(text):
    """
    Lower-case, accents removed, punctuation to spaces. The SDN list is ASCII
    ("FUNDACION ...", "RAMIREZ NUNEZ, Jose"); until 2026-11-13 the comparison
    kept accents, so "Fundación ..." could never match "FUNDACION ...".
    """
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def check_ofac(name, sdn_entries):
    """Check a name against OFAC SDN list. Returns (match: bool, details: str)."""
    if not name or not sdn_entries:
        return False, ""

    norm_name = _ofac_norm(name)
    if not norm_name or len(norm_name) < 3:
        return False, ""
    name_tokens = set(norm_name.split())

    for sdn_name, sdn_country in sdn_entries:
        norm_sdn = _ofac_norm(sdn_name)
        if not norm_sdn:
            continue

        # Same words in another order. People are listed "LAST, First", so
        # "Jose Ramirez Nunez" against "RAMIREZ NUNEZ, Jose" never matched by
        # string. Every word of a 2+-word SDN entry present in the name is a
        # match; a false positive costs a manual review, a miss costs more.
        sdn_tokens = set(norm_sdn.split())
        if len(sdn_tokens) >= 2 and sdn_tokens <= name_tokens:
            return True, f"WORDS match: '{sdn_name}' ({sdn_country})"

        # Exact match
        if norm_name == norm_sdn:
            return True, f"EXACT match: '{sdn_name}' ({sdn_country})"

        # Substring match (only for names >= 5 chars to avoid false positives)
        if len(norm_name) >= 5 and len(norm_sdn) >= 5:
            if norm_name in norm_sdn or norm_sdn in norm_name:
                return True, f"SUBSTRING match: '{sdn_name}' ({sdn_country})"

    return False, ""


# ─── Document download + text extraction for name/address matching ──────────

def download_drive_file(drive_api, file_id_or_url):
    """Download a file from Google Drive by file ID or URL. Returns (bytes, mime_type) or (None, None)."""
    if not file_id_or_url:
        return None, None

    # Extract file ID from URL if needed
    file_id = file_id_or_url
    if file_id.startswith("http"):
        # https://drive.google.com/file/d/FILE_ID/view or similar
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', file_id)
        if match:
            file_id = match.group(1)
        else:
            # Try open?id= format
            match = re.search(r'[?&]id=([a-zA-Z0-9-_]+)', file_id)
            if match:
                file_id = match.group(1)
            else:
                return None, None

    try:
        file_meta = drive_api.files().get(fileId=file_id, fields="mimeType,name").execute()
        mime_type = file_meta.get("mimeType", "")

        # Export Google Docs as PDF
        if mime_type == "application/vnd.google-apps.document":
            content = drive_api.files().export(fileId=file_id, mimeType="application/pdf").execute()
            return content, "application/pdf"

        # Download regular files
        content = drive_api.files().get_media(fileId=file_id).execute()
        return content, mime_type
    except Exception as e:
        print(f"  [DOC] Error downloading {file_id}: {type(e).__name__}: {str(e)[:100]}")
        return None, None


def extract_text_from_pdf(pdf_bytes):
    """Extract text from PDF bytes using 3-tier extraction:
    Tier 1: PyMuPDF (digital-native PDFs with text layer)
    Tier 2: pdftotext (poppler-utils, handles some edge cases)
    Tier 3: tesseract OCR (scanned PDFs / image-only PDFs)
    Falls back to regex if all tools fail.
    """
    if not pdf_bytes:
        return ""

    # Tier 1: PyMuPDF (best for digital-native PDFs)
    try:
        import pymupdf
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        try:
            doc = pymupdf.open(tmp_path)
            text_parts = []
            for page in doc:
                text_parts.append(page.get_text())
            doc.close()
            extracted = " ".join(text_parts).strip()
            if extracted and len(extracted) > 20:
                return extracted
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f"  [DOC] PyMuPDF extraction failed: {type(e).__name__}: {str(e)[:80]}")

    # Tier 2: pdftotext (poppler-utils, good fallback)
    try:
        import subprocess, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        try:
            result = subprocess.run(
                ["pdftotext", "-q", tmp_path, "-"],
                capture_output=True, timeout=15
            )
            extracted = result.stdout.decode('utf-8', errors='replace').strip()
            if extracted and len(extracted) > 20:
                return extracted
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f"  [DOC] pdftotext extraction failed: {type(e).__name__}: {str(e)[:80]}")

    # Tier 3: tesseract OCR (for scanned PDFs / image-only docs)
    try:
        import subprocess, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name
        try:
            # Convert PDF pages to images using pdftoppm, then OCR each
            with tempfile.TemporaryDirectory() as tmpdir:
                # pdftoppm converts PDF to PNG images
                subprocess.run(
                    ["pdftoppm", "-png", "-r", "200", tmp_path, f"{tmpdir}/page"],
                    capture_output=True, timeout=30
                )
                # OCR each page image
                text_parts = []
                for img_file in sorted(os.listdir(tmpdir)):
                    if img_file.endswith('.png'):
                        img_path = os.path.join(tmpdir, img_file)
                        result = subprocess.run(
                            ["tesseract", img_path, "-", "--psm", "6"],
                            capture_output=True, timeout=30
                        )
                        text_parts.append(result.stdout.decode('utf-8', errors='replace'))
                extracted = " ".join(text_parts).strip()
                if extracted and len(extracted) > 10:
                    print(f"  [DOC] OCR extracted {len(extracted)} chars from scanned PDF")
                    return extracted
        finally:
            os.unlink(tmp_path)
    except Exception as e:
        print(f"  [DOC] tesseract OCR failed: {type(e).__name__}: {str(e)[:80]}")

    # Last resort: regex-based extraction (handles very simple PDFs)
    try:
        text = pdf_bytes.decode('latin-1', errors='replace')
        texts = re.findall(r'\(([^)]+)\)\s*Tj', text)
        array_texts = re.findall(r'\[([^]]+)\]\s*TJ', text)
        for arr in array_texts:
            parts = re.findall(r'\(([^)]*)\)', arr)
            texts.append(''.join(parts))
        return ' '.join(texts)
    except Exception:
        return ""


def extract_text_from_doc(doc_bytes, mime_type):
    """Extract text from document bytes based on mime type.
    Handles PDF (3-tier), images (OCR), plain text, and HTML.
    """
    if not doc_bytes:
        return ""

    if mime_type == "application/pdf":
        return extract_text_from_pdf(doc_bytes)

    # Images (JPG, PNG) — OCR with tesseract
    if mime_type in ("image/jpeg", "image/jpg", "image/png", "image/gif"):
        try:
            import subprocess, tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as tmp:
                tmp.write(doc_bytes)
                tmp_path = tmp.name
            try:
                result = subprocess.run(
                    ["tesseract", tmp_path, "-", "--psm", "6"],
                    capture_output=True, timeout=30
                )
                extracted = result.stdout.decode('utf-8', errors='replace').strip()
                if extracted:
                    print(f"  [DOC] OCR extracted {len(extracted)} chars from image")
                return extracted
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            print(f"  [DOC] Image OCR failed: {type(e).__name__}: {str(e)[:80]}")
            return ""

    # Plain text or HTML
    if mime_type in ("text/plain", "text/html", "application/octet-stream"):
        try:
            text = doc_bytes.decode('utf-8', errors='replace')
            if mime_type == "text/html" or "<html" in text.lower():
                text = re.sub(r'<[^>]+>', ' ', text)
            return text
        except Exception:
            return ""

    # For other formats, try utf-8 decode as fallback
    try:
        return doc_bytes.decode('utf-8', errors='replace')
    except Exception:
        return ""


def check_name_in_doc(doc_text, legal_name):
    """Check if legal name appears in document text. Returns (match: bool, details: str)."""
    if not doc_text or not legal_name:
        return False, "no data"

    norm_legal = normalize_text(legal_name)
    norm_doc = normalize_text(doc_text)

    if not norm_legal or len(norm_legal) < 3:
        return False, "name too short"

    if norm_legal in norm_doc:
        return True, f"'{legal_name}' found in document"

    # Check if key tokens of legal name appear in doc
    # (handles cases where doc has slightly different formatting)
    tokens = [t for t in norm_legal.split() if len(t) >= 4]
    if len(tokens) >= 2:
        found_tokens = sum(1 for t in tokens if t in norm_doc)
        if found_tokens >= len(tokens) * 0.7:  # 70% of significant tokens match
            return True, f"Partial match: {found_tokens}/{len(tokens)} tokens of '{legal_name}'"

    return False, f"'{legal_name}' NOT found in document"


def check_address_in_doc(doc_text, address):
    """Check if address appears in document text. Returns (match: bool, details: str)."""
    if not doc_text or not address:
        return False, "no data"

    norm_addr = normalize_text(address)
    norm_doc = normalize_text(doc_text)

    if not norm_addr or len(norm_addr) < 5:
        return False, "address too short"

    if norm_addr in norm_doc:
        return True, f"Address found in document"

    # Check if key components of address appear in doc
    # (street number + street name, city, etc.)
    addr_tokens = [t for t in norm_addr.split() if len(t) >= 3 and not t.isdigit()]
    if len(addr_tokens) >= 2:
        found = sum(1 for t in addr_tokens if t in norm_doc)
        if found >= len(addr_tokens) * 0.6:  # 60% of non-numeric address tokens
            return True, f"Partial address match: {found}/{len(addr_tokens)} tokens"

    return False, "Address NOT found in document"


# ─── Step 1: INGEST + GRANTEE MATCHING ─────────────────────────────────────

def step_ingest(sheets_api, drive_api, config, scorecard_cfg, run_id, trigger_type="manual", triggered_by="eva"):
    """
    Read new form responses from the Form Responses tab.
    For each application:
      - Match to existing grantee registry (by normalized legal name + country)
      - If matched: reuse existing Grantee_ID, mark as renewal
      - If new: assign new Grantee_ID, create folder in Grant Application 2027/
      - Cross-reference Seguimiento 2027 pipeline data
    """
    start_time = time.time()
    sheet_id = config['active']['intake_sheet_id']
    wm = load_watermark(config['active_env'])
    wm_before = wm['last_timestamp']

    # Load grantee registry and seguimiento data
    registry = load_grantee_registry()
    seguimiento = load_seguimiento_2027()
    listas = load_tracker_listas()

    # Build seguimiento lookup by normalized org name
    seg_by_name = {}
    for s in seguimiento:
        key = norm_org_name(s.get("org_name", ""))
        if key:
            seg_by_name[key] = s

    folder_2027_id = applicant_folder_root(config)
    supabase_cfg = (config.get("ingest") or {}).get("supabase", {})
    question_labels = load_question_labels()

    print(f"[Step 1: INGEST] Reading from sheet {sheet_id}")
    print(f"  Watermark before: {wm_before}")
    print(f"  Grantee registry: {len(registry)} existing grantees")
    print(f"  Seguimiento 2027: {len(seguimiento)} orgs in pipeline")

    # Read from whichever source is configured — Supabase primary, Sheets plan B
    src_headers, src_rows, src_name = fetch_source_rows(
        sheets_api, sheet_id, config, since_ts=wm_before
    )
    all_data = ([src_headers] + src_rows) if src_headers else []
    if len(all_data) < 2:
        print("  No data found (headers only)")
        log_result = {
            "step": 1, "step_name": "INGEST", "status": "success",
            "apps_in": 0, "apps_out": 0, "errors": "", "warnings": "",
            "watermark_before": wm_before or "", "watermark_after": wm_before or "",
            "new_apps_count": 0, "duration_seconds": round(time.time() - start_time, 2),
            "trigger_type": trigger_type, "triggered_by": triggered_by
        }
        return {"run_id": run_id, "applications": [], "watermark": wm, "log": log_result}

    headers = all_data[0]
    data_rows = all_data[1:] if len(all_data) > 1 else []

    # Map column names to indices
    col_map = {name: idx for idx, name in enumerate(headers) if name}

    # Filter new rows based on watermark
    ts_col = col_map.get("Timestamp", 0)
    new_rows = []
    for row in data_rows:
        row_ts_raw = row[ts_col] if ts_col < len(row) else ""
        row_ts, ts_warn = normalize_timestamp(row_ts_raw)
        if ts_warn:
            print(f"  ⚠️  Row {len(new_rows)+1}: {ts_warn}")
        if wm_before is None or (row_ts and row_ts > wm_before):
            new_rows.append(row)

    print(f"  Total rows in sheet: {len(data_rows)}")
    print(f"  New rows since watermark: {len(new_rows)}")

    # Build application objects with grantee matching
    applications = []
    base_seq = wm['total_processed']
    new_grantees_created = 0
    renewals_matched = 0
    seg_matches = 0

    # P0 Idempotency: get App_IDs already processed in Cleaned tab
    existing_app_ids = get_existing_app_ids(sheets_api, sheet_id)
    # Needed to tell a replay from a reused ID — see resolve_app_id.
    existing_app_timestamps = get_existing_app_timestamps(sheets_api, sheet_id)
    if existing_app_ids:
        print(f"  Idempotency check: {len(existing_app_ids)} apps already in Cleaned tab")

    ingest_errors = []
    for i, row in enumerate(new_rows):
        # Adopt the ID the form showed the applicant, when it sends one.
        row_ts_for_id, _ = normalize_timestamp(
            row[col_map.get("Timestamp", 0)] if col_map.get("Timestamp", 0) < len(row) else ""
        )
        app_id, app_id_source, app_id_flags = resolve_app_id(
            row, col_map, existing_app_ids, existing_app_timestamps,
            base_seq + i + 1, row_ts_for_id,
        )
        for _f in app_id_flags:
            print(f"  ⚠️  {_f}")

        # P0 Idempotency: skip only a genuine replay — the same ID carrying the
        # same timestamp. An ID reused across two different submissions was
        # suffixed and flagged above, so it still gets processed rather than
        # silently dropped.
        if app_id in existing_app_ids and app_id_source != "form_reused_suffixed":
            print(f"  {app_id} | SKIP (already in Cleaned tab)")
            continue

        try:
            fields = {}
            for field_id, col_name in QUESTION_MAP.items():
                col_idx = col_map.get(col_name)
                if col_idx is not None and col_idx < len(row):
                    fields[field_id] = row[col_idx]
                else:
                    fields[field_id] = ""

            # ── Grantee matching ──
            legal_name = fields.get("B1", "").strip()
            country = fields.get("B2", "").strip()

            grantee_id, matched_name, is_renewal = match_grantee(legal_name, country, registry)

            folder_id, folder_error = None, None
            if not legal_name:
                # No legal name: no grantee, no folder. Until 2026-11-13 this
                # created "GR-2027-00N - " with an empty name; three of the four
                # 2027 registry entries left by the 2 Nov rehearsal were that.
                # step_flag raises missing_legal_name for a person to resolve.
                grantee_id, matched_name, is_renewal = "", "", False
                grantee_match_status = "NO_LEGAL_NAME"
                folder_error = "no legal name (B1)"
            elif grantee_id:
                # Existing grantee — renewal. Same GR-id, but this year's
                # documents go in a 2027 folder (one folder per year); the
                # folder of earlier years is never touched.
                renewals_matched += 1
                grantee_match_status = "MATCHED"
                folder_id, folder_error = ensure_grantee_folder(
                    drive_api, grantee_id, matched_name or legal_name, folder_2027_id)
                for g in registry:
                    if g.get("grantee_id") == grantee_id and folder_id:
                        g["folder_2027"] = folder_id   # folder_link keeps its old value
                        break
            else:
                # New grantee — assign ID and create folder
                grantee_id = generate_grantee_id(2027, registry)
                grantee_match_status = "NEW"
                folder_id, folder_error = ensure_grantee_folder(
                    drive_api, grantee_id, legal_name, folder_2027_id)

                # Add to registry
                new_grantee = {
                    "grantee_id": grantee_id,
                    "legal_name": legal_name,
                    "country": country,
                    "first_year": 2027,
                    "prior_apps_count": 0,
                    "total_awarded": 0,
                    # Was fields["E4"], which under v3 is the economic barrier,
                    # not a pillar. The pillar is inferred later (step 3) and
                    # confirmed by the program team; it is not known here.
                    "pillar": "",
                    "status": "New",
                    "folder_link": folder_id or "",
                    "folder_2027": folder_id or "",
                }
                registry.append(new_grantee)
                new_grantees_created += 1

                # Append to Grantee Registry tab
                add_grantee_to_registry_tab(sheets_api, sheet_id, new_grantee)

            # ── Cross-reference Seguimiento 2027 ──
            seg_data = None
            seg_key = norm_org_name(legal_name)
            if seg_key in seg_by_name:
                seg_data = seg_by_name[seg_key]
                seg_matches += 1
            else:
                # Try partial match
                for sk, sv in seg_by_name.items():
                    if seg_key and sk and (seg_key in sk or sk in seg_key):
                        seg_data = sv
                        seg_matches += 1
                        break

            # Look up registry data for matched grantee
            grantee_registry_data = {}
            if grantee_match_status == "MATCHED":
                for g in registry:
                    if g.get("grantee_id") == grantee_id:
                        grantee_registry_data = g
                        break

            # Attach grantee context to application
            app = {
                "app_id": app_id,
                "timestamp": normalize_timestamp(fields.get("timestamp", ""))[0],
                "timestamp_raw": fields.get("timestamp", ""),
                "fields": fields,
                "row_index": wm['last_row'] + i + 2,
                "grantee_id": grantee_id,
                "grantee_match_status": grantee_match_status,
                "grantee_matched_name": matched_name or legal_name,
                "is_renewal": is_renewal,
                "grantee_registry_data": grantee_registry_data,
                "seg_2027_data": seg_data,
                "seg_2027_estatus": seg_data.get("estatus", "") if seg_data else "",
                "seg_2027_tipo": seg_data.get("tipo", "") if seg_data else "",
                "seg_2027_owner": seg_data.get("owner", "") if seg_data else "",
                "drive_folder_id": folder_id or "",
            }

            # ── Documents: every uploaded file and a copy of the application ──
            if folder_id:
                docs = store_application_documents(
                    drive_api, folder_id, app_id, fields, supabase_cfg, question_labels)
            else:
                docs = {"stored": [], "existing": [], "copy_url": "",
                        "errors": [folder_error or "no folder"]}
            app["documents"] = docs
            if docs["errors"]:
                print(f"  ⚠️  {app_id} documents: {'; '.join(docs['errors'])}")
            elif docs["stored"]:
                print(f"  {app_id} documents stored: {', '.join(docs['stored'])}")
            applications.append(app)

            print(f"  {app_id} | {grantee_id} | {grantee_match_status} | {legal_name[:30]}")

        except Exception as e:
            err_msg = f"{app_id}: {type(e).__name__}: {str(e)}"
            ingest_errors.append(err_msg)
            print(f"  {app_id} | ERROR: {err_msg}")
            # Continue to next application — one bad row shouldn't kill the batch

    # Update watermark
    new_wm_ts = wm_before
    if new_rows:
        last_row = new_rows[-1]
        last_ts_raw = last_row[ts_col] if ts_col < len(last_row) else ""
        new_wm_ts, _ = normalize_timestamp(last_ts_raw)
        wm['last_timestamp'] = new_wm_ts
        wm['last_row'] = wm['last_row'] + len(new_rows)
        wm['total_processed'] = wm['total_processed'] + len(new_rows)
        wm['last_run_id'] = run_id

    duration = round(time.time() - start_time, 2)
    print(f"  Applications ingested: {len(applications)}")
    print(f"  Renewals matched: {renewals_matched}")
    print(f"  New grantees created: {new_grantees_created}")
    print(f"  Seguimiento matches: {seg_matches}")
    print(f"  Duration: {duration}s")

    # Save run data
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "ingest.json", 'w') as f:
        json.dump({
            "run_id": run_id,
            "applications": applications,
            "watermark_before": wm_before,
            "grantee_registry_size": len(registry),
            "renewals_matched": renewals_matched,
            "new_grantees_created": new_grantees_created,
            "seg_matches": seg_matches
        }, f, indent=2, ensure_ascii=False)

    # Save updated registry
    with open(CONFIG_DIR / "grantee_registry.json", 'w') as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    warnings_list = []
    if new_grantees_created > 0:
        warnings_list.append(f"{new_grantees_created} new grantees created with folders")

    errors_str = "; ".join(ingest_errors) if ingest_errors else ""
    step_status = "success" if not ingest_errors else ("partial" if applications else "error")

    log_result = {
        "step": 1, "step_name": "INGEST", "status": step_status,
        "apps_in": len(new_rows), "apps_out": len(applications),
        "errors": errors_str, "warnings": "; ".join(warnings_list),
        "watermark_before": wm_before or "",
        "watermark_after": new_wm_ts or "",
        "new_apps_count": len(new_rows),
        "duration_seconds": duration,
        "trigger_type": trigger_type, "triggered_by": triggered_by
    }

    return {"run_id": run_id, "applications": applications, "watermark": wm, "log": log_result}


# ─── Step 2: CLEAN & VALIDATE ──────────────────────────────────────────────

def step_clean(applications, country_map, run_id):
    """Clean and validate form data."""
    start_time = time.time()
    print(f"[Step 2: CLEAN] Processing {len(applications)} applications")

    cleaned_apps = []

    clean_errors = []
    for app in applications:
      try:
        f = app['fields']
        # First thing every later step sees. Here rather than at ingest so a
        # run resumed with --step clean from a saved ingest.json gets it too.
        normalize_option_fields(f)
        cleaned = {
            "App_ID": app['app_id'],
            "Timestamp": app.get("timestamp", ""),  # Already normalized in step_ingest
        }
        flags = []
        notes = []

        # Trim whitespace on all text fields
        for key in f:
            if isinstance(f[key], str):
                f[key] = f[key].strip()

        # Normalize legal name (Title case)
        b1_clean = f.get("B1", "").strip()
        cleaned["B1_Legal_Name_Clean"] = b1_clean

        # Country normalization
        b2_raw = f.get("B2", "").strip()
        country_info = country_map.get(b2_raw)
        if country_info:
            cleaned["B2_Country_Normalized"] = country_info["canonical"]
            cleaned["B2_Country_ISO"] = country_info["iso"]
        elif b2_raw:
            cleaned["B2_Country_Normalized"] = b2_raw
            cleaned["B2_Country_ISO"] = ""
            flags.append(f"country_not_found:{b2_raw}")
        else:
            cleaned["B2_Country_Normalized"] = ""
            cleaned["B2_Country_ISO"] = ""

        # ── v3: B3 is the legal representative (was B4) ──
        cleaned["B3_Legal_Rep_Clean"] = f.get("B3", "").strip()

        # ── v3: B4 is the registered address (was B5) ──
        cleaned["B4_Address_Clean"] = f.get("B4", "").strip()

        # ── v3: B6 is the website (was B10). The v2 code URL-validated B6
        #    while B6 was "Year founded", so invalid_url fired on every app. ──
        b6 = f.get("B6", "").strip()
        cleaned["B6_Website_Valid"] = b6 if (not b6 or URL_REGEX.match(b6)) else ""
        if b6 and not URL_REGEX.match(b6):
            flags.append("invalid_url")

        # ── v3: D1 is a composite (name, title, email, phone). The primary
        #    email now lives inside it; D3 is the authorized signer, D4 the
        #    copy address. Extract and validate rather than assuming D3. ──
        d1_raw = f.get("D1", "").strip()
        d1_emails = re.findall(r'[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+', d1_raw)
        cleaned["D1_Contact_Raw"] = d1_raw
        cleaned["D1_Email_Extracted"] = d1_emails[0].lower() if d1_emails else ""
        cleaned["D1_Phone_Normalized"] = re.sub(r'\D', '', d1_raw)[-15:] if d1_raw else ""
        if d1_raw and not d1_emails:
            flags.append("nonsense_invalid_email:D1")

        d3_raw = f.get("D3", "").strip()
        d3_emails = re.findall(r'[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+', d3_raw)
        cleaned["D3_Signer_Raw"] = d3_raw
        cleaned["D3_Email_Extracted"] = d3_emails[0].lower() if d3_emails else ""
        if d3_raw and not d3_emails:
            flags.append("nonsense_invalid_email:D3")

        d4 = f.get("D4", "").strip().lower()
        cleaned["D4_Copy_Email_Valid"] = d4 if (not d4 or EMAIL_REGEX.match(d4)) else ""
        if d4 and not EMAIL_REGEX.match(d4):
            flags.append("nonsense_invalid_email:D4")

        # ── v3 numeric parsing: B5, E5, G1, G2.
        #    A4 and B9 are removed. B9 used to be the dependency denominator
        #    while actually being a prose paragraph, which guaranteed 0/10 on
        #    Sustainability; B5 is now a clean numeric annual budget. ──
        num_col_map = {
            "B5": "B5_Annual_Budget_Num",
            "E5": "E5_Participants_Num",
            "G1": "G1_Total_Budget_Num",
            "G2": "G2_Requested_Num",
        }
        for num_field in NUMERIC_FIELDS:
            raw_val = f.get(num_field, "")
            num_val, is_valid = parse_number(raw_val)
            cleaned[num_col_map.get(num_field, f"{num_field}_Num")] = num_val if num_val is not None else ""
            if raw_val and not is_valid:
                flags.append(f"nonsense_text_in_number:{num_field}")

        # ── v3: E2 is a start/end DATE PAIR. Duration is derived from it —
        #    the v2 code had E2 in NUMERIC_FIELDS as a month count. ──
        e2_start, e2_end, e2_months = parse_date_pair(f.get("E2", ""))
        cleaned["E2_Start_Date"] = e2_start or ""
        cleaned["E2_End_Date"] = e2_end or ""
        cleaned["E2_Duration_Months"] = e2_months if e2_months is not None else ""
        if f.get("E2", "").strip() and e2_months is None:
            flags.append("unparseable_dates:E2")
        elif e2_months is not None and e2_months <= 0:
            flags.append(f"invalid_date_range:E2:{e2_months}mo")

        # Word count validation — v3 PARAGRAPH_FIELDS (9 fields)
        for field_id, max_words in PARAGRAPH_FIELDS:
            text = f.get(field_id, "")
            wc = count_words(text)
            cleaned[f"{field_id}_Word_Count"] = wc
            cleaned[f"{field_id}_Word_Limit"] = max_words
            if wc > max_words:
                flags.append(f"word_count_exceeded:{field_id}:{wc}>{max_words}")
            if 0 < wc < MIN_PARAGRAPH_WORDS:
                flags.append(f"nonsense_short_answer:{field_id}")

        # ── v3: E7 is the primary-result SHORT TEXT, validated against the
        #    methodology formula rather than word-counted. ──
        e7_raw = f.get(RESULT_FORMULA_FIELD, "")
        has_qty, has_when = result_formula_parts(e7_raw)
        cleaned["E7_Has_Quantity"] = "YES" if has_qty else "NO"
        cleaned["E7_Has_Date"] = "YES" if has_when else "NO"
        cleaned["E7_Formula_Complete"] = "YES" if (has_qty and has_when) else "NO"
        if e7_raw.strip() and not (has_qty and has_when):
            missing = []
            if not has_qty:
                missing.append("number/%")
            if not has_when:
                missing.append("date")
            flags.append("result_formula_incomplete:" + "+".join(missing))

        # ── Budget validation.
        #    v3: G1 = TOTAL project budget, G2 = amount REQUESTED.
        #    G4 categories must sum to G2 (the request), and the valid
        #    relation is G2 <= G1. The v2 code had this inverted. ──
        g1_num = parse_number(f.get("G1", ""))[0]
        g2_num = parse_number(f.get("G2", ""))[0]
        g4_text = f.get("G4", "")
        g4_numbers = re.findall(r'[\d,]+\.?\d*', str(g4_text))
        g4_sum = sum(float(n.replace(',', '')) for n in g4_numbers) if g4_numbers else None
        cleaned["G4_Budget_Sum_Valid"] = ""
        cleaned["G4_Budget_Sum_Diff"] = ""
        if g4_sum is not None and g2_num is not None:
            diff = round(g4_sum - g2_num, 2)
            cleaned["G4_Budget_Sum_Valid"] = "YES" if abs(diff) < 1 else "NO"
            cleaned["G4_Budget_Sum_Diff"] = diff
            if abs(diff) >= 1:
                flags.append(f"budget_sum_mismatch:diff={diff}")
        else:
            cleaned["G4_Budget_Sum_Valid"] = "CANNOT_VERIFY"

        # Requested must not exceed the total project budget
        if g1_num is not None and g2_num is not None:
            cleaned["G2_Within_G1"] = "YES" if g2_num <= g1_num else "NO"
            if g2_num > g1_num:
                flags.append(f"request_exceeds_total:G2={g2_num}>G1={g1_num}")
        else:
            cleaned["G2_Within_G1"] = "CANNOT_VERIFY"

        # Cost per participant (G6, internal only) = G2 / E5
        e5_num = cleaned.get("E5_Participants_Num")
        if isinstance(g2_num, (int, float)) and isinstance(e5_num, (int, float)) and e5_num > 0:
            cleaned["G6_Cost_Per_Participant"] = round(g2_num / e5_num, 2)
        else:
            cleaned["G6_Cost_Per_Participant"] = ""

        # Dependency ratio = G2 / B5 (requested / last year's org budget)
        b5_num = cleaned.get("B5_Annual_Budget_Num")
        if isinstance(g2_num, (int, float)) and isinstance(b5_num, (int, float)) and b5_num > 0:
            cleaned["Dependency_Ratio"] = round(g2_num / b5_num, 4)
        else:
            cleaned["Dependency_Ratio"] = ""

        # Duplicate detection (within this batch)
        cleaned["Is_Duplicate_Name"] = ""
        cleaned["Is_Duplicate_Email"] = ""

        cleaned["Cleaning_Flags"] = ", ".join(flags) if flags else ""
        cleaned["Cleaning_Notes"] = "; ".join(notes) if notes else ""

        app['cleaned'] = cleaned
        app['cleaning_flags'] = flags
        cleaned_apps.append(app)
      except Exception as e:
        err_msg = f"{app.get('app_id', 'unknown')}: {type(e).__name__}: {str(e)}"
        clean_errors.append(err_msg)
        print(f"  ERROR in clean: {err_msg}")
        # Mark app with minimal cleaned data so it can still be tracked
        app['cleaned'] = {"App_ID": app.get("app_id", ""), "Timestamp": app.get("timestamp", ""), "Cleaning_Flags": f"clean_error: {str(e)[:100]}"}
        app['cleaning_flags'] = [f"clean_error:{type(e).__name__}"]
        cleaned_apps.append(app)

    # Check duplicates within batch
    name_counts = {}
    email_counts = {}
    for app in cleaned_apps:
        name = normalize_text(app['fields'].get("B1", ""))
        email = app['fields'].get("D3", "").strip().lower()
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1
        if email:
            email_counts[email] = email_counts.get(email, 0) + 1

    for app in cleaned_apps:
        name = normalize_text(app['fields'].get("B1", ""))
        email = app['fields'].get("D3", "").strip().lower()
        if name and name_counts[name] > 1:
            app['cleaned']["Is_Duplicate_Name"] = "YES"
            app['cleaning_flags'].append("duplicate_name")
        if email and email_counts[email] > 1:
            app['cleaned']["Is_Duplicate_Email"] = "YES"
            app['cleaning_flags'].append("duplicate_email")
        app['cleaned']["Cleaning_Flags"] = ", ".join(app['cleaning_flags']) if app['cleaning_flags'] else ""

    # Save cleaned data
    run_dir = RUNS_DIR / run_id
    with open(run_dir / "cleaned.json", 'w') as f:
        json.dump([app['cleaned'] for app in cleaned_apps], f, indent=2)

    # Save cleaning log
    with open(run_dir / "cleaning_log.md", 'w') as f:
        f.write(f"# Cleaning Log — Run {run_id}\n\n")
        f.write(f"Applications processed: {len(cleaned_apps)}\n\n")
        for app in cleaned_apps:
            if app['cleaning_flags']:
                f.write(f"## {app['app_id']} — {app['fields'].get('B1', 'Unknown')}\n")
                f.write(f"Flags: {', '.join(app['cleaning_flags'])}\n\n")

    duration = round(time.time() - start_time, 2)
    total_flags = sum(1 for a in cleaned_apps if a['cleaning_flags'])
    print(f"  Cleaned: {len(cleaned_apps)} applications")
    print(f"  With cleaning flags: {total_flags}")
    print(f"  Duration: {duration}s")

    errors_str = "; ".join(clean_errors) if clean_errors else ""
    step_status = "success" if not clean_errors else "partial"

    log_result = {
        "step": 2, "step_name": "CLEAN", "status": step_status,
        "apps_in": len(applications), "apps_out": len(cleaned_apps),
        "apps_flagged": total_flags,
        "errors": errors_str, "warnings": "",
        "duration_seconds": duration
    }

    return {"applications": cleaned_apps, "log": log_result}


# ─── Step 3: CLASSIFY ──────────────────────────────────────────────────────

def step_classify(applications, scorecard_cfg, country_map, region_map, run_id):
    """Classify applications: profile, pillar, region, renewal."""
    start_time = time.time()
    print(f"[Step 3: CLASSIFY] Processing {len(applications)} applications")

    a2_inicial = scorecard_cfg.get("a2_ranges", {}).get("inicial", ["Less than 1 year"])
    a2_establecida = scorecard_cfg.get("a2_ranges", {}).get("establecida", ["1 to 3 years", "More than 3 years"])

    # Build ISO → region mapping
    iso_to_region = {}
    for region, isos in region_map.get("regions", {}).items():
        for iso in isos:
            iso_to_region[iso] = region

    classified_apps = []

    classify_errors = []
    for app in applications:
      try:
        f = app['fields']
        classified = {
            "App_ID": app['app_id'],
            "Timestamp": app.get("timestamp", ""),  # Already normalized in step_ingest
        }

        # ── Profile determination ──
        #    A2 matching is normalized because the form's "1–3 years" uses an
        #    EN DASH (U+2013). The v2 config said "1 to 3 years" and never
        #    matched, so every applicant fell through to Establecida.
        a1 = f.get("A1", "").strip()
        a2 = f.get("A2", "").strip()

        if a1.lower().startswith("individual") or match_a2_range(a2, a2_inicial):
            profile = "Inicial"
        else:
            profile = "Establecida"
        classified["Profile"] = profile
        classified["A2_Normalized"] = normalize_a2(a2)

        classification_notes = []

        # ── Pillar: INFERRED (E4 no longer collected) ──
        #    Removed on Iván's call 2026-11-09: an applicant selects whatever
        #    sounds right, so the tag must rest on what they describe doing.
        pillar, pillar_just, pillar_scores, pillars_all = infer_pillar(f)
        # "Pillar" sigue siendo el primario y conserva su significado, para que
        # los conteos y agrupaciones por pilar que ya existen no cambien.
        # Pillars_All es aditivo: ahí vive la información que antes se perdía.
        classified["Pillar"] = pillar or ""
        classified["Pillars_All"] = ", ".join(pillars_all)
        classified["Pillar_Count"] = len(pillars_all)
        classified["Pillar_Source"] = "inferred"
        classified["Pillar_Justification"] = pillar_just
        if not pillar:
            classification_notes.append("pillar_not_inferable")
        if len(pillars_all) > 1:
            classification_notes.append(
                f"multi_pillar:{'+'.join(pillars_all)}")

        # ── Stage: INFERRED (E5/E6 no longer collected) ──
        #    There is no declared stage to compare against, so stage_suggested
        #    is an assertion. It therefore ships with a justification citing
        #    fields, so a reviewer can audit the inference in one line.
        stage, stage_just, stage_scores = infer_stage(f)
        classified["Stage_Suggested"] = stage or ""
        classified["Stage_Source"] = "inferred"
        classified["Stage_Justification"] = stage_just
        if not stage:
            classification_notes.append("stage_not_inferable")

        # ── Consistency rules (methodology Paso 3) ──
        #
        #  Restoring E12 (the declared TARGET stage) brings three of the
        #  methodology's five rules back. Two stay dead because the current
        #  stage is no longer declared, so there is nothing to compare the
        #  inference against.
        #
        #    1. F1 outside the expected set for the TARGET stage   ALIVE
        #    2. target more than one stage above the inferred
        #       current stage in a project of <=12 months          ALIVE
        #    3. renewal reached a stage below what was committed    ALIVE (J2)
        #    4. declared current stage below the target             dead
        #    5. inferred stage differs from the declared current    dead
        f1 = f.get("F1", "").strip()
        classified["F1_Main_Measure"] = f1

        target = f.get("E12", "").strip()
        classified["Stage_Target"] = target
        classified["Stage_Target_Source"] = "declared" if target else ""

        # Rule 1 — the methodology measures against the stage the grantee is
        # moving TOWARD, not the one they are in today. Before E12 came back
        # this had to fall back on the inferred current stage.
        basis = target if target in VALID_STAGES else stage
        basis_label = "target" if target in VALID_STAGES else "inferred current"
        expected = EXPECTED_MEASURES_BY_STAGE.get(basis, []) if basis else []
        if basis and f1:
            if f1 in expected:
                classified["Measure_Matches_Stage"] = "YES"
            else:
                classified["Measure_Matches_Stage"] = "NO"
                classification_notes.append(
                    f"measure_stage_mismatch:F1={f1},{basis_label}={basis},"
                    f"expected={'/'.join(expected)}"
                )
        else:
            classified["Measure_Matches_Stage"] = "CANNOT_VERIFY"
        classified["Expected_Measures"] = "/".join(expected)
        classified["Measure_Basis"] = basis_label if basis else ""

        # Rule 2 — an ambitious target. Needs the inferred current stage, the
        # declared target, and the duration derived from the E2 date pair.
        months = app.get('cleaned', {}).get("E2_Duration_Months")
        if stage in VALID_STAGES and target in VALID_STAGES:
            jump = VALID_STAGES.index(target) - VALID_STAGES.index(stage)
            classified["Stage_Jump"] = jump
            if jump < 0:
                classification_notes.append(
                    f"target_below_current:{target}<{stage}"
                )
            elif jump > 1 and isinstance(months, (int, float)) and 0 < months <= 12:
                classification_notes.append(
                    f"ambitious_target:{stage}->{target}_in_{int(months)}mo"
                )
        else:
            classified["Stage_Jump"] = ""

        # Rule 3 — a renewal that fell short of what it committed to in 2026.
        # J2 gives the stage reached; the 2026 commitment comes from the
        # registry, since the form cannot ask about a past agreement.
        j2 = f.get("J2", "").strip()
        classified["Stage_Reached_2026"] = j2
        # Derived locally on purpose: the route block that sets is_renewal runs
        # further down, so reading it here would pick up the PREVIOUS
        # application's value on every iteration after the first.
        _a3 = f.get("A3", "").strip()
        _is_renewal = _a3.lower().startswith("yes") and "2026" in _a3 \
            and "before" not in _a3.lower()
        if _is_renewal and j2 in VALID_STAGES:
            committed = (app.get("grantee_registry_data", {}) or {}).get("target_stage_2026", "")
            if committed in VALID_STAGES:
                if VALID_STAGES.index(j2) < VALID_STAGES.index(committed):
                    classification_notes.append(
                        f"renewal_below_commitment:reached_{j2}_committed_{committed}"
                    )
            else:
                classification_notes.append("renewal_commitment_2026_not_on_record")

        if f1 and f1 not in VALID_MEASURES:
            classification_notes.append(f"unrecognized_measure:{f1}")

        # Derived project duration (from E2 date pair) — feeds the
        # "more than one stage in <=12 months" judgement at review time.
        classified["Duration_Months"] = app.get('cleaned', {}).get("E2_Duration_Months", "")

        # ── Region: E3 + B2 (B11 "countries where you operate" was removed) ──
        country_iso = app.get('cleaned', {}).get("B2_Country_ISO", "")
        region = iso_to_region.get(country_iso, "Unknown")
        classified["Region"] = region
        classified["Country_ISO"] = country_iso
        classified["Project_Location"] = f.get("E3", "").strip()

        # ── Renewal ──
        #    v2 tested `a3.lower() == "yes"`, but the form's values are
        #    "No" / "Yes, in 2026" / "Yes, before 2026" — so it never matched
        #    and renewal scoring plus validation were dead code.
        a3 = f.get("A3", "").strip()
        a3_low = a3.lower()
        is_renewal = a3_low.startswith("yes") and "2026" in a3 and "before" not in a3_low
        is_prior_grantee = a3_low.startswith("yes")
        classified["Is_Renewal"] = "Yes" if is_renewal else "No"
        classified["Is_Prior_Grantee"] = "Yes" if is_prior_grantee else "No"
        classified["Route"] = "Renovación" if is_renewal else "Nuevo"
        classified["Classification_Notes"] = "; ".join(classification_notes)

        if is_renewal:
            # Use grantee matching from Step 1
            grantee_match_status = app.get("grantee_match_status", "")
            classified["Grantee_ID"] = app.get("grantee_id", "")
            classified["Grantee_Match_Status"] = grantee_match_status
            classified["2026_Grantee_Match"] = grantee_match_status

            # ── Prior funding now comes from the REGISTRY, not from the
            #    applicant. A4 ("which years and how much did you receive")
            #    was removed, which also retires P2.6 amount validation.
            #
            #    This is a net improvement: test runs showed applicant-stated
            #    amounts contradicting the registry in two of the cases
            #    checked, in both directions and by roughly 2x. The registry
            #    is now the single source of truth, so there is nothing left
            #    to reconcile.
            #
            #    Los nombres y montos concretos se quitaron a propósito: este
            #    archivo se comparte y puede acabar en un repo público, y una
            #    nota que dice "la organización X declaró el doble de lo que
            #    recibió" se lee como una acusación fuera de contexto. El
            #    hecho técnico —que las cifras declaradas no eran confiables—
            #    es lo único que justifica la decisión.
            registry_data = app.get("grantee_registry_data", {})
            yearly_amounts = registry_data.get("yearly_amounts", {})
            registry_2026_amount = yearly_amounts.get("2026", None)

            classified["Registry_2026_Amount"] = (
                registry_2026_amount if registry_2026_amount is not None else ""
            )
            classified["Registry_Total_Awarded"] = registry_data.get("total_awarded", "")
            classified["Registry_Prior_Apps"] = registry_data.get("prior_apps_count", "")

            if grantee_match_status == "MATCHED":
                classified["Renewal_Validated"] = "MATCHED"
            else:
                classified["Renewal_Validated"] = "PENDING"
                classified["Classification_Notes"] = "; ".join(
                    filter(None, [
                        classified.get("Classification_Notes", ""),
                        "renewal_claimed_but_no_registry_match",
                    ])
                )
            if app.get("seg_2027_estatus"):
                classified["Seguimiento_2027_Status"] = app["seg_2027_estatus"]
                classified["Seguimiento_2027_Tipo"] = app.get("seg_2027_tipo", "")
                classified["Seguimiento_2027_Owner"] = app.get("seg_2027_owner", "")
            else:
                classified["Seguimiento_2027_Status"] = ""
                classified["Seguimiento_2027_Tipo"] = ""
                classified["Seguimiento_2027_Owner"] = ""
        else:
            classified["Grantee_ID"] = app.get("grantee_id", "")
            classified["Grantee_Match_Status"] = app.get("grantee_match_status", "")
            classified["2026_Grantee_Match"] = ""
            classified["Renewal_Validated"] = ""
            classified["Seguimiento_2027_Status"] = app.get("seg_2027_estatus", "")
            classified["Seguimiento_2027_Tipo"] = app.get("seg_2027_tipo", "")
            classified["Seguimiento_2027_Owner"] = app.get("seg_2027_owner", "")
        # Project type (placeholder — LLM inference would go here)
        classified["Project_Type"] = ""
        classified["Project_Type_Method"] = ""

        app['classified'] = classified
        classified_apps.append(app)
      except Exception as e:
        err_msg = f"{app.get('app_id', 'unknown')}: {type(e).__name__}: {str(e)}"
        classify_errors.append(err_msg)
        print(f"  ERROR in classify: {err_msg}")
        app['classified'] = {"App_ID": app.get("app_id", ""), "Timestamp": app.get("timestamp", ""), "Profile": "ERROR", "Pillar": "", "Region": "", "Is_Renewal": "", "Classification_Notes": f"classify_error: {str(e)[:100]}"}
        classified_apps.append(app)

    # Save classified data
    run_dir = RUNS_DIR / run_id
    with open(run_dir / "classified.json", 'w') as f:
        json.dump([app['classified'] for app in classified_apps], f, indent=2)

    duration = round(time.time() - start_time, 2)
    inicial_count = sum(1 for a in classified_apps if a['classified']['Profile'] == 'Inicial')
    establecida_count = len(classified_apps) - inicial_count
    renewal_count = sum(1 for a in classified_apps if a['classified']['Is_Renewal'] == 'Yes')

    print(f"  Inicial: {inicial_count} | Establecida: {establecida_count}")
    print(f"  Renewals: {renewal_count}")
    print(f"  Duration: {duration}s")

    errors_str = "; ".join(classify_errors) if classify_errors else ""
    step_status = "success" if not classify_errors else "partial"

    log_result = {
        "step": 3, "step_name": "CLASSIFY", "status": step_status,
        "apps_in": len(applications), "apps_out": len(classified_apps),
        "errors": errors_str, "warnings": "",
        "duration_seconds": duration
    }

    return {"applications": classified_apps, "log": log_result}


# ─── Step 4: FLAG FOR REVIEW ───────────────────────────────────────────────

def step_flag(applications, run_id, drive_api=None):
    """Apply quality and compliance flags."""
    start_time = time.time()
    print(f"[Step 4: FLAG] Processing {len(applications)} applications")

    flagged_apps = []

    flag_errors = []
    for app in applications:
      try:
        f = app['fields']
        flags = {}
        flags_detail = []

        # ── Nonsense detection ──

        # Repeated text in paragraph fields
        for field_id, _ in PARAGRAPH_FIELDS:
            text = f.get(field_id, "")
            if has_repeated_text(text):
                flags["nonsense_repeated_text"] = "YES"
                flags_detail.append(f"repeated_text:{field_id}")

        # Random characters
        for field_id in list(QUESTION_MAP.keys()):
            text = f.get(field_id, "")
            if has_consecutive_consonants(text):
                flags["nonsense_random_chars"] = "YES"
                flags_detail.append(f"random_chars:{field_id}")
                break  # One flag is enough

        # One word in paragraph
        for field_id, _ in PARAGRAPH_FIELDS:
            text = f.get(field_id, "")
            if text and count_words(text) == 1:
                flags["nonsense_one_word"] = "YES"
                flags_detail.append(f"one_word:{field_id}")
                break

        # Copy-paste detection — v3: compare the two long narrative fields,
        # E4 (economic barrier) and E8 (application + partner). The v2 code
        # compared E10 vs E11, which under v3 numbering are the milestone
        # table and the risk paragraph — different fields, different purpose.
        e4_txt = f.get("E4", "").strip()
        e8_txt = f.get("E8", "").strip()
        b1 = f.get("B1", "").strip()
        if e4_txt and e8_txt and normalize_text(e4_txt) == normalize_text(e8_txt):
            flags["nonsense_copy_paste"] = "YES"
            flags_detail.append("E4=E8")
        elif e4_txt and b1 and normalize_text(e4_txt) == normalize_text(b1):
            flags["nonsense_copy_paste"] = "YES"
            flags_detail.append("E4=B1")

        # Text in number fields
        for num_field in NUMERIC_FIELDS:
            raw = f.get(num_field, "")
            if raw:
                _, valid = parse_number(raw)
                if not valid:
                    flags["nonsense_text_in_number"] = "YES"
                    flags_detail.append(f"text_in_number:{num_field}")
                    break

        # Short answer — threshold from the frozen spec ([15], Iván), not 20
        for field_id, _ in PARAGRAPH_FIELDS:
            text = f.get(field_id, "")
            if text and 0 < count_words(text) < MIN_PARAGRAPH_WORDS:
                flags["nonsense_short_answer"] = "YES"
                flags_detail.append(f"short_answer:{field_id}:{count_words(text)}words")
                break

        # Invalid email — v3: the primary email is embedded in the D1
        # composite (name, title, email, phone). D3 is the authorized signer
        # and D4 the copy address. v2 treated D3 as the email field.
        d1_email = app.get('cleaned', {}).get("D1_Email_Extracted", "")
        if f.get("D1", "").strip() and not d1_email:
            flags["nonsense_invalid_email"] = "YES"
            flags_detail.append("no_valid_email_in_D1")
        d4_val = f.get("D4", "").strip()
        if d4_val and not EMAIL_REGEX.match(d4_val.lower()):
            flags["nonsense_invalid_email"] = "YES"
            flags_detail.append("invalid_email:D4")

        # Empty required fields — always-required plus the conditionals that
        # actually apply to this applicant.
        profile_for_req = app.get('classified', {}).get("Profile", "Establecida")
        empty_required = []
        for req_field in REQUIRED_FIELDS:
            if not f.get(req_field, "").strip():
                empty_required.append(req_field)
        for cond_field, predicate in CONDITIONAL_REQUIRED.items():
            try:
                if predicate(f, profile_for_req) and not f.get(cond_field, "").strip():
                    empty_required.append(f"{cond_field}(cond)")
            except Exception:
                pass

        # Measurement fields are required of everyone; a renewal may skip F5
        # under the short route (decision 4, config-driven).
        cfg_run = app.get("_config") or {}
        for tf in MEASUREMENT_REQUIRED:
            if not f.get(tf, "").strip():
                empty_required.append(tf)
        for sf in ("F5",):
            if is_renewal_skipping(sf, f, cfg_run) and not f.get(sf, "").strip():
                flags_detail.append(f"renewal_short_route:{sf}_skipped")
        if empty_required:
            flags["nonsense_empty_required"] = "YES"
            flags_detail.append(f"empty_required:{','.join(empty_required[:6])}")

        # Stale column from the pre-removal form — a v2 submission reaching a
        # v3 pipeline would map old values onto renumbered fields, so say so
        # loudly instead of scoring it.
        stale = [x for x in REMOVED_FIELDS_V2 if str(f.get(x, "")).strip()]
        if stale:
            flags["stale_v2_fields"] = "YES"
            flags_detail.append(f"stale_v2_fields:{','.join(stale)}")

        # ── Compliance flags ──

        # Missing nonprofit proof — v3 reads A1b for the NGO distinction
        a1 = f.get("A1", "").strip()
        a1b = f.get("A1b", "").strip().lower()
        c1 = f.get("C1", "").strip()
        is_ngo = "nonprofit" in a1b or "ngo" in a1b
        if is_ngo and not c1:
            flags["missing_nonprofit_proof"] = "YES"
            flags_detail.append("NGO_without_registration_doc")
        elif a1.lower().startswith("organization") and not c1:
            flags["missing_nonprofit_proof"] = "YES"
            flags_detail.append("organization_without_registration_doc")
        elif a1.lower().startswith("individual") and not c1:
            flags["missing_nonprofit_proof"] = "YES"
            flags_detail.append("individual_without_photo_id")

        # Bitcoin rule — impact must not rest on price gains, downloads,
        # wallet counts, raw volume or granted sats. v3 reads E7 (result)
        # and E9 (Bitcoin uses) plus F1-F3; E13 was removed.
        btc_rule_corpus = " ".join([
            f.get("E7", "") or "", f.get("E9", "") or "",
            f.get("F1", "") or "", f.get("F2", "") or "", f.get("F3", "") or "",
        ]).lower()
        btc_hits = [k for k in BITCOIN_RULE_KEYWORDS if k in btc_rule_corpus]
        if btc_hits:
            flags["bitcoin_rule_violation"] = "YES"
            flags_detail.append(f"bitcoin_rule:{','.join(btc_hits[:3])}")

        # Budget — v3: G1 is the TOTAL budget, G2 the REQUEST, so the valid
        # relation is G2 <= G1. The v2 code had this inverted.
        g1_v = app.get('cleaned', {}).get("G1_Total_Budget_Num")
        g2_v = app.get('cleaned', {}).get("G2_Requested_Num")
        if isinstance(g2_v, (int, float)) and g2_v <= 0:
            flags["budget_invalid"] = "YES"
            flags_detail.append("G2_zero_or_negative")
        if isinstance(g1_v, (int, float)) and isinstance(g2_v, (int, float)) and g2_v > g1_v:
            flags["budget_invalid"] = "YES"
            flags_detail.append(f"request_exceeds_total:G2={g2_v}>G1={g1_v}")
        if app.get('cleaned', {}).get("G4_Budget_Sum_Valid") == "NO":
            flags["budget_invalid"] = "YES"
            flags_detail.append(f"G4_sum_mismatch:{app['cleaned'].get('G4_Budget_Sum_Diff','?')}")

        # Participant identifiers — decision 3 technical default, Iván
        # 2026-11-10. We ask for aggregate figures only. If a paragraph looks
        # like it carries a roster — several full names, or ID-shaped numbers —
        # it is flagged and must not be treated as evidence. The portfolio
        # includes Afghanistan, Cuba and Haiti; a list of named participants
        # reaching us is a safety problem, not a reporting one.
        pdata_cfg = (app.get("_config") or {}).get("participant_data", {})
        if pdata_cfg.get("flag_suspected_identifiers", True):
            roster_corpus = " ".join(
                (f.get(fid, "") or "") for fid, _ in PARAGRAPH_FIELDS
            )
            # three or more Capitalised Name pairs in one field reads as a list
            name_pairs = re.findall(r'\b[A-Z][a-z]{2,}\s+[A-Z][a-z]{2,}\b', roster_corpus)
            id_numbers = re.findall(r'\b\d{8,}\b', roster_corpus)
            if len(name_pairs) >= 5 or len(id_numbers) >= 3:
                flags["suspected_participant_identifiers"] = "YES"
                flags_detail.append(
                    f"possible_participant_roster:{len(name_pairs)}_names,"
                    f"{len(id_numbers)}_id_numbers"
                )

        # Dependency on the foundation — informational flag (D5, 2026-11-10).
        # Not a gate and not scored: it is context a reviewer should see, since
        # the foundation's standing criterion is that a grantee must not depend
        # entirely on us. Raised only at the high end, so it stays signal.
        dep_v = app.get('cleaned', {}).get("Dependency_Ratio")
        if isinstance(dep_v, (int, float)) and dep_v > 0:
            if dep_v >= 0.75:
                flags["high_dependency"] = "YES"
                flags_detail.append(
                    f"dependency:{dep_v*100:.0f}%_of_annual_budget"
                )
            elif dep_v >= 0.50:
                flags_detail.append(f"dependency_note:{dep_v*100:.0f}%")

        # Participant protection — hard gate. I1 != No requires a policy in
        # I2 and a named responsible person.
        i1 = f.get("I1", "").strip().lower()
        i2 = f.get("I2", "").strip()
        if i1 and i1 != "no" and not i2:
            flags["child_protection_missing"] = "YES"
            flags_detail.append(f"I1={i1}_without_safeguarding_policy")

        # No legal name: ingest created no grantee and no folder for it.
        if not f.get("B1", "").strip():
            flags["missing_legal_name"] = "YES"
            flags_detail.append("no_legal_name:no_grantee_or_folder_created")

        # Documents that did not reach the applicant's Drive folder. Not a
        # judgement on the application, but a person has to fetch them: a
        # re-run skips this application (it is already in the Cleaned tab).
        doc_errors = (app.get("documents") or {}).get("errors") or []
        if doc_errors:
            flags["documents_not_stored"] = "YES"
            flags_detail.append("documents_not_stored:" + " | ".join(doc_errors)[:300])

        # Eligibility — hard gate. Any statement of 0.2 left unchecked sends the
        # application to manual review, where a person reads K2. The server
        # already requires K2 whenever a box is missing, so "K2 explains it"
        # cannot be the condition: that would make the gate unreachable.
        elig = f.get("0.2", "").lower()
        elig_missing = [key for key, phrase in ELIGIBILITY_STATEMENTS
                        if phrase not in elig]
        if elig_missing:
            flags["eligibility_incomplete"] = "YES"
            flags_detail.append(
                f"eligibility_missing:{','.join(elig_missing)}"
                + ("" if f.get("K2", "").strip() else ";no_K2_explanation")
            )

        # Disclosures — hard gate. K1 other than "None" needs K2 detail.
        k1 = f.get("K1", "").strip()
        k2 = f.get("K2", "").strip()
        if k1 and k1.strip().lower() not in ("none", "ninguno", ""):
            flags["disclosure_present"] = "YES"
            flags_detail.append(f"K1={k1[:40]}")
            if not k2:
                flags_detail.append("K1_without_K2_detail")

        # Duplicate
        if app.get('cleaned', {}).get("Is_Duplicate_Name") == "YES":
            flags["duplicate_application"] = "YES"
            flags_detail.append("duplicate_name")
        elif app.get('cleaned', {}).get("Is_Duplicate_Email") == "YES":
            flags["duplicate_application"] = "YES"
            flags_detail.append("duplicate_email")

        # ── Automated name match (B1 legal name vs C1 registration doc) ──
        #    ⚠️ v3 RENUMBERING: the address is B4, not B5. Under v3, B5 is the
        #    numeric annual budget — the v2 line `b5 = f.get("B5")` would have
        #    compared a dollar amount against the registration document and
        #    reported a mismatch on every single application.
        b1 = f.get("B1", "").strip()
        b4_address = f.get("B4", "").strip()
        c1_val = f.get("C1", "").strip()

        # Determine if C1 is a Supabase Storage path, a Drive URL/ID, or just
        # a filename. La vista intake_rows entrega C1/C2/J3 como
        # "storage:<ruta>"; ese valor trae "/" y ".", así que caía en la rama
        # de "solo nombre de archivo" y dejaba name_mismatch y
        # address_mismatch en PENDING sin descargar nada.
        c1_is_storage = c1_val.startswith(SUPABASE_DOC_PREFIX)
        c1_is_downloadable = c1_is_storage or c1_val.startswith("http") or (len(c1_val) > 20 and "/" not in c1_val and "." not in c1_val)

        if c1_val and c1_is_downloadable:
            # Download the registration doc and extract text
            if c1_is_storage:
                doc_bytes, doc_mime = download_supabase_doc(c1_val)
            else:
                doc_bytes, doc_mime = download_drive_file(drive_api, c1_val)
            doc_text = extract_text_from_doc(doc_bytes, doc_mime) if doc_bytes else ""

            if doc_text:
                # Check name match
                name_match, name_detail = check_name_in_doc(doc_text, b1)
                if not name_match:
                    flags["name_mismatch"] = "YES"
                    flags_detail.append(f"name_mismatch: {name_detail}")

                # Check address match
                addr_match, addr_detail = check_address_in_doc(doc_text, b4_address)
                if not addr_match:
                    flags["address_mismatch"] = "YES"
                    flags_detail.append(f"address_mismatch: {addr_detail}")

                # Store match results for scoring step
                app['doc_name_match'] = name_match
                app['doc_address_match'] = addr_match
                app['doc_name_detail'] = name_detail
                app['doc_address_detail'] = addr_detail
            else:
                # Doc exists but couldn't extract text — flag for manual review
                flags["name_mismatch"] = "PENDING"
                flags["address_mismatch"] = "PENDING"
                flags_detail.append("doc_text_extraction_failed")
                app['doc_name_match'] = False
                app['doc_address_match'] = False
                app['doc_name_detail'] = "extraction failed"
                app['doc_address_detail'] = "extraction failed"
        elif c1_val:
            # C1 is just a filename (e.g., "registration.pdf") — can't download
            flags["name_mismatch"] = "PENDING"
            flags["address_mismatch"] = "PENDING"
            flags_detail.append("doc_not_downloadable: filename only")
            app['doc_name_match'] = False
            app['doc_address_match'] = False
            app['doc_name_detail'] = "filename only, no URL/ID"
            app['doc_address_detail'] = "filename only, no URL/ID"

        # ── Automated OFAC SDN check ──
        #    ⚠️ v3 RENUMBERING: the legal representative is B3, not B4. Under
        #    v3, B4 is the registered address — the v2 line
        #    `b4 = f.get("B4")` would have screened a street address against
        #    the sanctions list instead of a person's name, silently skipping
        #    the representative check on a HARD gate.
        b3_legal_rep = f.get("B3", "").strip()
        b1_for_ofac = f.get("B1", "").strip()

        try:
            sdn_entries, sdn_meta = download_ofac_sdn()

            # Check org name (B1)
            org_match, org_detail = check_ofac(b1_for_ofac, sdn_entries)
            # Check legal representative name (B3)
            rep_match, rep_detail = check_ofac(b3_legal_rep, sdn_entries)

            if org_match:
                flags["ofac_flag"] = "YES"
                flags_detail.append(f"ofac_org_match: {org_detail}")
            elif rep_match:
                flags["ofac_flag"] = "YES"
                flags_detail.append(f"ofac_rep_match: {rep_detail}")
            # If no match, ofac_flag stays empty (clean)

            # Store SDN metadata for process log (only from first app)
            if not hasattr(step_flag, '_sdn_meta_recorded'):
                step_flag._sdn_meta_recorded = True
                step_flag._sdn_meta = sdn_meta
        except Exception as ofac_err:
            # OFAC check fails gracefully — flag for manual review, don't block pipeline
            print(f"  [OFAC] Check failed for {app.get('app_id', '?')}: {type(ofac_err).__name__}: {str(ofac_err)[:100]}")
            flags["ofac_flag"] = "PENDING"
            flags_detail.append(f"ofac_check_failed: {type(ofac_err).__name__}")

        # Renewal discrepancy
        a3 = f.get("A3", "").strip().lower()
        if a3 == "yes":
            renewal_status = app.get('classified', {}).get("Renewal_Validated", "")
            if renewal_status == "PENDING":
                flags["renewal_discrepancy"] = "PENDING"
                flags_detail.append("renewal_validation_pending")

        # Build flag row
        all_flag_keys = [
            "nonsense_repeated_text", "nonsense_random_chars", "nonsense_one_word",
            "nonsense_text_in_number", "nonsense_copy_paste", "nonsense_short_answer",
            "nonsense_invalid_email", "nonsense_empty_required",
            "name_mismatch", "address_mismatch", "ofac_flag",
            "missing_nonprofit_proof", "duplicate_application", "renewal_discrepancy",
            # Raised above but missing from this list until 2026-11-13, so they
            # were never counted: an application whose only flag was a child-
            # protection or disclosure hard gate came out Has_Flags=NO and
            # "Sin flags" in the Review Package. Only Flags_Detail had them.
            "eligibility_incomplete", "child_protection_missing", "disclosure_present",
            "bitcoin_rule_violation", "budget_invalid", "high_dependency",
            "suspected_participant_identifiers",
            "missing_legal_name", "documents_not_stored",
        ]
        # Any flag raised that is still not listed is counted too, rather than
        # dropped: a new check must not be invisible because this list was not
        # updated. test_form_options.py fails if one is raised and not listed.
        all_flag_keys += [k for k in flags if k not in all_flag_keys]

        flag_row = {
            "App_ID": app['app_id'],
            "Timestamp": app.get("timestamp", ""),  # Already normalized in step_ingest
        }

        flag_count = 0
        critical_count = 0
        critical_flags = HARD_GATE_FLAGS

        for fk in all_flag_keys:
            val = flags.get(fk, "")
            flag_row[fk] = val
            if val == "YES":
                flag_count += 1
                if fk in critical_flags:
                    critical_count += 1

        flag_row["Has_Flags"] = "YES" if flag_count > 0 else "NO"
        flag_row["Flags_Count"] = flag_count
        flag_row["Critical_Flags_Count"] = critical_count
        flag_row["Flags_Detail"] = "; ".join(flags_detail) if flags_detail else ""

        app['flags'] = flag_row
        app['flags_detail'] = flags_detail
        flagged_apps.append(app)
      except Exception as e:
        err_msg = f"{app.get('app_id', 'unknown')}: {type(e).__name__}: {str(e)}"
        flag_errors.append(err_msg)
        print(f"  ERROR in flag: {err_msg}")
        app['flags'] = {"App_ID": app.get("app_id", ""), "Timestamp": app.get("timestamp", ""), "Has_Flags": "YES", "Flags_Count": 1, "Critical_Flags_Count": 1, "Flags_Detail": f"flag_error: {str(e)[:100]}"}
        app['flags_detail'] = [f"flag_error:{type(e).__name__}"]
        flagged_apps.append(app)

    # Save flagged data
    run_dir = RUNS_DIR / run_id
    with open(run_dir / "flagged.json", 'w') as f:
        json.dump([app['flags'] for app in flagged_apps], f, indent=2)

    duration = round(time.time() - start_time, 2)
    total_flagged = sum(1 for a in flagged_apps if a['flags']['Has_Flags'] == 'YES')

    print(f"  Flagged: {total_flagged}/{len(flagged_apps)}")
    print(f"  Duration: {duration}s")

    errors_str = "; ".join(flag_errors) if flag_errors else ""
    step_status = "success" if not flag_errors else "partial"

    # Build OFAC SDN metadata string for process log
    sdn_meta_str = ""
    if hasattr(step_flag, '_sdn_meta'):
        m = step_flag._sdn_meta
        sdn_meta_str = f"OFAC SDN: {m['entry_count']} entries, downloaded {m['download_date']}, age {m['cache_age_days']}d, source={m['source']}"
        # Reset for next pipeline run
        del step_flag._sdn_meta_recorded
        del step_flag._sdn_meta

    log_result = {
        "step": 4, "step_name": "FLAG", "status": step_status,
        "apps_in": len(applications), "apps_out": len(flagged_apps),
        "apps_flagged": total_flagged,
        "errors": errors_str, "warnings": sdn_meta_str,
        "duration_seconds": duration
    }

    return {"applications": flagged_apps, "log": log_result}


# ─── Step 5: SCORECARD ─────────────────────────────────────────────────────

def _median(values):
    """Median of a list of numbers. Returns None for an empty list."""
    vals = sorted(v for v in values if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


# Partner nouns that count as "a real opportunity to use what is learned".
_PARTNER_TERMS = [
    "merchant", "employer", "cooperative", "coop", "business", "shop", "store",
    "vendor", "market", "association", "union", "school", "university",
    "clinic", "hospital", "municipality", "company", "enterprise", "bank",
    "exchange", "comercio", "comerciante", "empleador", "cooperativa",
    "empresa", "escuela", "asociacion", "asociación", "mercado",
]

_MITIGATION_TERMS = [
    "mitigate", "mitigation", "reduce", "prevent", "contingency", "backup",
    "fallback", "address", "manage", "monitor", "train", "we will",
    "plan to", "mitigar", "reducir", "prevenir", "plan de",
]

_RISK_TERMS = [
    "risk", "challenge", "barrier", "obstacle", "delay", "shortfall",
    "turnover", "volatility", "connectivity", "literacy", "resistance",
    "riesgo", "desafio", "desafío", "obstaculo", "obstáculo", "retraso",
]

_CONTINUITY_WHO = [
    "we", "our team", "the community", "local", "partner", "cooperative",
    "staff", "volunteer", "leaders", "municipality", "comunidad", "equipo",
]

_CONTINUITY_RESOURCE = [
    "revenue", "income", "fee", "membership", "donation", "funder", "grant",
    "sales", "budget", "fund", "sponsor", "self-sustaining", "ingreso",
    "cuota", "donacion", "donación", "venta", "fondo",
]

_AFFECTED_GROUP_TERMS = [
    "women", "girls", "men", "youth", "children", "students", "farmers",
    "merchants", "workers", "migrants", "refugees", "unbanked", "families",
    "teachers", "entrepreneurs", "elderly", "indigenous", "dalit",
    "mujeres", "jovenes", "jóvenes", "niños", "agricultores", "familias",
]

_FINANCIAL_TERMS = [
    "bitcoin", "btc", "lightning", "wallet", "payment", "remittance",
    "savings", "credit", "bank", "cash", "fee", "cost", "income",
    "bitcoin", "pago", "remesa", "ahorro", "banco",
]


def _has_any(text, terms):
    low = (text or "").lower()
    return any(t in low for t in terms)


def _count_any(text, terms):
    low = (text or "").lower()
    return sum(1 for t in terms if t in low)


def step_score(applications, scorecard_cfg, run_id):
    """
    Step 5: SCORE — methodology's board-approved 4 criteria, 100 points.

    Resilience fit 30 · Measurable result 25 · Ability to deliver 20 ·
    Value and sustainability 25.

    Replaces the v2 7-criteria scorecard, which was a different scorecard
    from the one the board approved and which read ~55 points' worth of
    stale field IDs. Field IDs here are v3 — see eva-form-field-map-v3-FROZEN.md.

    100% deterministic. No LLM. Same input, same score, every time.
    Every sub-criterion emits a "(Npts)" fragment so the reason string's
    arithmetic can be verified independently.
    """
    start_time = time.time()
    print(f"[Step 5: SCORE] Processing {len(applications)} applications")

    crit = scorecard_cfg.get("criteria", {})
    semaphore_green = scorecard_cfg.get("semaphore", {}).get("green", 70)
    semaphore_yellow = scorecard_cfg.get("semaphore", {}).get("yellow", 50)
    dep_cfg = scorecard_cfg.get("dependency_ratio", {})
    # dep_cfg provides the bands only — the ratio is a flag, not points (D5)
    cap_cfg = scorecard_cfg.get("team_capacity_points", {"1": 5, "2": 3, "3": 1})
    cpp_cfg = scorecard_cfg.get("cost_per_participant", {})
    max_request = scorecard_cfg.get("max_realistic_request", 1000000)

    # ── Cost per participant needs a cycle median, which does not exist
    #    until applications arrive. Use the configured seed if the board set
    #    one; otherwise derive it from this batch when there are enough
    #    valid values; otherwise DEFER the sub-criterion and say so rather
    #    than silently awarding or withholding 7 points.
    median_seed = cpp_cfg.get("median_seed")
    batch_cpp = [
        a.get('cleaned', {}).get("G6_Cost_Per_Participant")
        for a in applications
    ]
    batch_cpp = [v for v in batch_cpp if isinstance(v, (int, float)) and v > 0]
    if isinstance(median_seed, (int, float)) and median_seed > 0:
        cpp_median, cpp_median_src = float(median_seed), "config seed"
    elif len(batch_cpp) >= 3:
        cpp_median, cpp_median_src = _median(batch_cpp), f"batch median of {len(batch_cpp)}"
    else:
        cpp_median, cpp_median_src = None, "unavailable"
    if cpp_median is None:
        print(f"  ⚠️  cost_per_participant DEFERRED — no cycle median "
              f"({len(batch_cpp)} valid values, need 3 or a config seed)")

    scored_apps = []
    score_errors = []

    for app in applications:
      try:
        f = app['fields']
        cleaned = app.get('cleaned', {})
        classified = app.get('classified', {})
        profile = classified.get("Profile", "Establecida")

        score_row = {
            "App_ID": app['app_id'],
            "Timestamp": app.get("timestamp", ""),
            "Grantee_Name": f.get("B1", ""),
            "Project_Title": f.get("E1", "")[:120],
            "Profile": profile,
        }

        # ════════════════════════════════════════════════════════════════
        # CRITERION 1 — RESILIENCE FIT (30)
        # ════════════════════════════════════════════════════════════════
        rf_pts = 0
        rf_reasons = []

        # 1a. Clear economic barrier — E4 (8)
        #     Full marks name the barrier, who it affects, and why Bitcoin helps.
        e4 = (f.get("E4", "") or "").strip()
        e4_wc = count_words(e4)
        barrier_parts = 0
        if e4_wc >= MIN_PARAGRAPH_WORDS:
            barrier_parts += 1
        if _has_any(e4, _AFFECTED_GROUP_TERMS):
            barrier_parts += 1
        if _has_any(e4, _FINANCIAL_TERMS):
            barrier_parts += 1
        barrier_pts = {3: 8, 2: 5, 1: 2, 0: 0}[barrier_parts]
        rf_pts += barrier_pts
        rf_reasons.append(
            f"E4 barrier: {barrier_parts}/3 components "
            f"[length>={MIN_PARAGRAPH_WORDS}w, affected group, financial relevance] ({barrier_pts}pts)"
        )

        # 1b. Stage logic — inferred stage + E7 + F1 (12)
        #     With E5/E6 removed there is no declared stage to compare against,
        #     so points come from internal coherence instead of agreement.
        stage = classified.get("Stage_Suggested", "")
        measure_match = classified.get("Measure_Matches_Stage", "CANNOT_VERIFY")
        e7_complete = cleaned.get("E7_Formula_Complete", "NO")

        stage_pts = 0
        stage_bits = []
        if stage:
            stage_pts += 4
            stage_bits.append(f"stage inferred={stage} (4pts)")
        else:
            stage_bits.append("stage not inferable (0pts)")
        if measure_match == "YES":
            stage_pts += 4
            stage_bits.append(f"F1 in expected set (4pts)")
        elif measure_match == "NO":
            stage_bits.append(
                f"F1={f.get('F1','')} outside expected "
                f"{classified.get('Expected_Measures','')} (0pts)"
            )
        else:
            stage_bits.append("F1/stage unverifiable (0pts)")
        if e7_complete == "YES":
            stage_pts += 4
            stage_bits.append("E7 result has number and date (4pts)")
        else:
            stage_bits.append("E7 result incomplete (0pts)")
        rf_pts += stage_pts
        rf_reasons.append("Stage logic: " + "; ".join(stage_bits))

        # 1c. Real opportunity to use — E8 + E9 (10)
        e8 = (f.get("E8", "") or "").strip()
        e9 = (f.get("E9", "") or "").strip()
        opp_pts = 0
        opp_bits = []
        if _has_any(e8, _PARTNER_TERMS):
            opp_pts += 5
            opp_bits.append("E8 names a concrete partner (5pts)")
        elif e8:
            opp_bits.append("E8 present but no identifiable partner (0pts)")
        else:
            opp_bits.append("E8 empty (0pts)")
        if count_words(e8) >= MIN_PARAGRAPH_WORDS:
            opp_pts += 2
            opp_bits.append("E8 adequately described (2pts)")
        else:
            opp_bits.append("E8 too short (0pts)")
        if e9:
            opp_pts += 3
            opp_bits.append(f"E9 Bitcoin use selected: {e9[:40]} (3pts)")
        else:
            opp_bits.append("E9 no Bitcoin use selected (0pts)")
        rf_pts += opp_pts
        rf_reasons.append("Opportunity: " + "; ".join(opp_bits))

        score_row["Score_Resilience_Fit"] = rf_pts
        score_row["Resilience_Fit_Reason"] = " | ".join(rf_reasons)

        # ════════════════════════════════════════════════════════════════
        # CRITERION 2 — MEASURABLE RESULT (25)
        # ════════════════════════════════════════════════════════════════
        mr_pts = 0
        mr_reasons = []

        # 2a. Primary result — E7 (8)
        has_qty = cleaned.get("E7_Has_Quantity") == "YES"
        has_when = cleaned.get("E7_Has_Date") == "YES"
        pr_pts = (4 if has_qty else 0) + (4 if has_when else 0)
        mr_pts += pr_pts
        mr_reasons.append(
            f"E7 formula: quantity={'yes' if has_qty else 'no'} "
            f"({4 if has_qty else 0}pts), date={'yes' if has_when else 'no'} "
            f"({4 if has_when else 0}pts)"
        )

        # 2b. Baseline — F2 (7)
        #     Inicial may answer with a collection plan instead of a value and
        #     still receive full marks (methodology note for Iván).
        f2 = (f.get("F2", "") or "").strip()
        f2_has_num = bool(re.search(r'\d', f2))
        f2_has_plan = _has_any(f2, ["will collect", "plan to collect", "baseline will",
                                    "we will measure", "survey in", "recolectar",
                                    "levantar", "plan de"])
        if f2_has_num:
            bl_pts = 7
            bl_why = "value present (7pts)"
        elif f2_has_plan and profile == "Inicial":
            bl_pts = 7
            bl_why = "Inicial with a stated collection plan (7pts)"
        elif f2_has_plan:
            bl_pts = 4
            bl_why = "collection plan but Establecida owes a value (4pts)"
        elif f2:
            bl_pts = 2
            bl_why = "text without a value or plan (2pts)"
        else:
            bl_pts = 0
            bl_why = "empty (0pts)"
        mr_pts += bl_pts
        mr_reasons.append(f"F2 baseline: {bl_why}")

        # 2c. Target + verification — F3 + F4 (6)
        f3 = (f.get("F3", "") or "").strip()
        f4 = (f.get("F4", "") or "").strip()
        tv_pts = 0
        tv_bits = []
        if re.search(r'\d', f3):
            tv_pts += 2
            tv_bits.append("F3 has a value (2pts)")
        else:
            tv_bits.append("F3 has no value (0pts)")
        if has_time_markers_text(f3):
            tv_pts += 2
            tv_bits.append("F3 has a date (2pts)")
        else:
            tv_bits.append("F3 has no date (0pts)")
        f4_low = f4.lower()
        if f4 and not (f4_low.startswith("other") and len(f4) < 12):
            tv_pts += 2
            tv_bits.append(f"F4 method={f4[:30]} (2pts)")
        else:
            tv_bits.append("F4 missing or bare 'Other' (0pts)")
        mr_pts += tv_pts
        mr_reasons.append("Target/verification: " + "; ".join(tv_bits))

        # 2d. Milestones — E10 (4)
        #     Three rows, each needing a date and its evidence.
        e10 = (f.get("E10", "") or "").strip()
        date_hits = len(re.findall(
            r'\b(19|20)\d{2}\b|\bQ[1-4]\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', e10
        ))
        has_evidence = _has_any(e10, ["evidence", "report", "photo", "record",
                                      "list", "receipt", "survey", "registry",
                                      "certificate", "attendance", "evidencia",
                                      "informe", "registro", "lista"])
        ms_pts = 0
        ms_bits = []
        if date_hits >= 3:
            ms_pts += 2
            ms_bits.append(f"3+ dated milestones ({date_hits}) (2pts)")
        elif date_hits >= 1:
            ms_bits.append(f"only {date_hits} dated (0pts)")
        else:
            ms_bits.append("no dates (0pts)")
        if has_evidence:
            ms_pts += 2
            ms_bits.append("evidence named (2pts)")
        else:
            ms_bits.append("no evidence named (0pts)")
        mr_pts += ms_pts
        mr_reasons.append("E10 milestones: " + "; ".join(ms_bits))

        score_row["Score_Measurable_Result"] = mr_pts
        score_row["Measurable_Result_Reason"] = " | ".join(mr_reasons)

        # ════════════════════════════════════════════════════════════════
        # CRITERION 3 — ABILITY TO DELIVER (20)
        # ════════════════════════════════════════════════════════════════
        ad_pts = 0
        ad_reasons = []

        # 3a. Experience — F5 + J1 (8)
        #     H1/H2 (prior BTC project yes/no + description) were removed, so
        #     F5 carries the experience signal. The methodology's half-credit
        #     route for an inexperienced Inicial pointed at H4, which was also
        #     removed; H1 (team capacity) is the surviving stand-in.
        f5 = (f.get("F5", "") or "").strip()
        j1 = (f.get("J1", "") or "").strip()
        h1 = (f.get("H1", "") or "").strip()
        is_prior = classified.get("Is_Prior_Grantee", "No") == "Yes"

        # ── ONE judgement over the best available source, not an additive
        #    split. The methodology reads: "Experiencia | 8 | Proyecto previo
        #    descrito con números o enlace" — a single call on whether prior
        #    work is evidenced, from whichever field carries it.
        #
        #    The earlier version awarded F5 up to 5 and J1 up to 3 and added
        #    them. That capped a renewal at 3 of 8 whenever it skipped F5 —
        #    which is exactly what a renewal short route would do, so the
        #    short route silently cost 5 points. Found while validating the
        #    renewal decision, 2026-11-10.
        # ── Permiso y crédito tienen que leer la MISMA señal.
        #
        #    is_renewal_skipping deja saltar F5 con base en A3, que es lo que
        #    el solicitante declara. El crédito por J1, en cambio, pedía
        #    Is_Prior_Grantee, que viene del match contra el registro. Las dos
        #    señales discrepan cuando el nombre legal cambió, viene con otra
        #    ortografía o en otro alfabeto.
        #
        #    En esa discrepancia el solicitante quedaba autorizado a dejar F5
        #    vacío y después perdía los 8 puntos de experiencia por tenerlo
        #    vacío. Ocho puntos mueven el semáforo. Y caía justo sobre las
        #    renovaciones legítimas con datos de registro sucios.
        #
        #    Un J1 con números es evidencia suficiente de trabajo previo. Si
        #    la declaración fuera falsa, eso es otro problema y lo atrapa una
        #    bandera para revisión humana, no un descuento callado de puntos.
        #    Encontrado por test_form_contract, 2026-11-11.
        a3_raw = f.get("A3", "") or ""
        declares_renewal = (a3_raw.lower().startswith("yes")
                            and "2026" in a3_raw
                            and "before" not in a3_raw.lower())
        has_prior_history = is_prior or declares_renewal

        f5_has_numbers = bool(f5 and re.search(r'\d', f5))
        j1_has_numbers = bool(has_prior_history and j1 and re.search(r'\d', j1))

        exp_bits = []
        if f5_has_numbers or j1_has_numbers:
            exp_pts = 8
            src = []
            if f5_has_numbers:
                src.append("F5")
            if j1_has_numbers:
                src.append("J1")
            exp_bits.append(f"prior results evidenced with numbers in {'+'.join(src)} (8pts)")
        elif f5 or (has_prior_history and j1):
            exp_pts = 3
            src = "F5" if f5 else "J1"
            exp_bits.append(f"prior work described in {src} but without numbers (3pts)")
        elif profile == "Inicial" and h1:
            exp_pts = 4
            exp_bits.append("Inicial with no prior history — half credit via H1 (4pts)")
        else:
            exp_pts = 0
            exp_bits.append("no prior experience evidenced (0pts)")

        # A renewal may skip F5 without penalty: J1 covers the same ground for
        # the 2026 grant, and we hold that record ourselves.
        if has_prior_history and not f5 and j1:
            exp_bits.append("renewal: J1 stands in for F5")

        # La discrepancia en sí es informativa: el solicitante dice que fue
        # grantee 2026 y el registro no lo encuentra. Ya no cuesta puntos,
        # pero un humano tiene que conciliar el nombre legal.
        if declares_renewal and not is_prior:
            exp_bits.append(
                "declares 2026 renewal but no registry match — credited on "
                "the declaration, needs name reconciliation")

        ad_pts += exp_pts
        ad_reasons.append("Experience: " + "; ".join(exp_bits))

        # 3b. Team capacity — H1 (5)
        cap_opt = ""
        m = re.match(r'\s*([123])', h1)
        if m:
            cap_opt = m.group(1)
        elif "robust" in h1.lower():
            cap_opt = "1"
        elif "some in-house" in h1.lower() or "some capacity" in h1.lower():
            cap_opt = "2"
        elif "do not have" in h1.lower():
            cap_opt = "3"
        cap_pts = int(cap_cfg.get(cap_opt, 0)) if cap_opt else 0
        ad_pts += cap_pts
        ad_reasons.append(
            f"H1 team capacity: option {cap_opt or 'unrecognized'} ({cap_pts}pts)"
        )

        # 3c. Risks — E11 (4)
        e11 = (f.get("E11", "") or "").strip()
        risk_pts = 0
        risk_bits = []
        if _has_any(e11, _RISK_TERMS):
            risk_pts += 2
            risk_bits.append("concrete risk named (2pts)")
        else:
            risk_bits.append("no identifiable risk (0pts)")
        if _has_any(e11, _MITIGATION_TERMS):
            risk_pts += 2
            risk_bits.append("mitigation described (2pts)")
        else:
            risk_bits.append("no mitigation (0pts)")
        ad_pts += risk_pts
        ad_reasons.append("E11 risks: " + "; ".join(risk_bits))

        # 3d. Participants — E5 + E6 (3)
        e5_num = cleaned.get("E5_Participants_Num")
        e6 = (f.get("E6", "") or "").strip()
        part_pts = 0
        part_bits = []
        if isinstance(e5_num, (int, float)) and e5_num > 0:
            part_pts += 1
            part_bits.append(f"E5 count={int(e5_num)} (1pts)")
        else:
            part_bits.append("E5 missing or zero (0pts)")
        specific = [
            w for w in re.split(r'[,;/]', e6)
            if w.strip() and w.strip().lower() not in GENERIC_BENEFICIARY_TERMS
        ]
        if len(specific) >= 2 and count_words(e6) >= MIN_PARAGRAPH_WORDS:
            part_pts += 2
            part_bits.append(f"E6 selection and relationship described ({len(specific)} specifics) (2pts)")
        elif e6:
            part_bits.append(f"E6 thin ({len(specific)} specifics, {count_words(e6)}w) (0pts)")
        else:
            part_bits.append("E6 empty (0pts)")
        ad_pts += part_pts
        ad_reasons.append("Participants: " + "; ".join(part_bits))

        score_row["Score_Ability_To_Deliver"] = ad_pts
        score_row["Ability_To_Deliver_Reason"] = " | ".join(ad_reasons)

        # ════════════════════════════════════════════════════════════════
        # CRITERION 4 — VALUE AND SUSTAINABILITY (25)
        # ════════════════════════════════════════════════════════════════
        vs_pts = 0
        vs_reasons = []
        max_available = 100

        # 4a. Cost per participant — G6 = G2/E5 (7)
        g6 = cleaned.get("G6_Cost_Per_Participant")
        if cpp_median is None:
            cpp_pts = 0
            max_available -= 7
            vs_reasons.append(
                f"G6 cost/participant: DEFERRED — no cycle median available "
                f"({cpp_median_src}); 7pts excluded from the maximum (0pts)"
            )
            score_row["Cost_Per_Participant_Status"] = "DEFERRED"
        elif isinstance(g6, (int, float)) and g6 > 0:
            full_mult = cpp_cfg.get("full_marks_multiple", 1.5)
            half_mult = cpp_cfg.get("half_marks_multiple", 3.0)
            if g6 <= full_mult * cpp_median:
                cpp_pts = 7
                band = f"<={full_mult}x median"
            elif g6 <= half_mult * cpp_median:
                cpp_pts = 3
                band = f"<={half_mult}x median"
            else:
                cpp_pts = 0
                band = f">{half_mult}x median"
            vs_reasons.append(
                f"G6 cost/participant ${g6:,.2f} vs median ${cpp_median:,.2f} "
                f"({cpp_median_src}): {band} ({cpp_pts}pts)"
            )
            score_row["Cost_Per_Participant_Status"] = band
        else:
            cpp_pts = 0
            vs_reasons.append("G6 cost/participant: not computable from G2/E5 (0pts)")
            score_row["Cost_Per_Participant_Status"] = "NOT_COMPUTABLE"
        vs_pts += cpp_pts

        # 4b. Other funders — G3 (5)
        g3 = (f.get("G3", "") or "").strip()
        g3_low = g3.lower()
        has_confirmed = "confirmed" in g3_low or "confirmado" in g3_low
        has_pending = "pending" in g3_low or "pendiente" in g3_low
        says_no = g3_low.startswith("no") and not has_confirmed and not has_pending
        if has_confirmed:
            of_pts = 5
            of_why = "at least one confirmed co-funder (5pts)"
        elif has_pending:
            of_pts = 2
            of_why = "co-funders listed but all pending (2pts)"
        elif says_no or not g3:
            of_pts = 0
            of_why = "Paystand.org as sole funder (0pts)"
        else:
            of_pts = 2
            of_why = "co-funders listed, status unclear (2pts)"
        vs_pts += of_pts
        vs_reasons.append(f"G3 other funders: {of_why}")

        # 4c. Dependency ratio — G2/B5 — FLAG ONLY, scores nothing.
        #
        #     D5, Iván 2026-11-10: this was briefly worth 3 points. As points it
        #     rewarded organizational size — a small organization requesting
        #     half its annual budget scored below a large one requesting the
        #     same amount — and it compounded with "other funders" awarding
        #     zero when Paystand.org is the sole funder, which in Haiti or Cuba
        #     is often unavoidable at any quality level.
        #
        #     The calculation stays and is surfaced to the reviewer as context.
        #     The 3 points moved to Continuity, which measures the same concern
        #     through the grantee's own plan rather than through their size.
        dep = cleaned.get("Dependency_Ratio")
        if isinstance(dep, (int, float)) and dep > 0:
            if dep < dep_cfg.get("low_risk", 0.25):
                dep_band = "low"
            elif dep < dep_cfg.get("medium_risk", 0.50):
                dep_band = "medium"
            elif dep < dep_cfg.get("high_risk", 0.75):
                dep_band = "high"
            else:
                dep_band = "very high"
            score_row["Dependency_Ratio"] = dep
            score_row["Dependency_Band"] = dep_band
            score_row["Dependency_Note"] = (
                f"Requesting {dep*100:.1f}% of last year's budget ({dep_band} dependency) "
                f"— context for the reviewer, not scored"
            )
        else:
            score_row["Dependency_Ratio"] = ""
            score_row["Dependency_Band"] = ""
            score_row["Dependency_Note"] = "Dependency not computable from G2/B5 — not scored"

        # 4d. Continuity — G7 (10)
        #     Carries the 3 points released by D5. The foundation's concern is
        #     that a grantee not depend entirely on us; this measures whether
        #     they have actually planned for that, which is the better signal.
        g7 = (f.get("G7", "") or "").strip()
        cont_pts = 0
        cont_bits = []
        if count_words(g7) >= MIN_PARAGRAPH_WORDS:
            cont_pts += 4
            cont_bits.append("what continues is described (4pts)")
        else:
            cont_bits.append("too short to describe what continues (0pts)")
        if _has_any(g7, _CONTINUITY_WHO):
            cont_pts += 3
            cont_bits.append("who sustains it is named (3pts)")
        else:
            cont_bits.append("no one named as sustaining it (0pts)")
        if _has_any(g7, _CONTINUITY_RESOURCE):
            cont_pts += 3
            cont_bits.append("resources identified (3pts)")
        else:
            cont_bits.append("no resources identified (0pts)")
        vs_pts += cont_pts
        vs_reasons.append("G7 continuity: " + "; ".join(cont_bits))

        # 4e. Budget coherence — G4 (Establecida) or G5 (Inicial) (3)
        g4_valid = cleaned.get("G4_Budget_Sum_Valid", "")
        g5 = (f.get("G5", "") or "").strip()
        if profile == "Establecida":
            if g4_valid == "YES":
                bc_pts = 3
                bc_why = "G4 categories sum to G2 (3pts)"
            elif g4_valid == "NO":
                bc_pts = 0
                bc_why = f"G4 sum off by {cleaned.get('G4_Budget_Sum_Diff','?')} (0pts)"
            else:
                bc_pts = 0
                bc_why = "G4 not verifiable (0pts)"
        else:
            if count_words(g5) >= MIN_PARAGRAPH_WORDS:
                bc_pts = 3
                bc_why = "G5 uses of funds described (3pts)"
            elif g5:
                bc_pts = 1
                bc_why = "G5 present but thin (1pts)"
            else:
                bc_pts = 0
                bc_why = "G5 empty (0pts)"
        vs_pts += bc_pts
        vs_reasons.append(f"Budget coherence: {bc_why}")

        score_row["Score_Value_Sustainability"] = vs_pts
        score_row["Value_Sustainability_Reason"] = " | ".join(vs_reasons)

        # ════════════════════════════════════════════════════════════════
        # TOTAL + SEMÁFORO
        # ════════════════════════════════════════════════════════════════
        total_score = rf_pts + mr_pts + ad_pts + vs_pts
        score_row["Total_Score"] = total_score
        score_row["Score_Max_Available"] = max_available

        # Thresholds apply to the 100-point scale. When a sub-criterion is
        # deferred the raw total cannot reach 100, so compare on a normalized
        # basis and record both numbers rather than quietly penalising.
        if max_available != 100 and max_available > 0:
            normalized = round(total_score * 100.0 / max_available, 1)
        else:
            normalized = float(total_score)
        score_row["Total_Normalized"] = normalized

        if normalized >= semaphore_green:
            by_score = "GREEN"
        elif normalized >= semaphore_yellow:
            by_score = "YELLOW"
        else:
            by_score = "RED"
        score_row["Semaforo_By_Score"] = by_score
        # A hard gate holds the semáforo RED until a person releases it; the
        # score-based colour stays next to it so the reviewer sees both.
        app_flags = app.get("flags")
        if app_flags is None:
            gates = []
            score_row["Semaforo_Hold"] = "flags not evaluated"
        else:
            gates = [g for g in HARD_GATE_FLAGS if app_flags.get(g) == "YES"]
            score_row["Semaforo_Hold"] = ", ".join(gates)
        score_row["Semaforo"] = "RED" if gates else by_score

        notes = [f"4 criteria scored deterministically. Total {total_score}/{max_available}."]
        if max_available != 100:
            notes.append(f"Normalized to {normalized}/100 for the semáforo.")
        if not stage:
            notes.append("Stage could not be inferred — needs manual classification.")
        score_row["Scoring_Notes"] = " ".join(notes)

        app['score'] = score_row
        scored_apps.append(app)
      except Exception as e:
        err_msg = f"{app.get('app_id', 'unknown')}: {type(e).__name__}: {str(e)}"
        score_errors.append(err_msg)
        print(f"  ERROR in score: {err_msg}")
        app['score'] = {
            "App_ID": app.get("app_id", ""),
            "Timestamp": app.get("timestamp", ""),
            "Total_Score": "ERROR",
            "Semaforo": "PENDING",
            "Scoring_Notes": f"score_error: {str(e)[:100]}",
        }
        scored_apps.append(app)

    run_dir = RUNS_DIR / run_id
    with open(run_dir / "scored.json", 'w') as f:
        json.dump([app['score'] for app in scored_apps], f, indent=2)

    duration = round(time.time() - start_time, 2)
    print(f"  Scored: {len(scored_apps)} (4 criteria, deterministic)")
    print(f"  Duration: {duration}s")

    errors_str = "; ".join(score_errors) if score_errors else ""
    step_status = "success" if not score_errors else "partial"

    warnings = ""
    if cpp_median is None:
        warnings = ("cost_per_participant DEFERRED (no cycle median); "
                    "totals scored out of 93 and normalized")

    log_result = {
        "step": 5, "step_name": "SCORE", "status": step_status,
        "apps_in": len(applications), "apps_out": len(scored_apps),
        "apps_scored": len(scored_apps),
        "errors": errors_str, "warnings": warnings,
        "duration_seconds": duration
    }

    return {"applications": scored_apps, "log": log_result}


# ─── Step 6: REVIEW PACKAGE ────────────────────────────────────────────────

def step_package(applications, run_id):
    """Generate review package summaries for each application."""
    start_time = time.time()
    print(f"[Step 6: PACKAGE] Processing {len(applications)} applications")

    package_rows = []

    package_errors = []
    for app in applications:
      try:
        f = app['fields']
        classified = app.get('classified', {})
        flags = app.get('flags', {})
        score = app.get('score', {})
        cleaned = app.get('cleaned', {})

        # Flags summary
        flags_detail = flags.get("Flags_Detail", "")
        has_flags = flags.get("Has_Flags", "NO")
        flags_summary = f"{flags_detail}" if has_flags == "YES" else "Sin flags"

        # Budget summary — v3 semantics: G1 is the TOTAL project budget and
        # G2 the amount requested (the v2 names had these the other way
        # round). Annual org budget is B5; B9 no longer exists.
        g1_total = cleaned.get("G1_Total_Budget_Num", f.get("G1", ""))
        g2_requested = cleaned.get("G2_Requested_Num", f.get("G2", ""))
        b5_annual = cleaned.get("B5_Annual_Budget_Num", f.get("B5", ""))
        dep_ratio = cleaned.get("Dependency_Ratio", score.get("Dependency_Ratio", ""))
        cost_pp = cleaned.get("G6_Cost_Per_Participant", "")

        dep_txt = f"{float(dep_ratio) * 100:.1f}%" if isinstance(dep_ratio, (int, float)) else "n/a"
        budget_summary = (
            f"Requested: ${g2_requested} | Total project: ${g1_total} | "
            f"Org annual budget: ${b5_annual} | Dependency: {dep_txt} | "
            f"Cost/participant: ${cost_pp}"
        )

        # Contact summary — v3: D1 is the composite primary contact, D3 the
        # authorized signer. v2 read D2/D3 as position and email.
        contact_summary = f.get('D1', '')
        if f.get('D3', '').strip():
            contact_summary += f" | signer: {f.get('D3', '')}"
        if f.get('D4', '').strip():
            contact_summary += f" | copy: {f.get('D4', '')}"

        # Suggested next step
        semaforo = score.get("Semaforo", "PENDING")
        if semaforo == "PENDING":
            suggested = "Complete LLM scoring, then review"
        elif has_flags == "YES" and flags.get("Critical_Flags_Count", 0) > 0:
            suggested = "Manual review before committee (critical flags)"
        # The semáforo is stored as GREEN / YELLOW / RED. This compared it to
        # emoji until 2026-11-13, so every application got the last branch.
        elif semaforo == "GREEN":
            suggested = "Approve for committee review"
        elif semaforo == "YELLOW":
            suggested = "Committee review with attention to flags"
        else:
            suggested = "Manual review before committee"

        package_row = {
            "app_id": app['app_id'],
            "timestamp": app['timestamp'],
            "Grantee_Name": f.get("B1", ""),
            "Project_Title": f.get("E1", ""),
            "Profile": classified.get("Profile", ""),
            "Pillar": classified.get("Pillar", ""),
            # El paquete de revisión tiene que mostrar los dos: si el revisor
            # solo ve el primario, el segundo pilar se pierde ahí mismo y no
            # sirve de nada haberlo inferido.
            "Pillars_All": classified.get("Pillars_All", ""),
            "Region": classified.get("Region", ""),
            "Is_Renewal": classified.get("Is_Renewal", "No"),
            "Total_Score": score.get("Total_Score", ""),
            "Semaforo": semaforo,
            "Flags_Summary": flags_summary,
            "Budget_Summary": budget_summary,
            "Contact_Summary": contact_summary,
            "Suggested_Next_Step": suggested,
            # The copy of the whole application and the applicant's folder,
            # both written at ingest (store_application_documents).
            "One_Pager_Link": (app.get("documents") or {}).get("copy_url", ""),
            "Documents_Folder": drive_folder_url(app.get("drive_folder_id", "")),
            "Stage_Suggested": classified.get("Stage_Suggested", ""),
            "Stage_Target": classified.get("Stage_Target", ""),
            "Score_Resilience_Fit": score.get("Score_Resilience_Fit", ""),
            "Score_Measurable_Result": score.get("Score_Measurable_Result", ""),
            "Score_Ability_To_Deliver": score.get("Score_Ability_To_Deliver", ""),
            "Score_Value_Sustainability": score.get("Score_Value_Sustainability", ""),
            "Total_Normalized": score.get("Total_Normalized", ""),
            "Semaforo_Hold": score.get("Semaforo_Hold", ""),
            "Eva_Assessment_Link": "",   # set by write_assessment_docs()
            "Status": "New",
            "Status_Since": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }

        package_rows.append(package_row)
      except Exception as e:
        err_msg = f"{app.get('app_id', 'unknown')}: {type(e).__name__}: {str(e)}"
        package_errors.append(err_msg)
        print(f"  ERROR in package: {err_msg}")
        package_rows.append({
            "App_ID": app.get("app_id", ""),
            "Timestamp": app.get("timestamp", ""),
            "Grantee_Name": app.get("fields", {}).get("B1", "ERROR"),
            "Project_Title": "Package generation failed",
            "Suggested_Next_Step": f"Manual review — package_error: {str(e)[:80]}",
        })

    # Save package data
    run_dir = RUNS_DIR / run_id
    with open(run_dir / "package.json", 'w') as f:
        json.dump(package_rows, f, indent=2)

    # Generate markdown review package
    md_path = NOTES_DIR / f"{run_id}-review-package.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    with open(md_path, 'w') as f:
        f.write(f"# Review Package — Run {run_id}\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Applications: {len(applications)}\n\n---\n\n")

        for row in package_rows:
            f.write(f"## {row['Grantee_Name']} — {row['Project_Title']}\n")
            f.write(f"**App ID:** {row['app_id']} | **Timestamp:** {row['timestamp']}\n\n")
            f.write(f"### Clasificación\n")
            f.write(f"- Perfil: {row['Profile']}\n")
            f.write(f"- Pilar: {row['Pillar']}\n")
            f.write(f"- Región: {row['Region']}\n")
            f.write(f"- Renovación: {row['Is_Renewal']}\n\n")
            f.write(f"### Scorecard\n")
            f.write(f"- Total Score: {row['Total_Score']}\n")
            f.write(f"- Semáforo: {row['Semaforo']}\n\n")
            f.write(f"### Flags\n")
            f.write(f"- {row['Flags_Summary']}\n\n")
            f.write(f"### Budget\n")
            f.write(f"- {row['Budget_Summary']}\n\n")
            f.write(f"### Contacto\n")
            f.write(f"- {row['Contact_Summary']}\n\n")
            f.write(f"### Próximo paso\n")
            f.write(f"- {row['Suggested_Next_Step']}\n\n---\n\n")

    duration = round(time.time() - start_time, 2)
    print(f"  Package rows: {len(package_rows)}")
    print(f"  Markdown: {md_path}")
    print(f"  Duration: {duration}s")

    errors_str = "; ".join(package_errors) if package_errors else ""
    step_status = "success" if not package_errors else "partial"

    log_result = {
        "step": 6, "step_name": "PACKAGE", "status": step_status,
        "apps_in": len(applications), "apps_out": len(package_rows),
        "errors": errors_str, "warnings": "",
        "duration_seconds": duration
    }

    return {"package_rows": package_rows, "log": log_result, "md_path": str(md_path)}


# ─── Step 7: WRITE TO SHEET ────────────────────────────────────────────────

# ─── P1.3: Schema validation ─────────────────────────────────────────────────
# Expected first column header for each tab — used to detect schema drift
# ─── Review board (decided 2026-11-13) ─────────────────────────────────────
# One row per application in "6. Review Package" is the board: Eva's
# pre-classification on the left, the team's review on the right. The team's
# columns are never written by the pipeline after the row is created; the
# Status column is shared (Eva sets "New", the team moves it). Every change the
# team makes is appended to "9. Review Log" by review_sync(), which is the
# formal record. The reasoning itself is a Google Doc per application
# ("<APP-ID> · Eva assessment") in the applicant's folder, where the team can
# comment line by line. Eva pre-classifies; the team decides.
REVIEW_STATUSES = ["New", "In review", "Decided", "Closed"]
REVIEW_TEAM_COLUMNS = [
    "Assigned_To", "Final_Stage", "Final_Pillars", "Final_Semaforo",
    "Agreement_With_Eva", "Disputed_Items", "Hard_Gate_Released",
    "Hard_Gate_Release_Reason", "Team_Comment", "Reviewed_By", "Review_Date",
]
REVIEW_TRACKED_COLUMNS = ["Status"] + REVIEW_TEAM_COLUMNS
REVIEW_DROPDOWNS = {
    "Status": REVIEW_STATUSES,
    "Final_Stage": VALID_STAGES,
    "Final_Semaforo": ["GREEN", "YELLOW", "RED"],
    "Agreement_With_Eva": ["Yes", "Partial", "No"],
    "Hard_Gate_Released": ["Yes", "No", "Not applicable"],
}
REVIEW_LOG_COLUMNS = ["Log_Time", "App_ID", "Event", "Field", "Old_Value",
                      "New_Value", "By", "Run_ID"]

# The columns step_write puts in each results tab. The sheet's row 1 must
# contain every one of them (any order, case-insensitive): rows are written by
# header name, and a value whose column is missing is dropped. On 2026-11-13
# the production sheet still had the v2 headers, so of what the pipeline
# computes it would have kept 13 of 51 Cleaned values, 12 of 40 Classified and
# 8 of 22 Scorecard — no stage, no pillars list, none of the four criteria.
# step_write now refuses to write when columns are missing
# (missing_result_columns); sync_sheet_headers.py fixes row 1.
# test_form_options.py checks these lists against what a real run produces.
TAB_COLUMNS = {
    TAB_CLEAN: [
        "App_ID", "Timestamp", "B1_Legal_Name_Clean", "B2_Country_Normalized",
        "B2_Country_ISO", "B3_Legal_Rep_Clean", "B4_Address_Clean", "B6_Website_Valid",
        "D1_Contact_Raw", "D1_Email_Extracted", "D1_Phone_Normalized", "D3_Signer_Raw",
        "D3_Email_Extracted", "D4_Copy_Email_Valid", "B5_Annual_Budget_Num",
        "E5_Participants_Num", "G1_Total_Budget_Num", "G2_Requested_Num", "E2_Start_Date",
        "E2_End_Date", "E2_Duration_Months", "E1_Word_Count", "E1_Word_Limit", "E4_Word_Count",
        "E4_Word_Limit", "E6_Word_Count", "E6_Word_Limit", "E8_Word_Count", "E8_Word_Limit",
        "E11_Word_Count", "E11_Word_Limit", "F5_Word_Count", "F5_Word_Limit", "G5_Word_Count",
        "G5_Word_Limit", "G7_Word_Count", "G7_Word_Limit", "J1_Word_Count", "J1_Word_Limit",
        "E7_Has_Quantity", "E7_Has_Date", "E7_Formula_Complete", "G4_Budget_Sum_Valid",
        "G4_Budget_Sum_Diff", "G2_Within_G1", "G6_Cost_Per_Participant", "Dependency_Ratio",
        "Is_Duplicate_Name", "Is_Duplicate_Email", "Cleaning_Flags", "Cleaning_Notes",
    ],
    TAB_CLASSIFY: [
        "App_ID", "Timestamp", "Profile", "A2_Normalized", "Pillar", "Pillars_All",
        "Pillar_Count", "Pillar_Source", "Pillar_Justification", "Stage_Suggested",
        "Stage_Source", "Stage_Justification", "F1_Main_Measure", "Stage_Target",
        "Stage_Target_Source", "Measure_Matches_Stage", "Expected_Measures", "Measure_Basis",
        "Stage_Jump", "Stage_Reached_2026", "Duration_Months", "Region", "Country_ISO",
        "Project_Location", "Is_Renewal", "Is_Prior_Grantee", "Route", "Classification_Notes",
        "Grantee_ID", "Grantee_Match_Status", "2026_Grantee_Match", "Registry_2026_Amount",
        "Registry_Total_Awarded", "Registry_Prior_Apps", "Renewal_Validated",
        "Seguimiento_2027_Status", "Seguimiento_2027_Tipo", "Seguimiento_2027_Owner",
        "Project_Type", "Project_Type_Method",
    ],
    TAB_FLAGS: [
        "App_ID", "Timestamp", "nonsense_repeated_text", "nonsense_random_chars",
        "nonsense_one_word", "nonsense_text_in_number", "nonsense_copy_paste",
        "nonsense_short_answer", "nonsense_invalid_email", "nonsense_empty_required",
        "name_mismatch", "address_mismatch", "ofac_flag", "missing_nonprofit_proof",
        "duplicate_application", "renewal_discrepancy", "eligibility_incomplete",
        "child_protection_missing", "disclosure_present", "bitcoin_rule_violation",
        "budget_invalid", "high_dependency", "suspected_participant_identifiers",
        "missing_legal_name", "documents_not_stored", "Has_Flags", "Flags_Count",
        "Critical_Flags_Count", "Flags_Detail",
    ],
    TAB_SCORE: [
        "App_ID", "Timestamp", "Grantee_Name", "Project_Title", "Profile",
        "Score_Resilience_Fit", "Resilience_Fit_Reason", "Score_Measurable_Result",
        "Measurable_Result_Reason", "Score_Ability_To_Deliver", "Ability_To_Deliver_Reason",
        "Cost_Per_Participant_Status", "Dependency_Ratio", "Dependency_Band",
        "Dependency_Note", "Score_Value_Sustainability", "Value_Sustainability_Reason",
        "Total_Score", "Score_Max_Available", "Total_Normalized", "Semaforo", "Semaforo_By_Score", "Semaforo_Hold", "Scoring_Notes",
    ],
    TAB_PACKAGE: [
        "App_ID", "Timestamp", "Grantee_Name", "Project_Title", "Profile", "Pillar",
        "Pillars_All", "Region", "Is_Renewal", "Total_Score", "Semaforo", "Flags_Summary",
        "Budget_Summary", "Contact_Summary", "Suggested_Next_Step", "One_Pager_Link",
        "Documents_Folder",
        # Eva's reasoning, summarised for the board (decided 2026-11-13)
        "Stage_Suggested", "Stage_Target", "Score_Resilience_Fit", "Score_Measurable_Result",
        "Score_Ability_To_Deliver", "Score_Value_Sustainability", "Total_Normalized",
        "Semaforo_Hold", "Eva_Assessment_Link", "Status", "Status_Since",
    ] + REVIEW_TEAM_COLUMNS,
    TAB_REVIEW_LOG: REVIEW_LOG_COLUMNS,
}

EXPECTED_TAB_HEADERS = {
    TAB_REGISTRY: "Grantee_ID",
    TAB_FORM: "Timestamp",
    TAB_CLEAN: "App_ID",
    TAB_CLASSIFY: "App_ID",
    TAB_FLAGS: "App_ID",
    TAB_SCORE: "App_ID",
    TAB_PACKAGE: "App_ID",
    TAB_DASH: "Metric",
    TAB_LOG: "Log_ID",
}

def validate_sheet_schema(sheets_api, spreadsheet_id):
    """Check that each tab exists and has the expected first-column header.
    Returns list of error strings (empty = all good)."""
    errors = []
    try:
        # Get spreadsheet metadata to check tab existence
        meta = sheets_api.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets.properties.title"
        ).execute()
        existing_tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]

        for tab_name, expected_first_header in EXPECTED_TAB_HEADERS.items():
            if tab_name not in existing_tabs:
                errors.append(f"Missing tab: '{tab_name}'")
                continue
            # Read just A1 to check first header
            result = read_sheet(sheets_api, spreadsheet_id, tab_name, range_str=f"'{tab_name}'!A1:A1")
            actual = result[0][0] if result and result[0] else ""
            if actual != expected_first_header:
                errors.append(
                    f"Tab '{tab_name}': expected A1='{expected_first_header}', got '{actual}'"
                )
    except Exception as e:
        errors.append(f"Schema validation error: {type(e).__name__}: {str(e)[:100]}")
    return errors


def atomic_batch_write(sheets_api, spreadsheet_id, tab_data_list):
    """P1.2: Write all tabs in a single batchUpdate API call.
    tab_data_list: [(tab_name, values, start_row), ...]
    Returns (success_count, error_list).
    If batchUpdate fails entirely, falls back to per-tab writes with retry."""
    data_payloads = []
    for tab_name, values, start_row in tab_data_list:
        if not values:
            continue
        num_cols = len(values[0]) if values else 1
        def col_letter(n):
            r = ""
            while n > 0:
                n, rem = divmod(n - 1, 26)
                r = chr(65 + rem) + r
            return r
        end_col = col_letter(num_cols)
        data_payloads.append({
            "range": f"'{tab_name}'!A{start_row}:{end_col}",
            "values": values
        })
        try:
            ensure_grid(sheets_api, spreadsheet_id, tab_name,
                        start_row + len(values) - 1, max(len(r) for r in values))
        except Exception as grid_err:
            # The write below then fails with the real reason and is reported.
            print(f"  [{tab_name}] could not grow grid: {type(grid_err).__name__}: {grid_err}")

    if not data_payloads:
        return 0, []

    try:
        sheets_api.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": data_payloads
            }
        ).execute()
        return len(data_payloads), []
    except Exception as batch_err:
        print(f"  [ATOMIC] batchUpdate failed ({type(batch_err).__name__}): {batch_err}")
        print(f"  [ATOMIC] Falling back to per-tab writes...")
        errors = []
        success = 0
        for tab_name, values, start_row in tab_data_list:
            if not values:
                continue
            try:
                write_sheet(sheets_api, spreadsheet_id, tab_name, values, start_row=start_row)
                success += 1
            except Exception as e:
                print(f"  [{tab_name}] FALLBACK WRITE ERROR: {type(e).__name__}: {e}")
                errors.append(f"{tab_name}: {type(e).__name__}: {str(e)[:100]}")
        return success, errors


def step_write(sheets_api, applications, package_rows, config, run_id, all_logs, trigger_type, triggered_by):
    """Write all results to the spreadsheet tabs + process log."""
    start_time = time.time()
    print(f"[Step 7: WRITE] Writing {len(applications)} applications to sheet")
    sheet_id = config['active']['intake_sheet_id']

    # Prepare rows for each tab
    clean_rows = [app['cleaned'] for app in applications if 'cleaned' in app]
    classify_rows = [app['classified'] for app in applications if 'classified' in app]
    flag_rows = [app['flags'] for app in applications if 'flags' in app]
    score_rows = [app['score'] for app in applications if 'score' in app]

    # Convert dict rows to list rows (matching header order)
    # Case-insensitive lookup: tab headers may be "App_ID" but dict key is "app_id"
    def dict_to_list(row_dict, headers):
        ci_dict = {}
        for k, v in row_dict.items():
            ci_dict[k.lower()] = v
            ci_dict[k] = v
        return [row_dict.get(h) or ci_dict.get(h.lower(), "") for h in headers]

    # P1.3: Schema validation — verify headers before processing
    write_errors = []
    # Errors that mean result rows may not be in the sheet. Dashboard and
    # Process Log errors are not in here: the results themselves landed.
    data_errors = []
    schema_errors = validate_sheet_schema(sheets_api, sheet_id)
    if schema_errors:
        for err in schema_errors:
            print(f"  [SCHEMA] ⚠️ {err}")
            write_errors.append(f"schema: {err}")
        # Don't abort — log warnings and proceed. Critical schema mismatches
        # would cause empty writes (caught by downstream checks), not data corruption.

    # P1.2: Atomic batch write — prepare all tab data, write in single batchUpdate
    tab_write_list = []
    tab_headers_by_tab = {}
    for tab_name, rows_list in [
        (TAB_CLEAN, clean_rows),
        (TAB_CLASSIFY, classify_rows),
        (TAB_FLAGS, flag_rows),
        (TAB_SCORE, score_rows),
        (TAB_PACKAGE, package_rows),
    ]:
        if not rows_list:
            print(f"  [{tab_name}] No rows to write")
            continue
        try:
            # Read headers from the tab (full row 1 to capture all columns)
            header_data = read_sheet(sheets_api, sheet_id, tab_name, range_str=f"'{tab_name}'!1:1")
            if not header_data:
                print(f"  [{tab_name}] Could not read headers, skipping")
                write_errors.append(f"{tab_name}: no headers")
                data_errors.append(f"{tab_name}: no headers")
                continue
            tab_headers = header_data[0]
            tab_headers_by_tab[tab_name] = tab_headers

            # Find next empty row
            existing = read_sheet(sheets_api, sheet_id, tab_name)
            next_row = len(existing) + 1 if existing else 2

            # Convert rows
            values = [dict_to_list(row, tab_headers) for row in rows_list]
            tab_write_list.append((tab_name, values, next_row))
            print(f"  [{tab_name}] Prepared {len(values)} rows for row {next_row}")
        except Exception as e:
            print(f"  [{tab_name}] PREP ERROR: {type(e).__name__}: {e}")
            write_errors.append(f"{tab_name}: prep: {type(e).__name__}: {str(e)[:100]}")
            data_errors.append(f"{tab_name}: prep")

    # Every value must have a column. Checked for all tabs BEFORE writing any,
    # so a tab with missing columns cannot leave the others half-written; and
    # the watermark is held, so nothing is skipped once row 1 is fixed.
    missing_cols = {}
    for tab_name, rows_list in [(TAB_CLEAN, clean_rows), (TAB_CLASSIFY, classify_rows),
                                (TAB_FLAGS, flag_rows), (TAB_SCORE, score_rows),
                                (TAB_PACKAGE, package_rows)]:
        headers = next((h for t, h in tab_headers_by_tab.items() if t == tab_name), None)
        if headers is None or not rows_list:
            continue
        have = {str(h).strip().lower() for h in headers}
        keys = []
        for r in rows_list:
            for key in r:
                if key.lower() not in have and key not in keys:
                    keys.append(key)
        if keys:
            missing_cols[tab_name] = keys
    if missing_cols:
        for tab_name, keys in missing_cols.items():
            msg = (f"missing_result_columns: '{tab_name}' lacks {len(keys)} column(s): "
                   f"{', '.join(keys[:12])}{' …' if len(keys) > 12 else ''}")
            print(f"  [{tab_name}] ✗ {msg}")
            write_errors.append(msg)
            data_errors.append(msg)
        print("  Nothing written to the result tabs. Run sync_sheet_headers.py, then re-run.")
        tab_write_list = []

    # Atomic write: all tabs in one batchUpdate call
    if tab_write_list:
        success_count, atomic_errors = atomic_batch_write(sheets_api, sheet_id, tab_write_list)
        if atomic_errors:
            write_errors.extend(atomic_errors)
            data_errors.extend(atomic_errors)
        for tab_name, values, start_row in tab_write_list:
            print(f"  [{tab_name}] Wrote {len(values)} rows (row {start_row})")
        print(f"  [ATOMIC] {success_count}/{len(tab_write_list)} tabs written successfully")

    # Update Dashboard
    try:
        update_dashboard(sheets_api, sheet_id, applications, run_id)
    except Exception as e:
        print(f"  [Dashboard] ERROR: {type(e).__name__}: {e}")
        write_errors.append(f"Dashboard: {type(e).__name__}: {str(e)[:100]}")

    # Write Process Log
    log_rows = []
    log_seq = 1
    for log_entry in all_logs:
        log_row = [
            f"LOG-{run_id}-{log_seq:03d}",  # Log_ID
            run_id,                          # Run_ID
            datetime.now(timezone.utc).isoformat(),  # Timestamp
            log_entry.get("step", ""),       # Step
            log_entry.get("step_name", ""),  # Step_Name
            log_entry.get("status", ""),     # Status
            log_entry.get("apps_in", ""),    # Apps_In
            log_entry.get("apps_out", ""),   # Apps_Out
            log_entry.get("apps_flagged", ""),  # Apps_Flagged
            log_entry.get("apps_scored", ""),   # Apps_Scored
            log_entry.get("duration_seconds", ""),  # Duration_Seconds
            trigger_type,                    # Trigger_Type
            triggered_by,                    # Triggered_By
            log_entry.get("watermark_before", ""),  # Watermark_Before
            log_entry.get("watermark_after", ""),   # Watermark_After
            log_entry.get("new_apps_count", ""),    # New_Apps_Count
            log_entry.get("errors", ""),     # Errors
            log_entry.get("warnings", ""),   # Warnings
            log_entry.get("notes", ""),      # Notes
        ]
        log_rows.append(log_row)
        log_seq += 1

    if log_rows:
        try:
            # Read existing log to find next row
            existing_log = read_sheet(sheets_api, sheet_id, TAB_LOG)
            next_log_row = len(existing_log) + 1 if existing_log else 2
            write_sheet(sheets_api, sheet_id, TAB_LOG, log_rows, start_row=next_log_row)
            print(f"  [{TAB_LOG}] Wrote {len(log_rows)} log rows")
        except Exception as e:
            print(f"  [{TAB_LOG}] WRITE ERROR: {type(e).__name__}: {e}")
            write_errors.append(f"{TAB_LOG}: {type(e).__name__}: {str(e)[:100]}")

    # Update watermark only if the results are in the sheet. Until 2026-11-13
    # it advanced whenever there were applications, so a failed write moved
    # the mark past them and they were never processed again. Holding it back
    # is safe: on the next run the Cleaned-tab idempotency check skips the
    # ones that did land.
    env = config['active_env']
    if applications and data_errors:
        print(f"  Watermark NOT advanced ({env}): {len(data_errors)} write error(s); "
              f"these applications will be retried next run")
        write_errors.append("watermark held back: results not fully written")
    elif applications:
        wm = load_watermark(env)
        last_app = applications[-1]
        wm['last_timestamp'] = last_app['timestamp']
        wm['last_run_id'] = run_id
        save_watermark(env, wm)
        print(f"  Watermark updated ({env}): {wm['last_timestamp']}")

    duration = round(time.time() - start_time, 2)
    print(f"  Duration: {duration}s")

    write_status = "success" if not write_errors else "partial"
    log_result = {
        "step": 7, "step_name": "WRITE", "status": write_status,
        "apps_in": len(applications), "apps_out": len(applications),
        "errors": "; ".join(write_errors) if write_errors else "",
        "warnings": "",
        "duration_seconds": duration
    }

    return {"log": log_result}


@with_retry
def update_dashboard(sheets_api, spreadsheet_id, applications, run_id):
    """Update the Dashboard tab with portfolio metrics."""
    print(f"  [Dashboard] Calculating metrics...")

    total = len(applications)
    if total == 0:
        print(f"  [Dashboard] No applications to summarize")
        return

    # Calculate metrics
    profiles = {}
    pillars = {}
    regions = {}
    semaforos = {}
    renewals = 0
    flagged = 0
    critical = 0
    ofac = 0

    for app in applications:
        classified = app.get('classified', {})
        flags = app.get('flags', {})
        score = app.get('score', {})

        profile = classified.get("Profile", "Unknown")
        profiles[profile] = profiles.get(profile, 0) + 1

        pillar = classified.get("Pillar", "Unknown")
        pillars[pillar] = pillars.get(pillar, 0) + 1

        region = classified.get("Region", "Unknown")
        regions[region] = regions.get(region, 0) + 1

        sem = score.get("Semaforo", "PENDING")
        semaforos[sem] = semaforos.get(sem, 0) + 1

        if classified.get("Is_Renewal") == "Yes":
            renewals += 1

        if flags.get("Has_Flags") == "YES":
            flagged += 1
        if flags.get("Critical_Flags_Count", 0) > 0:
            critical += 1
        if flags.get("ofac_flag") == "YES":
            ofac += 1

    # Build update values (matching the pre-populated metric rows)
    now = datetime.now(timezone.utc).isoformat()

    # Read existing dashboard to get row count
    existing = read_sheet(sheets_api, spreadsheet_id, TAB_DASH)
    # The metrics are in rows 2 onwards, column B is the value
    # We'll update column B for each metric row

    updates = []
    metric_map = {
        1: total,           # Total applications received
        2: total,           # Total processed
        3: 0,               # Pending processing
        # row 4 is blank
        5: profiles.get("Inicial", 0),
        6: profiles.get("Establecida", 0),
        7: renewals,
        8: total - renewals,
        # row 9 is blank
        10: pillars.get("Technology Adoption", 0),
        11: pillars.get("Economic Empowerment", 0),
        12: pillars.get("Education", 0),
        13: pillars.get("All three", 0),
        # row 14 is blank
        15: regions.get("LATAM", 0),
        16: regions.get("Caribbean", 0),
        17: regions.get("North America", 0),
        18: regions.get("EMEA", 0),
        19: regions.get("APAC", 0),
        20: regions.get("Sub-Saharan Africa", 0),
        21: regions.get("MENA", 0),
        # row 22 is blank
        23: semaforos.get("GREEN", 0),   # stored as words; counted emoji until 2026-11-13
        24: semaforos.get("YELLOW", 0),
        25: semaforos.get("RED", 0),
        # row 26 is blank
        27: flagged,
        28: critical,
        29: ofac,
        # row 30 is blank
        # rows 31-33 are decisions (manual)
        # row 34 is blank
        34: now,             # Last run timestamp
        35: run_id,          # Last run ID
    }

    # Write each metric value to column B
    values = []
    for row_offset, value in metric_map.items():
        row_num = row_offset + 1  # +1 because row 1 is headers
        values.append({
            "range": f"'{TAB_DASH}'!B{row_num}",
            "values": [[str(value) if value is not None else ""]]
        })

    # Batch update — use data[] format per Sheets API
    data = [{"range": vr["range"], "values": vr["values"]} for vr in values]
    sheets_api.spreadsheets().values().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"valueInputOption": "RAW", "data": data}
    ).execute()

    print(f"  [Dashboard] Updated {len(values)} metrics")


# ─── Main Pipeline ─────────────────────────────────────────────────────────

def run_review_sync(sheets_api, config, run_id, all_logs):
    """review_sync with the pipeline's error handling: a failure is logged and
    reported, never fatal, and the changes are retried on the next run."""
    start = time.time()
    try:
        res = review_sync(sheets_api, config['active']['intake_sheet_id'],
                          config['active_env'], run_id)
        print(f"[REVIEW] {res['logged']} change(s) logged, {res['status_changes']} status change(s)")
        all_logs.append({"step": 8, "step_name": "REVIEW", "status": "success",
                         "apps_in": res['logged'], "apps_out": res['logged'], "errors": "",
                         "warnings": "", "duration_seconds": round(time.time() - start, 2)})
    except Exception as e:
        print(f"[REVIEW] ERROR: {type(e).__name__}: {e}")
        send_slack_notification(f"Review log sync failed — Run {run_id}: {e}", is_error=True)
        all_logs.append({"step": 8, "step_name": "REVIEW", "status": "error",
                         "apps_in": 0, "apps_out": 0, "errors": f"{type(e).__name__}: {str(e)[:200]}",
                         "warnings": "", "duration_seconds": round(time.time() - start, 2)})


def run_pipeline(args):
    """Run the full intake pipeline or a single step."""
    config = load_config()
    scorecard_cfg = load_scorecard_config()
    country_map = load_country_mapping()
    region_map = load_region_mapping()

    # Set active environment
    env = args.environment or 'test'
    config['active'] = config[env]
    config['active_env'] = env

    sheets_api = get_sheets_service()
    drive_api = get_drive_service()
    run_id = args.run_id or generate_run_id()
    trigger_type = args.trigger_type or "manual"
    triggered_by = args.triggered_by or "eva"

    print(f"{'='*60}")
    print(f"INTAKE PIPELINE — Run ID: {run_id}")
    print(f"Environment: {env.upper()}")
    print(f"Sheet: {config['active']['intake_sheet_id']}")
    print(f"Trigger: {trigger_type} by {triggered_by}")
    print(f"{'='*60}\n")

    all_logs = []
    applications = []
    pipeline_failed = False
    pipeline_error_msg = ""
    package_rows = []

    # ── P0: Each step wrapped in try/except — one failure doesn't kill the rest ──

    if args.run_all or args.step == "ingest":
        try:
            result = step_ingest(sheets_api, drive_api, config, scorecard_cfg, run_id, trigger_type, triggered_by)
            applications = result['applications']
            all_logs.append(result['log'])

            if not applications:
                print("\nNo new applications. Pipeline complete.")
                # The team works on the board between intakes; their edits are
                # logged on every run, not only when new applications arrive.
                run_review_sync(sheets_api, config, run_id, all_logs)
                try:
                    step_write(sheets_api, [], [], config, run_id, all_logs, trigger_type, triggered_by)
                except Exception as e:
                    print(f"  ERROR in write (empty batch): {e}")
                    send_slack_notification(f"Write step failed for empty batch — Run {run_id}: {e}", is_error=True)
                return
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 1 (INGEST) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            all_logs.append({
                "step": 1, "step_name": "INGEST", "status": "error",
                "apps_in": 0, "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0, "trigger_type": trigger_type, "triggered_by": triggered_by
            })

    if args.run_all or args.step == "clean":
        if not applications and args.run_id and not pipeline_failed:
            run_dir = RUNS_DIR / args.run_id
            if run_dir.exists():
                with open(run_dir / "ingest.json") as f:
                    data = json.load(f)
                    applications = data['applications']
        try:
            result = step_clean(applications, country_map, run_id)
            all_logs.append(result['log'])
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 2 (CLEAN) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 2 (CLEAN) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 2, "step_name": "CLEAN", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})

    if args.run_all or args.step == "classify":
        try:
            result = step_classify(applications, scorecard_cfg, country_map, region_map, run_id)
            all_logs.append(result['log'])
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 3 (CLASSIFY) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 3 (CLASSIFY) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 3, "step_name": "CLASSIFY", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})

    if args.run_all or args.step == "flag":
        try:
            # step_flag reads the config for the measurement-tiering,
            # renewal-short-route and participant-data decisions, all of
            # which are config-driven so they stay reversible.
            for _a in applications:
                _a['_config'] = scorecard_cfg
            result = step_flag(applications, run_id, drive_api=drive_api)
            all_logs.append(result['log'])
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 4 (FLAG) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 4 (FLAG) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 4, "step_name": "FLAG", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})

    if args.run_all or args.step == "score":
        try:
            result = step_score(applications, scorecard_cfg, run_id)
            all_logs.append(result['log'])
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 5 (SCORE) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 5 (SCORE) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 5, "step_name": "SCORE", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})

    if args.run_all or args.step == "package":
        try:
            result = step_package(applications, run_id)
            package_rows = result['package_rows']
            all_logs.append(result['log'])
            doc_errors = write_assessment_docs(
                drive_api, applications, package_rows,
                board_url=config['active'].get('intake_sheet_url', ''))
            if doc_errors:
                print(f"  ⚠️  Eva assessment not created for {len(doc_errors)}: {'; '.join(doc_errors)[:300]}")
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 6 (PACKAGE) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 6 (PACKAGE) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 6, "step_name": "PACKAGE", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})
            package_rows = []

    if args.run_all or args.step == "write":
        if args.run_all and not package_rows and 'result' in locals():
            package_rows = result.get('package_rows', [])
        try:
            result = step_write(sheets_api, applications, package_rows, config, run_id, all_logs, trigger_type, triggered_by)
            all_logs.append(result['log'])
        except Exception as e:
            pipeline_failed = True
            pipeline_error_msg = f"Step 7 (WRITE) failed: {type(e).__name__}: {str(e)}"
            print(f"\n❌ {pipeline_error_msg}")
            print(traceback.format_exc())
            send_slack_notification(f"Step 7 (WRITE) failed — Run {run_id} ({env}): {pipeline_error_msg}", is_error=True)
            all_logs.append({"step": 7, "step_name": "WRITE", "status": "error",
                "apps_in": len(applications), "apps_out": 0, "errors": str(e), "warnings": "",
                "duration_seconds": 0})

    if args.run_all:
        run_review_sync(sheets_api, config, run_id, all_logs)

    # Print summary
    print(f"\n{'='*60}")
    if pipeline_failed:
        print(f"PIPELINE COMPLETED WITH ERRORS — Run ID: {run_id}")
    else:
        print(f"PIPELINE COMPLETE — Run ID: {run_id}")
    print(f"Steps executed: {len(all_logs)}")
    for log in all_logs:
        status_icon = "✅" if log['status'] == 'success' else "⚠️" if log['status'] == 'partial' else "❌"
        print(f"  {status_icon} Step {log['step']} ({log['step_name']}): {log['status']} — {log.get('apps_out', 0)} apps — {log['duration_seconds']}s")
    print(f"{'='*60}")

    # P0: Slack notification on pipeline result
    app_count = len(applications)
    error_count = sum(1 for l in all_logs if l.get('status') == 'error')
    partial_count = sum(1 for l in all_logs if l.get('status') == 'partial')
    if pipeline_failed or error_count > 0:
        failed_steps = [l['step_name'] for l in all_logs if l.get('status') == 'error']
        send_slack_notification(
            f"Run {run_id} ({env}) — {app_count} apps, {error_count} errors, {partial_count} partials. "
            f"Failed steps: {', '.join(failed_steps)}. {pipeline_error_msg}",
            is_error=True
        )
    elif app_count > 0:
        send_slack_notification(
            f"Run {run_id} ({env}) — {app_count} apps processed, {partial_count} partial steps. "
            f"All steps completed."
        )


# ─── CLI ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='PayStand Foundation 2027 Grant Intake Pipeline')
    parser.add_argument('--run-all', action='store_true', help='Run all 7 steps')
    parser.add_argument('--step', choices=['ingest', 'clean', 'classify', 'flag', 'score', 'package', 'write'],
                        help='Run a single step')
    parser.add_argument('--run-id', help='Run ID (for continuing a previous run)')
    parser.add_argument('--environment', choices=['test', 'production'], default='test',
                        help='Which environment to use (default: test)')
    parser.add_argument('--trigger-type', default='manual', help='How this run was triggered')
    parser.add_argument('--triggered-by', default='eva', help='Who triggered this run')

    args = parser.parse_args()

    if not args.run_all and not args.step:
        parser.print_help()
        sys.exit(1)

    try:
        _run_lock = acquire_run_lock(info={
            "environment": args.environment,
            "trigger": args.trigger_type,
            "by": args.triggered_by,
        })
    except PipelineLocked as held:
        print(f"Another intake run is in progress ({held}). Not starting; "
              f"the next scheduled run will pick up anything new.")
        sys.exit(EXIT_LOCKED)

    run_pipeline(args)