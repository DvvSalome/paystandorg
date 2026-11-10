// Server-side validation for a Grant Application 2027 submission.
// Pure JS (no Deno or Node APIs) so it runs in the Edge Function and in node tests.
// Never trust the browser: every rule the form enforces is re-checked here.

export const FILE_QUESTIONS = ["C1", "C2", "I2", "J3"];
export const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED_MIME = ["application/pdf", "image/jpeg", "image/png"];
const EXT = /\.(pdf|jpe?g|png)$/i;
const MAX_STR = 5000;

function words(s) { return s && String(s).trim() ? String(s).trim().split(/\s+/).length : 0; }
function num(x) { const n = parseFloat(String(x == null ? "" : x).replace(/[$,\s]/g, "")); return isNaN(n) ? null : n; }

export function loadQuestions(src) {
  const w = {};
  new Function("window", src)(w);
  return w.GA27;
}

export function deriveState(v) {
  const a1 = v.A1 || "", a2 = v.A2 || "", a3 = v.A3 || "";
  const profile = !a1 && !a2 ? "—" : (a1.indexOf("Individual") === 0 || a2 === "Less than 1 year") ? "Initial" : "Established";
  const route = !a3 ? "—" : a3 === "Yes, in 2026" ? "Renewal" : "New";
  return { profile, route };
}

// Keep only keys that belong to a known question; cap sizes; drop everything else.
export function cleanAnswers(G, raw) {
  const ids = G.FIELDS.map((f) => f.id);
  const out = {};
  if (!raw || typeof raw !== "object") return out;
  for (const k of Object.keys(raw)) {
    const base = k.split("__")[0];
    if (!ids.includes(base)) continue;
    let val = raw[k];
    if (typeof val === "string") val = val.slice(0, MAX_STR);
    else if (Array.isArray(val) || (val && typeof val === "object")) {
      if (JSON.stringify(val).length > 20000) continue;
    } else if (typeof val !== "boolean" && typeof val !== "number") continue;
    out[k] = val;
  }
  return out;
}

export function validate(G, answers, files) {
  const errors = {};
  const v = answers;
  const st = deriveState(v);
  const visible = (f) => { if (!f.showIf) return true; try { return !!f.showIf(v, st); } catch { return true; } };

  for (const f of G.FIELDS) {
    if (!visible(f)) continue;
    const val = v[f.id];
    if (f.req) {
      let ok;
      if (f.req === "all") ok = Array.isArray(val) && val.length >= f.options.length;
      else if (typeof f.req === "number") ok = Array.isArray(val) && val.length >= f.req;
      else ok = typeof val === "string" ? val.trim() !== "" : !!val;
      if (!ok) { errors[f.id] = "required"; continue; }
    }
    if (val == null || val === "") continue;
    if (f.options && (f.type === "radio") && !f.options.includes(val)) errors[f.id] = "invalid option";
    if (f.options && f.type === "checks" && Array.isArray(val) && !val.every((x) => f.options.includes(x))) errors[f.id] = "invalid option";
    if (f.type === "country" && !G.COUNTRIES.includes(val)) errors[f.id] = "unknown country";
    if (f.type === "number" && (num(val) == null || num(val) < (f.min != null ? f.min : 0))) errors[f.id] = "invalid number";
    if (f.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(val)) errors[f.id] = "invalid email";
    if (f.maxWords) {
      const text = v[f.id + "__summary"] != null ? v[f.id + "__summary"] : val;
      if (words(text) > f.maxWords) errors[f.id] = "too long";
    }
  }
  if (v.D1__email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.D1__email)) errors.D1 = "invalid email";
  const dp = v.E2__months; if (v.E2 && !(dp > 0)) errors.E2 = "end date must be after start";

  const g1 = num(v.G1), g2 = num(v.G2);
  if (g1 != null && g2 != null && g2 > g1) errors.G2 = "request larger than total budget";
  const g4 = G.FIELDS.find((f) => f.id === "G4");
  if (g4 && visible(g4) && v.G4 && g2 != null) {
    const cats = v.G4__cats || {}; let sum = 0;
    for (const k of Object.keys(cats)) sum += num(cats[k]) || 0;
    if (Math.abs(sum - g2) >= 1) errors.G4 = "categories must add up to G2";
  }

  // Files: shape, type and size; required file questions must be declared.
  const seen = {};
  for (const f of files || []) {
    if (!FILE_QUESTIONS.includes(f.question)) { errors.files = "unexpected file question"; continue; }
    if (seen[f.question]) { errors.files = "duplicate file"; continue; }
    seen[f.question] = true;
    const q = G.FIELDS.find((x) => x.id === f.question);
    if (!q || !visible(q)) { errors[f.question] = "file not expected"; continue; }
    if (!EXT.test(f.name || "") || !ALLOWED_MIME.includes(f.type)) errors[f.question] = "file must be PDF, JPG or PNG";
    else if (!(f.size > 0) || f.size > MAX_BYTES) errors[f.question] = "file larger than 10 MB";
  }
  for (const f of G.FIELDS) {
    if (f.type === "file" && f.req && visible(f) && !seen[f.id]) errors[f.id] = "required";
  }
  return { errors, ...st };
}

// Text that starts with = + - @ is read as a formula by Google Sheets. Use when mirroring to a Sheet.
export function sheetSafe(s) {
  return typeof s === "string" && /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
}
