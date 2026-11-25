import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { parseCodes, findViewer, shapeApplication, groupFiles } from "../supabase/functions/_shared/admin.js";
const sha = async (s) => createHash("sha256").update(s).digest("hex");
const codes = parseCodes("ana:abcdefghijklmnop, luis : 1234567890abcdefgh ,corto:abc,sinpuntos,:vacio1234567890123");
assert.deepEqual(codes.map((c) => c.name), ["ana", "luis"]);               // short / malformed entries are dropped
assert.equal(parseCodes("").length, 0); assert.equal(parseCodes(undefined).length, 0);
assert.equal(await findViewer(codes, "abcdefghijklmnop", sha), "ana");
assert.equal(await findViewer(codes, "1234567890abcdefgh", sha), "luis");
assert.equal(await findViewer(codes, "ABCDEFGHIJKLMNOP", sha), null);       // case matters
assert.equal(await findViewer(codes, "", sha), null);
assert.equal(await findViewer(codes, "x".repeat(500), sha), null);
assert.equal(await findViewer([], "abcdefghijklmnop", sha), null);
const f = groupFiles([{ application_id: "A", question: "C1" }, { application_id: "A", question: "C2" }, { application_id: "B", question: "C1" }]);
assert.equal(f.A.length, 2);
const s = shapeApplication({ application_id: "A", answers: { B1: "x" }, finalized_at: "t", secret_hash: "no" }, [{ question: "C1", file_name: "a.pdf", size_bytes: 3, mime_type: "application/pdf", storage_path: "A/C1-a.pdf" }]);
assert.deepEqual(Object.keys(s).sort(), ["answers", "application_id", "created_at", "files", "finalized_at", "profile", "route"]);
assert.equal(s.files[0].storage_path, undefined);                            // storage paths never leave the server
console.log("admin: ok");

// drafts
import { shapeDraft } from "../supabase/functions/_shared/admin.js";
const old = shapeDraft({ code: "GA27-AAA-BBB-CCC", email: "a@b.org", created_at: "c", updated_at: "u", saved_sections: ["A"], state: { v: 1, fields: { B1: ["x"] }, files: { C1: "a.pdf" } } }, "abc123");
assert.equal(JSON.stringify(old).includes("GA27-"), false);                 // the resume code never leaves the server
assert.deepEqual(old.fields, { B1: ["x"] }); assert.equal(old.answers, null); assert.deepEqual(old.files, { C1: "a.pdf" });
const neu = shapeDraft({ code: "GA27-AAA-BBB-CCC", state: { fields: { B1: ["x"] }, answers: { B1: "x" } } }, "id2");
assert.deepEqual(neu.answers, { B1: "x" }); assert.equal(neu.fields, null);   // answers present: the control dump is dropped
const bad = shapeDraft({ code: "x", state: "nope", saved_sections: null }, "id3");
assert.deepEqual([bad.fields, bad.answers, bad.saved_sections, bad.files], [{}, null, [], {}]);
console.log("admin drafts: ok");
