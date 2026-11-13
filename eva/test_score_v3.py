#!/usr/bin/env python3
"""
Smoke test for the v3 4-criteria scorer.

Extracts step_score and its dependencies from intake_pipeline.py by AST so the
test runs without the Google client libraries installed. This is a wiring and
sanity check, not the independent verification — that lives in scoring_verify.py
and must stay a separate reimplementation.

Usage:  python3 test_score_v3.py
"""
import ast
import json
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent

WANT_FN = {
    "_parse_one_date", "parse_date_pair", "result_formula_parts",
    "count_words", "parse_number", "has_time_markers_text",
    "normalize_a2", "match_a2_range", "_count_signals",
    "infer_pillar", "infer_stage", "_median", "_has_any", "_count_any",
    "step_score",
}
WANT_CONST = {
    "MIN_PARAGRAPH_WORDS", "_DATE_FORMATS", "_MONTH_WORDS",
    "NUMERIC_FIELDS", "PARAGRAPH_FIELDS", "QUESTION_MAP",
    "VALID_STAGES", "VALID_PILLARS", "VALID_MEASURES",
    "STAGE_SIGNALS", "PILLAR_SIGNALS", "EXPECTED_MEASURES_BY_STAGE",
    "GENERIC_BENEFICIARY_TERMS", "RESULT_FORMULA_FIELD",
    "_PARTNER_TERMS", "_MITIGATION_TERMS", "_RISK_TERMS",
    "_CONTINUITY_WHO", "_CONTINUITY_RESOURCE",
    "_AFFECTED_GROUP_TERMS", "_FINANCIAL_TERMS",
}


def load_pipeline_namespace():
    tree = ast.parse((HERE / "intake_pipeline.py").read_text())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in WANT_FN:
            keep.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in WANT_CONST:
                    keep.append(node)
                    break
    runs_dir = Path(tempfile.mkdtemp())
    (runs_dir / "testrun").mkdir(parents=True, exist_ok=True)
    ns = {
        "re": re, "json": json, "time": time, "datetime": datetime,
        "RUNS_DIR": runs_dir,
    }
    mod = ast.Module(body=keep, type_ignores=[])
    exec(compile(ast.fix_missing_locations(mod), "<pipeline>", "exec"), ns)
    return ns


def make_app(app_id, fields, profile="Establecida"):
    """Build an app dict the way steps 1-4 would leave it."""
    ns = NS
    cleaned = {}

    # mirror the numeric parsing step_clean performs
    for fid, col in (("B5", "B5_Annual_Budget_Num"), ("E5", "E5_Participants_Num"),
                     ("G1", "G1_Total_Budget_Num"), ("G2", "G2_Requested_Num")):
        v, ok = ns["parse_number"](fields.get(fid, ""))
        cleaned[col] = v if v is not None else ""

    has_q, has_d = ns["result_formula_parts"](fields.get("E7", ""))
    cleaned["E7_Has_Quantity"] = "YES" if has_q else "NO"
    cleaned["E7_Has_Date"] = "YES" if has_d else "NO"
    cleaned["E7_Formula_Complete"] = "YES" if (has_q and has_d) else "NO"

    g2 = cleaned.get("G2_Requested_Num")
    e5 = cleaned.get("E5_Participants_Num")
    b5 = cleaned.get("B5_Annual_Budget_Num")
    cleaned["G6_Cost_Per_Participant"] = (
        round(g2 / e5, 2) if isinstance(g2, float) and isinstance(e5, float) and e5 > 0 else ""
    )
    cleaned["Dependency_Ratio"] = (
        round(g2 / b5, 4) if isinstance(g2, float) and isinstance(b5, float) and b5 > 0 else ""
    )

    g4_nums = re.findall(r"[\d,]+\.?\d*", str(fields.get("G4", "")))
    g4_sum = sum(float(n.replace(",", "")) for n in g4_nums) if g4_nums else None
    if g4_sum is not None and isinstance(g2, float):
        diff = round(g4_sum - g2, 2)
        cleaned["G4_Budget_Sum_Valid"] = "YES" if abs(diff) < 1 else "NO"
        cleaned["G4_Budget_Sum_Diff"] = diff
    else:
        cleaned["G4_Budget_Sum_Valid"] = "CANNOT_VERIFY"

    start, end, months = ns["parse_date_pair"](fields.get("E2", ""))
    cleaned["E2_Duration_Months"] = months if months is not None else ""

    # mirror step_classify
    stage, stage_just, _ = ns["infer_stage"](fields)
    # infer_pillar devuelve 4 valores desde 2026-11-11: un proyecto puede
    # tener más de un pilar y la lista completa viaja aparte del primario.
    pillar, pillar_just, _, pillars_all = ns["infer_pillar"](fields)
    f1 = fields.get("F1", "").strip()
    expected = ns["EXPECTED_MEASURES_BY_STAGE"].get(stage, []) if stage else []
    if stage and f1:
        match = "YES" if f1 in expected else "NO"
    else:
        match = "CANNOT_VERIFY"
    a3 = fields.get("A3", "")
    classified = {
        "Profile": profile,
        "Stage_Suggested": stage or "",
        "Stage_Justification": stage_just,
        "Pillar": pillar or "",
        "Pillars_All": ", ".join(pillars_all),
        "Pillar_Count": len(pillars_all),
        "Pillar_Justification": pillar_just,
        "Measure_Matches_Stage": match,
        "Expected_Measures": "/".join(expected),
        "Is_Prior_Grantee": "Yes" if a3.lower().startswith("yes") else "No",
    }
    return {"app_id": app_id, "timestamp": "2027-01-15T10:00:00Z",
            "fields": fields, "cleaned": cleaned, "classified": classified}


