#!/usr/bin/env python3
"""
Cross-check: the pipeline's scorer against the verifier's independent rescore.

This is the test that matters. The v2 pair agreed with each other because both
read the same stale field map — agreement alone proves nothing unless the two
implementations were written separately. These were:

  * intake_pipeline.step_score  — one inline block, written first
  * scoring_verify.rescore      — a table of small functions, written from the
                                  rubric in eva-form-field-map-v3-FROZEN.md §4

Both are fed the five hand-calculated fixtures. Three-way agreement — pipeline,
verifier, and the hand calculation — is the actual guarantee.

Usage:  python3 test_crosscheck.py
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
sys.path.insert(0, str(HERE))

import scoring_verify as SV  # noqa: E402

PIPE_FNS = {
    "_parse_one_date", "parse_date_pair", "result_formula_parts",
    "count_words", "parse_number", "has_time_markers_text",
    "normalize_a2", "match_a2_range", "_count_signals",
    "infer_pillar", "infer_stage", "_median", "_has_any", "_count_any",
    "step_score",
}
PIPE_CONSTS = {
    "MIN_PARAGRAPH_WORDS", "_DATE_FORMATS", "_MONTH_WORDS",
    "NUMERIC_FIELDS", "PARAGRAPH_FIELDS", "QUESTION_MAP",
    "VALID_STAGES", "VALID_PILLARS", "VALID_MEASURES",
    "STAGE_SIGNALS", "PILLAR_SIGNALS", "EXPECTED_MEASURES_BY_STAGE",
    "GENERIC_BENEFICIARY_TERMS", "RESULT_FORMULA_FIELD",
    "_PARTNER_TERMS", "_MITIGATION_TERMS", "_RISK_TERMS",
    "_CONTINUITY_WHO", "_CONTINUITY_RESOURCE",
    "_AFFECTED_GROUP_TERMS", "_FINANCIAL_TERMS",
}


def load_pipeline():
    """Pull step_score and its dependencies out by AST, skipping Google imports."""
    tree = ast.parse((HERE / "intake_pipeline.py").read_text())
    keep = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in PIPE_FNS:
            keep.append(node)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in PIPE_CONSTS:
                    keep.append(node)
                    break
    runs = Path(tempfile.mkdtemp())
    (runs / "xcheck").mkdir(parents=True, exist_ok=True)
    ns = {"re": re, "json": json, "time": time, "datetime": datetime, "RUNS_DIR": runs}
    exec(compile(ast.fix_missing_locations(ast.Module(body=keep, type_ignores=[])),
                 "<pipeline>", "exec"), ns)
    return ns


CRITERIA = ("resilience_fit", "measurable_result",
            "ability_to_deliver", "value_sustainability")

PIPE_COLS = {
    "resilience_fit": "Score_Resilience_Fit",
    "measurable_result": "Score_Measurable_Result",
    "ability_to_deliver": "Score_Ability_To_Deliver",
    "value_sustainability": "Score_Value_Sustainability",
}


def main():
    pipe = load_pipeline()
    cfg = SV.load_config()
    failures = []

    print("=" * 78)
    print("CROSS-CHECK — pipeline vs independent verifier vs hand calculation")
    print("=" * 78)

    for fx in SV.FIXTURES:
        name = fx["name"]
        app = {
            "app_id": "FIX-" + name,
            "timestamp": "2027-01-15T10:00:00Z",
            "fields": fx["fields"],
            "cleaned": fx["cleaned"],
            "classified": fx["classified"],
        }

        # The pipeline derives its median from the batch or a config seed, so
        # inject the fixture's median through the config to keep both sides on
        # the same footing.
        cfg_run = json.loads(json.dumps(cfg))
        cfg_run.setdefault("cost_per_participant", {})["median_seed"] = fx["median"]

        out = pipe["step_score"]([dict(app)], cfg_run, "xcheck")
        pscore = out["applications"][0]["score"]
        vscore = SV.rescore(app, cfg, fx["median"])
        hand = fx["expected"]

        print(f"\n--- {name}")
        print(f"{'criterion':24} {'pipeline':>9} {'verifier':>9} {'hand':>6}")
        for key in CRITERIA:
            p = pscore.get(PIPE_COLS[key])
            v = vscore[key]
            h = hand[key]
            mark = "ok " if (p == v == h) else "MISMATCH"
            print(f"{key:24} {p:>9} {v:>9} {h:>6}   {mark}")
            if not (p == v == h):
                failures.append(f"{name}.{key}: pipeline={p} verifier={v} hand={h}")

        for key, col in (("total", "Total_Score"), ("max_available", "Score_Max_Available")):
            p, v, h = pscore.get(col), vscore[key], hand[key]
            mark = "ok " if (p == v == h) else "MISMATCH"
            print(f"{key:24} {p:>9} {v:>9} {h:>6}   {mark}")
            if not (p == v == h):
                failures.append(f"{name}.{key}: pipeline={p} verifier={v} hand={h}")

        p, v, h = pscore.get("Semaforo"), vscore["semaforo"], hand["semaforo"]
        mark = "ok " if (p == v == h) else "MISMATCH"
        print(f"{'semaforo':24} {p:>9} {v:>9} {h:>6}   {mark}")
        if not (p == v == h):
            failures.append(f"{name}.semaforo: pipeline={p} verifier={v} hand={h}")

        # Layer 3 on the pipeline's own output, including the D5 guard
        ok, checks, fails = SV.post_score({**app, "score": pscore}, cfg, fx["median"])
        print(f"{'post-score layer 3':24} {len(checks):>9} checks"
              + ("" if ok else f"   {len(fails)} FAILED"))
        for fa in fails:
            failures.append(f"{name}.post_score: {fa}")

    print("\n" + "=" * 78)
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        for f in failures:
            print("  " + f)
        print("=" * 78)
        return 1
    # Counted, not hardcoded. The literal said "five" after a sixth fixture
    # was added — a suite that misstates its own coverage invites exactly the
    # false confidence it exists to prevent.
    print(f"All three agree on all {len(SV.FIXTURES)} fixtures, and Layer 3 "
          f"passes on pipeline output.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
