// Edge Function "intake": receives Grant Application 2027 submissions.
//   POST /submit    -> validates, stores answers, returns signed upload URLs
//   POST /finalize  -> checks uploads arrived, marks complete, sends confirmation email
//   POST /draft/save, /draft/load -> save and resume an unfinished application with a code
//   POST /admin/list, /admin/drafts, /admin/file -> read-only dashboard for the Paystand team (header x-admin-code)
// Secrets (set with `supabase secrets set`, never in the repo):
//   TURNSTILE_SECRET   optional until the captcha is enabled
//   RESEND_API_KEY, EMAIL_FROM   optional, confirmation email
//   ALLOWED_ORIGINS    comma-separated, e.g. https://apply.example.org
//   ADMIN_CODES        "name:code,name:code", one long random code per person (16+ chars)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected by Supabase.
import { createClient } from "npm:@supabase/supabase-js@2";
import "../_shared/window-shim.js";   // must stay before questions.js
import "../_shared/questions.js";      // bundled as a module, so it ships with the deploy
import { cleanAnswers, validate } from "../_shared/validate.js";
import { isEmail, loadDraft, normalizeCode, saveDraft } from "../_shared/drafts.js";
import { findViewer, groupFiles, MAX_APPS, MAX_DRAFTS, parseCodes, shapeApplication, shapeDraft } from "../_shared/admin.js";

const BUCKET = "applications";
// deno-lint-ignore no-explicit-any
const G = (globalThis as any).window.GA27;
if (!G || !G.FIELDS) throw new Error("questions.js did not load");
const db = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, {
  auth: { persistSession: false },
});

const allowed = (Deno.env.get("ALLOWED_ORIGINS") || "").split(",").map((s) => s.trim()).filter(Boolean);

function cors(req: Request): Record<string, string> {
  const origin = req.headers.get("origin") || "";
  const ok = allowed.length === 0 || allowed.includes(origin);
  return {
    "Access-Control-Allow-Origin": ok ? (allowed.length === 0 ? "*" : origin) : "null",
    "Access-Control-Allow-Headers": "content-type, x-admin-code",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Vary": "Origin",
  };
}
function json(req: Request, status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { ...cors(req), "Content-Type": "application/json" } });
}

async function sha256(s: string) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
function randomToken() {
  const a = new Uint8Array(24); crypto.getRandomValues(a);
  return Array.from(a).map((b) => b.toString(16).padStart(2, "0")).join("");
}
function safeName(n: string) { return n.normalize("NFKD").replace(/[^\w.\- ]+/g, "_").slice(0, 80); }

async function rateLimited(key: string, max: number, windowMinutes: number) {
  const since = new Date(Date.now() - windowMinutes * 60_000).toISOString();
  const { count } = await db.from("rate_events").select("id", { count: "exact", head: true }).eq("key", key).gte("at", since);
  if ((count || 0) >= max) return true;
  await db.from("rate_events").insert({ key });
  return false;
}

async function captchaOk(token: string, ip: string) {
  const secret = Deno.env.get("TURNSTILE_SECRET");
  if (!secret) return true;                       // captcha not enabled yet
  if (!token) return false;
  const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST", body: new URLSearchParams({ secret, response: token, remoteip: ip }),
  });
  return !!(await r.json()).success;
}

// Drafts: adapter between _shared/drafts.js and the database.
const draftStore = {
  async get(code: string) { const { data } = await db.from("drafts").select("*").eq("code", code).maybeSingle(); return data; },
  async insert(row: unknown) { const { error } = await db.from("drafts").insert(row); if (error) throw error; },
  async update(code: string, patch: unknown) { const { error } = await db.from("drafts").update(patch).eq("code", code); if (error) throw error; },
  rateLimited,
};
async function draftRoute(req: Request, kind: "save" | "load") {
  const text = await req.text();
  if (text.length > 260_000) return json(req, 413, { error: "Request too large." });
  let body: any;
  try { body = JSON.parse(text); } catch { return json(req, 400, { error: "Invalid JSON." }); }
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
  const ipHash = await sha256(ip + (Deno.env.get("IP_SALT") || ""));
  const r = kind === "save"
    ? await saveDraft(draftStore, body, ipHash, (n: number) => crypto.getRandomValues(new Uint8Array(n)))
    : await loadDraft(draftStore, body, ipHash);
  return json(req, r.status, r.body);
}