# Organización FICTICIA. La versión anterior usaba el nombre, la persona de
# contacto y el correo reales de un grantee del padrón. Un fixture no necesita
# datos de una persona real, y estos archivos pueden terminar en un repo
# público o compartirse fuera del equipo. Se mantiene la FORMA de los datos
# —país, montos, prosa densa— que es lo único que la prueba necesita.
STRONG = {
    "A1": "Organization", "A1b": "Nonprofit / NGO", "A2": "More than 3 years",
    "A3": "Yes, in 2026",
    "B1": "Kasi Circular Trust", "B2": "South Africa", "B3": "Thandi Mokoena",
    "B4": "12 Main Road, Mossel Bay, Western Cape, 6500", "B5": "180000",
    "B6": "https://kasicirculartrust.example.org",
    "C1": "registration.pdf", "C2": "w8ben-e.pdf",
    "D1": "Thandi Mokoena, Director, director@kasicirculartrust.example.org, "
          "+27 11 555 0100",
    "D2": "Yes",
    "E1": "Township Circular Economy Expansion. Deepening merchant adoption "
          "and youth financial literacy through daily education and real use.",
    "E2": "2027-01-15 to 2027-12-31",
    "E3": "South Africa, Mossel Bay, JCC Camp",
    "E4": "Township residents and small merchants face high remittance and "
          "banking fees, and unbanked women have no access to savings tools; "
          "Bitcoin payments remove those fees for everyday local trade.",
    "E5": "320",
    "E6": "Unbanked women, small merchants, youth surfers; selected through "
          "existing community programmes and merchant registry, with a four-year "
          "ongoing relationship through the surf academy.",
    "E7": "By December 2027, 80% of 320 participants will complete an unassisted "
          "Bitcoin transaction.",
    "E8": "Participants spend at onboarded merchants in the township; the local "
          "merchant cooperative and two employers paying wages in Bitcoin create "
          "that opportunity through BTC Map listed shops.",
    "E9": "Paying, Receiving payments, Saving",
    "E10": "Merchant onboarding to 60 shops | 2027-04-30 | merchant registry export; "
           "Youth cohort completes training | 2027-08-31 | attendance records and "
           "certificates; 12-month survey delivered | 2027-12-15 | survey report",
    "E11": "The main risk is merchant turnover and connectivity outages; we will "
           "mitigate by training two staff per shop and monitoring monthly.",
    "F1": "Commerce", "F2": "40 merchants transacting as of 2026-12-01",
    "F3": "60 merchants transacting by 2027-12-31",
    "F4": "Merchant registry or BTC Map",
    "F5": "2026: onboarded 40 merchants, 45 surf participants, staff paid 100% in "
          "BTC for 4.5 years, 10 children in the literacy cohort.",
    "G1": "95000", "G2": "40000",
    "G3": "Yes. Rights Trust International, 25000, confirmed; Open Grants Fund, 15000, pending",
    "G4": "Program delivery 18000, People and training 12000, Technology 6000, "
          "Monitoring and safeguarding 2500, Administration 1500",
    "G7": "The merchant network and surf academy keep operating after the grant; "
          "the community cooperative sustains it with merchant membership fees and "
          "ongoing HRF funding.",
    "H1": "1. We have a robust in-house capacity",
    "I1": "Directly", "I2": "safeguarding-policy.pdf; Thandi Mokoena",
    "J1": "In 2026 we promised 30 merchants and reached 40; promised 40 surf "
          "participants and reached 45.",
    "K1": "None", "K3": "Yes", "K4": "Yes", "K5": "Thandi Mokoena, 2027-01-15",
}

WEAK = {
    "A1": "Individual", "A2": "Less than 1 year", "A3": "No",
    "B1": "New Crypto Group", "B2": "USA", "B3": "Someone", "B4": "Somewhere",
    "B5": "", "B6": "not-a-url",
    "E1": "Crypto Project", "E2": "soon", "E3": "TBD",
    "E4": "People need money", "E5": "", "E6": "people",
    "E7": "We will help many people",
    "E8": "They will use it", "E9": "",
    "E10": "We will figure it out",
    "E11": "Nothing will go wrong",
    "F1": "Recovery", "F2": "Not sure yet", "F3": "A lot more",
    "F4": "Other", "F5": "",
    "G1": "100000", "G2": "95000", "G3": "No",
    "G4": "", "G5": "stuff",
    "G7": "It will continue",
    "H1": "3. We do not have the in-house capacity",
    "I1": "No", "K1": "None", "K3": "Yes", "K4": "Yes", "K5": "x",
}

