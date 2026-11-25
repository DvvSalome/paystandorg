// Playwright: the Drafts tab of the dashboard against a fake /admin/* API.
// Needs the site on :8099, a payload.json (a submission) and a snapshot.json (a /draft/save body), both captured from the demo form.
// Run: node tests/admin-drafts.js <payload.json> <snapshot.json> <screenshot-dir>
const { chromium } = require("playwright");
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const snap = JSON.parse(fs.readFileSync(process.argv[3], "utf8")).state;
const OUT = process.argv[4];
const EP = "https://gkaukpnmpfdpljofnlxy.supabase.co/functions/v1/intake";
const CODE = "test-code-123456789";
const ago = (d) => new Date(Date.now() - d * 86400000).toISOString();
const HOSTILE = '<img src=x onerror="window.__xss=1"> hostile-org';

// one submitted application, with the same email as the "already submitted" draft
const APP = { application_id: "APP-2027-0001", finalized_at: ago(1), created_at: ago(1), profile: "Established", route: "New", answers: payload.answers,
  files: payload.files.map((f) => ({ question: f.question, name: f.name, size: 1000, type: f.type })) };
const oldStyle = { fields: snap.fields, files: snap.files };                  // like the first drafts: control values only
const newStyle = { answers: snap.answers, files: snap.files };                // like drafts saved by the current form
const DRAFTS = [
  { id: "old000000001", email: "viejo@example.org", created_at: ago(5), updated_at: ago(1), saved_sections: [], files: snap.files, answers: null, fields: snap.fields },
  { id: "new000000002", email: "nuevo@example.org", created_at: ago(4), updated_at: ago(2), saved_sections: [], files: snap.files, answers: snap.answers, fields: null },
  { id: "tiny000000003", email: null, created_at: ago(1), updated_at: ago(0.2), saved_sections: [], files: {}, answers: { B1: HOSTILE }, fields: null },
  { id: "exp000000004", email: "vencido@example.org", created_at: ago(90), updated_at: ago(70), saved_sections: [], files: {}, answers: { B1: "Expired Org" }, fields: null },
  { id: "sub000000005", email: "camila@example.org", created_at: ago(9), updated_at: ago(6), saved_sections: [], files: {}, answers: { B1: "Already Sent Org" }, fields: null },
];

