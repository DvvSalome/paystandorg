/* Grant Application 2027 — question definitions (v3, 61 questions).
   Source: Ivan's Apps Script preview, 10 Nov 2026. Edit here to change questions;
   the form engine in form.js does not hard-code any question. */
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
    { id: "0.2", s: "0", type: "checks", req: "all",
      label: "Eligibility checklist",
      help: "All four must be checked. If you cannot check one, explain it in section K rather than stopping here.",
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
