# Fix for intake_pipeline.py: match_grantee level 4 (country-boosted match) mis-tokenizes accented names.
#
# Bug: tokens come from re.findall(r'[a-z0-9]+', legal_name.lower()). That regex splits at every accented
# letter: "Fundación" -> "fundaci" + "n", "Asociación" -> "asociaci" + "n", "Medellín" -> "medell" + "n".
# "fundacion" is in domain_common but "fundaci" and "n" are not, so every "Fundación X" in the same country
# as a registered "Fundación Y" shares 2 tokens ({"fundaci", "n"}) = min_overlap -> false MATCH (wrongly
# treated as a returning grantee: reuses its GR id, skips the Drive folder, pulls its registry data).
#
# Fix (3 edits):
#  1) near the other imports at the top:   import unicodedata
#  2) paste this helper at module level, right above `def match_grantee`:
def _name_tokens(s):
    """Lower-case, strip accents, split on non-alphanumerics, drop tokens shorter than 3 characters."""
    s = unicodedata.normalize("NFKD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {t for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 3}
#  3) inside match_grantee, level 4, replace these two lines:
#       app_tokens = set(re.findall(r'[a-z0-9]+', legal_name.lower())) - domain_common
#       reg_tokens = set(re.findall(r'[a-z0-9]+', g["legal_name"].lower())) - domain_common
#     with:
#       app_tokens = _name_tokens(legal_name) - domain_common
#       reg_tokens = _name_tokens(g["legal_name"]) - domain_common
