import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Eva's copy of each application (the "Solicitud" Google Doc in the
// applicant's folder) takes its question text from eva/data/question_labels.json.
// A stale file would print last week's wording next to this week's answers.
// Regenerate with: node scripts/gen-question-labels.mjs

const w = {};
new Function("window", readFileSync("site/assets/questions.js", "utf8"))(w);
const G = w.GA27;
const L = JSON.parse(readFileSync("eva/data/question_labels.json", "utf8"));

assert.deepEqual(
  L.sections, G.SECTIONS.map((s) => ({ id: s.id, title: s.title })),
  "eva/data/question_labels.json sections are stale: run node scripts/gen-question-labels.mjs"
);
assert.deepEqual(
  L.fields, G.FIELDS.map((f) => ({ id: f.id, section: f.s, label: f.label, type: f.type })),
  "eva/data/question_labels.json fields are stale: run node scripts/gen-question-labels.mjs"
);
console.log(`question labels: ${L.fields.length} fields match questions.js`);
