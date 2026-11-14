// Save-and-resume drafts. Pure JS (no Deno APIs) so node tests can run it with an in-memory store.
// store = { get(code) -> row|null, insert(row), update(code, patch), delete(code),
//           rateLimited(key, max, windowMinutes) -> Promise<boolean> }
// The server makes the code; the browser can only update a code it already knows.

export const CODE_RE = /^GA27-[A-Z0-9]{3}-[A-Z0-9]{3}-[A-Z0-9]{3}$/;
const ALPHABET = "ACDEFGHJKLMNPQRTUVWXY34789";      // no 0/O, 1/I/L, 2/Z, 5/S, 6/G, 8/B look-alikes
export const MAX_STATE_CHARS = 200_000;

// The one email rule. The browser (site/assets/form.js) carries an identical
// copy because it cannot import this file; tests/email.test.mjs fails if the
// two drift. Before this there were three rules: the form's submit check
// required a dot, the save card did not ("ana@x" passed), and the server
// checked nothing at all — so a direct API call could store "hola" as the
// contact address.
//   local part: no spaces, no @
//   domain: labels without spaces, @ or empty parts, at least one dot,
//           ending in a label of two or more characters
export const EMAIL_RE = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)*\.[^\s@.]{2,}$/;
export function isEmail(x) {
  return typeof x === "string" && x.trim().length <= 200 && EMAIL_RE.test(x.trim());
}
export const MAX_AGE_DAYS = 60;

export function makeCode(randomBytes) {
  const b = randomBytes(9);
  let s = "";
  for (let i = 0; i < 9; i++) s += ALPHABET[b[i] % ALPHABET.length];
  return `GA27-${s.slice(0, 3)}-${s.slice(3, 6)}-${s.slice(6, 9)}`;
}

export function normalizeCode(c) {
  const s = String(c || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
  const m = /^GA27([A-Z0-9]{9})$/.exec(s);
  return m ? `GA27-${m[1].slice(0, 3)}-${m[1].slice(3, 6)}-${m[1].slice(6, 9)}` : "";
}

function cleanState(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const txt = JSON.stringify(raw);
  return txt.length > MAX_STATE_CHARS ? null : raw;
}

// body: { code?, state, saved_sections? }  ->  { status, body }
export async function saveDraft(store, body, ipHash, randomBytes) {
  if (await store.rateLimited("draft:ip:" + ipHash, 60, 60)) return { status: 429, body: { error: "Too many saves. Please wait a few minutes." } };
  const state = cleanState(body && body.state);
  if (!state) return { status: 422, body: { error: "Nothing to save, or the form is too large." } };
  const sections = Array.isArray(body.saved_sections)
    ? body.saved_sections.filter((s) => typeof s === "string" && /^[A-Z0-9]{1,3}$/.test(s)).slice(0, 30) : [];
  const email = isEmail(state.email) ? state.email.trim().toLowerCase() : null;

  if (body.code) {
    const code = normalizeCode(body.code);
    const row = code && (await store.get(code));
    if (!row) return { status: 404, body: { error: "That code was not found. Save again to get a new one." } };
    await store.update(code, { state, saved_sections: sections, email, updated_at: new Date().toISOString() });
    return { status: 200, body: { code } };
  }
  // new draft: cap how many one IP can open per day
  if (await store.rateLimited("draft:new:" + ipHash, 10, 24 * 60)) return { status: 429, body: { error: "Too many new drafts today." } };
  for (let i = 0; i < 5; i++) {
    const code = makeCode(randomBytes);
    if (await store.get(code)) continue;
    await store.insert({ code, state, saved_sections: sections, email });
    return { status: 200, body: { code } };
  }
  return { status: 500, body: { error: "Could not create a code. Please try again." } };
}

export async function loadDraft(store, body, ipHash, now = Date.now()) {
  // 20 tries per hour per IP: the code space (26^9) is not guessable at that rate
  if (await store.rateLimited("draft:load:" + ipHash, 20, 60)) return { status: 429, body: { error: "Too many attempts. Please try again later." } };
  const code = normalizeCode(body && body.code);
  const row = code && (await store.get(code));
  const fresh = row && now - new Date(row.updated_at).getTime() < MAX_AGE_DAYS * 86_400_000;
  if (!fresh) return { status: 404, body: { error: "We could not find a saved application with that code." } };
  return { status: 200, body: { code, state: row.state, saved_sections: row.saved_sections || [], updated_at: row.updated_at } };
}
