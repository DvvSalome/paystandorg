#!/usr/bin/env python3
"""
Scoring verification — v3, methodology's 4-criteria scorecard.

Three layers:
  1. PRE-SCORE   validate inputs before scoring (fields present, types sane)
  2. SCORE       the deterministic scoring in intake_pipeline.py
  3. POST-SCORE  verify outputs (independent rescore, arithmetic, bounds)

Plus FIXTURES: five applications with hand-calculated expected scores.

── Why this file is written the way it is ─────────────────────────────────────

The v2 pair of files shared the same stale field map, so Layer 3's "independent
rescore" agreed with the pipeline and reported a pass. Two implementations of
the same mistake agreeing is not verification.

Two things guard against repeating that:

  * The rescore below is written from the rubric in
    eva/eva-form-field-map-v3-FROZEN.md §4, not from intake_pipeline.py. The
    structure is deliberately different — a table of small scoring functions
    rather than one long inline block — so a copy-paste error in one is
    unlikely to be mirrored in the other.

  * The fixtures carry expected scores calculated by hand from the rubric.
    Those are the real anchor: if both implementations drift together, the
    fixtures still fail.

No LLM anywhere. Keyword matching, digit detection, word counts, ratios.

Usage:
    python3 scoring_verify.py --fixtures     hand-calculated cases
    python3 scoring_verify.py --pre-score    validate the latest run's inputs
    python3 scoring_verify.py --post-score   verify the latest run's outputs
    python3 scoring_verify.py --all
"""

import argparse
import json
import re
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent
DATA_DIR = WORKSPACE / "data"
RUNS_DIR = WORKSPACE / "cache" / "intake_runs"


def load_config():
    with open(DATA_DIR / "scorecard_config.json") as fh:
        return json.load(fh)


# ══════════════════════════════════════════════════════════════════════════
#  Vocabularies — transcribed from the rubric, not imported from the
#  pipeline. Importing would defeat the point of a second implementation.
# ══════════════════════════════════════════════════════════════════════════

AFFECTED_GROUPS = {
    "women", "girls", "men", "youth", "children", "students", "farmers",
    "merchants", "workers", "migrants", "refugees", "unbanked", "families",
    "teachers", "entrepreneurs", "elderly", "indigenous", "dalit",
    "mujeres", "jovenes", "jóvenes", "niños", "agricultores", "familias",
}

FINANCIAL = {
    "bitcoin", "btc", "lightning", "wallet", "payment", "remittance",
    "savings", "credit", "bank", "cash", "fee", "cost", "income",
    "pago", "remesa", "ahorro", "banco",
}

PARTNERS = {
    "merchant", "employer", "cooperative", "coop", "business", "shop", "store",
    "vendor", "market", "association", "union", "school", "university",
    "clinic", "hospital", "municipality", "company", "enterprise", "bank",
    "exchange", "comercio", "comerciante", "empleador", "cooperativa",
    "empresa", "escuela", "asociacion", "asociación", "mercado",
}

RISKS = {
    "risk", "challenge", "barrier", "obstacle", "delay", "shortfall",
    "turnover", "volatility", "connectivity", "literacy", "resistance",
    "riesgo", "desafio", "desafío", "obstaculo", "obstáculo", "retraso",
}

MITIGATIONS = {
    "mitigate", "mitigation", "reduce", "prevent", "contingency", "backup",
    "fallback", "address", "manage", "monitor", "train", "we will",
    "plan to", "mitigar", "reducir", "prevenir", "plan de",
}

SUSTAINERS = {
    "we", "our team", "the community", "local", "partner", "cooperative",
    "staff", "volunteer", "leaders", "municipality", "comunidad", "equipo",
}

RESOURCES = {
    "revenue", "income", "fee", "membership", "donation", "funder", "grant",
    "sales", "budget", "fund", "sponsor", "self-sustaining", "ingreso",
    "cuota", "donacion", "donación", "venta", "fondo",
}

EVIDENCE = {
    "evidence", "report", "photo", "record", "list", "receipt", "survey",
    "registry", "certificate", "attendance", "evidencia", "informe",
    "registro", "lista",
}

GENERIC_GROUPS = {
    "people", "community", "communities", "individuals", "population",
    "everyone", "all", "public", "users", "gente", "comunidad", "personas",
}

COLLECTION_PLAN = {
    "will collect", "plan to collect", "baseline will", "we will measure",
    "survey in", "recolectar", "levantar", "plan de",
}

MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|"
    "noviembre|diciembre"
)


# ── primitives ────────────────────────────────────────────────────────────

def txt(fields, key):
    return (fields.get(key) or "").strip()


def wc(s):
    return len(s.split()) if s and s.strip() else 0


def has_digit(s):
    return bool(re.search(r"\d", s or ""))


def has_quantity(s):
    return bool(re.search(r"\d+\s*%|\b\d[\d,.]*\b", s or ""))


def has_date(s):
    if not s:
        return False
    return bool(
        re.search(r"\b(19|20)\d{2}\b", s)
        or re.search(r"\bQ[1-4]\b", s, re.I)
        or re.search(r"\b(?:" + MONTHS + r")\b", s, re.I)
        or re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", s)
    )


