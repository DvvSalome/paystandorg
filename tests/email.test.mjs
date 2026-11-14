import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { EMAIL_RE, isEmail } from "../supabase/functions/_shared/drafts.js";

// One email rule, enforced in two places that cannot share code: the server
// (drafts.js, imported by the Edge Function) and the browser (form.js). Before
// this there were three different rules and the server checked nothing.
//
// Run: node tests/email.test.mjs

// ── what counts as an address ─────────────────────────────────────────────
const ok = [
  "ana@example.org", "Ana.Ruiz@Example.ORG", "a+grants@sub.domain.co.uk",
  "maria_lopez@fundacion.org.gt", "x@y.io", "  ana@example.org  ",
];
const bad = [
  "", "hola", "ana@", "@example.org", "ana@example", "ana@x.o",
  "ana example@x.org", "ana@@x.org", "ana@x..org", "ana@.org",
  "Ana <ana@x.org>", "ana@x.org, luis@y.org", "a".repeat(195) + "@x.org",
];
for (const e of ok) assert.ok(isEmail(e), `should accept: ${JSON.stringify(e)}`);
for (const e of bad) assert.ok(!isEmail(e), `should reject: ${JSON.stringify(e)}`);
assert.ok(!isEmail(null) && !isEmail(undefined) && !isEmail(42));

// ── the browser carries the identical rule ────────────────────────────────
const form = readFileSync("site/assets/form.js", "utf8");
const m = form.match(/var EMAIL_RE = (\/.+\/);/);
assert.ok(m, "form.js must declare var EMAIL_RE");
assert.equal(
  m[1], EMAIL_RE.toString(),
  "form.js EMAIL_RE differs from supabase/functions/_shared/drafts.js — the " +
  "form would accept addresses the server rejects, or the reverse"
);
// and no other email regex has crept back in
const stray = form.match(/\/\^\[\^@?\\s@?\]\+@[^\n]*\//g) || [];
assert.equal(stray.length, 1, `form.js should have one email regex, found ${stray.length}`);

// ── the server enforces it on submit ──────────────────────────────────────
const index = readFileSync("supabase/functions/intake/index.ts", "utf8");
assert.match(index, /if \(!isEmail\(email\)\)/, "submit must reject a missing or invalid contact email");
const bundle = readFileSync("dist/intake-function.ts", "utf8");
assert.ok(bundle.includes(EMAIL_RE.toString()), "dist/intake-function.ts is stale: rebuild it");
assert.ok(/if \(!isEmail\(email\)\)/.test(bundle), "dist/intake-function.ts is stale: rebuild it");

console.log("email: all checks passed");
