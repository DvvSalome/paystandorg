// Playwright: fill the form (demo data), save, reload, resume with the code, compare every control.
// Uses an in-memory fake of /draft/save and /draft/load. Run: node tests/draft-roundtrip.js (needs site on :8099)
const { chromium } = require("playwright");
const URL = "http://localhost:8099/form/?embed=1&demo=1";
const BASE = "http://localhost:8099/form/?embed=1";
const EP = "https://gkaukpnmpfdpljofnlxy.supabase.co/functions/v1/intake";
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const db = new Map(); let n = 0;
  await ctx.route(EP + "/draft/*", async (route) => {
    const req = route.request(), body = JSON.parse(req.postData() || "{}");
    const kind = req.url().endsWith("/save") ? "save" : "load";
    const reply = (status, b) => route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(b) });
    if (kind === "save") {
      const code = body.code || "GA27-AAA-AAA-A" + String(++n).padStart(2, "0");
      db.set(code, { state: body.state, saved_sections: body.saved_sections }); return reply(200, { code });
    }
    const c = String(body.code).toUpperCase(), row = db.get(c); return row ? reply(200, { code: c, ...row }) : reply(404, { error: "We could not find a saved application with that code." });
  });
  const dump = (page) => page.evaluate(() => Array.from(document.querySelectorAll("#form .f")).map((f) => {
    const cs = Array.from(f.querySelectorAll("input,textarea,select")).filter((c) => c.type !== "file" && !c.readOnly)
      .map((c) => c.type === "checkbox" || c.type === "radio" ? (c.checked ? 1 : 0) : c.value);
    return f.dataset.fid + ":" + JSON.stringify(cs);
  }).join("\n"));
  const label = (page) => page.textContent("#plabel");

  const a = await ctx.newPage(); const errs = [];
  a.on("pageerror", (e) => errs.push(e.message));
  await a.goto(URL); await a.waitForSelector("#f-B1");
  const before = await dump(a), labelBefore = await label(a);
  await a.click(".savebar .savebtn.primary");
  await a.waitForSelector(".codeval:not(:empty)");
  const code = await a.textContent(".codeval"); console.log("code", code, "| before:", labelBefore);
  await a.fill("#i-B1, #f-B1 input", "Changed after save");     // edit -> sections become unsaved
  const secTxt = await a.textContent("#sec-B .secmsg"); console.log("section B after edit:", secTxt);
  await a.click("#sec-B .savebtn"); await a.waitForFunction(() => /Saved/.test(document.querySelector("#sec-B .secmsg").textContent));
  console.log("section B after save:", await a.textContent("#sec-B .secmsg"));
  await a.fill("#f-B1 input", await a.evaluate(() => "Fundación Semillas Digitales (DEMO)")); // back to original
  await a.click("#sec-B .savebtn"); await a.waitForTimeout(300);

  const b = await ctx.newPage(); b.on("pageerror", (e) => errs.push(e.message));
  await b.goto(BASE); await b.waitForSelector("#f-B1");
  console.log("empty form:", await label(b));
  await b.fill(".resumerow input", code.toLowerCase()); await b.click(".resumerow .savebtn");
  await b.waitForFunction(() => /back/.test(document.querySelector(".savemsg").textContent));
  const after = await dump(b), labelAfter = await label(b);
  console.log("after resume:", labelAfter);
  const x = before.split("\n"), y = after.split("\n"); let diff = 0;
  x.forEach((l, i) => { if (l !== y[i]) { diff++; console.log("DIFF", l.slice(0, 120), "=>", (y[i] || "").slice(0, 120)); } });
  console.log("controls compared:", x.length, "fields; differences:", diff);
  console.log("file notes:", await b.$$eval(".filenote", (n) => n.map((x) => x.textContent.slice(0, 50))));
  console.log("sec B msg:", await b.textContent("#sec-B .secmsg"), "| G4 sum:", await b.textContent("#bsum-G4"));
  await b.fill(".resumerow input", "GA27-ZZZ-ZZZ-ZZZ"); await b.click(".resumerow .savebtn");
  await b.waitForFunction(() => /could not find/.test(document.querySelector(".savemsg").textContent)); console.log("bad code ok");
  console.log("page errors:", errs.length ? errs : "none");
  await browser.close();
  process.exit(diff || errs.length ? 1 : 0);
})();