def has_time_marker(s):
    if not s:
        return False
    pats = [
        r"\b(19|20)\d{2}\b", r"\bQ[1-4]\b",
        r"\bmonth\s*\d+", r"\bphase\s*\d+", r"\bweek\s*\d+",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        r"\b(?:" + MONTHS + r")\b",
        r"\bwithin \d+", r"\bby \w+",
        r"\bfirst quarter\b|\bsecond quarter\b|\bthird quarter\b|\bfourth quarter\b",
    ]
    return any(re.search(p, s, re.I) for p in pats)


def any_term(s, terms):
    low = (s or "").lower()
    return any(t in low for t in terms)


def as_num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if v in (None, ""):
        return None
    try:
        return float(re.sub(r"[$,\s]", "", str(v)))
    except (TypeError, ValueError):
        return None


MIN_WORDS = 15


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 3a — independent rescore, written from the rubric
#
#  Each sub-criterion is its own function returning (points, detail). The
#  pipeline computes these inline inside one long block; keeping them
#  separate here means the two implementations do not share shape.
# ══════════════════════════════════════════════════════════════════════════

# ── Criterion 1: Resilience fit (30) ──

def sub_economic_barrier(f):
    """E4 — 8 pts. Full marks name the barrier, who it affects, why Bitcoin helps."""
    e4 = txt(f, "E4")
    parts = sum([
        wc(e4) >= MIN_WORDS,
        any_term(e4, AFFECTED_GROUPS),
        any_term(e4, FINANCIAL),
    ])
    return {3: 8, 2: 5, 1: 2, 0: 0}[parts], {"components": parts}


def sub_stage_logic(f, cl, cleaned):
    """Inferred stage + E7 + F1 — 12 pts, in three equal parts."""
    pts = 0
    d = {}
    d["stage"] = cl.get("Stage_Suggested", "")
    if d["stage"]:
        pts += 4
    d["measure_match"] = cl.get("Measure_Matches_Stage", "CANNOT_VERIFY")
    if d["measure_match"] == "YES":
        pts += 4
    d["formula"] = cleaned.get("E7_Formula_Complete", "NO")
    if d["formula"] == "YES":
        pts += 4
    return pts, d


def sub_real_opportunity(f):
    """E8 + E9 — 10 pts. A named partner is the expensive half."""
    e8, e9 = txt(f, "E8"), txt(f, "E9")
    pts = 0
    d = {}
    d["partner"] = any_term(e8, PARTNERS)
    if d["partner"]:
        pts += 5
    d["e8_words"] = wc(e8)
    if d["e8_words"] >= MIN_WORDS:
        pts += 2
    d["bitcoin_use"] = bool(e9)
    if d["bitcoin_use"]:
        pts += 3
    return pts, d


# ── Criterion 2: Measurable result (25) ──

def sub_primary_result(f, cleaned):
    """E7 — 8 pts: a number and a date, 4 each."""
    e7 = txt(f, "E7")
    q = cleaned.get("E7_Has_Quantity")
    dt = cleaned.get("E7_Has_Date")
    # Fall back to recomputing when the cleaned flags are absent.
    q = (q == "YES") if q is not None else has_quantity(e7)
    dt = (dt == "YES") if dt is not None else has_date(e7)
    return (4 if q else 0) + (4 if dt else 0), {"quantity": q, "date": dt}


def sub_baseline(f, profile):
    """F2 — 7 pts. Initial may answer with a collection plan instead."""
    f2 = txt(f, "F2")
    if has_digit(f2):
        return 7, {"mode": "value"}
    if any_term(f2, COLLECTION_PLAN):
        return (7, {"mode": "plan_initial"}) if profile == "Inicial" \
            else (4, {"mode": "plan_established"})
    if f2:
        return 2, {"mode": "text_only"}
    return 0, {"mode": "empty"}


def sub_target_verification(f):
    """F3 + F4 — 6 pts: value 2, date 2, a real verification method 2."""
    f3, f4 = txt(f, "F3"), txt(f, "F4")
    pts = 0
    d = {}
    d["f3_value"] = has_digit(f3)
    if d["f3_value"]:
        pts += 2
    d["f3_date"] = has_time_marker(f3)
    if d["f3_date"]:
        pts += 2
    d["f4_usable"] = bool(f4) and not (f4.lower().startswith("other") and len(f4) < 12)
    if d["f4_usable"]:
        pts += 2
    return pts, d


def sub_milestones(f):
    """E10 — 4 pts: three dated milestones 2, evidence named 2."""
    e10 = txt(f, "E10")
    dates = len(re.findall(
        r"\b(19|20)\d{2}\b|\bQ[1-4]\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", e10))
    pts = (2 if dates >= 3 else 0) + (2 if any_term(e10, EVIDENCE) else 0)
    return pts, {"dated": dates, "evidence": any_term(e10, EVIDENCE)}


# ── Criterion 3: Ability to deliver (20) ──

