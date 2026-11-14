import { createClient } from "npm:@supabase/supabase-js@2";

// ---- window shim ----
// questions.js is shared with the browser and writes to `window.GA27`.
// Deno has no `window`, so give it one before questions.js is evaluated.
globalThis.window = globalThis.window || {};

// ---- questions (from site/assets/questions.js) ----
/* Grant Application 2027 — question definitions (v3, 60 questions).
   Source: Ivan's Apps Script preview, 10 Nov 2026. Edit here to change questions;
   the form engine in form.js does not hard-code any question.

   It is 60, not 61. Two other documents say 61 and each counts something
   that is not a question, which is why the number looked confirmed:

     - The form specification lists 61 numbered items because it includes
       G6 (cost per participant), which its own row marks "Computed: G2 ÷ E5
       — Internal, not shown to the applicant". G6 is derived in the
       pipeline's step_clean; nobody is ever asked it.
     - QUESTION_MAP in intake_pipeline.py has 61 entries because it includes
       Timestamp, the submission-time column.

   So: 60 questions here, 60 + Timestamp = 61 columns for Eva, and 60 + G6
   = 61 rows in the spec. Verified by diffing all three sets in both
   directions on 2026-11-13: zero discrepancies against QUESTION_MAP, and
   G6 the only item the spec has that this file does not.

   Nobody ever sees all 60: 13 are conditional. An individual applying for
   the first time sees 49; an organisation applying for the first time, 53;
   a 2026 renewal, 58. */