MID = dict(STRONG)
MID.update({
    "B1": "Bitcoin Arusha", "A2": "1–3 years", "A3": "No", "J1": "",
    "F5": "Distributed 60 pads to 2 schools, 2 women producing pads.",
    "G3": "Yes. Local donor, 5000, pending",
    "G2": "30000", "B5": "45000",
    "H1": "2. We have some in-house capacity",
    "E9": "Paying",
    "F1": "Skills",
})

STAGE_INFERENCE = dict(STRONG)
STAGE_INFERENCE.update({
    "B1": "Primera Escuela Bitcoin",
    "E1": "Bitcoin education curriculum for schools",
    "E4": "Students and teachers lack financial literacy and have no access to "
          "savings; Bitcoin education gives them practical money skills.",
    "E8": "Graduates teach their own classes at partner schools; the school "
          "network and teacher cooperative create that opportunity.",
    "E9": "Saving",
    "F1": "Commerce",   # deliberately wrong for an Awareness-stage project
    "F2": "0 teachers certified as of 2026-12-01",
    "F3": "500 teachers certified by 2027-12-31",
})


def run():
    global NS
    NS = load_pipeline_namespace()
    cfg = json.loads((HERE / "data" / "scorecard_config.json").read_text())

    apps = [
        make_app("APP-20271115-001", STRONG, "Establecida"),
        make_app("APP-20271115-002", WEAK, "Inicial"),
        make_app("APP-20271115-003", MID, "Establecida"),
        make_app("APP-20271115-004", STAGE_INFERENCE, "Establecida"),
    ]

    result = NS["step_score"](apps, cfg, "testrun")
    rows = [a["score"] for a in result["applications"]]

    print("=" * 78)
    print("v3 SCORER — 4 criteria (Resilience 30 / Measurable 25 / Deliver 20 / Value 25)")
    print("=" * 78)

    failures = []
    for r in rows:
        rf = r["Score_Resilience_Fit"]
        mr = r["Score_Measurable_Result"]
        ad = r["Score_Ability_To_Deliver"]
        vs = r["Score_Value_Sustainability"]
        tot, mx = r["Total_Score"], r["Score_Max_Available"]

        print(f"\n── {r['App_ID']}  {r['Grantee_Name']}  [{r['Profile']}]")
        print(f"   Resilience fit        {rf:>3}/30")
        print(f"   Measurable result     {mr:>3}/25")
        print(f"   Ability to deliver    {ad:>3}/20")
        print(f"   Value/sustainability  {vs:>3}/25")
        print(f"   TOTAL {tot}/{mx}   normalized {r['Total_Normalized']}/100   {r['Semaforo']}")

        # invariants
        if rf + mr + ad + vs != tot:
            failures.append(f"{r['App_ID']}: parts {rf+mr+ad+vs} != total {tot}")
        for name, val, cap in (("resilience", rf, 30), ("measurable", mr, 25),
                               ("deliver", ad, 20), ("value", vs, 25)):
            if not 0 <= val <= cap:
                failures.append(f"{r['App_ID']}: {name} {val} outside 0-{cap}")
        if not 0 <= tot <= mx:
            failures.append(f"{r['App_ID']}: total {tot} outside 0-{mx}")
        for col in ("Resilience_Fit_Reason", "Measurable_Result_Reason",
                    "Ability_To_Deliver_Reason", "Value_Sustainability_Reason"):
            if not r.get(col) or len(r[col]) < 20:
                failures.append(f"{r['App_ID']}: {col} missing or too short")

    # ordering sanity: STRONG should beat MID should beat WEAK
    by_id = {r["App_ID"]: r["Total_Normalized"] for r in rows}
    strong, mid, weak = (by_id["APP-20271115-001"], by_id["APP-20271115-003"],
                         by_id["APP-20271115-002"])
    print("\n" + "=" * 78)
    print(f"ordering: strong {strong} > mid {mid} > weak {weak}")
    if not (strong > mid > weak):
        failures.append(f"ordering violated: {strong} / {mid} / {weak}")

    # the stage-inference fixture must detect the F1/stage mismatch
    si = next(a for a in result["applications"] if a["app_id"] == "APP-20271115-004")
    cl = si["classified"]
    print(f"stage inference: inferred={cl['Stage_Suggested']!r} "
          f"F1={si['fields']['F1']!r} expected={cl['Expected_Measures']!r} "
          f"match={cl['Measure_Matches_Stage']}")
    if cl["Measure_Matches_Stage"] != "NO":
        failures.append("STAGE_INFERENCE fixture should flag an F1/stage mismatch")

    print("=" * 78)
    if failures:
        print(f"❌ {len(failures)} FAILURE(S)")
        for x in failures:
            print(f"   {x}")
        return 1
    print("✅ all invariants hold")
    return 0


if __name__ == "__main__":
    sys.exit(run())