def sub_experience(f, cl, profile):
    """F5 + J1 — 8 pts. Initial with no history gets half credit via H1."""
    f5, j1, h1 = txt(f, "F5"), txt(f, "J1"), txt(f, "H1")
    registry_prior = cl.get("Is_Prior_Grantee", "No") == "Yes"

    # The short route is GRANTED on A3, which is what the applicant declares,
    # so the credit has to be judged on the same signal. Reading only the
    # registry match let an applicant be authorised to leave F5 blank and then
    # lose all 8 points for the blank — whenever the legal name had changed or
    # was spelled differently. Derived here from A3 directly rather than
    # imported, to keep this file an independent reading of the rubric.
    a3 = txt(f, "A3")
    declares_renewal = (a3.lower().startswith("yes")
                        and "2026" in a3
                        and "before" not in a3.lower())
    prior = registry_prior or declares_renewal

    # Single judgement, per the rubric: 8 points for prior work evidenced with
    # numbers, from whichever field carries it. Not F5 and J1 added together —
    # that would cap a renewal at 3 whenever it skipped F5, penalising the very
    # short route the renewal rule is meant to allow.
    d = {"prior": prior, "registry_prior": registry_prior,
         "declares_renewal": declares_renewal}
    numbers = (bool(f5) and has_digit(f5)) or (prior and bool(j1) and has_digit(j1))
    described = bool(f5) or (prior and bool(j1))
    if numbers:
        d["basis"] = "numbers"
        return 8, d
    if described:
        d["basis"] = "text_only"
        return 3, d
    if profile == "Inicial" and h1:
        d["basis"] = "half_credit_via_H1"
        return 4, d
    d["basis"] = "none"
    return 0, d


def sub_team_capacity(f, cfg):
    """H1 — 5 pts: option 1 = 5, 2 = 3, 3 = 1."""
    h1 = txt(f, "H1")
    table = cfg.get("team_capacity_points", {"1": 5, "2": 3, "3": 1})
    m = re.match(r"\s*([123])", h1)
    opt = m.group(1) if m else ""
    if not opt:
        low = h1.lower()
        if "robust" in low:
            opt = "1"
        elif "some in-house" in low or "some capacity" in low:
            opt = "2"
        elif "do not have" in low:
            opt = "3"
    return (int(table.get(opt, 0)) if opt else 0), {"option": opt or None}


def sub_risks(f):
    """E11 — 4 pts: a concrete risk 2, its mitigation 2."""
    e11 = txt(f, "E11")
    r = any_term(e11, RISKS)
    m = any_term(e11, MITIGATIONS)
    return (2 if r else 0) + (2 if m else 0), {"risk": r, "mitigation": m}


def sub_participants(f, cleaned):
    """E5 + E6 — 3 pts: a count 1, selection and relationship described 2."""
    e6 = txt(f, "E6")
    n = as_num(cleaned.get("E5_Participants_Num"))
    pts = 0
    d = {"count": n}
    if n is not None and n > 0:
        pts += 1
    specifics = [
        w for w in re.split(r"[,;/]", e6)
        if w.strip() and w.strip().lower() not in GENERIC_GROUPS
    ]
    d["specifics"] = len(specifics)
    d["words"] = wc(e6)
    if len(specifics) >= 2 and wc(e6) >= MIN_WORDS:
        pts += 2
    return pts, d


# ── Criterion 4: Value and sustainability (25) ──

def sub_cost_per_participant(cleaned, median, cfg):
    """
    G6 = G2/E5 — 7 pts against the cycle median.

    When no median exists the sub-criterion is DEFERRED: 0 points, and 7 come
    off the maximum so the total is not silently depressed.
    """
    g6 = as_num(cleaned.get("G6_Cost_Per_Participant"))
    c = cfg.get("cost_per_participant", {})
    if median is None:
        return 0, {"status": "DEFERRED"}, 7
    if g6 is None or g6 <= 0:
        return 0, {"status": "NOT_COMPUTABLE"}, 0
    full = c.get("full_marks_multiple", 1.5)
    half = c.get("half_marks_multiple", 3.0)
    if g6 <= full * median:
        return 7, {"status": "within_full", "g6": g6}, 0
    if g6 <= half * median:
        return 3, {"status": "within_half", "g6": g6}, 0
    return 0, {"status": "above", "g6": g6}, 0


def sub_other_funders(f):
    """G3 — 5 pts: a confirmed co-funder 5, pending only 2, sole source 0."""
    g3 = txt(f, "G3")
    low = g3.lower()
    confirmed = "confirmed" in low or "confirmado" in low
    pending = "pending" in low or "pendiente" in low
    if confirmed:
        return 5, {"status": "confirmed"}
    if pending:
        return 2, {"status": "pending_only"}
    if not g3 or (low.startswith("no") and not confirmed and not pending):
        return 0, {"status": "sole_funder"}
    return 2, {"status": "unclear"}