(function () {
  "use strict";
  var COUNTRIES = ["Afghanistan","Albania","Algeria","Angola","Argentina","Armenia","Australia","Austria","Bangladesh","Belgium","Benin","Bolivia","Bosnia and Herzegovina","Botswana","Brazil","Bulgaria","Burkina Faso","Burundi","Cambodia","Cameroon","Canada","Cape Verde","Central African Republic","Chad","Chile","Colombia","Comoros","Congo (DRC)","Congo (Republic)","Costa Rica","Côte d'Ivoire","Croatia","Cuba","Czechia","Denmark","Djibouti","Dominican Republic","Ecuador","Egypt","El Salvador","Eritrea","Estonia","Eswatini","Ethiopia","Finland","France","Gabon","Gambia","Georgia","Germany","Ghana","Greece","Guatemala","Guinea","Guinea-Bissau","Guyana","Haiti","Honduras","Hungary","India","Indonesia","Iran","Iraq","Ireland","Israel","Italy","Jamaica","Japan","Jordan","Kenya","Kosovo","Kyrgyzstan","Laos","Latvia","Lebanon","Lesotho","Liberia","Lithuania","Madagascar","Malawi","Malaysia","Mali","Mauritania","Mexico","Moldova","Mongolia","Morocco","Mozambique","Myanmar","Namibia","Nepal","Netherlands","New Zealand","Nicaragua","Niger","Nigeria","North Macedonia","Norway","Pakistan","Palestine","Panama","Papua New Guinea","Paraguay","Peru","Philippines","Poland","Portugal","Romania","Rwanda","Senegal","Serbia","Sierra Leone","Slovakia","Slovenia","Somalia","South Africa","South Korea","South Sudan","Spain","Sri Lanka","Sudan","Suriname","Sweden","Switzerland","Syria","Taiwan","Tajikistan","Tanzania","Thailand","Timor-Leste","Togo","Trinidad and Tobago","Tunisia","Turkey","Uganda","Ukraine","United Kingdom","United States","Uruguay","Uzbekistan","Venezuela","Vietnam","Yemen","Zambia","Zimbabwe"];
  var SECTIONS = [
    { id: "0", title: "Before you apply",
      note: "Two short checklists. The first tells you which documents to gather; the second confirms you are eligible. Takes about two minutes." },
    { id: "A", title: "Tell us about you",
      note: "Five questions about who is applying and how much you are requesting. Your answers here determine which of the later questions apply to you, so some sections will be shorter than others." },
    { id: "B", title: "Organization",
      note: "Your legal details, exactly as they appear on your registration document or identification. These carry through to the grant agreement if you are selected, so accuracy here saves time later." },
    { id: "C", title: "Documents",
      note: "Upload your legal identity document and, if you have it to hand, your tax form. Accepted files: PDF, JPG or PNG, maximum 10 MB each. The tax form is optional now and required only if you are selected." },
    { id: "D", title: "Contact and authorized representative",
      note: "Who we write to about this application, and who would sign the agreement. These can be the same person." },
    { id: "E", title: "Project",
      note: "The substance of your application: what you will do, who with, and what will change. This is the longest section — around twenty minutes if you have your plan to hand." },
    { id: "F", title: "Measurement",
      note: "How you will show the project worked. Choose one main measure and tell us where you are starting from and where you expect to be in twelve months. If you do not have a starting figure yet, you can tell us how you will collect it." },
    { id: "G", title: "Budget and sustainability",
      note: "The money, and what keeps running after the grant ends. Amounts in US dollars, numbers only — no currency symbols." },
    { id: "H", title: "Experience and support",
      note: "Your team's capacity, and what non-financial support would help. We offer technical assistance and volunteers, so this helps us match what we have to what you need." },
    { id: "I", title: "Participant protection",
      note: "How you keep participants safe, including children and anyone whose data you hold. Required of every applicant." },
    { id: "J", title: "Renewal",
      note: "Shown only if you received a grant from us in 2026. Tell us what happened with it." },
    { id: "K", title: "Disclosures and certification",
      note: "Anything we should know about, and your confirmation that the application is accurate. Last section." }
  ];

  var F = [
    
    { id: "0.1", s: "0", type: "checks", req: false,
      label: "What you will need to apply",
      help: "Tick each item to confirm you have it ready. This list is for your reference and will not block submission.",
      options: [
        "Organizations: registration or tax ID number, legal representative's name, proof of nonprofit or charitable status (NGOs), W-9 or W-8BEN-E, last year's budget",
        "Individuals: photo ID, W-9 or W-8BEN",
        "Project description, budget, timeline and milestone plan",
        "Contact details for the primary contact and the authorized representative"
      ] },
    // req is deliberately absent. It used to be "all", which contradicted
    // three other places that expect an applicant to be able to proceed with
    // an explanation:
    //
    //   · this field's own help text ("explain it in section K rather than
    //     stopping here") — unreachable, because validation blocked at 3 of 4
    //   · K2.showIf, which already appears when fewer than four are checked
    //   · Eva's eligibility gate ("a 0.2 box is missing and K2 does not
    //     explain it"), which the pipeline has been carrying unused
    //
    // Nothing is lost by relaxing it: K2 is required whenever fewer than four
    // are checked, so every such application still arrives with a written
    // reason, and Eva still routes it to manual review. What changes is that
    // the applicant can finish and say why, instead of hitting a wall the
    // form told them would not be there.
    { id: "0.2", s: "0", type: "checks",
      label: "Eligibility checklist",
      help: "All four should be checked. If you cannot check one, you can still continue — you will be asked to explain it in section K.",
      options: [
        "Our work serves people facing economic barriers",
        "We have a charitable purpose — no political campaigning or private benefit",
        "We accept outcome reporting and follow-up requirements",
        "Our impact does not rely on Bitcoin price gains"
      ] },

    
    { id: "A1", s: "A", type: "radio", req: true,
      label: "Are you applying as an organization or as an individual?",
      options: ["Organization (legally registered entity)", "Individual"] },
    { id: "A1b", s: "A", type: "radio", req: true,
      label: "What type of organization?",
      showIf: function (v) { return (v.A1 || "").indexOf("Organization") === 0; },
      cond: "A1 = Organization",
      options: ["Nonprofit / NGO", "Social enterprise or other company"] },
    { id: "A2", s: "A", type: "radio", req: true,
      label: "How long has your organization or project been operating?",
      options: ["Less than 1 year", "1–3 years", "More than 3 years"] },
    { id: "A3", s: "A", type: "radio", req: true,
      label: "Have you received a grant from Paystand.org before?",
      options: ["No", "Yes, in 2026", "Yes, before 2026"] },
    { id: "A4", s: "A", type: "number", req: true, min: 1, prefix: "USD",
      label: "How much are you requesting from Paystand.org?",
      help: "An approximate figure is fine \u2014 you can refine it in the budget section." },

    
    { id: "B1", s: "B", type: "text", req: true,
      label: "Legal name, exactly as it appears on your registration document or on your ID",
      help: "This must match the document you upload in section C exactly." },
    { id: "B2", s: "B", type: "country", req: true,
      label: "Country of registration, or country of residence" },
    { id: "B3", s: "B", type: "text", req: true,
      label: "Full name of the legal representative or founder" },
    { id: "B4", s: "B", type: "textarea", req: true, maxWords: 40, rows: 2,
      label: "Registered address",
      help: "Street, city, state or region, postal code." },
    { id: "B5", s: "B", type: "number", req: true, prefix: "USD",
      label: "Total organizational budget last year",
      showIf: function (v, st) { return st.profile === "Established"; },
      cond: "Established profile" },
    { id: "B7", s: "B", type: "number", req: true, min: 0,
      label: "Number of full-time paid staff",
      showIf: function (v) { return (v.A1 || "").indexOf("Organization") === 0; },
      cond: "A1 = Organization" },
    { id: "B8", s: "B", type: "text", req: true,
      label: "Registration or tax ID number",
      help: "As it appears on your registration document.",
      showIf: function (v) { return (v.A1 || "").indexOf("Organization") === 0; },
      cond: "A1 = Organization" },
    { id: "B6", s: "B", type: "url", req: false,
      label: "Website or main social media profile" },

    
    { id: "C1", s: "C", type: "file", req: true,
      label: "Legal identity document",
      helpFn: function (v) {
        if ((v.A1 || "").indexOf("Individual") === 0) return "A photo of a valid official identification.";
        if ((v.A1b || "").indexOf("Nonprofit") === 0) return "Official registration AND proof of nonprofit or charitable status — in the US the IRS 501(c)(3) determination letter, elsewhere the local equivalent. A W-9 or W-8 does not prove nonprofit status.";
        if ((v.A1b || "").indexOf("Social") === 0) return "Government registration certificate — commercial registry or tax certificate.";
        return "Answer A1 to see which document applies to you.";
      } },
    { id: "C2", s: "C", type: "file", req: false,
      label: "Tax form — W-9 or W-8",
      helpFn: function (v) {
        var base = "Optional now, required if you are selected. Uploading it now speeds up your agreement.";
        if ((v.A1 || "").indexOf("Individual") === 0) return "In the US: W-9. Outside the US: W-8BEN. " + base;
        return "Registered in the US: W-9. Outside the US: W-8BEN-E. " + base;
      } },
    { id: "C3", s: "C", type: "text", req: false,
      label: "If the registration is in a person's name: who is it, and what is their role?",
      help: "Leave blank if the registration is in the organization's name.",
      showIf: function (v) { return (v.A1 || "").indexOf("Organization") === 0; },
      cond: "A1 = Organization" },

    
    { id: "D1", s: "D", type: "composite", req: true,
      label: "Primary contact",
      help: "We will use this email for all correspondence about your application.",
      parts: [
        { k: "name", ph: "Full name", t: "text" },
        { k: "title", ph: "Title", t: "text" },
        { k: "email", ph: "Email", t: "email" },
        { k: "phone", ph: "Phone or WhatsApp", t: "tel" }
      ] },
    { id: "D2", s: "D", type: "radio", req: true,
      label: "Is the primary contact authorized to sign agreements for the organization?",
      options: ["Yes", "No"] },
    { id: "D3", s: "D", type: "composite", req: true,
      label: "Authorized representative who will sign the agreement",
      showIf: function (v) { return v.D2 === "No"; },
      cond: "D2 = No",
      parts: [
        { k: "name", ph: "Full name", t: "text" },
        { k: "title", ph: "Title", t: "text" },
        { k: "email", ph: "Email", t: "email" }
      ] },
    { id: "D4", s: "D", type: "email", req: false,
      label: "Additional email to copy on the agreement and payment notices" },

    
    { id: "E1", s: "E", type: "titlesummary", req: true, maxWords: 60,
      label: "Project title, and a summary in 2–3 sentences" },
    { id: "E2", s: "E", type: "datepair", req: true,
      label: "Start date and end date",
      help: "Project duration is calculated from these two dates." },
    { id: "E3", s: "E", type: "text", req: true,
      label: "Where will the project take place?",
      help: "Country, city, communities." },
    { id: "E4", s: "E", type: "textarea", req: true, maxWords: 150,
      label: "What economic barrier will this project address?",
      help: "Name the barrier, who it affects, and why Bitcoin helps." },
    { id: "E5", s: "E", type: "number", req: true, min: 1,
      label: "How many people will participate directly?" },
    { id: "E6", s: "E", type: "textarea", req: true, maxWords: 150,
      label: "Who are they, how will they be selected, and what is your relationship with them?" },
    { id: "E7", s: "E", type: "text", req: true,
      label: "Your primary result in one sentence",
      help: "Use the form: \"By [date], [number or %] of [participants] will [result].\"" },
    { id: "E8", s: "E", type: "textarea", req: true, maxWords: 150,
      label: "How will participants apply what they learn, and which partner creates that opportunity?",
      help: "A merchant, employer, cooperative or local partner — name it." },
    { id: "E9", s: "E", type: "checks", req: 1,
      label: "What will Bitcoin be used for?",
      options: ["Paying", "Receiving payments", "Remittances", "Saving", "Other"] },
    { id: "E10", s: "E", type: "milestones", req: true,
      label: "Three milestones",
      help: "Each needs a target date and the evidence you will provide." },
    { id: "E11", s: "E", type: "textarea", req: true, maxWords: 150,
      label: "What could prevent success, and how will you reduce that risk?" },
    { id: "E12", s: "E", type: "radio", req: true, boxed: true,
      label: "Where do you expect the community to be when the grant ends?",
      help: "Your commitment for the end of the grant. It is recorded in the agreement if you are selected.",
      options: [
        "Awareness \u2014 the community is learning about Bitcoin and its practical use",
        "Useful adoption \u2014 people use Bitcoin for some real transactions",
        "Local circulation \u2014 Bitcoin flows between community members for goods and services",
        "Resilience \u2014 the local economy sustains itself without external support"
      ] },
    { id: "E13", s: "E", type: "textarea", req: true, maxWords: 150,
      label: "How will value circulate locally?",
      help: "A rise in the Bitcoin price does not count as impact \u2014 describe how value moves between people." },

    
    { id: "F1", s: "F", type: "radio", req: true, boxed: true,
      label: "Main measure \u2014 which one will you report on?",
      help: "Choose the one that best fits what your project changes. You will report on this same measure throughout.",
      options: [
        "Skills \u2014 share of trained participants who complete a Bitcoin transaction on their own",
        "Access \u2014 share of participants with a wallet they have used in the last 90 days",
        "Commerce \u2014 number of merchants trading in the last 30 days",
        "Remittances \u2014 share of remittances received in Bitcoin, and the cost compared with before",
        "Recovery \u2014 an emergency fund in place, funded by the community"
      ] },
    { id: "F2", s: "F", type: "baseline", req: true,
      label: "Where are you starting from?",
      help: "Give the figure today and the date you measured it \u2014 or, if you do not have it yet, say how and when you will collect it. Either answer is complete." },
    { id: "F3", s: "F", type: "valuedate", req: true,
      label: "Where do you expect to be at 12 months?",
      help: "The figure you are aiming for, and the date you will measure it." },
    { id: "F4", s: "F", type: "radio", req: true,
      label: "How will you verify it?",
      options: ["Survey", "Partner or transaction records", "Merchant registry or BTC Map", "Other"] },
    { id: "F5", s: "F", type: "textarea", req: false, maxWords: 150,
      label: "Previous Bitcoin or financial-inclusion projects and their results",
      help: "Numbers, and a link if available. Leave blank if you have none." },

    
    { id: "G1", s: "G", type: "number", req: true, prefix: "USD",
      label: "Total project budget" },
    { id: "G2", s: "G", type: "number", req: true, prefix: "USD", min: 1,
      label: "Amount requested from Paystand.org",
      help: "Pre-filled from A4. Adjust it if your budget work changed the figure — this is the authoritative number." },
    { id: "G3", s: "G", type: "funders", req: true,
      label: "Are you applying to other funders for this same project?" },
    { id: "G4", s: "G", type: "budget", req: true,
      label: "Requested amount by category",
      help: "The categories must sum to G2.",
      showIf: function (v, st) { return st.profile === "Established"; },
      cond: "Established profile",
      cats: ["Program delivery", "People and training", "Technology or equipment", "Monitoring and safeguarding", "Administration"] },
    { id: "G5", s: "G", type: "textarea", req: true, maxWords: 100,
      label: "Main uses of the funds",
      showIf: function (v, st) { return st.profile === "Initial"; },
      cond: "Initial profile" },
    { id: "G7", s: "G", type: "textarea", req: true, maxWords: 150,
      label: "What will keep working after the grant ends, and how will you sustain it?",
      help: "Say what continues, who sustains it, and with what resources." },
    { id: "G8", s: "G", type: "radio", req: true,
      label: "How would you prefer to receive the funds?",
      options: ["Bitcoin (through Bitwage)", "Bank transfer, ACH (US accounts)", "Other \u2014 we will ask for details"] },

    
    { id: "H1", s: "H", type: "radio", req: true, boxed: true,
      label: "Which option best describes your team's capacity?",
      options: [
        "1. We have a robust in-house capacity, including administrative staff and a team able to deliver high-quality skills development sessions to all our beneficiaries independently.",
        "2. We have some in-house capacity, but we will need additional external support to comply with project reporting and reach the breadth of beneficiaries we intend to serve.",
        "3. We do not have the in-house capacity to meet administrative tasks or deliver training independently; in addition to tools and materials provided by Paystand, we will need external help for high-quality delivery."
      ] },
    { id: "H2", s: "H", type: "textarea", req: true, maxWords: 150,
      label: "How would you use Paystand.org's technical support and volunteers?",
      help: "We offer both \u2014 tell us what would actually help." },

    
    { id: "I1", s: "I", type: "radio", req: true,
      label: "Will the project involve children under 18?",
      options: ["Directly", "Incidental contact", "No"] },
    { id: "I2", s: "I", type: "safeguard", req: true,
      label: "Child safeguarding policy",
      help: "Upload your policy, or confirm one will be in place before funding, and name the person responsible.",
      showIf: function (v) { return v.I1 === "Directly" || v.I1 === "Incidental contact"; },
      cond: "I1 = Directly or Incidental contact" },
    { id: "I3", s: "I", type: "textarea", req: true, maxWords: 100,
      label: "What participant data will you collect, and how will you protect it?",
      help: "Who holds it, where it is stored, and how long you keep it." },

    
    { id: "J1", s: "J", type: "textarea", req: true, maxWords: 200,
      label: "What did you promise in 2026, and what did you achieve?",
      help: "Use numbers.",
      showIf: function (v) { return v.A3 === "Yes, in 2026"; },
      cond: "A3 = Yes, in 2026" },
    { id: "J2", s: "J", type: "radio", req: true,
      label: "Which stage did the community reach in 2026?",
      showIf: function (v) { return v.A3 === "Yes, in 2026"; },
      cond: "A3 = Yes, in 2026",
      options: ["Awareness", "Useful adoption", "Local circulation", "Resilience"] },
    { id: "J3", s: "J", type: "file", req: false,
      label: "Upload your 2026 report, if you have one",
      showIf: function (v) { return v.A3 === "Yes, in 2026"; },
      cond: "A3 = Yes, in 2026" },

    
    { id: "K1", s: "K", type: "checks", req: 1,
      label: "Anything to disclose?",
      help: "Tick \"None\" if there is nothing to disclose.",
      options: ["Legal or financial issues", "Adverse media", "Conflict of interest with Paystand.org", "None"] },
    { id: "K2", s: "K", type: "textarea", req: true, maxWords: 300,
      label: "Details of any disclosure, or of any eligibility statement you could not check",
      showIf: function (v) {
        var k1 = v.K1 || [];
        var disclosed = k1.length && k1.indexOf("None") === -1;
        var elig = (v["0.2"] || []).length < 4;
        return disclosed || elig;
      },
      cond: "K1 ≠ None, or 0.2 incomplete" },
    { id: "K3", s: "K", type: "checks", req: "all",
      label: "Certification",
      options: [
        "The information in this application is accurate",
        "Funds will be used only for the approved purpose",
        "We will report material changes",
        "Paystand.org may verify this information and contact us",
        "I am authorized to apply on behalf of this applicant"
      ] },
    { id: "K4", s: "K", type: "checks", req: "all",
      label: "Data consent",
      links: [{ t: "Grant terms and conditions", href: "https://www.paystand.org/grants-terms-and-conditions" }],
      options: ["I consent to the storing and processing of personal data, per the Terms and Privacy Policy"] },
    { id: "K5", s: "K", type: "submitter", req: true,
      label: "Name of the person submitting, and date" }
  ];
  window.GA27 = { COUNTRIES: COUNTRIES, SECTIONS: SECTIONS, FIELDS: F };
})();

