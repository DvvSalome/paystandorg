#!/usr/bin/env python3
"""Builds dist/intake-function.ts: the whole Edge Function in ONE file, for pasting into the
Supabase Dashboard editor (Edge Functions > Deploy a new function > Via Editor)."""
import re, pathlib
root = pathlib.Path(__file__).resolve().parent.parent
fn = root / "supabase" / "functions"
shim = (fn / "_shared" / "window-shim.js").read_text()
questions = (fn / "_shared" / "questions.js").read_text()
validate = re.sub(r"^export ", "", (fn / "_shared" / "validate.js").read_text(), flags=re.M)
# validate.js imports isEmail from drafts.js; in the single file both are inlined, so the import goes.
validate = re.sub(r'^import \{[^}]*\} from "\./drafts\.js";\n', "", validate, flags=re.M)
drafts = re.sub(r"^export ", "", (fn / "_shared" / "drafts.js").read_text(), flags=re.M)
index = (fn / "intake" / "index.ts").read_text()
index = re.sub(r'^import "\.\./_shared/[^\n]*\n', "", index, flags=re.M)
index = re.sub(r'^import \{[^}]*\} from "\.\./_shared/(validate|drafts)\.js";\n', "", index, flags=re.M)
head, rest = index.split("\n", 1) if False else ("", index)
# keep the supabase-js import at the very top, then shim, questions, validate, then the rest
m = re.search(r'^import \{ createClient \} from "npm:@supabase/supabase-js@2";\n', rest, flags=re.M)
imp, rest = m.group(0), rest.replace(m.group(0), "")
out = imp + "\n// ---- window shim ----\n" + shim + "\n// ---- questions (from site/assets/questions.js) ----\n" + questions + \
      "\n// ---- validation (from supabase/functions/_shared/validate.js) ----\n" + validate + \
      "\n// ---- drafts (from supabase/functions/_shared/drafts.js) ----\n" + drafts + \
      "\n// ---- function ----\n" + rest
(root / "dist").mkdir(exist_ok=True)
(root / "dist" / "intake-function.ts").write_text(out)
print("dist/intake-function.ts", len(out.encode()) // 1024, "KB")