(async () => {
  const b = await chromium.launch();
  const must = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok  :", m); };
  async function open(viewport, draftsStatus) {
    const ctx = await b.newContext({ viewport });
    const p = await ctx.newPage(); const errs = []; p.errs = errs;
    p.on("pageerror", (e) => errs.push(e.message)); p.on("dialog", (d) => { errs.push("dialog: " + d.message()); d.dismiss(); });
    await ctx.route(EP + "/admin/*", async (route) => {
      const r = route.request(), h = { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type, x-admin-code" };
      if (r.method() === "OPTIONS") return route.fulfill({ status: 204, headers: h });
      const json = (status, body) => route.fulfill({ status, headers: h, contentType: "application/json", body: JSON.stringify(body) });
      if (r.headers()["x-admin-code"] !== CODE) return json(401, { error: "That access code is not valid." });
      if (r.url().endsWith("/list")) return json(200, { viewer: "admin", applications: [APP] });
      if (r.url().endsWith("/drafts")) return draftsStatus === 404 ? json(404, { error: "Not found." }) : json(200, { drafts: DRAFTS });
      return json(404, { error: "Not found." });
    });
    await p.goto("http://localhost:8099/admin/");
    await p.fill("#code", CODE); await p.click("#loginform button"); await p.waitForSelector("tr.row");
    return p;
  }

  const p = await open({ width: 1440, height: 900 });
  must((await p.textContent("#navdrafts")).trim() === "3", "Drafts tab badge counts only the 3 in progress (not expired, not already submitted)");
  must((await p.textContent(".tiles")).includes("Drafts in progress"), "applications page has a Drafts in progress tile");
  await p.click(".tile.link");
  await p.waitForFunction(() => (document.querySelector(".pagehead h2") || {}).textContent === "Drafts");
  must(await p.$eval("#tabs a[data-tab=drafts]", (a) => a.getAttribute("aria-current") === "page"), "clicking the tile opens the Drafts tab");
  must((await p.$$("tr.row")).length === 3, "3 drafts shown by default");
  const tiles = await p.textContent(".tiles");
  must(/Drafts in progress/.test(tiles) && /Already submitted/.test(tiles), "drafts summary tiles");
  await p.screenshot({ path: OUT + "/drafts-list-1440.png" });
  await p.selectOption("select[aria-label='Which drafts to show']", "all");
  must((await p.$$("tr.row")).length === 5, "show all: 5 drafts");
  const chips = await p.$$eval("tr.row .chip", (n) => n.map((x) => x.textContent));
  must(chips.includes("Expired") && chips.includes("Already submitted") && chips.includes("In progress"), "status chips: In progress, Expired, Already submitted");
  await p.selectOption("select[aria-label='Which drafts to show']", "active");
  await p.fill("input[type=search]", "fondo local ejemplo");
  must((await p.$$("tr.row")).length === 2, "search looks inside draft answers (old-style and new-style)");
  await p.fill("input[type=search]", "");
  await p.selectOption("select[aria-label='Sort drafts']", "complete");
  must((await p.$$eval("tr.row .ptxt", (n) => n[0].textContent)).includes("of"), "progress label shown");

  // detail: an old-style draft is rebuilt from control values and must read exactly like the new-style one
  await p.click("tr.row:has-text('viejo@example.org')");
  await p.waitForSelector(".sec");
  const oldText = await p.textContent(".layout");
  ["Calle 00", "Bitcoin para comercios", "Primer taller con 40", "Fondo Local Ejemplo", "Program delivery", "Technology or equipment", "camila@example.org", "Colombia"]
    .forEach((t) => must(oldText.includes(t), "old-style draft rebuilt, shows: " + t));
  must(oldText.includes("Attached before saving") && oldText.includes("not stored"), "draft files shown as names only");
  await p.screenshot({ path: OUT + "/draft-detail-1440.png" });
  await p.click(".crumbs a.btn >> nth=0");
  await p.click("tr.row:has-text('nuevo@example.org')");
  await p.waitForSelector(".sec");
  const newText = await p.textContent(".layout");
  // K5's date is filled in by the form itself (read-only), so older drafts never kept it: compare everything else
  const strip = (t) => t.replace(/K5[^]*?(?=Section|$)/, "");
  must(strip(oldText) === strip(newText), "a draft saved the old way reads exactly like one saved the new way (apart from the auto-filled K5 date)");
  await p.click(".crumbs a.btn >> nth=0");

  // a nearly empty draft with hostile text
  await p.click("tr.row:has-text('hostile-org')");
  await p.waitForSelector(".sec");
  must(await p.evaluate(() => window.__xss === undefined), "HTML typed by an applicant never runs");
  must((await p.textContent(".layout")).includes("Nothing answered in this section yet."), "empty sections say so");
  must((await p.$$(".q")).length === 1, "only the answered question is listed");
  await p.click(".crumbs a.btn >> nth=0");

  // applications still fine
  await p.click("#tabs a[data-tab=apps]");
  await p.waitForFunction(() => (document.querySelector(".pagehead h2") || {}).textContent === "Applications");
  must((await p.$$("tr.row")).length === 1, "submitted applications unchanged");

  // phone
  const m = await open({ width: 390, height: 800 });
  await m.click("#tabs a[data-tab=drafts]");
  await m.waitForFunction(() => (document.querySelector(".pagehead h2") || {}).textContent === "Drafts");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (drafts list)");
  await m.screenshot({ path: OUT + "/drafts-list-390.png" });
  await m.click("tr.row >> nth=0"); await m.waitForSelector(".sec");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (draft detail)");

  // server without the drafts route yet: applications keep working, Drafts explains
  const o = await open({ width: 1200, height: 800 }, 404);
  must((await o.$$("tr.row")).length === 1, "old server: applications still load");
  must((await o.$$eval(".tile.link", (n) => n.length)) === 0, "old server: no drafts tile");
  await o.click("#tabs a[data-tab=drafts]");
  await o.waitForSelector(".empty");
  must((await o.textContent("#main")).includes("Drafts are not available yet"), "old server: Drafts page explains what is missing");

  const all = [].concat(p.errs, m.errs, o.errs);
  console.log("page errors:", all.length ? all : "none"); if (all.length) process.exitCode = 1;
  await b.close();
})();
