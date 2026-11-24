// Read-only access for the Paystand team (dashboard at site/admin/). Pure JS, testable in node.
// Access = one personal code per person, kept in the Edge Function secret ADMIN_CODES:
//   "ana:long-random-code,luis:another-long-code"   (name:code, comma separated)
// Codes shorter than 16 characters are ignored, so a weak one cannot be set by mistake.

export const MIN_CODE_LEN = 16;
export const MAX_APPS = 1000;

export function parseCodes(secret) {
  const out = [];
  for (const part of String(secret || "").split(",")) {
    const i = part.indexOf(":");
    if (i < 1) continue;
    const name = part.slice(0, i).trim(), code = part.slice(i + 1).trim();
    if (name && code.length >= MIN_CODE_LEN) out.push({ name, code });
  }
  return out;
}

// Constant-time comparison of hashes: never compare the codes themselves with ===.
function sameHash(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}
// sha256: async (string) -> hex. Returns the person's name, or null.
export async function findViewer(codes, provided, sha256) {
  const p = String(provided || "");
  if (!p || p.length > 200) return null;
  const hp = await sha256(p);
  let who = null;
  for (const c of codes) if (sameHash(await sha256(c.code), hp)) who = c.name;   // no early exit
  return who;
}

// One application as the dashboard needs it. `files` rows come from application_files.
export function shapeApplication(row, files) {
  return {
    application_id: row.application_id,
    finalized_at: row.finalized_at,
    created_at: row.created_at,
    profile: row.profile || null,
    route: row.route || null,
    answers: row.answers || {},
    files: (files || []).map((f) => ({ question: f.question, name: f.file_name, size: f.size_bytes, type: f.mime_type })),
  };
}

export function groupFiles(rows) {
  const by = {};
  for (const f of rows || []) (by[f.application_id] = by[f.application_id] || []).push(f);
  return by;
}