def sub_continuity(f):
    """
    G7 — 10 pts: what continues 4, who sustains it 3, with what resources 3.

    Carries the 3 points released when the dependency ratio became a flag
    (D5, 2026-11-10).
    """
    g7 = txt(f, "G7")
    pts = 0
    d = {"words": wc(g7)}
    if wc(g7) >= MIN_WORDS:
        pts += 4
    d["who"] = any_term(g7, SUSTAINERS)
    if d["who"]:
        pts += 3
    d["resources"] = any_term(g7, RESOURCES)
    if d["resources"]:
        pts += 3
    return pts, d


def sub_budget_coherence(f, cleaned, profile):
    """G4 for Established, G5 for Initial — 3 pts."""
    if profile == "Establecida":
        v = cleaned.get("G4_Budget_Sum_Valid", "")
        return (3 if v == "YES" else 0), {"g4": v or "missing"}
    g5 = txt(f, "G5")
    if wc(g5) >= MIN_WORDS:
        return 3, {"g5": "described"}
    if g5:
        return 1, {"g5": "thin"}
    return 0, {"g5": "empty"}


# ── assemble ──────────────────────────────────────────────────────────────

def rescore(app, cfg, median=None):
    """Independent rescore of all four criteria. Returns a comparable dict."""
    f = app.get("fields", {})
    cleaned = app.get("cleaned", {})
    cl = app.get("classified", {})
    profile = cl.get("Profile", "Establecida")

    detail = {}
    rf = 0
    for name, fn in (
        ("economic_barrier", lambda: sub_economic_barrier(f)),
        ("stage_logic", lambda: sub_stage_logic(f, cl, cleaned)),
        ("real_opportunity", lambda: sub_real_opportunity(f)),
    ):
        p, d = fn()
        rf += p
        detail[name] = {"pts": p, **d}

    mr = 0
    for name, fn in (
        ("primary_result", lambda: sub_primary_result(f, cleaned)),
        ("baseline", lambda: sub_baseline(f, profile)),
        ("target_verification", lambda: sub_target_verification(f)),
        ("milestones", lambda: sub_milestones(f)),
    ):
        p, d = fn()
        mr += p
        detail[name] = {"pts": p, **d}

    ad = 0
    for name, fn in (
        ("experience", lambda: sub_experience(f, cl, profile)),
        ("team_capacity", lambda: sub_team_capacity(f, cfg)),
        ("risks", lambda: sub_risks(f)),
        ("participants", lambda: sub_participants(f, cleaned)),
    ):
        p, d = fn()
        ad += p
        detail[name] = {"pts": p, **d}

    cpp, cpp_d, deferred = sub_cost_per_participant(cleaned, median, cfg)
    vs = cpp
    detail["cost_per_participant"] = {"pts": cpp, **cpp_d}
    for name, fn in (
        ("other_funders", lambda: sub_other_funders(f)),
        ("continuity", lambda: sub_continuity(f)),
        ("budget_coherence", lambda: sub_budget_coherence(f, cleaned, profile)),
    ):
        p, d = fn()
        vs += p
        detail[name] = {"pts": p, **d}

    total = rf + mr + ad + vs
    max_available = 100 - deferred
    normalized = round(total * 100.0 / max_available, 1) if max_available else 0.0

    green = cfg.get("semaphore", {}).get("green", 70)
    yellow = cfg.get("semaphore", {}).get("yellow", 50)
    light = "GREEN" if normalized >= green else ("YELLOW" if normalized >= yellow else "RED")

    return {
        "resilience_fit": rf,
        "measurable_result": mr,
        "ability_to_deliver": ad,
        "value_sustainability": vs,
        "total": total,
        "max_available": max_available,
        "normalized": normalized,
        "semaforo": light,
        "detail": detail,
    }


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 1 — pre-score validation
# ══════════════════════════════════════════════════════════════════════════

SCORING_FIELDS = [
    "E4", "E7", "E8", "E9", "E10", "E11", "E5", "E6",
    "F1", "F2", "F3", "F4", "F5",
    "G2", "G3", "G4", "G5", "G7",
    "H1", "J1", "B5",
]

CRITICAL_FIELDS = ["B1", "E1"]