async function submit(req: Request) {
  const text = await req.text();
  if (text.length > 400_000) return json(req, 413, { error: "Request too large." });
  let body: any;
  try { body = JSON.parse(text); } catch { return json(req, 400, { error: "Invalid JSON." }); }

  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
  const ipHash = await sha256(ip + (Deno.env.get("IP_SALT") || ""));
  if (await rateLimited("ip:" + ipHash, 8, 60)) return json(req, 429, { error: "Too many attempts. Please try again later." });
  if (!(await captchaOk(body.captcha || "", ip))) return json(req, 400, { error: "Captcha check failed." });

  const answers = cleanAnswers(G, body.answers);
  const files = Array.isArray(body.files) ? body.files.slice(0, 8) : [];
  const { errors, profile, route } = validate(G, answers, files);
  if (Object.keys(errors).length) return json(req, 422, { error: "Some answers need attention.", fields: errors });

  // The contact email is required and must be a real address. The form
  // blocks anything else, but this endpoint is public: without this check a
  // direct request could submit with "hola" or nothing as the only way to
  // reach the applicant.
  const email = String(answers.D1__email || "").trim().toLowerCase();
  if (!isEmail(email)) {
    return json(req, 422, { error: "Some answers need attention.", fields: { D1: "Enter a valid email address." } });
  }
  // The other addresses on the form are optional, but when present they get
  // the same rule: the signer (D3) and the copy address (D4).
  const others: Record<string, string> = {};
  if (answers.D3__email && !isEmail(String(answers.D3__email))) others.D3 = "Enter a valid email address for the signer.";
  if (answers.D4 && !isEmail(String(answers.D4))) others.D4 = "Enter a valid email address.";
  if (Object.keys(others).length) return json(req, 422, { error: "Some answers need attention.", fields: others });
  if (await rateLimited("email:" + email, 3, 24 * 60)) {
    return json(req, 429, { error: "This email already submitted several applications today." });
  }

  const { data: idRow, error: idErr } = await db.rpc("next_application_id");
  if (idErr || !idRow) return json(req, 500, { error: "Could not create the application." });
  const application_id = idRow as string;
  const token = randomToken();

  const { error: insErr } = await db.from("applications").insert({
    application_id, status: "received", answers, profile, route,
    legal_name: answers.B1 || null, country: answers.B2 || null, contact_email: email || null,
    finalize_token_hash: await sha256(token), ip_hash: ipHash,
    user_agent: (req.headers.get("user-agent") || "").slice(0, 300),
  });
  if (insErr) return json(req, 500, { error: "Could not save the application." });

  const uploads: { question: string; url: string }[] = [];
  for (const f of files) {
    const path = `${application_id}/${f.question}-${safeName(f.name)}`;
    const { data, error } = await db.storage.from(BUCKET).createSignedUploadUrl(path);
    if (error || !data) return json(req, 500, { error: "Could not prepare the file upload." });
    await db.from("application_files").insert({
      application_id, question: f.question, storage_path: path, file_name: f.name, mime_type: f.type, size_bytes: f.size,
    });
    uploads.push({ question: f.question, url: data.signedUrl });
  }
  return json(req, 200, { application_id, token, uploads });
}

async function finalize(req: Request) {
  let body: any;
  try { body = await req.json(); } catch { return json(req, 400, { error: "Invalid JSON." }); }
  const { application_id, token } = body || {};
  if (!application_id || !token) return json(req, 400, { error: "Missing application_id or token." });

  const { data: app } = await db.from("applications").select("*").eq("application_id", application_id).single();
  if (!app || app.finalize_token_hash !== (await sha256(token))) return json(req, 403, { error: "Invalid token." });
  if (app.status === "complete") return json(req, 200, { ok: true });

  const { data: expected } = await db.from("application_files").select("storage_path").eq("application_id", application_id);
  const { data: present } = await db.storage.from(BUCKET).list(application_id);
  const have = new Set((present || []).map((o) => `${application_id}/${o.name}`));
  const missing = (expected || []).filter((f) => !have.has(f.storage_path));
  if (missing.length) return json(req, 409, { error: "Some files did not finish uploading. Please submit again." });

  await db.from("applications").update({ status: "complete", finalized_at: new Date().toISOString() }).eq("application_id", application_id);
  const dcode = normalizeCode(body.draft_code);              // the applicant's saved draft is no longer needed
  if (dcode) await db.from("drafts").delete().eq("code", dcode);

  const key = Deno.env.get("RESEND_API_KEY"), from = Deno.env.get("EMAIL_FROM");
  if (key && from && app.contact_email) {
    await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" },
      body: JSON.stringify({
        from, to: app.contact_email,
        subject: `We received your application ${application_id}`,
        text: `Thank you for applying to the Paystand Impact Foundation Grant Application 2027.\n\nYour application ID is ${application_id}. Please keep it for any correspondence.`,
      }),
    }).catch(() => {});
  }
  return json(req, 200, { ok: true });
}

