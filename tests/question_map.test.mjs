import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Three lists name the same questions and must agree:
//   1. the form's questions          site/assets/questions.js
//   2. Supabase's view map           supabase/eva_question_map.json
//   3. Eva's pipeline QUESTION_MAP   eva/intake_pipeline.py
// If the form gains or loses a question and one of the others is not
// updated, the pipeline reads a column that does not exist or ignores one it
// should read — silently. Removing A4 on 2026-11-13 touched all three.
//
// Run: node tests/question_map.test.mjs

const sb = { window: {} };
new Function("window", readFileSync("site/assets/questions.js", "utf8"))(sb.window);
const formIds = sb.window.GA27.FIELDS.map((f) => f.id).sort();

const map = JSON.parse(readFileSync("supabase/eva_question_map.json", "utf8"));
const mapIds = map.map.map((r) => r[0]).sort();
const mapHeader = Object.fromEntries(map.map);

const py = readFileSync("eva/intake_pipeline.py", "utf8");
const block = py.slice(py.indexOf("QUESTION_MAP = {"), py.indexOf("\n}", py.indexOf("QUESTION_MAP = {")));
const qm = Object.fromEntries([...block.matchAll(/^\s*"([^"]+)":\s*"([^"]+)"/gm)].map((m) => [m[1], m[2]]));
const qmIds = Object.keys(qm).filter((k) => k !== "timestamp").sort();

assert.deepEqual(mapIds, formIds, "supabase/eva_question_map.json does not list the same questions as the form");
assert.deepEqual(qmIds, formIds, "eva/intake_pipeline.py QUESTION_MAP does not list the same questions as the form");
for (const id of formIds) {
  assert.equal(qm[id], mapHeader[id], `column name for ${id} differs between the pipeline and the Supabase map`);
}
assert.equal(qm.timestamp, map.timestamp, "timestamp column name differs");

// the generated view carries exactly these columns
const view = readFileSync("supabase/migrations/20261112000000_eva_view.sql", "utf8");
for (const id of formIds) assert.ok(view.includes(`as "${mapHeader[id]}"`), `view is stale: no column for ${id} — run python3 scripts/gen-eva-view.py`);
assert.ok(!/A4_Requested_Amount/.test(view), "view still has A4 — run python3 scripts/gen-eva-view.py");

console.log(`question map: form, Supabase and pipeline agree on ${formIds.length} questions`);