// ---- validation (from supabase/functions/_shared/validate.js) ----
// Server-side validation for a Grant Application 2027 submission.
// Pure JS (no Deno or Node APIs) so it runs in the Edge Function and in node tests.
// Never trust the browser: every rule the form enforces is re-checked here.

const FILE_QUESTIONS = ["C1", "C2", "I2", "J3"];
const MAX_BYTES = 10 * 1024 * 1024;
const ALLOWED_MIME = ["application/pdf", "image/jpeg", "image/png"];
const EXT = /\.(pdf|jpe?g|png)$/i;
const MAX_STR = 5000;

function words(s) { return s && String(s).trim() ? String(s).trim().split(/\s+/).length : 0; }
function num(x) { const n = parseFloat(String(x == null ? "" : x).replace(/[$,\s]/g, "")); return isNaN(n) ? null : n; }

function loadQuestions(src) {
  const w = {};
  new Function("window", src)(w);
  return w.GA27;
}

function deriveState(v) {
  const a1 = v.A1 || "", a2 = v.A2 || "", a3 = v.A3 || "";
  const profile = !a1 && !a2 ? "—" : (a1.indexOf("Individual") === 0 || a2 === "Less than 1 year") ? "Initial" : "Established";
  const route = !a3 ? "—" : a3 === "Yes, in 2026" ? "Renewal" : "New";
  return { profile, route };
}

