import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// Guard for the question definitions. Two classes of regression, both of
// which have already happened once in this repo:
//
//   1. The browser and the Edge Function validate from separate copies of
//      questions.js. Editing site/assets/questions.js without running
//      scripts/sync-questions.sh leaves the server validating different
//      rules than the client, which surfaces in production as a submission
//      the form accepted and the API rejected, with no useful message.
//      This drifted on 2026-11-13 and was caught by hand.
//
//   2. The eligibility checklist (0.2) carried req: "all", which blocked an
//      applicant at three of four boxes — while its own help text, K2's
//      visibility rule, and Eva's eligibility gate all expected them to be
//      able to continue with a written explanation. Three pieces built a
//      path; one field property closed it.
//
// Run: node tests/questions.test.mjs

const SRC = "site/assets/questions.js";
const SHARED = "supabase/functions/_shared/questions.js";
const BUNDLE = "dist/intake-function.ts";

const load = (p) => readFileSync(p, "utf8");

function fields(src) {
  const sandbox = { window: {} };
  new Function("window", src)(sandbox.window);
  return sandbox.window.GA27;
}

// ── 1. the copies cannot drift ────────────────────────────────────────────

// sync-questions.sh is a plain cp, so byte equality is the contract.
assert.equal(
  load(SRC), load(SHARED),
  `${SHARED} differs from ${SRC}. Run scripts/sync-questions.sh — the Edge ` +
  `Function validates from its own copy, and a stale one makes the server ` +
  `reject what the browser accepted.`
);

// The bundle inlines _shared/, so every field's validation signature has to
// survive the build. Compared as a set of id/type/req triples rather than as
// text, so unrelated formatting in the bundle does not fail the test.
const sig = (s) =>
  [...s.matchAll(/\{\s*id:\s*"([^"]+)",\s*s:\s*"([^"]+)",\s*type:\s*"([^"]+)"(?:,\s*req:\s*([^,}\s]+))?/g)]
    .map((m) => `${m[1]}|${m[3]}|${m[4] ?? "-"}`)
    .sort();

const sigSrc = sig(load(SRC));
const sigBundle = sig(load(BUNDLE));
assert.ok(sigSrc.length >= 60, `expected 60+ field signatures, got ${sigSrc.length}`);
assert.deepEqual(
  sigBundle, sigSrc,
  `${BUNDLE} is stale. Run python3 scripts/build-function-single.py after ` +
  `syncing — the dashboard deploys from this file.`
);

// ── 2. the question count is 60 ───────────────────────────────────────────

const G = fields(load(SRC));
assert.equal(
  G.FIELDS.length, 60,
  "60 questions. QUESTION_MAP has 61 because it includes Timestamp, and the " +
  "form specification lists 61 because it includes G6, a computed value. " +
  "Neither is a question. If this number changed on purpose, update the " +
  "header comment, the spec and QUESTION_MAP together."
);

const byId = Object.fromEntries(G.FIELDS.map((f) => [f.id, f]));

// ── 3. the eligibility path stays open ────────────────────────────────────

const elig = byId["0.2"];
const k2 = byId["K2"];
assert.ok(elig && k2, "0.2 and K2 must both exist");

assert.notEqual(
  elig.req, "all",
  '0.2 must not require all four boxes. It did until 2026-11-13, which ' +
  'blocked an applicant at three of four — while the help text, K2.showIf ' +
  'and Eva\'s eligibility gate all expected them to continue and explain. ' +
  'K2 carries the accountability: it is required whenever fewer than four ' +
  'are checked.'
);

assert.equal(k2.req, true, "K2 must stay required — it is what replaces req:all on 0.2");
assert.equal(typeof k2.showIf, "function", "K2 must stay conditional");

// K2 has to appear in every state where fewer than four boxes are ticked,
// otherwise relaxing 0.2 would let an unexplained application through.
for (let n = 0; n <= 4; n++) {
  const v = { "0.2": elig.options.slice(0, n), K1: ["None"] };
  assert.equal(
    k2.showIf(v), n < 4,
    `with ${n} of 4 eligibility boxes checked, K2 should ` +
    `${n < 4 ? "appear" : "stay hidden"}`
  );
}

// K2 also has to appear for a disclosure, independently of 0.2.
assert.equal(
  k2.showIf({ "0.2": elig.options.slice(), K1: ["Conflict of interest"] }), true,
  "K2 must appear when K1 has a disclosure, even with all eligibility boxes checked"
);

// The end-to-end matrix, using the same rule both validators apply.
const blocks = (f, v) => {
  if (f.req === "all") return !v || v.length < f.options.length;
  if (f.req === 1) return !v || v.length < 1;
  if (f.req === true) return !v || !String(v).trim();
  return false;
};
const canSubmit = (checks, k2text) => {
  const v = { "0.2": checks, K1: ["None"], K2: k2text };
  if (blocks(elig, checks)) return false;
  if (k2.showIf(v) && blocks(k2, k2text)) return false;
  return true;
};
const all4 = elig.options.slice();
const three = elig.options.slice(0, 3);
assert.equal(canSubmit(all4, ""), true, "four checked should submit");
assert.equal(canSubmit(three, ""), false, "three checked with no explanation must be blocked");
assert.equal(canSubmit(three, "We are a cooperative; point 2 does not apply."), true,
  "three checked WITH an explanation must submit — this is the case that was impossible");
assert.equal(canSubmit([], "We cannot certify any of these yet."), true,
  "none checked with an explanation should submit and land in manual review");

// ── 4. the assertions that must stay mandatory ────────────────────────────

// K3 and K4 are things the applicant asserts, not facts they might not
// satisfy. Relaxing 0.2 must not become a precedent for relaxing these.
for (const id of ["K3", "K4"]) {
  assert.equal(
    byId[id]?.req, "all",
    `${id} must keep req: "all" — certification and data consent are ` +
    `assertions, not conditions that can be explained away`
  );
}

// ── 5. conditional fields stay conditional ────────────────────────────────

// The renewal short route and the organisation-only questions depend on
// these staying conditional; making one unconditional would ask an
// individual for their registration number.
const mustBeConditional = ["A1b", "B5", "B7", "B8", "C3", "D3", "G4", "G5",
                           "I2", "J1", "J2", "J3", "K2"];
for (const id of mustBeConditional) {
  assert.equal(
    typeof byId[id]?.showIf, "function",
    `${id} must stay conditional`
  );
}
assert.equal(
  G.FIELDS.filter((f) => typeof f.showIf === "function").length,
  mustBeConditional.length,
  `exactly ${mustBeConditional.length} fields should be conditional; if that ` +
  `changed on purpose, update this list and the counts in the header comment ` +
  `(an individual sees 49, a new organisation 53, a 2026 renewal 58)`
);

console.log("questions: all checks passed");
