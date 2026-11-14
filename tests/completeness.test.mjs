import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { loadQuestions, validate } from "../supabase/functions/_shared/validate.js";

// A question with several parts is answered only when every part it asks for
// is there. Until 2026-11-13 the form and the server both accepted any
// non-empty combined value: a D1 with just a name, an E1 with just a title,
// a G3 of "Yes" with no funder, an E10 with one cell typed.
//
// The rule lives once, in questions.js (GA27.missingParts), which the browser
// and the Edge Function both load. This test drives it directly and through
// the server's validate().
//
// Run: node tests/completeness.test.mjs

const G = loadQuestions(readFileSync("supabase/functions/_shared/questions.js", "utf8"));
const F = Object.fromEntries(G.FIELDS.map((f) => [f.id, f]));
const none = () => false;
const mp = (id, v, hasFile = none) => G.missingParts(F[id], v, hasFile);

// D1 — all four parts
assert.deepEqual(mp("D1", { D1__name: "Ana" }), ["title", "email", "phone or whatsapp"]);
assert.deepEqual(mp("D1", { D1__name: "Ana", D1__title: "Dir", D1__email: "a@x.org", D1__phone: "1" }), []);
assert.deepEqual(mp("D1", { D1__name: "  ", D1__title: "Dir", D1__email: "a@x.org", D1__phone: "1" }), ["full name"],
  "whitespace is not an answer");

// D3 — name, title, email
assert.deepEqual(mp("D3", { D3__name: "Luis", D3__email: "l@x.org" }), ["title"]);

// E1 — title and summary
assert.deepEqual(mp("E1", { E1__title: "Mercados" }), ["summary"]);
assert.deepEqual(mp("E1", { E1__title: "Mercados", E1__summary: "Texto." }), []);

// E10 — three complete milestones
const row = (m, d, e) => ({ milestone: m, date: d, evidence: e });
assert.equal(mp("E10", { E10__rows: [row("Launch", "", "")] }).length, 3,
  "one cell typed leaves all three milestones incomplete");
assert.deepEqual(mp("E10", { E10__rows: [row("a", "2027-03-01", "list"), row("b", "2027-06-01", "list"), row("c", "2027-09-01", "")] }),
  ["milestone 3: evidence"]);
assert.deepEqual(mp("E10", { E10__rows: [row("a", "2027-03-01", "x"), row("b", "2027-06-01", "y"), row("c", "2027-09-01", "z")] }), []);

// G3 — "No", or "Yes" with at least one complete funder and no half rows
assert.deepEqual(mp("G3", {}), ["yes or no"]);
assert.deepEqual(mp("G3", { G3__yn: "No" }), []);
assert.deepEqual(mp("G3", { G3__yn: "Yes", G3__rows: [{}, {}] }), ["at least one funder, with amount and status"]);
assert.deepEqual(mp("G3", { G3__yn: "Yes", G3__rows: [{ funder: "HRF", amount: "", status: "" }, {}] }), ["funder 1: amount, status"]);
assert.deepEqual(mp("G3", { G3__yn: "Yes", G3__rows: [{ funder: "HRF", amount: "5000", status: "pending" }, {}] }), []);

// I2 — (file or commitment) and the person responsible
assert.equal(mp("I2", { I2__person: "Ana" }).length, 1);
assert.deepEqual(mp("I2", { I2__committed: true }), ["name of the person responsible"]);
assert.deepEqual(mp("I2", { I2__person: "Ana" }, (id) => id === "I2"), [], "a file plus a person is complete");
assert.deepEqual(mp("I2", { I2__committed: true, I2__person: "Ana" }), []);

// Questions that already required every part stay as they were
assert.deepEqual(mp("E2", { E2__start: "2027-01-01" }), ["end date"]);
assert.deepEqual(mp("F3", { F3__value: "60" }), ["date"]);
assert.deepEqual(mp("F2", { F2__mode: "plan", F2__plan: "Survey in March" }), []);

// ── the server refuses a partial answer ──────────────────────────────────
const partialD1 = { A1: "Individual", D1: "Ana", D1__name: "Ana" };
const { errors } = validate(G, partialD1, []);
assert.match(errors.D1 || "", /^incomplete: title; email; phone or whatsapp$/,
  "the Edge Function must reject a D1 with only a name");

// ── the server has no email rule of its own any more ─────────────────────
const vjs = readFileSync("supabase/functions/_shared/validate.js", "utf8");
assert.ok(!/\/\^\[\^@\\s\]\+@/.test(vjs), "validate.js must use isEmail, not its own regex");

console.log("completeness: all checks passed");
