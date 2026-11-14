// Generates eva/data/question_labels.json from site/assets/questions.js.
// Eva writes a copy of each application into the applicant's Drive folder and
// needs the question text the applicant saw, in form order. questions.js is the
// single source; tests/question_labels.test.mjs fails if this file is stale.
// Run: node scripts/gen-question-labels.mjs
import { readFileSync, writeFileSync } from "node:fs";

const w = {};
new Function("window", readFileSync("site/assets/questions.js", "utf8"))(w);
const G = w.GA27;
const out = {
  _generated: "by scripts/gen-question-labels.mjs from site/assets/questions.js — do not edit by hand",
  sections: G.SECTIONS.map((s) => ({ id: s.id, title: s.title })),
  fields: G.FIELDS.map((f) => ({ id: f.id, section: f.s, label: f.label, type: f.type })),
};
writeFileSync("eva/data/question_labels.json", JSON.stringify(out, null, 2) + "\n");
console.log(`eva/data/question_labels.json: ${out.sections.length} sections, ${out.fields.length} fields`);