def pre_score(app, cfg):
    f = app.get("fields", {})
    cleaned = app.get("cleaned", {})
    cl = app.get("classified", {})
    errors, warnings = [], []

    for k in CRITICAL_FIELDS:
        if not txt(f, k):
            errors.append(f"missing critical field {k}")

    missing = [k for k in SCORING_FIELDS if not txt(f, k)]
    if missing:
        warnings.append("empty scoring fields: " + ", ".join(missing))

    for fid in ("B5", "E5", "G1", "G2"):
        raw = txt(f, fid)
        if raw and as_num(raw) is None:
            warnings.append(f"{fid}={raw!r} is not parseable as a number")

    g1, g2 = as_num(cleaned.get("G1_Total_Budget_Num")), as_num(cleaned.get("G2_Requested_Num"))
    if g1 is not None and g2 is not None and g2 > g1:
        warnings.append(f"G2 ({g2:,.0f}) exceeds G1 ({g1:,.0f}) — request above total budget")
    if g2 is not None and g2 <= 0:
        errors.append("G2 is zero or negative")

    f1 = txt(f, "F1")
    valid = cfg.get("valid_measures", [])
    if f1 and f1 not in valid:
        warnings.append(f"F1 {f1!r} is not one of {valid}")

    stage = cl.get("Stage_Suggested", "")
    if not stage:
        warnings.append("stage could not be inferred — 4 pts of Resilience fit unavailable")
    elif cl.get("Measure_Matches_Stage") == "NO":
        warnings.append(
            f"F1 {f1!r} outside the expected set for {stage!r} — 4 pts unavailable"
        )

    if cl.get("Is_Prior_Grantee") == "Yes" and not txt(f, "J1"):
        warnings.append("prior grantee but J1 empty — 3 pts of Experience unavailable")

    b5, dep = as_num(cleaned.get("B5_Annual_Budget_Num")), cleaned.get("Dependency_Ratio")
    if isinstance(dep, (int, float)) and dep >= 0.75:
        warnings.append(f"dependency {dep*100:.0f}% of annual budget — flagged, not scored")
    elif b5 is None and g2 is not None:
        warnings.append("B5 missing — dependency cannot be computed (flag only, no points lost)")

    return (not errors), warnings, errors


# ══════════════════════════════════════════════════════════════════════════
#  LAYER 3b — post-score verification
# ══════════════════════════════════════════════════════════════════════════

SCORE_COLS = [
    "Score_Resilience_Fit", "Score_Measurable_Result",
    "Score_Ability_To_Deliver", "Score_Value_Sustainability",
    "Total_Score", "Semaforo",
]

REASON_COLS = {
    "Resilience_Fit_Reason": "E4 barrier",
    "Measurable_Result_Reason": "E7 formula",
    "Ability_To_Deliver_Reason": "Experience",
    "Value_Sustainability_Reason": "G7 continuity",
}

CAPS = {
    "resilience_fit": 30, "measurable_result": 25,
    "ability_to_deliver": 20, "value_sustainability": 25,
}


def post_score(app, cfg, median=None):
    score = app.get("score", {})
    checks, failures = [], []

    for col in SCORE_COLS:
        if col not in score:
            failures.append(f"missing column {col}")
        else:
            checks.append(f"{col} present")
    if failures:
        return False, checks, failures

    got = {
        "resilience_fit": score.get("Score_Resilience_Fit"),
        "measurable_result": score.get("Score_Measurable_Result"),
        "ability_to_deliver": score.get("Score_Ability_To_Deliver"),
        "value_sustainability": score.get("Score_Value_Sustainability"),
    }

    ref = rescore(app, cfg, median)
    for k in CAPS:
        if got[k] == ref[k]:
            checks.append(f"{k}: {got[k]} matches the independent rescore")
        else:
            failures.append(f"{k}: pipeline={got[k]}, independent={ref[k]}")

    parts_sum = sum(v for v in got.values() if isinstance(v, (int, float)))
    if score.get("Total_Score") == parts_sum:
        checks.append(f"total {parts_sum} equals the sum of the four criteria")
    else:
        failures.append(f"total: pipeline={score.get('Total_Score')}, sum={parts_sum}")

    for k, cap in CAPS.items():
        v = got[k]
        if isinstance(v, (int, float)) and 0 <= v <= cap:
            checks.append(f"{k} {v}/{cap} within range")
        else:
            failures.append(f"{k} {v} outside 0-{cap}")

    mx = score.get("Score_Max_Available", 100)
    if isinstance(score.get("Total_Score"), (int, float)) and 0 <= score["Total_Score"] <= mx:
        checks.append(f"total within 0-{mx}")
    else:
        failures.append(f"total {score.get('Total_Score')} outside 0-{mx}")

    if score.get("Semaforo") == ref["semaforo"]:
        checks.append(f"semáforo {score['Semaforo']} matches the threshold")
    else:
        failures.append(f"semáforo: pipeline={score.get('Semaforo')}, expected={ref['semaforo']}")

    # Dependency must be present as context and must NOT be scored (D5).
    if "Dependency_Note" in score:
        checks.append("dependency reported as a note")
    else:
        failures.append("Dependency_Note missing — the ratio should be surfaced as context")
    vs_reason = score.get("Value_Sustainability_Reason", "")
    if re.search(r"[Dd]ependency[^|]*\(\d+pts\)", vs_reason):
        failures.append("dependency appears to be scoring points — D5 made it a flag")
    else:
        checks.append("dependency scores no points")

    for col, keyword in REASON_COLS.items():
        val = score.get(col, "")
        if not val or len(val) < 20:
            failures.append(f"{col} missing or too short")
        elif keyword.lower() not in val.lower():
            failures.append(f"{col} does not mention {keyword!r}")
        else:
            checks.append(f"{col} present and cites {keyword!r}")

    # Reason arithmetic: the (Npts) fragments in a reason must sum to its score.
    for col, key in (
        ("Resilience_Fit_Reason", "resilience_fit"),
        ("Measurable_Result_Reason", "measurable_result"),
        ("Ability_To_Deliver_Reason", "ability_to_deliver"),
        ("Value_Sustainability_Reason", "value_sustainability"),
    ):
        found = [int(m) for m in re.findall(r"\((?:\+)?(\d+)pts?\)", score.get(col, ""))]
        if len(found) >= 2:
            if sum(found) == got[key]:
                checks.append(f"{col}: {found} sums to {got[key]}")
            else:
                failures.append(f"{col}: fragments sum to {sum(found)}, score is {got[key]}")
        else:
            checks.append(f"{col}: too few fragments to check arithmetic")

    return (not failures), checks, failures