// Keep only keys that belong to a known question; cap sizes; drop everything else.
function cleanAnswers(G, raw) {
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

function validate(G, answers, files) {
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
function sheetSafe(s) {
  return typeof s === "string" && /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
}

// ---- drafts (from supabase/functions/_shared/drafts.js) ----
// Save-and-resume drafts. Pure JS (no Deno APIs) so node tests can run it with an in-memory store.
// store = { get(code) -> row|null, insert(row), update(code, patch), delete(code),
//           rateLimited(key, max, windowMinutes) -> Promise<boolean> }
// The server makes the code; the browser can only update a code it already knows.

const CODE_RE = /^GA27-[A-Z0-9]{3}-[A-Z0-9]{3}-[A-Z0-9]{3}$/;
const ALPHABET = "ACDEFGHJKLMNPQRTUVWXY34789";      // no 0/O, 1/I/L, 2/Z, 5/S, 6/G, 8/B look-alikes
const MAX_STATE_CHARS = 200_000;

// The one email rule. The browser (site/assets/form.js) carries an identical
// copy because it cannot import this file; tests/email.test.mjs fails if the
// two drift. Before this there were three rules: the form's submit check
// required a dot, the save card did not ("ana@x" passed), and the server
// checked nothing at all — so a direct API call could store "hola" as the
// contact address.
//   local part: no spaces, no @
//   domain: labels without spaces, @ or empty parts, at least one dot,
//           ending in a label of two or more characters
const EMAIL_RE = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)*\.[^\s@.]{2,}$/;
function isEmail(x) {
  return typeof x === "string" && x.trim().length <= 200 && EMAIL_RE.test(x.trim());
}
const MAX_AGE_DAYS = 60;

function makeCode(randomBytes) {
  const b = randomBytes(9);
  let s = "";
  for (let i = 0; i < 9; i++) s += ALPHABET[b[i] % ALPHABET.length];
  return `GA27-${s.slice(0, 3)}-${s.slice(3, 6)}-${s.slice(6, 9)}`;
}

function normalizeCode(c) {
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
async function saveDraft(store, body, ipHash, randomBytes) {
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

async function loadDraft(store, body, ipHash, now = Date.now()) {
  // 20 tries per hour per IP: the code space (26^9) is not guessable at that rate
  if (await store.rateLimited("draft:load:" + ipHash, 20, 60)) return { status: 429, body: { error: "Too many attempts. Please try again later." } };
  const code = normalizeCode(body && body.code);
  const row = code && (await store.get(code));
  const fresh = row && now - new Date(row.updated_at).getTime() < MAX_AGE_DAYS * 86_400_000;
  if (!fresh) return { status: 404, body: { error: "We could not find a saved application with that code." } };
  return { status: 200, body: { code, state: row.state, saved_sections: row.saved_sections || [], updated_at: row.updated_at } };
}

// ---- function ----
// Edge Function "intake": receives Grant Application 2027 submissions.
//   POST /submit    -> validates, stores answers, returns signed upload URLs
//   POST /finalize  -> checks uploads arrived, marks complete, sends confirmation email
//   POST /draft/save, /draft/load -> save and resume an unfinished application with a code
// Secrets (set with `supabase secrets set`, never in the repo):
//   TURNSTILE_SECRET   optional until the captcha is enabled
//   RESEND_API_KEY, EMAIL_FROM   optional, confirmation email
//   ALLOWED_ORIGINS    comma-separated, e.g. https://apply.example.org
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected by Supabase.

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

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(req) });
  if (req.method !== "POST") return json(req, 405, { error: "Method not allowed." });
  const path = new URL(req.url).pathname;
  try {
    if (path.endsWith("/submit")) return await submit(req);
    if (path.endsWith("/finalize")) return await finalize(req);
    if (path.endsWith("/draft/save")) return await draftRoute(req, "save");
    if (path.endsWith("/draft/load")) return await draftRoute(req, "load");
    return json(req, 404, { error: "Not found." });
  } catch (e) {
    console.error(e);
    return json(req, 500, { error: "Unexpected error." });
  }
});