// ---- Dashboard (read-only). Only the people listed in ADMIN_CODES get in. ----
async function adminViewer(req: Request): Promise<{ who?: string; res?: Response }> {
  const ip = req.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
  const key = "adminfail:" + (await sha256(ip + (Deno.env.get("IP_SALT") || "")));
  const since = new Date(Date.now() - 60 * 60_000).toISOString();
  const { count } = await db.from("rate_events").select("id", { count: "exact", head: true }).eq("key", key).gte("at", since);
  if ((count || 0) >= 10) return { res: json(req, 429, { error: "Too many wrong codes. Try again in an hour." }) };
  const codes = parseCodes(Deno.env.get("ADMIN_CODES") || "");
  const who = codes.length ? await findViewer(codes, req.headers.get("x-admin-code") || "", sha256) : null;
  if (!who) {
    // Why it failed, for the function logs only (never the code itself): how many valid ADMIN_CODES entries were read, and how long the code sent was.
    console.log(`admin auth failed: valid ADMIN_CODES entries=${codes.length}, code length sent=${(req.headers.get("x-admin-code") || "").length}`);
    await db.from("rate_events").insert({ key }); return { res: json(req, 401, { error: "That access code is not valid." }) }; }
  return { who };
}

async function adminList(req: Request) {
  const a = await adminViewer(req); if (a.res) return a.res;
  const { data: apps, error } = await db.from("applications")
    .select("application_id, finalized_at, created_at, profile, route, answers")
    .eq("status", "complete").order("finalized_at", { ascending: false }).limit(MAX_APPS);
  if (error) return json(req, 500, { error: "Could not read the applications." });
  const ids = (apps || []).map((x) => x.application_id);
  const { data: files } = ids.length
    ? await db.from("application_files").select("application_id, question, file_name, size_bytes, mime_type").in("application_id", ids)
    : { data: [] };
  const by = groupFiles(files || []);
  return json(req, 200, { viewer: a.who, applications: (apps || []).map((x) => shapeApplication(x, by[x.application_id])) });
}

async function adminDrafts(req: Request) {
  const a = await adminViewer(req); if (a.res) return a.res;
  const { data, error } = await db.from("drafts").select("code, state, saved_sections, email, created_at, updated_at")
    .order("updated_at", { ascending: false }).limit(MAX_DRAFTS);
  if (error) return json(req, 500, { error: "Could not read the drafts." });
  const out = [];
  for (const row of data || []) out.push(shapeDraft(row, (await sha256("draft:" + row.code)).slice(0, 12)));   // the code itself never leaves
  return json(req, 200, { drafts: out });
}

async function adminFile(req: Request) {
  const a = await adminViewer(req); if (a.res) return a.res;
  let body: any; try { body = await req.json(); } catch { return json(req, 400, { error: "Invalid JSON." }); }
  const { data: f } = await db.from("application_files").select("storage_path, file_name")
    .eq("application_id", String(body?.application_id || "")).eq("question", String(body?.question || "")).maybeSingle();
  if (!f) return json(req, 404, { error: "File not found." });
  const { data, error } = await db.storage.from(BUCKET).createSignedUrl(f.storage_path, 300, { download: f.file_name });
  if (error || !data) return json(req, 500, { error: "Could not open the file." });
  return json(req, 200, { url: data.signedUrl });          // link valid for 5 minutes
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
  if (req.method !== "POST") return json(req, 405, { error: "Method not allowed." });
  const path = new URL(req.url).pathname;
  try {
    if (path.endsWith("/submit")) return await submit(req);
    if (path.endsWith("/finalize")) return await finalize(req);
    if (path.endsWith("/draft/save")) return await draftRoute(req, "save");
    if (path.endsWith("/draft/load")) return await draftRoute(req, "load");
    if (path.endsWith("/admin/list")) return await adminList(req);
    if (path.endsWith("/admin/drafts")) return await adminDrafts(req);
    if (path.endsWith("/admin/file")) return await adminFile(req);
    return json(req, 404, { error: "Not found." });
  } catch (e) {
    console.error(e);
    return json(req, 500, { error: "Unexpected error." });
  }
});