# ══════════════════════════════════════════════════════════════════════════
#  FIXTURES — expected values calculated by hand from the rubric
# ══════════════════════════════════════════════════════════════════════════

_PERFECT_FIELDS = {
    "B1": "Kasi Circular Trust",
    "E1": "Township Merchant Network. Expanding merchant adoption so residents "
          "can spend Bitcoin at nearby shops.",
    # 28 words, names "women" and "merchants", mentions banking/fees/savings
    "E4": "Unbanked women and small merchants face high banking fees and have no "
          "access to savings tools; Bitcoin payments remove those fees for "
          "everyday local trade in the township.",
    "E5": "320",
    "E6": "Unbanked women, small merchants, youth surfers; selected through "
          "existing community programmes and the merchant registry, with a "
          "four-year relationship through the surf academy.",
    "E7": "By December 2027, 80% of 320 participants will complete an unassisted "
          "Bitcoin transaction.",
    "E8": "Participants spend at onboarded merchants in the township; the merchant "
          "cooperative and two employers paying wages in Bitcoin create that "
          "opportunity through listed shops.",
    "E9": "Paying, Receiving payments, Saving",
    "E10": "Merchant onboarding to 60 shops | 2027-04-30 | merchant registry export; "
           "Youth cohort completes training | 2027-08-31 | attendance records; "
           "12-month survey delivered | 2027-12-15 | survey report",
    "E11": "The main risk is merchant turnover and connectivity outages; we will "
           "mitigate by training two staff per shop and monitoring monthly.",
    "F1": "Commerce",
    "F2": "40 merchants transacting as of 2026-12-01",
    "F3": "60 merchants transacting by 2027-12-31",
    "F4": "Merchant registry or BTC Map",
    "F5": "2026: onboarded 40 merchants, 45 surf participants, staff paid in "
          "Bitcoin for 4 years.",
    "G1": "95000",
    "G2": "40000",
    "G3": "Yes. Rights Trust International, 25000, confirmed; Open Grants Fund, 15000, pending",
    "G4": "Program delivery 18000, People and training 12000, Technology 6000, "
          "Monitoring 2500, Administration 1500",
    "G7": "The merchant network and surf academy keep operating after the grant; "
          "the community cooperative sustains it with merchant membership fees "
          "and ongoing funder support.",
    "H1": "1. We have a robust in-house capacity",
    "J1": "In 2026 we promised 30 merchants and reached 40.",
}

_PERFECT_CLEANED = {
    "E5_Participants_Num": 320.0,
    "G1_Total_Budget_Num": 95000.0,
    "G2_Requested_Num": 40000.0,
    "B5_Annual_Budget_Num": 180000.0,
    "G4_Budget_Sum_Valid": "YES",
    "G6_Cost_Per_Participant": 125.0,
    "Dependency_Ratio": 0.2222,
    "E7_Has_Quantity": "YES",
    "E7_Has_Date": "YES",
    "E7_Formula_Complete": "YES",
}

_PERFECT_CLASSIFIED = {
    "Profile": "Establecida",
    "Stage_Suggested": "Local circulation",
    "Measure_Matches_Stage": "YES",
    "Expected_Measures": "Commerce/Remittances",
    "Is_Prior_Grantee": "Yes",
}


def _mut(base, **over):
    out = dict(base)
    out.update(over)
    return out


