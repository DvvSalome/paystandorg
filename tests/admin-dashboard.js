// Playwright: the dashboard against a fake /admin/* API. Needs the site on :8099 and a payload.json captured from the demo form.
// Run: node tests/admin-dashboard.js <payload.json> <screenshot-dir>
const { chromium } = require("playwright");
const fs = require("fs");
const payload = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const OUT = process.argv[3];
const EP = "https://gkaukpnmpfdpljofnlxy.supabase.co/functions/v1/intake";
const CODE = "test-code-123456789";

const mk = (id, mut, at, profile, route) => {
  const a = JSON.parse(JSON.stringify(payload.answers));
  mut(a);
  return {
    application_id: id, finalized_at: at, created_at: at, profile, route, answers: a,
    files: payload.files.map((f) => ({ question: f.question, name: f.name, size: 250000, type: f.type })),
  };
};
const HOSTILE = '<img src=x onerror="window.__xss=1"> hostile-org';
const APPS = [
  mk("APP-2027-0001", () => {}, "2026-11-24T15:00:00Z", "Established", "New"),
  mk("APP-2027-0002", (a) => { a.B1 = "Asociación Río Verde"; a.B2 = "Brazil"; a.G2 = "35000"; a.G1 = "60000"; }, "2026-11-23T10:30:00Z", "Established", "Renewal"),
  mk("APP-2027-0003", (a) => { a.A2 = "Less than 1 year"; a.B1 = HOSTILE; a.B3 = '=HYPERLINK("http://evil","click")'; a.B2 = "Chile"; a.G2 = "12000"; a.E4 = "<script>window.__xss=2</script> plain"; }, "2026-11-22T08:00:00Z", "Initial", "New"),
];

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ acceptDownloads: true, viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  const errs = [];
  p.on("pageerror", (e) => errs.push(e.message));
  p.on("dialog", (d) => { errs.push("dialog: " + d.message()); d.dismiss(); });
  await ctx.route(EP + "/admin/*", async (route) => {
    const r = route.request();
    const h = { "access-control-allow-origin": "*", "access-control-allow-headers": "content-type, x-admin-code" };
    if (r.method() === "OPTIONS") return route.fulfill({ status: 204, headers: h });
    if (r.headers()["x-admin-code"] !== CODE) return route.fulfill({ status: 401, headers: h, contentType: "application/json", body: JSON.stringify({ error: "That access code is not valid." }) });
    if (r.url().endsWith("/list")) return route.fulfill({ status: 200, headers: h, contentType: "application/json", body: JSON.stringify({ viewer: "ana", applications: APPS }) });
    return route.fulfill({ status: 200, headers: h, contentType: "application/json", body: JSON.stringify({ url: "http://localhost:8099/index.html" }) });
  });
  const must = (c, m) => { if (!c) { console.log("FAIL:", m); process.exitCode = 1; } else console.log("ok  :", m); };

  await p.goto("http://localhost:8099/admin/");
  must(await p.isVisible("#login"), "shows login first");
  await p.fill("#code", "wrong-code");
  await p.click("#loginform button");
  await p.waitForFunction(() => /not valid/.test(document.getElementById("loginerr").textContent));
  must(!(await p.isVisible("#app")), "wrong code stays on login");
  await p.fill("#code", CODE);
  await p.click("#loginform button");
  await p.waitForSelector("tr.row");
  must((await p.$$("tr.row")).length === 3, "3 applications listed");
  must((await p.textContent("#viewer")).includes("ana"), "viewer name shown");
  must((await p.textContent(".tiles")).includes("$67,000"), "total requested = 20k+35k+12k");
  await p.screenshot({ path: OUT + "/dash-list-1440.png" });

  await p.fill("input[type=search]", "río verde");
  must((await p.$$("tr.row")).length === 1, "search finds by organization");
  await p.fill("input[type=search]", "camila@example.org");
  must((await p.$$("tr.row")).length === 3, "search looks inside any answer (D1 email, not shown in the list)");
  await p.fill("input[type=search]", "no-such-text-anywhere");
  must((await p.$$("tr.row")).length === 0 && (await p.textContent(".list")).includes("No application matches"), "search with no match says so");
  await p.fill("input[type=search]", "");
  await p.selectOption("select[aria-label='All countries']", "Brazil");
  must((await p.$$("tr.row")).length === 1, "country filter");
  await p.selectOption("select[aria-label='All countries']", "");
  await p.selectOption("select[aria-label='Sort']", "amount");
  must((await p.textContent("tr.row .mono")).trim() === "APP-2027-0002", "sort by largest request");
  await p.selectOption("select[aria-label='Sort']", "new");

  await p.click("tr.row >> nth=0");
  await p.waitForSelector(".sec");
  must((await p.$$(".sec")).length === 12, "12 sections rendered");
  const text = await p.textContent("#main");
  ["Calle 00", "Bitcoin para comercios", "Primer taller con 40", "Fondo Local Ejemplo", "Program delivery", "Technology or equipment", "camila@example.org", "Participant protection"]
    .forEach((t) => must(text.includes(t), "detail shows: " + t));
  const ids = await p.$$eval(".q .qid", (n) => n.map((x) => x.textContent));
  console.log("questions shown:", ids.length);
  must((await p.$$(".sub-t")).length >= 3, "tables for milestones, funders and budget");
  await p.screenshot({ path: OUT + "/dash-detail-1440.png" });
  await p.click(".file .btn >> nth=0");
  await p.waitForTimeout(400);
  must((await p.textContent(".crumbs")).includes("1 of 3"), "position shown (1 of 3)");
  await p.click("text=Next ›");
  await p.waitForFunction(() => /0002/.test(document.querySelector(".head .kicker").textContent));
  must((await p.textContent(".crumbs")).includes("2 of 3"), "Next moves to the second application");
  await p.click("text=‹ Previous");
  await p.waitForFunction(() => /0001/.test(document.querySelector(".head .kicker").textContent));
  await p.click(".rail a >> nth=5");
  await p.waitForTimeout(900);
  must(await p.$$eval(".rail a.on", (n) => n.length === 1), "section list highlights the section being read");
  await p.click(".crumbs a.btn >> nth=0");
  must((await p.textContent("#navcount")).trim() === "1", "nav shows 1 application not opened yet");

  // overview
  await p.click("#tabs a[data-tab=overview]");
  await p.waitForSelector(".chart");
  must((await p.$$(".chart")).length === 8, "8 charts on the overview");
  must(await p.$eval("#tabs a[data-tab=overview]", (a) => a.getAttribute("aria-current") === "page"), "active tab is marked");
  await p.hover(".brow >> nth=0");
  must(await p.isVisible("#tip") && (await p.textContent("#tip")).length > 3, "hovering a bar shows a tooltip");
  await p.screenshot({ path: OUT + "/dash-overview-1440.png", fullPage: true });
  await p.click(".chart:nth-of-type(1) .tblink >> nth=0");
  must((await p.$$(".chart .sub-t")).length === 1, "a chart can be viewed as a table");
  await p.click(".chart .tblink >> nth=0");
  await p.click(".chart:has(h3:text('Amount requested by country')) .brow >> nth=0");
  await p.waitForSelector("tr.row");
  must((await p.$$("tr.row")).length === 1 && (await p.textContent(".chips")).includes("Country:"), "clicking a country bar filters the list");
  await p.click(".fchip");
  must((await p.$$("tr.row")).length === 3, "removing the filter tag shows all again");

  // help
  await p.click("#tabs a[data-tab=help]");
  await p.waitForSelector(".help");
  must((await p.$$(".help .card")).length === 6, "help page renders");
  await p.click("#tabs a[data-tab=apps]");
  await p.waitForSelector("tr.row");

  await p.fill("input[type=search]", "hostile-org");
  await p.click("tr.row");
  await p.waitForSelector(".sec");
  must(await p.evaluate(() => window.__xss === undefined), "HTML in answers is never executed");
  must((await p.textContent("#main")).includes("<script>window.__xss=2</script>"), "hostile text shown as plain text");
  await p.click(".crumbs a.btn >> nth=0");
  await p.fill("input[type=search]", "");

  const [dl] = await Promise.all([p.waitForEvent("download"), (async () => { await p.click("#usermenu"); await p.click("#export"); })()]);
  const csv = fs.readFileSync(await dl.path(), "utf8");
  must(csv.split("\r\n").filter(Boolean).length === 4, "CSV has header + 3 rows");
  must(csv.includes("\"'=HYPERLINK"), "CSV neutralizes a formula typed by an applicant");
  must(!csv.includes('"=HYPERLINK'), "no CSV cell starts with a formula");

  await p.click("#usermenu"); await p.click("#signout");
  must(await p.isVisible("#login"), "sign out returns to login");

  const m = await ctx.newPage();
  await m.setViewportSize({ width: 390, height: 800 });
  await m.goto("http://localhost:8099/admin/");
  await m.fill("#code", CODE);
  await m.click("#loginform button");
  await m.waitForSelector("tr.row");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (list)");
  await m.screenshot({ path: OUT + "/dash-list-390.png" });
  await m.click("tr.row >> nth=0");
  await m.waitForSelector(".sec");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (detail)");
  await m.screenshot({ path: OUT + "/dash-detail-390.png" });
  await m.click("#tabs a[data-tab=overview]");
  await m.waitForSelector(".chart");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (overview)");
  await m.screenshot({ path: OUT + "/dash-overview-390.png" });
  await m.click("#tabs a[data-tab=help]");
  await m.waitForSelector(".help");
  must(await m.evaluate(() => document.documentElement.scrollWidth <= 392), "no horizontal scroll at 390px (help)");

  console.log("page errors:", errs.length ? errs : "none");
  if (errs.length) process.exitCode = 1;
  await b.close();
})();
