import assert from "node:assert/strict";
import { saveDraft, loadDraft, makeCode, normalizeCode, CODE_RE } from "../supabase/functions/_shared/drafts.js";
import { randomFillSync } from "node:crypto";
const rnd = (n) => randomFillSync(new Uint8Array(n));
function mem() {
  const rows = new Map(), hits = {};
  return { rows,
    async get(c) { return rows.get(c) || null; },
    async insert(r) { rows.set(r.code, { ...r, updated_at: new Date().toISOString() }); },
    async update(c, p) { rows.set(c, { ...rows.get(c), ...p }); },
    async rateLimited(k, max) { hits[k] = (hits[k] || 0) + 1; return hits[k] > max; } };
}
// code format
for (let i = 0; i < 200; i++) assert.match(makeCode(rnd), CODE_RE);
assert.equal(normalizeCode("ga27 acd-efg hjk"), "GA27-ACD-EFG-HJK");
assert.equal(normalizeCode("nope"), "");
// create, update, load
let st = mem();
let r = await saveDraft(st, { state: { email: "A@B.org", v: { B1: "x" } }, saved_sections: ["A", "bad!"] }, "ip", rnd);
assert.equal(r.status, 200); const code = r.body.code; assert.match(code, CODE_RE);
assert.equal(st.rows.get(code).email, "a@b.org"); assert.deepEqual(st.rows.get(code).saved_sections, ["A"]);
r = await saveDraft(st, { code: code.toLowerCase(), state: { v: { B1: "y" } } }, "ip", rnd);
assert.equal(r.status, 200); assert.equal(r.body.code, code); assert.equal(st.rows.size, 1);
r = await loadDraft(st, { code }, "ip"); assert.equal(r.status, 200); assert.equal(r.body.state.v.B1, "y");
// client cannot invent a code
r = await saveDraft(st, { code: "GA27-AAA-AAA-AAA", state: { v: {} } }, "ip", rnd); assert.equal(r.status, 404); assert.equal(st.rows.size, 1);
// bad / huge state
assert.equal((await saveDraft(st, { state: "x" }, "ip", rnd)).status, 422);
assert.equal((await saveDraft(st, { state: { big: "x".repeat(210000) } }, "ip", rnd)).status, 422);
// expiry
st.rows.get(code).updated_at = new Date(Date.now() - 61 * 864e5).toISOString();
assert.equal((await loadDraft(st, { code }, "ip")).status, 404);
// rate limits
st = mem(); let last;
for (let i = 0; i < 21; i++) last = await loadDraft(st, { code: "GA27-AAA-AAA-AAA" }, "ip");
assert.equal(last.status, 429);
st = mem(); for (let i = 0; i < 11; i++) last = await saveDraft(st, { state: { v: {} } }, "ip", rnd);
assert.equal(last.status, 429);
console.log("drafts: ok");