FIXTURES = [
    {
        "name": "PERFECT",
        "why": "every sub-criterion at full marks, with a cycle median available",
        "median": 100.0,
        "fields": _PERFECT_FIELDS,
        "cleaned": _PERFECT_CLEANED,
        "classified": _PERFECT_CLASSIFIED,
        # barrier 8 + stage 12 + opportunity 10 = 30
        # result 8 + baseline 7 + target 6 + milestones 4 = 25
        # experience 8 + capacity 5 + risks 4 + participants 3 = 20
        # cost 7 + funders 5 + continuity 10 + budget 3 = 25
        "expected": {"resilience_fit": 30, "measurable_result": 25,
                     "ability_to_deliver": 20, "value_sustainability": 25,
                     "total": 100, "max_available": 100, "semaforo": "GREEN"},
    },
    {
        "name": "MEASURE_MISMATCH",
        "why": "identical to PERFECT but F1 sits outside the inferred stage's set, "
               "which must cost exactly the 4 pts of the stage-logic middle third",
        "median": 100.0,
        "fields": _mut(_PERFECT_FIELDS, F1="Recovery"),
        "cleaned": _PERFECT_CLEANED,
        "classified": _mut(_PERFECT_CLASSIFIED, Measure_Matches_Stage="NO"),
        "expected": {"resilience_fit": 26, "measurable_result": 25,
                     "ability_to_deliver": 20, "value_sustainability": 25,
                     "total": 96, "max_available": 100, "semaforo": "GREEN"},
    },
    {
        "name": "RENEWAL_REGISTRY_MISS",
        "why": "declares a 2026 renewal in A3, leaves F5 blank under the short "
               "route, and the registry does NOT match the legal name. The "
               "short route is granted on A3, so the 8 experience points must "
               "be granted on A3 too — J1 carries the numbers. Reading only "
               "the registry scored this 0 and cost 8 points, enough to move "
               "the semaforo, and it fell on exactly the legitimate renewals "
               "whose legal name changed or is spelled differently",
        "median": 100.0,
        "fields": _mut(_PERFECT_FIELDS, A3="Yes, in 2026", F5=""),
        "cleaned": _PERFECT_CLEANED,
        "classified": _mut(_PERFECT_CLASSIFIED, Is_Prior_Grantee="No"),
        # F5 feeds nothing but experience, so a blank F5 with a numeric J1
        # and a declared 2026 renewal must land on the same 8 pts as PERFECT.
        "expected": {"resilience_fit": 30, "measurable_result": 25,
                     "ability_to_deliver": 20, "value_sustainability": 25,
                     "total": 100, "max_available": 100, "semaforo": "GREEN"},
    },
    {
        "name": "COST_DEFERRED",
        "why": "no cycle median, so cost per participant defers: 0 pts and the "
               "maximum drops to 93, with the total normalized back to 100",
        "median": None,
        "fields": _PERFECT_FIELDS,
        "cleaned": _PERFECT_CLEANED,
        "classified": _PERFECT_CLASSIFIED,
        "expected": {"resilience_fit": 30, "measurable_result": 25,
                     "ability_to_deliver": 20, "value_sustainability": 18,
                     "total": 93, "max_available": 93, "semaforo": "GREEN"},
    },
    {
        "name": "WEAK_INITIAL",
        "why": "an individual applying with almost nothing, exercising the "
               "half-credit route for an inexperienced Initial applicant",
        "median": 100.0,
        "fields": {
            "B1": "New Crypto Group",
            "E1": "Crypto Project",
            "E4": "People need money",
            "E5": "",
            "E6": "people",
            "E7": "We will help many people",
            "E8": "They will use it",
            "E9": "",
            "E10": "We will figure it out",
            "E11": "Nothing goes wrong here",
            "F1": "Recovery",
            "F2": "Not sure yet",
            "F3": "A lot more",
            "F4": "Other",
            "F5": "",
            "G1": "100000",
            "G2": "95000",
            "G3": "No",
            "G5": "stuff",
            "G7": "It continues",
            "H1": "3. We do not have the in-house capacity",
            "J1": "",
        },
        "cleaned": {
            "E5_Participants_Num": "",
            "G1_Total_Budget_Num": 100000.0,
            "G2_Requested_Num": 95000.0,
            "B5_Annual_Budget_Num": 100000.0,
            "G4_Budget_Sum_Valid": "CANNOT_VERIFY",
            "G6_Cost_Per_Participant": "",
            "Dependency_Ratio": 0.95,
            "E7_Has_Quantity": "NO",
            "E7_Has_Date": "NO",
            "E7_Formula_Complete": "NO",
        },
        "classified": {
            "Profile": "Inicial",
            "Stage_Suggested": "",
            "Measure_Matches_Stage": "CANNOT_VERIFY",
            "Expected_Measures": "",
            "Is_Prior_Grantee": "No",
        },
        # barrier 0 + stage 0 + opportunity 0 = 0
        # result 0 + baseline 2 + target 0 + milestones 0 = 2
        # experience 4 (half credit) + capacity 1 + risks 0 + participants 0 = 5
        # cost 0 (not computable) + funders 0 + continuity 0 + budget 1 = 1
        "expected": {"resilience_fit": 0, "measurable_result": 2,
                     "ability_to_deliver": 5, "value_sustainability": 1,
                     "total": 8, "max_available": 100, "semaforo": "RED"},
    },
    {
        "name": "EMPTY",
        "why": "nothing at all — every criterion must floor at zero without raising",
        "median": 100.0,
        "fields": {},
        "cleaned": {},
        "classified": {"Profile": "Establecida"},
        "expected": {"resilience_fit": 0, "measurable_result": 0,
                     "ability_to_deliver": 0, "value_sustainability": 0,
                     "total": 0, "max_available": 100, "semaforo": "RED"},
    },
]


