// Edge Function "intake": receives Grant Application 2027 submissions.
//   POST /submit    -> validates, stores answers, returns signed upload URLs
//   POST /finalize  -> checks uploads arrived, marks complete, sends confirmation email
// Secrets (set with `supabase secrets set`, never in the repo):
//   TURNSTILE_SECRET   optional until the captcha is enabled
//   RESEND_API_KEY, EMAIL_FROM   optional, confirmation email
//   ALLOWED_ORIGINS    comma-separated, e.g. https://apply.example.org
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected by Supabase.
import { createClient } from "npm:@supabase/supabase-js@2";
import "../_shared/window-shim.js";   // must stay before questions.js
import "../_shared/questions.js";      // bundled as a module, so it ships with the deploy
import { cleanAnswers, validate } from "../_shared/validate.js";

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
    "Access-Control-Allow-Headers": "content-type",
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

  const email = String(answers.D1__email || "").toLowerCase();
  if (email && (await rateLimited("email:" + email, 3, 24 * 60))) {
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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
  if (req.method !== "POST") return json(req, 405, { error: "Method not allowed." });
  const path = new URL(req.url).pathname;
  try {
    if (path.endsWith("/submit")) return await submit(req);
    if (path.endsWith("/finalize")) return await finalize(req);
    return json(req, 404, { error: "Not found." });
  } catch (e) {
    console.error(e);
    return json(req, 500, { error: "Unexpected error." });
  }
});
