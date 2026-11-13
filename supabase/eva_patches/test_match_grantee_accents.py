"""Reproduces the bug with the exact match_grantee Eva pasted, then checks the fix. No Eva files needed."""
import re, sys, unicodedata

def norm_org_name(s):                      # stand-in: levels 1-3 never fire for the names used here
    return re.sub(r"[^a-z0-9]", "", str(s).lower())

DOMAIN_COMMON = {"bitcoin", "btc", "crypto", "foundation", "fundacion", "initiative", "project", "program", "org",
                 "organization", "the", "of", "and", "for", "in", "de", "la", "el", "los", "las", "en", "inc", "llc"}

def level4(legal_name, country, registry, tokens):
    """Level 4 of match_grantee, verbatim except for the tokenizer, which is injected."""
    country_lower = country.lower().strip()
    app_tokens = tokens(legal_name) - DOMAIN_COMMON
    for g in registry:
        g_country = str(g.get("country", "")).lower().strip()
        if g_country and country_lower in g_country:
            reg_tokens = tokens(g["legal_name"]) - DOMAIN_COMMON
            if app_tokens and reg_tokens:
                overlap = app_tokens & reg_tokens
                min_overlap = max(2, min(len(app_tokens), len(reg_tokens)) // 2)
                if len(overlap) >= min_overlap:
                    return g["grantee_id"]
    return None

old_tokens = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))
ns = {"re": re, "unicodedata": unicodedata}
exec(open(__file__.replace("test_", "")).read().split("def _name_tokens")[1].join(["def _name_tokens", ""]).split("#  3)")[0], ns)
new_tokens = ns["_name_tokens"]

reg = [{"grantee_id": "GR-2026-015", "legal_name": "Fundación Mi Tierra Digital", "country": "Colombia"},
       {"grantee_id": "GR-2026-020", "legal_name": "Asociación Bitcoin Cali", "country": "Colombia"}]
cases = [
  ("demo del ensayo: Fundación Semillas Digitales vs Fundación Mi Tierra Digital", "Fundación Semillas Digitales (DEMO)", "Colombia"),
  ("otra Asociación en el mismo país", "Asociación Nodo Medellín", "Colombia"),
  ("renovación legítima por tokens (SAS)", "Mi Tierra Digital S.A.S.", "Colombia"),
  ("mismo nombre sin tilde", "Fundacion Mi Tierra Digital", "Colombia"),
  ("otro país: no debe emparejar", "Fundación Semillas Digitales", "Peru"),
]
expected_new = [None, None, "GR-2026-015", "GR-2026-015", None]
ok = True
print(f"{'caso':<66}{'antes':<14}{'después':<14}")
for (label, name, country), exp in zip(cases, expected_new):
    before, after = level4(name, country, reg, old_tokens), level4(name, country, reg, new_tokens)
    flag = "OK " if after == exp else "FAIL"; ok &= after == exp
    print(f"{flag} {label:<62}{str(before):<14}{str(after):<14}")
bug_reproduced = level4(cases[0][1], cases[0][2], reg, old_tokens) == "GR-2026-015" and level4(cases[1][1], cases[1][2], reg, old_tokens) == "GR-2026-020"
print("\nbug reproducido con el código original:", bug_reproduced)
sys.exit(0 if ok and bug_reproduced else 1)