def run_fixtures():
    cfg = load_config()
    print("\n" + "=" * 76)
    print("FIXTURES — expected values calculated by hand from the rubric")
    print("=" * 76)

    passed = failed = 0
    for fx in FIXTURES:
        app = {
            "app_id": "FIX-" + fx["name"],
            "fields": fx["fields"],
            "cleaned": fx["cleaned"],
            "classified": fx["classified"],
        }
        ref = rescore(app, cfg, fx["median"])
        exp = fx["expected"]

        print(f"\n--- {fx['name']}")
        print(f"    {fx['why']}")
        ok = True
        for key in ("resilience_fit", "measurable_result", "ability_to_deliver",
                    "value_sustainability", "total", "max_available", "semaforo"):
            got, want = ref[key], exp[key]
            if got == want:
                print(f"  ok   {key:22} {got}")
            else:
                print(f"  FAIL {key:22} expected {want}, got {got}")
                ok = False
        if not ok:
            print("    detail:")
            for k, v in ref["detail"].items():
                print(f"      {k:22} {v}")
        print(f"  {'PASS' if ok else 'FAIL'}  {fx['name']}"
              f"   (normalized {ref['normalized']}/100, {ref['semaforo']})")
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    print("\n" + "=" * 76)
    print(f"FIXTURES: {passed}/{len(FIXTURES)} passed, {failed} failed")
    print("=" * 76)
    return failed == 0


# ══════════════════════════════════════════════════════════════════════════
#  real-data runners
# ══════════════════════════════════════════════════════════════════════════

# A real run directory is named by generate_run_id: YYYYMMDD-HHMMSS. Test
# suites have left other names here (contract-test, regression-test), and
# those sort AFTER every date, so "the latest run" used to be a test folder.
_RUN_DIR_RE = re.compile(r"^\d{8}-\d{6}$")


def latest_run():
    if not RUNS_DIR.exists():
        return None
    runs = sorted(p for p in RUNS_DIR.iterdir()
                  if p.is_dir() and _RUN_DIR_RE.match(p.name))
    return runs[-1] if runs else None


def _load_apps(run_dir, need_scores):
    ingest = run_dir / "ingest.json"
    if not ingest.exists():
        print(f"no ingest.json in {run_dir}")
        return None
    with open(ingest) as fh:
        raw = json.load(fh)
    apps = raw.get("applications", raw) if isinstance(raw, dict) else raw

    for name, key in (("cleaned.json", "cleaned"), ("classified.json", "classified"),
                      ("scored.json", "score")):
        path = run_dir / name
        if not path.exists():
            continue
        with open(path) as fh:
            rows = json.load(fh)
        by_id = {r.get("App_ID"): r for r in rows if isinstance(r, dict)}
        for a in apps:
            match = by_id.get(a.get("app_id"))
            if match:
                a[key] = match

    if need_scores:
        apps = [a for a in apps if a.get("score")]
    return apps


def run_pre_score():
    rd = latest_run()
    if not rd:
        print("no pipeline runs found")
        return False
    apps = _load_apps(rd, need_scores=False)
    if not apps:
        return False
    cfg = load_config()
    print(f"\n{'='*76}\nPRE-SCORE — {len(apps)} applications from {rd.name}\n{'='*76}")
    allok = True
    for a in apps:
        print(f"\n--- {a.get('app_id')}  {a.get('fields', {}).get('B1', '?')}")
        ok, warnings, errors = pre_score(a, cfg)
        for e in errors:
            print(f"  ERROR   {e}")
        for w in warnings:
            print(f"  warn    {w}")
        if not errors and not warnings:
            print("  clean")
        allok = allok and ok
    print(f"\n{'='*76}\nPRE-SCORE: {'PASS' if allok else 'ISSUES'}\n{'='*76}")
    return allok


def run_post_score():
    rd = latest_run()
    if not rd:
        print("no pipeline runs found")
        return False
    apps = _load_apps(rd, need_scores=True)
    if not apps:
        print("no scored applications in the latest run")
        return False
    cfg = load_config()
    print(f"\n{'='*76}\nPOST-SCORE — {len(apps)} applications from {rd.name}\n{'='*76}")
    allok = True
    for a in apps:
        s = a.get("score", {})
        print(f"\n--- {a.get('app_id')}  {s.get('Grantee_Name','?')}  "
              f"({s.get('Total_Score')}/{s.get('Score_Max_Available', 100)}, {s.get('Semaforo')})")
        ok, checks, failures = post_score(a, cfg)
        if failures:
            for fa in failures:
                print(f"  FAIL  {fa}")
            allok = False
        print(f"  {len(checks)} checks passed" + ("" if ok else f", {len(failures)} failed"))
    print(f"\n{'='*76}\nPOST-SCORE: {'PASS' if allok else 'ISSUES'}\n{'='*76}")
    return allok


def main():
    ap = argparse.ArgumentParser(description="v3 scoring verification")
    ap.add_argument("--fixtures", action="store_true")
    ap.add_argument("--pre-score", action="store_true")
    ap.add_argument("--post-score", action="store_true")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if not any([args.fixtures, args.pre_score, args.post_score, args.all]):
        ap.print_help()
        return

    results = []
    if args.fixtures or args.all:
        results.append(("FIXTURES", run_fixtures()))
    if args.pre_score or args.all:
        results.append(("PRE-SCORE", run_pre_score()))
    if args.post_score or args.all:
        results.append(("POST-SCORE", run_post_score()))

    print(f"\n{'='*76}\nSUMMARY\n{'='*76}")
    for name, ok in results:
        print(f"  {name:12} {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
