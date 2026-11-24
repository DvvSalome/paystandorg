/* Applications dashboard for the Paystand team. Read-only.
   Every value shown comes from applicants, so it is only ever written with textContent, never as HTML. */
(function () {
  "use strict";
  var G = window.GA27, CFG = window.GA27_CONFIG || {};
  var SECTIONS = G.SECTIONS, FIELDS = G.FIELDS;
  var SS_KEY = "ga27-admin-code", SEEN_KEY = "ga27-admin-seen";
  var MONEY = { B5: 1, G1: 1, G2: 1 };
  var APPS = [], VIEWER = "", UPDATED = null, FILTER = { q: "", profile: "", route: "", country: "", type: "", sort: "new" };

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function fieldById(id) { for (var i = 0; i < FIELDS.length; i++) if (FIELDS[i].id === id) return FIELDS[i]; return null; }
  function ans(a, id) { var v = a.answers[id]; return v == null ? "" : v; }
  function txt(v) { return Array.isArray(v) ? v.join("; ") : v === true ? "Yes" : v === false ? "No" : String(v == null ? "" : v); }
  function num(x) { var n = parseFloat(String(x == null ? "" : x).replace(/[$,\s]/g, "")); return isNaN(n) ? null : n; }
  function money(n) { return n == null ? "—" : "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 }); }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  function day(iso) { var d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }); }
  function kb(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function shortType(a1) { return String(a1 || "").replace(/\s*\(.*$/, ""); }
  function safeUrl(u) { return /^https?:\/\/[^\s]+$/i.test(String(u || "").trim()) ? String(u).trim() : ""; }

  function seen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"); } catch (e) { return []; } }
  function markSeen(id) { try { var s = seen(); if (s.indexOf(id) === -1) { s.push(id); localStorage.setItem(SEEN_KEY, JSON.stringify(s)); } } catch (e) {} }

  /* ---------- API ---------- */
  function api(route, body) {
    var code = ""; try { code = sessionStorage.getItem(SS_KEY) || ""; } catch (e) {}
    return fetch(CFG.endpoint + route, { method: "POST", headers: { "Content-Type": "application/json", "x-admin-code": code }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) { var e = new Error(j.error || "Request failed"); e.status = r.status; throw e; } return j; }); });
  }
  function load(silent) {
    return api("/admin/list").then(function (j) {
      APPS = j.applications || []; VIEWER = j.viewer || ""; UPDATED = new Date();
      $("login").hidden = true; $("app").hidden = false; $("viewer").textContent = VIEWER ? "Signed in as " + VIEWER : "";
      route();
    }).catch(function (e) {
      if (e.status === 401 || e.status === 429 || !silent) { showLogin(e.message, e.status === 401 && !silent ? "" : null); }
      throw e;
    });
  }
  function showLogin(msg) {
    $("app").hidden = true; $("login").hidden = false; $("loginerr").textContent = msg || "";
    try { sessionStorage.removeItem(SS_KEY); } catch (e) {}
  }

  /* ---------- derived data ---------- */
  function orgName(a) { return ans(a, "B1") || "(no name)"; }
  function searchText(a) {
    var parts = [a.application_id];
    Object.keys(a.answers).forEach(function (k) { parts.push(txt(a.answers[k])); });
    a.files.forEach(function (f) { parts.push(f.name); });
    return parts.join(" \n ").toLowerCase();
  }
  function filtered() {
    var q = FILTER.q.trim().toLowerCase(), s = seen();
    var out = APPS.filter(function (a) {
      if (FILTER.profile && a.profile !== FILTER.profile) return false;
      if (FILTER.route && a.route !== FILTER.route) return false;
      if (FILTER.country && ans(a, "B2") !== FILTER.country) return false;
      if (FILTER.type && shortType(ans(a, "A1")) !== FILTER.type) return false;
      if (q) { a._s = a._s || searchText(a); if (a._s.indexOf(q) === -1) return false; }
      return true;
    });
    out.sort(function (x, y) {
      if (FILTER.sort === "amount") return (num(ans(y, "G2")) || 0) - (num(ans(x, "G2")) || 0);
      if (FILTER.sort === "name") return orgName(x).localeCompare(orgName(y));
      if (FILTER.sort === "old") return String(x.finalized_at).localeCompare(String(y.finalized_at));
      return String(y.finalized_at).localeCompare(String(x.finalized_at));
    });
    return out;
  }
  function uniq(fn) { var m = {}; APPS.forEach(function (a) { var v = fn(a); if (v) m[v] = 1; }); return Object.keys(m).sort(); }

  /* ---------- list view ---------- */
  function route() {
    var id = decodeURIComponent((location.hash || "").replace(/^#\/?/, ""));
    var a = id && APPS.filter(function (x) { return x.application_id === id; })[0];
    window.scrollTo(0, 0);
    if (a) renderDetail(a); else renderList();
  }
  function tile(n, l, sub) {
    var t = el("div", "tile"); t.appendChild(el("div", "n", n)); t.appendChild(el("div", "l", l));
    if (sub) t.appendChild(el("div", "sub", sub)); return t;
  }
  function count(fn, v) { return APPS.filter(function (a) { return fn(a) === v; }).length; }
  function select(label, opts, key) {
    var s = el("select"); s.setAttribute("aria-label", label);
    var o0 = el("option", null, label); o0.value = ""; s.appendChild(o0);
    opts.forEach(function (o) {
      var val = Array.isArray(o) ? o[0] : o, name = Array.isArray(o) ? o[1] : o;      // "Brazil" or ["amount", "Largest request"]
      var op = el("option", null, name); op.value = val; if (val === FILTER[key]) op.selected = true; s.appendChild(op);
    });
    s.addEventListener("change", function () { FILTER[key] = s.value; renderRows(); });
    return s;
  }
  var rowsHost, countEl;
  function renderList() {
    var m = clear($("main"));
    var total = APPS.reduce(function (s, a) { return s + (num(ans(a, "G2")) || 0); }, 0);
    var tiles = el("div", "tiles");
    tiles.appendChild(tile(String(APPS.length), "Applications received"));
    tiles.appendChild(tile(money(total), "Total requested", APPS.length ? "Average " + money(total / APPS.length) : ""));
    tiles.appendChild(tile(count(function (a) { return a.profile; }, "Initial") + " / " + count(function (a) { return a.profile; }, "Established"), "Initial / Established"));
    tiles.appendChild(tile(count(function (a) { return a.route; }, "New") + " / " + count(function (a) { return a.route; }, "Renewal"), "New / Renewal"));
    tiles.appendChild(tile(String(uniq(function (a) { return ans(a, "B2"); }).length), "Countries"));
    m.appendChild(tiles);

    var tb = el("div", "toolbar");
    var q = el("input"); q.type = "search"; q.placeholder = "Search any answer, organization, ID…"; q.value = FILTER.q; q.setAttribute("aria-label", "Search");
    q.addEventListener("input", function () { FILTER.q = q.value; renderRows(); });
    tb.appendChild(q);
    tb.appendChild(select("All profiles", ["Initial", "Established"], "profile"));
    tb.appendChild(select("New and renewal", ["New", "Renewal"], "route"));
    tb.appendChild(select("All countries", uniq(function (a) { return ans(a, "B2"); }), "country"));
    tb.appendChild(select("All applicant types", uniq(function (a) { return shortType(ans(a, "A1")); }), "type"));
    var so = select("Sort", [["new", "Newest first"], ["old", "Oldest first"], ["amount", "Largest request"], ["name", "Name A–Z"]], "sort");
    so.firstChild.remove(); tb.appendChild(so);
    countEl = el("span", "count"); tb.appendChild(countEl);
    m.appendChild(tb);
    m.appendChild(el("p", "upd", "Updated " + (UPDATED ? UPDATED.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : "") + ". Click an application to read all of its answers."));
    rowsHost = el("div", "list"); m.appendChild(rowsHost);
    renderRows();
  }
  function renderRows() {
    var list = filtered(), s = seen();
    countEl.textContent = list.length + " of " + APPS.length + " shown";
    clear(rowsHost);
    if (!list.length) { rowsHost.appendChild(el("div", "empty", APPS.length ? "No application matches these filters." : "No applications have arrived yet.")); return; }
    var t = el("table"), th = el("thead"), hr = el("tr");
    [["Organization / project", ""], ["Country", ""], ["Type", ""], ["Stage", ""], ["Requested", "num"], ["Submitted", ""], ["Files", "num"]].forEach(function (h) { var c = el("th", h[1], h[0]); hr.appendChild(c); });
    th.appendChild(hr); t.appendChild(th);
    var tbd = el("tbody");
    list.forEach(function (a) {
      var tr = el("tr", "row"); tr.tabIndex = 0; tr.setAttribute("role", "link");
      var c1 = el("td"); var o = el("div", "org", orgName(a));
      if (s.indexOf(a.application_id) === -1) o.appendChild(el("span", "badge", "NEW"));
      c1.appendChild(o); c1.appendChild(el("div", "mono muted", a.application_id));
      var proj = a.answers.E1__title; if (proj) c1.appendChild(el("div", "muted", proj));
      tr.appendChild(c1);
      tr.appendChild(cell("Country", ans(a, "B2") || "—"));
      tr.appendChild(cell("Type", shortType(ans(a, "A1")) || "—"));
      var st = el("td"); st.setAttribute("data-l", "Stage");
      if (a.profile) st.appendChild(el("span", "chip" + (a.profile === "Initial" ? " warm" : ""), a.profile));
      if (a.route) st.appendChild(el("span", "chip", a.route));
      tr.appendChild(st);
      var am = cell("Requested", money(num(ans(a, "G2")))); am.className = "num"; tr.appendChild(am);
      tr.appendChild(cell("Submitted", day(a.finalized_at)));
      var fl = cell("Files", String(a.files.length)); fl.className = "num"; tr.appendChild(fl);
      var open = function () { location.hash = "#/" + encodeURIComponent(a.application_id); };
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter") open(); });
      tbd.appendChild(tr);
    });
    t.appendChild(tbd); rowsHost.appendChild(t);
  }
  function cell(l, v) { var c = el("td", null, v); c.setAttribute("data-l", l); return c; }

  /* ---------- detail view ---------- */
  function fact(k, v) { var f = el("div", "fact"); f.appendChild(el("div", "k", k)); f.appendChild(el("div", "v", v || "—")); return f; }
  function renderDetail(a) {
    markSeen(a.application_id);
    var m = clear($("main"));
    var back = el("a", "back", "← All applications"); back.href = "#/"; m.appendChild(back);

    var head = el("div", "card head");
    head.appendChild(el("p", "kicker", a.application_id));
    head.appendChild(el("h2", null, orgName(a)));
    if (a.profile) head.appendChild(el("span", "chip" + (a.profile === "Initial" ? " warm" : ""), a.profile));
    if (a.route) head.appendChild(el("span", "chip", a.route));
    var facts = el("div", "facts");
    facts.appendChild(fact("Project", a.answers.E1__title));
    facts.appendChild(fact("Country", ans(a, "B2")));
    facts.appendChild(fact("Applicant type", shortType(ans(a, "A1"))));
    facts.appendChild(fact("Amount requested", money(num(ans(a, "G2")))));
    facts.appendChild(fact("Total project budget", money(num(ans(a, "G1")))));
    facts.appendChild(fact("Primary contact", [a.answers.D1__name, a.answers.D1__email].filter(Boolean).join(" · ")));
    facts.appendChild(fact("Submitted", when(a.finalized_at)));
    head.appendChild(facts);
    var act = el("div", "actions");
    var pr = el("button", "btn", "Print / save as PDF"); pr.type = "button"; pr.addEventListener("click", function () { window.print(); });
    act.appendChild(pr); head.appendChild(act);
    m.appendChild(head);

    var nav = el("nav", "snav"); nav.setAttribute("aria-label", "Sections");
    m.appendChild(nav);
    var V = a.answers, ST = { profile: a.profile || "—" };
    SECTIONS.forEach(function (sec) {
      var fs = FIELDS.filter(function (f) { return f.s === sec.id; });
      // A question is hidden only if its rule says "does not apply" AND it has no stored answer: nothing saved is ever hidden.
      var shown = fs.filter(function (f) {
        var has = (V[f.id] != null && txt(V[f.id]).trim() !== "") || a.files.some(function (x) { return x.question === f.id; });
        try { return !f.showIf || !!f.showIf(V, ST) || has; } catch (e) { return true; }
      });
      var hidden = fs.length - shown.length;
      var box = el("section", "card sec"); box.id = "s-" + sec.id;
      box.appendChild(el("div", "secid", "Section " + sec.id));
      box.appendChild(el("h3", null, sec.title));
      shown.forEach(function (f) { box.appendChild(renderQuestion(a, f)); });
      if (hidden) box.appendChild(el("p", "na", hidden + " question" + (hidden === 1 ? "" : "s") + " in this section did not apply to this applicant."));
      m.appendChild(box);
      var link = el("a", null, sec.id + " · " + sec.title); link.href = "#s-" + sec.id;
      link.addEventListener("click", function (e) { e.preventDefault(); box.scrollIntoView({ behavior: "smooth", block: "start" }); });
      nav.appendChild(link);
    });
  }

  function subTable(cols, rows) {
    var t = el("table", "sub-t"), th = el("thead"), hr = el("tr");
    cols.forEach(function (c) { hr.appendChild(el("th", null, c[0])); }); th.appendChild(hr); t.appendChild(th);
    var tb = el("tbody");
    rows.forEach(function (r) { var tr = el("tr"); cols.forEach(function (c) { tr.appendChild(el("td", null, txt(r[c[1]]))); }); tb.appendChild(tr); });
    t.appendChild(tb); return t;
  }
  function pretty(k) { return k.replace(/_/g, " ").replace(/^./, function (c) { return c.toUpperCase(); }); }
  function parts(a, id) {
    return Object.keys(a.answers).filter(function (k) { return k.indexOf(id + "__") === 0 && /^[A-Za-z_]+$/.test(k.slice(id.length + 2)); })
      .map(function (k) { return [k.slice(id.length + 2), a.answers[k]]; });
  }
  function renderQuestion(a, f) {
    var q = el("div", "q"), lab = el("div", "ql");
    lab.appendChild(el("span", "qid", f.id)); lab.appendChild(document.createTextNode(f.label)); q.appendChild(lab);
    var body = el("div", "a"), v = a.answers[f.id], has = v != null && txt(v).trim() !== "";
    var files = a.files.filter(function (x) { return x.question === f.id; });

    if (f.type === "file" || files.length) {
      files.forEach(function (fl) {
        var w = el("span", "file"); w.appendChild(el("span", null, fl.name + " (" + kb(fl.size) + ")"));
        var b = el("button", "btn", "Open"); b.type = "button";
        b.addEventListener("click", function () {
          b.disabled = true;
          api("/admin/file", { application_id: a.application_id, question: f.id }).then(function (j) { window.open(j.url, "_blank", "noopener"); })
            .catch(function (e) { alert("Could not open the file: " + e.message); }).then(function () { b.disabled = false; });
        });
        w.appendChild(b); body.appendChild(w);
      });
      if (!files.length) { body.className = "a none"; body.textContent = "No file attached"; }
      if (f.type !== "file" && has) { body.appendChild(el("div", null, txt(v))); }
    } else if (f.type === "checks" && Array.isArray(v) && v.length) {
      var ul = el("ul"); v.forEach(function (x) { ul.appendChild(el("li", null, x)); }); body.appendChild(ul);
    } else if (f.type === "milestones" && a.answers.E10__rows) {
      body.appendChild(subTable([["Milestone", "milestone"], ["Date", "date"], ["Evidence", "evidence"]], a.answers.E10__rows));
    } else if (f.type === "funders" && has) {
      body.appendChild(el("div", null, a.answers.G3__yn || ""));
      if ((a.answers.G3__rows || []).length) body.appendChild(subTable([["Funder", "funder"], ["Amount", "amount"], ["Status", "status"]], a.answers.G3__rows));
    } else if (f.type === "budget" && a.answers.G4__cats) {
      var cats = a.answers.G4__cats, rows = Object.keys(cats).map(function (k) { return { cat: k, amt: money(num(cats[k])) }; });
      rows.push({ cat: "Total", amt: money(Object.keys(cats).reduce(function (s, k) { return s + (num(cats[k]) || 0); }, 0)) });
      body.appendChild(subTable([["Category", "cat"], ["Amount", "amt"]], rows));
    } else if (/^(composite|titlesummary|datepair|safeguard|submitter)$/.test(f.type) && parts(a, f.id).length) {
      var dl = el("dl", "kv");
      parts(a, f.id).forEach(function (p) { dl.appendChild(el("dt", null, pretty(p[0]))); dl.appendChild(el("dd", null, txt(p[1]))); });
      body.appendChild(dl);
    } else if (f.type === "url" && safeUrl(v)) {
      var l = el("a", null, safeUrl(v)); l.href = safeUrl(v); l.target = "_blank"; l.rel = "noopener noreferrer"; body.appendChild(l);
    } else if (has) {
      body.textContent = MONEY[f.id] && num(v) != null ? money(num(v)) : txt(v);
    } else { body.className = "a none"; body.textContent = "No answer"; }
    q.appendChild(body); return q;
  }

  /* ---------- CSV export ---------- */
  function csvCell(v) {
    var s = txt(v);
    if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;                       // stop spreadsheets from running applicant text as a formula
    return '"' + s.replace(/"/g, '""') + '"';
  }
  function exportCsv() {
    var cols = [["application_id", function (a) { return a.application_id; }], ["submitted_at", function (a) { return a.finalized_at; }],
      ["profile", function (a) { return a.profile || ""; }], ["route", function (a) { return a.route || ""; }]];
    FIELDS.forEach(function (f) { cols.push([f.id + " " + f.label, function (a) { return ans(a, f.id); }]); });
    cols.push(["files", function (a) { return a.files.map(function (x) { return x.question + ": " + x.name; }).join("; "); }]);
    var lines = [cols.map(function (c) { return csvCell(c[0]); }).join(",")];
    filtered().forEach(function (a) { lines.push(cols.map(function (c) { return csvCell(c[1](a)); }).join(",")); });
    var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    var link = el("a"); link.href = URL.createObjectURL(blob); link.download = "applications-" + new Date().toISOString().slice(0, 10) + ".csv";
    document.body.appendChild(link); link.click(); link.remove();
  }

  /* ---------- wiring ---------- */
  $("loginform").addEventListener("submit", function (e) {
    e.preventDefault();
    try { sessionStorage.setItem(SS_KEY, $("code").value.trim()); } catch (x) {}
    $("loginerr").textContent = "Checking…";
    load(false).then(function () { $("code").value = ""; $("loginerr").textContent = ""; }).catch(function () {});
  });
  $("signout").addEventListener("click", function () { APPS = []; location.hash = ""; showLogin(""); });
  $("refresh").addEventListener("click", function () { var b = $("refresh"); b.disabled = true; load(true).catch(function () {}).then(function () { b.disabled = false; }); });
  $("export").addEventListener("click", exportCsv);
  window.addEventListener("hashchange", function () { if (APPS.length || !$("app").hidden) route(); });
  window.setInterval(function () {                                  // new applications show up without pressing anything
    if (document.visibilityState === "visible" && !$("app").hidden && !/^#\/./.test(location.hash)) load(true).catch(function () {});
  }, 90000);

  var saved = ""; try { saved = sessionStorage.getItem(SS_KEY) || ""; } catch (e) {}
  if (!CFG.endpoint) { showLogin("The dashboard is not connected (no endpoint in config.js)."); }
  else if (saved) { load(true).catch(function () { showLogin(""); }); }
  else showLogin("");
})();
