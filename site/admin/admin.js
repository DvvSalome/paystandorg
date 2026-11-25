/* Applications dashboard for the Paystand team. Read-only.
   Every value shown comes from applicants, so it is only ever written with textContent, never as HTML. */
(function () {
  "use strict";
  var G = window.GA27, CFG = window.GA27_CONFIG || {};
  var SECTIONS = G.SECTIONS, FIELDS = G.FIELDS;
  var SS_KEY = "ga27-admin-code", SEEN_KEY = "ga27-admin-seen";
  var MONEY = { B5: 1, G1: 1, G2: 1 };
  var APPS = [], DRAFTS = null, VIEWER = "", UPDATED = null, LOADED = false;      // DRAFTS stays null if the server has no drafts route yet
  var FILTER = { q: "", profile: "", route: "", country: "", type: "", sort: "new" };
  var spy = null;

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); return n; }
  function ans(a, id) { var v = a.answers[id]; return v == null ? "" : v; }
  function txt(v) { return Array.isArray(v) ? v.join("; ") : v === true ? "Yes" : v === false ? "No" : String(v == null ? "" : v); }
  function num(x) { var n = parseFloat(String(x == null ? "" : x).replace(/[$,\s]/g, "")); return isNaN(n) ? null : n; }
  function money(n) { return n == null ? "—" : "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 }); }
  function compact(n) { return n >= 1e6 ? "$" + (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? "$" + Math.round(n / 100) / 10 + "K" : "$" + n; }
  function when(iso) { var d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
  function day(iso) { var d = new Date(iso); return isNaN(d) ? "—" : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }); }
  function ago(iso) {
    var s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (isNaN(s)) return "";
    if (s < 90) return "just now"; if (s < 3600) return Math.round(s / 60) + " min ago";
    if (s < 86400) return Math.round(s / 3600) + " h ago"; var d = Math.round(s / 86400); return d + (d === 1 ? " day ago" : " days ago");
  }
  function kb(n) { return n >= 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function shortType(a1) { return String(a1 || "").replace(/\s*\(.*$/, ""); }
  function head1(s) { return String(s || "").split(" — ")[0]; }
  function safeUrl(u) { return /^https?:\/\/[^\s]+$/i.test(String(u || "").trim()) ? String(u).trim() : ""; }
  function orgName(a) { return ans(a, "B1") || "(no name)"; }
  function plural(n, w) { return n + " " + w + (n === 1 ? "" : "s"); }

  function seen() { try { return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]"); } catch (e) { return []; } }
  function markSeen(id) { try { var s = seen(); if (s.indexOf(id) === -1) { s.push(id); localStorage.setItem(SEEN_KEY, JSON.stringify(s)); } } catch (e) {} }
  function unseenCount() { var s = seen(); return APPS.filter(function (a) { return s.indexOf(a.application_id) === -1; }).length; }

  var toastT;
  function toast(msg, bad) {
    var t = $("toast"); t.textContent = msg; t.className = "toast" + (bad ? " bad" : ""); t.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { t.hidden = true; }, 4500);
  }

  /* ---------- tooltip (one for the whole page; text only) ---------- */
  function tip(node, title, sub) {
    var t = $("tip");
    function show(x, y) {
      clear(t); t.appendChild(el("b", null, title)); if (sub) t.appendChild(el("span", null, sub)); t.hidden = false;
      var w = t.offsetWidth, h = t.offsetHeight;
      t.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, x + 14)) + "px";
      t.style.top = Math.max(8, Math.min(window.innerHeight - h - 8, y + 14)) + "px";
    }
    node.addEventListener("pointermove", function (e) { show(e.clientX, e.clientY); });
    node.addEventListener("pointerleave", function () { t.hidden = true; });
    node.addEventListener("focus", function () { var r = node.getBoundingClientRect(); show(r.left + r.width / 2, r.top); });
    node.addEventListener("blur", function () { t.hidden = true; });
  }

  /* ---------- API ---------- */
  function api(route, body) {
    var code = ""; try { code = sessionStorage.getItem(SS_KEY) || ""; } catch (e) {}
    return fetch(CFG.endpoint + route, { method: "POST", headers: { "Content-Type": "application/json", "x-admin-code": code }, body: JSON.stringify(body || {}) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) { var e = new Error(j.error || "Request failed"); e.status = r.status; throw e; } return j; }); });
  }
  function load(silent) {
    var before = APPS.map(function (a) { return a.application_id; });
    var dp = api("/admin/drafts").then(function (d) { return d.drafts || []; }, function () { return null; });
    return api("/admin/list").then(function (j) {
      return dp.then(function (d) { DRAFTS = d; return j; });
    }).then(function (j) {
      APPS = j.applications || []; VIEWER = j.viewer || ""; UPDATED = new Date(); LOADED = true;
      $("login").hidden = true; $("app").hidden = false;
      $("viewer").textContent = VIEWER ? "Signed in as " + VIEWER : ""; $("avatarletter").textContent = (VIEWER || "?").charAt(0);
      route();
      var fresh = APPS.filter(function (a) { return before.indexOf(a.application_id) === -1; }).length;
      if (silent && before.length && fresh) toast(plural(fresh, "new application") + " arrived");
    }).catch(function (e) {
      if (e.status === 401 || e.status === 429 || !silent) showLogin(e.message);
      else toast("Could not refresh: " + e.message, true);
      throw e;
    });
  }
  function showLogin(msg) {
    $("app").hidden = true; $("login").hidden = false; $("loginerr").textContent = msg || "";
    try { sessionStorage.removeItem(SS_KEY); } catch (e) {}
  }

  /* ---------- filtering ---------- */
  function searchText(a) {
    var parts = [a.application_id];
    Object.keys(a.answers).forEach(function (k) { parts.push(txt(a.answers[k])); });
    a.files.forEach(function (f) { parts.push(f.name); });
    return parts.join(" \n ").toLowerCase();
  }
  function filtered() {
    var q = FILTER.q.trim().toLowerCase();
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
  function anyFilter() { return !!(FILTER.q || FILTER.profile || FILTER.route || FILTER.country || FILTER.type); }

  /* ---------- routing ---------- */
  function setTab(name) {
    Array.prototype.forEach.call($("tabs").querySelectorAll("a"), function (a) {
      if (a.getAttribute("data-tab") === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }
  function route() {
    if (!LOADED) return;
    if (spy) { spy.disconnect(); spy = null; }
    var h = decodeURIComponent((location.hash || "").replace(/^#\/?/, ""));
    window.scrollTo(0, 0);
    var n = unseenCount(); $("navcount").textContent = n ? String(n) : "";
    var nd = activeDrafts().length; $("navdrafts").textContent = nd ? String(nd) : "";
    if (h === "overview") { setTab("overview"); renderOverview(); return; }
    if (h === "help") { setTab("help"); renderHelp(); return; }
    if (h === "drafts") { setTab("drafts"); renderDrafts(); return; }
    var dm = /^draft\/(.+)$/.exec(h), dr = dm && (DRAFTS || []).filter(function (x) { return x.id === dm[1]; })[0];
    if (dr) { setTab("drafts"); renderDraft(dr); return; }
    var a = /^APP-/.test(h) && APPS.filter(function (x) { return x.application_id === h; })[0];
    if (a) { setTab("apps"); renderDetail(a); return; }
    setTab("apps"); renderList();
  }

  /* ---------- applications list ---------- */
  function tile(n, l, sub) {
    var t = el("div", "tile"); t.appendChild(el("div", "n", n)); t.appendChild(el("div", "l", l));
    if (sub) t.appendChild(el("div", "sub", sub)); return t;
  }
  function countBy(fn, v) { return APPS.filter(function (a) { return fn(a) === v; }).length; }
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
  var rowsHost, countEl, chipsEl;
  function pageHead(title, sub) {
    var h = el("div", "pagehead"), l = el("div"); l.appendChild(el("h2", null, title));
    if (sub) l.appendChild(el("p", null, sub)); h.appendChild(l);
    var live = el("div", "live"); live.appendChild(el("i"));
    var last = APPS[0] && APPS.slice().sort(function (x, y) { return String(y.finalized_at).localeCompare(String(x.finalized_at)); })[0];
    live.appendChild(el("span", null, "Updated " + (UPDATED ? UPDATED.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }) : "") +
      (last ? " · last application " + ago(last.finalized_at) : "")));
    h.appendChild(live); return h;
  }
  function renderList() {
    var m = clear($("main"));
    m.appendChild(pageHead("Applications", "Click an application to read all of its answers and open its documents."));
    var total = APPS.reduce(function (s, a) { return s + (num(ans(a, "G2")) || 0); }, 0), fresh = unseenCount();
    var tiles = el("div", "tiles");
    tiles.appendChild(tile(String(APPS.length), "Applications received", fresh ? fresh + " not opened yet" : "All opened"));
    tiles.appendChild(tile(money(total), "Total requested", APPS.length ? "Average " + money(total / APPS.length) : ""));
    tiles.appendChild(tile(countBy(function (a) { return a.profile; }, "Initial") + " / " + countBy(function (a) { return a.profile; }, "Established"), "Initial / Established"));
    tiles.appendChild(tile(countBy(function (a) { return a.route; }, "New") + " / " + countBy(function (a) { return a.route; }, "Renewal"), "New / Renewal"));
    if (DRAFTS !== null) {                                    // started but not submitted: one click to see them
      var dt = tile(String(activeDrafts().length), "Drafts in progress", "Started, not submitted · view"); dt.className += " link"; dt.tabIndex = 0; dt.setAttribute("role", "link");
      dt.addEventListener("click", function () { location.hash = "#/drafts"; }); dt.addEventListener("keydown", function (e) { if (e.key === "Enter") location.hash = "#/drafts"; });
      tiles.appendChild(dt);
    }
    m.appendChild(tiles);

    var tb = el("div", "toolbar");
    var q = el("input"); q.type = "search"; q.placeholder = "Search any answer, organization, ID…"; q.value = FILTER.q; q.setAttribute("aria-label", "Search");
    q.addEventListener("input", function () { FILTER.q = q.value; renderRows(); });
    tb.appendChild(q);
    tb.appendChild(select("All stages", ["Initial", "Established"], "profile"));
    tb.appendChild(select("New and renewal", ["New", "Renewal"], "route"));
    tb.appendChild(select("All countries", uniq(function (a) { return ans(a, "B2"); }), "country"));
    tb.appendChild(select("All applicant types", uniq(function (a) { return shortType(ans(a, "A1")); }), "type"));
    var so = select("Sort", [["new", "Newest first"], ["old", "Oldest first"], ["amount", "Largest request"], ["name", "Name A–Z"]], "sort");
    so.firstChild.remove(); tb.appendChild(so);
    countEl = el("span", "count"); tb.appendChild(countEl);
    m.appendChild(tb);
    chipsEl = el("div", "chips"); m.appendChild(chipsEl);
    rowsHost = el("div", "list"); m.appendChild(rowsHost);
    if (!LOADED) { for (var i = 0; i < 4; i++) rowsHost.appendChild(el("div", "skel")); return; }
    renderRows();
  }
  function filterChips() {
    clear(chipsEl);
    [["profile", "Stage"], ["route", "Route"], ["country", "Country"], ["type", "Type"]].forEach(function (f) {
      if (!FILTER[f[0]]) return;
      var c = el("button", "fchip", f[1] + ": " + FILTER[f[0]]); c.type = "button"; c.setAttribute("aria-label", "Remove filter " + f[1]);
      c.appendChild(el("b", null, "×")); c.addEventListener("click", function () { FILTER[f[0]] = ""; renderList(); }); chipsEl.appendChild(c);
    });
    if (FILTER.q) { var c = el("button", "fchip", "Search: " + FILTER.q); c.type = "button"; c.appendChild(el("b", null, "×")); c.addEventListener("click", function () { FILTER.q = ""; renderList(); }); chipsEl.appendChild(c); }
  }
  function avatar(a) { return el("div", "mono-av", orgName(a).replace(/^[^A-Za-z0-9À-ÿ]+/, "").charAt(0) || "?"); }
  function cell(l, v, cls) { var c = el("td", cls || null, v); c.setAttribute("data-l", l); return c; }
  function renderRows() {
    var list = filtered(), s = seen();
    countEl.textContent = list.length + " of " + APPS.length + " shown";
    filterChips(); clear(rowsHost);
    if (!list.length) {
      var e = el("div", "empty"); e.appendChild(el("b", null, APPS.length ? "No application matches these filters" : "No applications yet"));
      e.appendChild(el("span", null, APPS.length ? "Try a different search or clear the filters." : "They will appear here as soon as someone submits the form."));
      if (APPS.length && anyFilter()) { var br = el("div"); br.style.marginTop = "14px"; var b = el("button", "btn", "Clear filters"); b.type = "button";
        b.addEventListener("click", function () { FILTER = { q: "", profile: "", route: "", country: "", type: "", sort: FILTER.sort }; renderList(); }); br.appendChild(b); e.appendChild(br); }
      rowsHost.appendChild(e); return;
    }
    var t = el("table", "main"), th = el("thead"), hr = el("tr");
    [["Organization / project", ""], ["Country", ""], ["Type", ""], ["Stage", ""], ["Requested", "num"], ["Submitted", ""], ["Files", "num"]].forEach(function (h) { hr.appendChild(el("th", h[1], h[0])); });
    th.appendChild(hr); t.appendChild(th);
    var tbd = el("tbody");
    list.forEach(function (a) {
      var tr = el("tr", "row"); tr.tabIndex = 0; tr.setAttribute("role", "link");
      var c1 = el("td"), w = el("div", "who"); w.appendChild(avatar(a));
      var txtBox = el("div"), o = el("div", "org", orgName(a));
      if (s.indexOf(a.application_id) === -1) o.appendChild(el("span", "badge", "NEW"));
      txtBox.appendChild(o);
      if (a.answers.E1__title) txtBox.appendChild(el("div", "proj", a.answers.E1__title));
      txtBox.appendChild(el("div", "mono", a.application_id));
      w.appendChild(txtBox); c1.appendChild(w); tr.appendChild(c1);
      tr.appendChild(cell("Country", ans(a, "B2") || "—"));
      tr.appendChild(cell("Type", shortType(ans(a, "A1")) || "—"));
      var st = el("td"); st.setAttribute("data-l", "Stage");
      if (a.profile) st.appendChild(el("span", "chip" + (a.profile === "Initial" ? " warm" : ""), a.profile));
      if (a.route) st.appendChild(el("span", "chip", a.route));
      tr.appendChild(st);
      tr.appendChild(cell("Requested", money(num(ans(a, "G2"))), "num amt"));
      tr.appendChild(cell("Submitted", day(a.finalized_at)));
      tr.appendChild(cell("Files", String(a.files.length), "num"));
      var open = function () { location.hash = "#/" + encodeURIComponent(a.application_id); };
      tr.addEventListener("click", open);
      tr.addEventListener("keydown", function (e) { if (e.key === "Enter") open(); });
      tbd.appendChild(tr);
    });
    t.appendChild(tbd); rowsHost.appendChild(t);
  }

  /* ---------- detail ---------- */
  function fact(k, v) { var f = el("div", "fact"); f.appendChild(el("div", "k", k)); f.appendChild(el("div", "v", v || "—")); return f; }
  function renderDetail(a) {
    markSeen(a.application_id);
    var n = unseenCount(); $("navcount").textContent = n ? String(n) : "";
    var m = clear($("main"));
    var order = filtered(), idx = -1;
    order.forEach(function (x, i) { if (x.application_id === a.application_id) idx = i; });
    if (idx === -1) { order = APPS; order.forEach(function (x, i) { if (x.application_id === a.application_id) idx = i; }); }

    var cr = el("div", "crumbs");
    var back = el("a", "btn small", "← Applications"); back.href = "#/"; cr.appendChild(back);
    var sp = el("div", "sp");
    function nav(label, target) {
      var b = el(target ? "a" : "span", "btn small", label);
      if (target) b.href = "#/" + encodeURIComponent(target.application_id); else b.setAttribute("aria-disabled", "true");
      if (!target) b.style.opacity = ".45"; return b;
    }
    sp.appendChild(nav("‹ Previous", order[idx - 1]));
    sp.appendChild(el("span", "muted", idx + 1 + " of " + order.length));
    sp.appendChild(nav("Next ›", order[idx + 1]));
    var cp = el("button", "btn small", "Copy link"); cp.type = "button";
    cp.addEventListener("click", function () { if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(function () { toast("Link copied"); }, function () {}); });
    var pr = el("button", "btn small", "Print / PDF"); pr.type = "button"; pr.addEventListener("click", function () { window.print(); });
    sp.appendChild(cp); sp.appendChild(pr); cr.appendChild(sp); m.appendChild(cr);

    var head = el("div", "card head"); head.appendChild(avatar(a));
    var hb = el("div"); hb.style.minWidth = "0"; hb.style.flex = "1";
    hb.appendChild(el("p", "kicker", a.application_id));
    hb.appendChild(el("h2", null, orgName(a)));
    if (a.profile) hb.appendChild(el("span", "chip" + (a.profile === "Initial" ? " warm" : ""), a.profile));
    if (a.route) hb.appendChild(el("span", "chip", a.route));
    var facts = el("div", "facts");
    facts.appendChild(fact("Project", a.answers.E1__title));
    facts.appendChild(fact("Country", ans(a, "B2")));
    facts.appendChild(fact("Applicant type", shortType(ans(a, "A1"))));
    facts.appendChild(fact("Amount requested", money(num(ans(a, "G2")))));
    facts.appendChild(fact("Total project budget", money(num(ans(a, "G1")))));
    facts.appendChild(fact("Primary contact", [a.answers.D1__name, a.answers.D1__email].filter(Boolean).join(" · ")));
    facts.appendChild(fact("Submitted", when(a.finalized_at)));
    hb.appendChild(facts); head.appendChild(hb); m.appendChild(head);

    var lay = el("div", "layout"), rail = el("nav", "rail"), body = el("div");
    rail.setAttribute("aria-label", "Sections"); rail.appendChild(el("p", "rt", "Sections"));
    lay.appendChild(rail); lay.appendChild(body); m.appendChild(lay);

    buildSections(a, body, rail, false);
  }

  // One card per section. For a draft only the questions already answered are shown (and the rest are counted).
  function buildSections(a, body, rail, isDraft) {
    var V = a.answers, ST = { profile: a.profile || "—" }, boxes = [];
    SECTIONS.forEach(function (sec) {
      var fs = FIELDS.filter(function (f) { return f.s === sec.id; });
      function has(f) { return (V[f.id] != null && txt(V[f.id]).trim() !== "") || (isDraft ? !!(a.draftFiles && a.draftFiles[f.id]) : a.files.some(function (x) { return x.question === f.id; })); }
      // A question is hidden only if its rule says "does not apply" AND it has no stored answer: nothing saved is ever hidden.
      var shown = fs.filter(function (f) {
        if (isDraft) return has(f);
        try { return !f.showIf || !!f.showIf(V, ST) || has(f); } catch (e) { return true; }
      });
      var hidden = fs.length - shown.length;
      if (isDraft && !shown.length) { hidden = 0; }
      var box = el("section", "card sec"); box.id = "s-" + sec.id;
      box.appendChild(el("div", "secid", "Section " + sec.id));
      box.appendChild(el("h3", null, sec.title));
      if (isDraft && !shown.length) box.appendChild(el("p", "na", "Nothing answered in this section yet."));
      shown.forEach(function (f) { box.appendChild(renderQuestion(a, f)); });
      if (hidden) box.appendChild(el("p", "na", isDraft ? plural(hidden, "question") + " here not answered yet." : plural(hidden, "question") + " in this section did not apply to this applicant."));
      body.appendChild(box); boxes.push(box);
      var link = el("a"); link.href = "#s-" + sec.id; link.appendChild(el("i", null, sec.id)); link.appendChild(document.createTextNode(sec.title));
      link.addEventListener("click", function (e) { e.preventDefault(); box.scrollIntoView({ behavior: "smooth", block: "start" }); });
      rail.appendChild(link);
    });
    if ("IntersectionObserver" in window) {                       // highlight the section being read
      var links = rail.querySelectorAll("a");
      spy = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { var i = boxes.indexOf(e.target); Array.prototype.forEach.call(links, function (l, j) { l.classList.toggle("on", i === j); }); } });
      }, { rootMargin: "-90px 0px -65% 0px" });
      boxes.forEach(function (b) { spy.observe(b); });
      if (links[0]) links[0].classList.add("on");
    }
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

    if (a.draftFiles && f.type === "file") {                   // a draft keeps only the file name: the file itself is never stored
      if (a.draftFiles[f.id]) body.textContent = "Attached before saving: " + a.draftFiles[f.id] + " (not stored in the draft)";
      else { body.className = "a none"; body.textContent = "No file attached"; }
    } else if (f.type === "file" || files.length) {
      files.forEach(function (fl) {
        var w = el("span", "file"); w.appendChild(el("span", null, fl.name + " (" + kb(fl.size) + ")"));
        var b = el("button", "btn small", "Open"); b.type = "button";
        b.addEventListener("click", function () {
          b.disabled = true;
          api("/admin/file", { application_id: a.application_id, question: f.id }).then(function (j) { window.open(j.url, "_blank", "noopener"); })
            .catch(function (e) { toast("Could not open the file: " + e.message, true); }).then(function () { b.disabled = false; });
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

  /* ---------- drafts (applications started and not submitted) ---------- */
  var DRAFT_TTL_MS = 60 * 86400000;
  function nonEmpty(v) { return v != null && txt(v).trim() !== ""; }
  // Older drafts only kept the value of every control, in the order the form builds them. Rebuild the answers the
  // way the form does (see site/assets/form.js). Newer drafts carry `answers` and skip this.
  function decodeFields(fields) {
    var A = {};
    FIELDS.forEach(function (f) {
      var v = fields[f.id]; if (!v) return;
      function s(i) { return v[i] == null ? "" : String(v[i]); }
      var id = f.id, t = f.type, i, rows, r;
      if (t === "text" || t === "email" || t === "url" || t === "textarea" || t === "number" || t === "country") { if (s(0).trim()) A[id] = s(0); }
      else if (t === "radio") { i = v.indexOf(1); if (i >= 0 && f.options[i] != null) A[id] = f.options[i]; }
      else if (t === "checks") { var sel = f.options.filter(function (o, k) { return v[k] === 1; }); if (sel.length) A[id] = sel; }
      else if (t === "valuedate") { if (s(0) || s(1)) { A[id + "__value"] = s(0); A[id + "__date"] = s(1); A[id] = s(0) && s(1) ? s(0) + " @ " + s(1) : s(0) || s(1); } }
      else if (t === "baseline") {
        if (v[2] === 1) { if (s(3)) { A[id] = "Plan: " + s(3); A[id + "__mode"] = "plan"; A[id + "__plan"] = s(3); } }
        else if (s(0) || s(1)) { A[id] = s(0) && s(1) ? s(0) + " @ " + s(1) : s(0) || s(1); A[id + "__mode"] = "value"; A[id + "__value"] = s(0); A[id + "__date"] = s(1); }
      }
      else if (t === "titlesummary") { if (s(0) || s(1)) { A[id + "__title"] = s(0); A[id + "__summary"] = s(1); A[id] = [s(0), s(1)].filter(Boolean).join(" — "); } }
      else if (t === "datepair") {
        if (s(0) || s(1)) {
          A[id + "__start"] = s(0); A[id + "__end"] = s(1);
          if (s(0) && s(1)) {                                  // same duration rule as the form
            var d1 = new Date(s(0) + "T00:00:00"), d2 = new Date(s(1) + "T00:00:00");
            var mo = (d2.getFullYear() - d1.getFullYear()) * 12 + (d2.getMonth() - d1.getMonth()); if (d2.getDate() < d1.getDate()) mo -= 1;
            if (!isNaN(mo)) A[id + "__months"] = mo;
            if (mo > 0) A[id] = s(0) + " to " + s(1);
          }
        }
      }
      else if (t === "composite") {
        var any = false, vals = {};
        f.parts.forEach(function (p, k) { if (s(k)) { any = true; vals[p.k] = s(k); A[id + "__" + p.k] = s(k); } });
        if (any) A[id] = [vals.name, vals.title, vals.email, vals.phone].filter(Boolean).join(", ");
      }
      else if (t === "milestones") {
        rows = []; for (r = 0; r < 3; r++) rows.push({ milestone: s(r * 3), date: s(r * 3 + 1), evidence: s(r * 3 + 2) });
        if (rows.some(function (x) { return x.milestone || x.date || x.evidence; })) {
          A[id + "__rows"] = rows; A[id] = rows.map(function (x) { return [x.milestone, x.date, x.evidence].filter(Boolean).join(" | "); }).filter(Boolean).join("; ");
        }
      }
      else if (t === "funders") {
        var yn = v[0] === 1 ? "No" : v[1] === 1 ? "Yes" : "";            // the form builds these radios in the order No, Yes
        rows = []; for (r = 0; r < 2; r++) rows.push({ funder: s(2 + r * 3), amount: s(3 + r * 3), status: s(4 + r * 3) });
        var named = rows.filter(function (x) { return x.funder; });
        if (yn) { A[id + "__yn"] = yn; A[id + "__rows"] = rows; A[id] = yn === "Yes" && named.length ? "Yes. " + named.map(function (x) { return [x.funder, x.amount, x.status].filter(Boolean).join(", "); }).join("; ") : yn; }
      }
      else if (t === "budget") {
        var cats = {}, anyc = false; f.cats.forEach(function (c, k) { cats[c] = s(k); if (s(k)) anyc = true; });
        if (anyc) { A[id + "__cats"] = cats; A[id] = f.cats.filter(function (c) { return cats[c]; }).map(function (c) { return c + " " + cats[c]; }).join(", "); }
      }
      else if (t === "safeguard") { if (v[0] === 1 || s(1)) { A[id + "__committed"] = v[0] === 1; A[id + "__person"] = s(1); A[id] = s(1) || "A policy will be in place before funding"; } }
      else if (t === "submitter") { if (s(0) || s(1)) { A[id + "__name"] = s(0); if (s(1)) A[id + "__date"] = s(1); A[id] = [s(0), s(1)].filter(Boolean).join(", "); } }   // the date is a read-only field the form fills itself, so older drafts never kept it
    });
    return A;
  }
  var REQ_ALWAYS = FIELDS.filter(function (f) { return f.req && !f.showIf; });     // required for everybody (the others depend on earlier answers)
  function draftInfo(d) {
    if (d._i) return d._i;
    var A = d.answers || decodeFields(d.fields || {});
    var done = REQ_ALWAYS.filter(function (f) { return nonEmpty(A[f.id]) || !!d.files[f.id]; }).length;
    var secs = SECTIONS.filter(function (sec) { return FIELDS.some(function (f) { return f.s === sec.id && (nonEmpty(A[f.id]) || !!d.files[f.id]); }); }).length;
    var email = (d.email || A.D1__email || "").toLowerCase(), filledQ = FIELDS.filter(function (f) { return nonEmpty(A[f.id]) || !!d.files[f.id]; }).length;
    d._i = { A: A, done: done, total: REQ_ALWAYS.length, pct: REQ_ALWAYS.length ? Math.round(done / REQ_ALWAYS.length * 100) : 0, secs: secs, email: email, filled: filledQ,
      name: A.B1 || "", expired: Date.now() - new Date(d.updated_at).getTime() > DRAFT_TTL_MS };
    return d._i;
  }
  function submittedEmails() {
    var m = {}; APPS.forEach(function (a) { [a.answers.D1__email, a.answers.D4].forEach(function (e) { if (e) m[String(e).toLowerCase()] = 1; }); }); return m;
  }
  function draftStatus(d) { var i = draftInfo(d); return { expired: i.expired, submitted: !!(i.email && submittedEmails()[i.email]) }; }
  function activeDrafts() { return (DRAFTS || []).filter(function (d) { var s = draftStatus(d); return !s.expired && !s.submitted; }); }
  function draftSearch(d) {
    if (d._s) return d._s; var i = draftInfo(d), parts = [i.email];
    Object.keys(i.A).forEach(function (k) { parts.push(txt(i.A[k])); }); Object.keys(d.files).forEach(function (k) { parts.push(d.files[k]); });
    d._s = parts.join(" \n ").toLowerCase(); return d._s;
  }
  var DF = { q: "", show: "active", sort: "saved" };
  function progress(pct, label) {
    var w = el("div", "prog"), tr = el("div", "track"), fl = el("div", "fill"); fl.style.width = pct + "%"; tr.appendChild(fl); w.appendChild(tr);
    w.appendChild(el("span", "ptxt", label)); w.setAttribute("role", "img"); w.setAttribute("aria-label", label); return w;
  }
  function statusChips(d, host) {
    var st = draftStatus(d);
    if (st.submitted) host.appendChild(el("span", "chip good", "Already submitted"));
    if (st.expired) host.appendChild(el("span", "chip gray", "Expired"));
    if (!st.submitted && !st.expired) host.appendChild(el("span", "chip warm", "In progress"));
  }
  var draftRowsHost, draftCount;
  function renderDrafts() {
    var m = clear($("main"));
    m.appendChild(pageHead("Drafts", "People who started an application and have not submitted it yet."));
    if (DRAFTS === null) {
      var e = el("div", "card empty"); e.appendChild(el("b", null, "Drafts are not available yet"));
      e.appendChild(el("span", null, "The server needs the latest version of the intake function (see docs/dashboard.md).")); m.appendChild(e); return;
    }
    var act = activeDrafts(), week = act.filter(function (d) { return Date.now() - new Date(d.updated_at).getTime() < 7 * 86400000; }).length;
    var avg = act.length ? Math.round(act.reduce(function (s, d) { return s + draftInfo(d).pct; }, 0) / act.length) : 0;
    var sub = (DRAFTS || []).filter(function (d) { return draftStatus(d).submitted; }).length;
    var tiles = el("div", "tiles");
    tiles.appendChild(tile(String(act.length), "Drafts in progress", "Started and not submitted"));
    tiles.appendChild(tile(String(week), "Active in the last 7 days", "Saved at least once this week"));
    tiles.appendChild(tile(avg + "%", "Average progress", "Of the questions everybody must answer"));
    tiles.appendChild(tile(String(sub), "Already submitted", "Same email as a submitted application"));
    m.appendChild(tiles);
    var p = el("p", "notice", "A draft disappears when its owner submits the application, and expires after 60 days without changes. Files are never stored in a draft, only their names.");
    m.appendChild(p);
    var tb = el("div", "toolbar");
    var q = el("input"); q.type = "search"; q.placeholder = "Search any answer, email, organization…"; q.value = DF.q; q.setAttribute("aria-label", "Search drafts");
    q.addEventListener("input", function () { DF.q = q.value; renderDraftRows(); }); tb.appendChild(q);
    var sh = el("select"); sh.setAttribute("aria-label", "Which drafts to show");
    [["active", "In progress only"], ["all", "All, including expired and submitted"]].forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; if (o[0] === DF.show) op.selected = true; sh.appendChild(op); });
    sh.addEventListener("change", function () { DF.show = sh.value; renderDraftRows(); }); tb.appendChild(sh);
    var so = el("select"); so.setAttribute("aria-label", "Sort drafts");
    [["saved", "Recently saved"], ["complete", "Most complete"], ["old", "Oldest first"]].forEach(function (o) { var op = el("option", null, o[1]); op.value = o[0]; if (o[0] === DF.sort) op.selected = true; so.appendChild(op); });
    so.addEventListener("change", function () { DF.sort = so.value; renderDraftRows(); }); tb.appendChild(so);
    draftCount = el("span", "count"); tb.appendChild(draftCount); m.appendChild(tb);
    draftRowsHost = el("div", "list"); m.appendChild(draftRowsHost); renderDraftRows();
  }
  function renderDraftRows() {
    var q = DF.q.trim().toLowerCase();
    var list = DRAFTS.filter(function (d) { var st = draftStatus(d); if (DF.show === "active" && (st.expired || st.submitted)) return false; return !q || draftSearch(d).indexOf(q) !== -1; });
    list.sort(function (x, y) {
      if (DF.sort === "complete") return draftInfo(y).pct - draftInfo(x).pct || String(y.updated_at).localeCompare(String(x.updated_at));
      if (DF.sort === "old") return String(x.updated_at).localeCompare(String(y.updated_at));
      return String(y.updated_at).localeCompare(String(x.updated_at));
    });
    draftCount.textContent = list.length + " of " + DRAFTS.length + " shown"; clear(draftRowsHost);
    if (!list.length) {
      var e = el("div", "empty"); e.appendChild(el("b", null, DRAFTS.length ? "No draft matches" : "No drafts yet"));
      e.appendChild(el("span", null, DRAFTS.length ? "Try a different search, or show all drafts." : "Drafts appear when someone saves their progress in the form.")); draftRowsHost.appendChild(e); return;
    }
    var t = el("table", "main"), th = el("thead"), hr = el("tr");
    [["Who", ""], ["Progress", ""], ["Sections started", "num"], ["Last saved", ""], ["Started", ""], ["Status", ""]].forEach(function (h) { hr.appendChild(el("th", h[1], h[0])); });
    th.appendChild(hr); t.appendChild(th); var tbd = el("tbody");
    list.forEach(function (d) {
      var i = draftInfo(d), tr = el("tr", "row"); tr.tabIndex = 0; tr.setAttribute("role", "link");
      var c1 = el("td"), w = el("div", "who"), av = el("div", "mono-av", (i.name || i.email || "?").replace(/^[^A-Za-z0-9À-ÿ]+/, "").charAt(0) || "?");
      var bx = el("div"); bx.appendChild(el("div", "org", i.name || "(no organization name yet)"));
      if (i.email) bx.appendChild(el("div", "proj", i.email));
      w.appendChild(av); w.appendChild(bx); c1.appendChild(w); tr.appendChild(c1);
      var pc = el("td"); pc.setAttribute("data-l", "Progress"); pc.appendChild(progress(i.pct, i.done + " of " + i.total + " required")); tr.appendChild(pc);
      tr.appendChild(cell("Sections started", i.secs + " of " + SECTIONS.length, "num"));
      tr.appendChild(cell("Last saved", ago(d.updated_at) + " · " + day(d.updated_at)));
      tr.appendChild(cell("Started", day(d.created_at)));
      var st = el("td"); st.setAttribute("data-l", "Status"); statusChips(d, st); tr.appendChild(st);
      var open = function () { location.hash = "#/draft/" + encodeURIComponent(d.id); };
      tr.addEventListener("click", open); tr.addEventListener("keydown", function (ev) { if (ev.key === "Enter") open(); });
      tbd.appendChild(tr);
    });
    t.appendChild(tbd); draftRowsHost.appendChild(t);
  }
  function renderDraft(d) {
    var i = draftInfo(d), m = clear($("main"));
    var cr = el("div", "crumbs"), back = el("a", "btn small", "← Drafts"); back.href = "#/drafts"; cr.appendChild(back); m.appendChild(cr);
    var head = el("div", "card head"); head.appendChild(el("div", "mono-av", (i.name || i.email || "?").replace(/^[^A-Za-z0-9À-ÿ]+/, "").charAt(0) || "?"));
    var hb = el("div"); hb.style.minWidth = "0"; hb.style.flex = "1";
    hb.appendChild(el("p", "kicker", "Draft · not submitted")); hb.appendChild(el("h2", null, i.name || "(no organization name yet)"));
    statusChips(d, hb);
    var facts = el("div", "facts");
    facts.appendChild(fact("Contact email", i.email)); facts.appendChild(fact("Project", i.A.E1__title)); facts.appendChild(fact("Country", i.A.B2));
    facts.appendChild(fact("Amount requested", nonEmpty(i.A.G2) ? money(num(i.A.G2)) : ""));
    facts.appendChild(fact("Progress", i.done + " of " + i.total + " required answered (" + i.pct + "%)"));
    facts.appendChild(fact("Sections started", i.secs + " of " + SECTIONS.length));
    facts.appendChild(fact("Last saved", when(d.updated_at) + " (" + ago(d.updated_at) + ")")); facts.appendChild(fact("Started", when(d.created_at)));
    hb.appendChild(facts); head.appendChild(hb); m.appendChild(head);
    m.appendChild(el("p", "notice", "This is an unfinished draft: answers can still change and files are not stored in a draft. The applicant continues it with their own code."));
    var lay = el("div", "layout"), rail = el("nav", "rail"), body = el("div");
    rail.setAttribute("aria-label", "Sections"); rail.appendChild(el("p", "rt", "Sections")); lay.appendChild(rail); lay.appendChild(body); m.appendChild(lay);
    buildSections({ answers: i.A, files: [], draftFiles: d.files, profile: null }, body, rail, true);
  }

  /* ---------- overview (charts) ---------- */
  // One series = one color (the validated blue). Bars are thin with a rounded data end, values sit at the tip,
  // hover and keyboard focus show the same tooltip, and every chart has a table view.
  function chartCard(title, subtitle, build, tCols, tRows, wide) {
    var c = el("section", "card chart" + (wide ? " wide" : "")), h = el("header"), l = el("div");
    l.appendChild(el("h3", null, title)); if (subtitle) l.appendChild(el("p", null, subtitle)); h.appendChild(l);
    var tg = el("button", "tblink", "View as table"); tg.type = "button"; tg.setAttribute("aria-pressed", "false"); h.appendChild(tg);
    var host = el("div"); c.appendChild(h); c.appendChild(host);
    function draw() {
      clear(host);
      if (tg.getAttribute("aria-pressed") === "true") host.appendChild(subTable(tCols, tRows)); else build(host);
    }
    tg.addEventListener("click", function () {
      var on = tg.getAttribute("aria-pressed") !== "true"; tg.setAttribute("aria-pressed", String(on));
      tg.textContent = on ? "View as chart" : "View as table"; draw();
    });
    draw(); return c;
  }
  function tally(fn) {
    var m = {}, order = [];
    APPS.forEach(function (a) { var k = fn(a); if (!k) return; if (!m[k]) { m[k] = { label: k, n: 0, amt: 0 }; order.push(k); } m[k].n++; m[k].amt += num(ans(a, "G2")) || 0; });
    return order.map(function (k) { return m[k]; }).sort(function (x, y) { return y.n - x.n || x.label.localeCompare(y.label); });
  }
  function barList(items, valueOf, fmt, tipOf, onClick) {
    return function (host) {
      var mx = Math.max.apply(null, items.map(valueOf).concat([1])), bars = el("div", "bars");
      items.forEach(function (it) {
        var r = el("div", "brow"); r.tabIndex = 0;
        r.appendChild(el("div", "bl", it.label));
        var t = el("div", "bt"), b = el("div", "bar"); b.style.width = "calc(" + (valueOf(it) / mx * 100) + "% - 64px)";
        t.appendChild(b); t.appendChild(el("span", "bv", fmt(valueOf(it)))); r.appendChild(t);
        var tp = tipOf(it); tip(r, tp[0], tp[1]);
        if (onClick && it.click !== false) { r.setAttribute("role", "link"); r.addEventListener("click", function () { onClick(it); });
          r.addEventListener("keydown", function (e) { if (e.key === "Enter") onClick(it); }); }
        bars.appendChild(r);
      });
      host.appendChild(bars);
    };
  }
  function countChart(title, subtitle, items, onClick) {
    return chartCard(title, subtitle, barList(items, function (i) { return i.n; }, String, function (i) { return [plural(i.n, "application"), i.label + " · " + money(i.amt) + " requested"]; }, onClick),
      [["Value", "label"], ["Applications", "n"], ["Requested", "amtf"]], items.map(function (i) { return { label: i.label, n: i.n, amtf: money(i.amt) }; }));
  }
  function perDay() {
    var days = {}, stamps = APPS.map(function (a) { return new Date(a.finalized_at).getTime(); }).filter(function (t) { return !isNaN(t); });
    if (!stamps.length) return [];
    function key(t) { var d = new Date(t); return d.getFullYear() + "-" + ("0" + (d.getMonth() + 1)).slice(-2) + "-" + ("0" + d.getDate()).slice(-2); }
    stamps.forEach(function (t) { days[key(t)] = (days[key(t)] || 0) + 1; });
    var end = new Date(Math.max.apply(null, stamps)); end.setHours(12, 0, 0, 0);
    var start = new Date(Math.min.apply(null, stamps)); start.setHours(12, 0, 0, 0);
    if (end - start > 29 * 86400000) start = new Date(end.getTime() - 29 * 86400000);
    var out = []; for (var t = start.getTime(); t <= end.getTime() + 1; t += 86400000) { var k = key(t); out.push({ k: k, d: new Date(t), n: days[k] || 0 }); }
    return out;
  }
  function dayChart() {
    var data = perDay(), mx = Math.max.apply(null, data.map(function (d) { return d.n; }).concat([1]));
    var fmt = function (d) { return d.toLocaleDateString("en-US", { month: "short", day: "numeric" }); };
    return chartCard("Applications per day", data.length ? "Last " + plural(data.length, "day") + " with activity" : "", function (host) {
      var cols = el("div", "cols"), top = data.reduce(function (b, d) { return d.n > b.n ? d : b; }, data[0]);
      data.forEach(function (d) {
        var c = el("div", "col"); c.tabIndex = 0; var b = el("b"); b.style.height = (d.n / mx * 100) + "%"; if (!d.n) b.style.height = "0"; c.appendChild(b);
        if (d === top && d.n) c.appendChild(el("span", "cv", String(d.n)));
        tip(c, plural(d.n, "application"), fmt(d.d)); cols.appendChild(c);
      });
      host.appendChild(cols);
      var x = el("div", "xlab"); x.appendChild(el("span", null, fmt(data[0].d))); x.appendChild(el("span", null, fmt(data[data.length - 1].d))); host.appendChild(x);
    }, [["Day", "day"], ["Applications", "n"]], data.map(function (d) { return { day: fmt(d.d), n: d.n }; }), true);
  }
  function splitBar(label, parts) {      // one whole, split into parts; thin bar + legend with counts (the legend carries identity, not color alone)
    var wrap = el("div"), total = parts.reduce(function (s, p) { return s + p.n; }, 0) || 1, cols = ["#FF6A2F", "#2F6FB3"];
    wrap.appendChild(el("div", "bl", label));
    var seg = el("div", "seg"); seg.setAttribute("role", "img"); seg.setAttribute("aria-label", label + ": " + parts.map(function (p) { return p.label + " " + p.n; }).join(", "));
    parts.forEach(function (p, i) { if (!p.n) return; var s = el("i"); s.style.background = cols[i]; s.style.flex = p.n + " 1 0"; tip(s, plural(p.n, "application"), p.label + " · " + Math.round(p.n / total * 100) + "%"); seg.appendChild(s); });
    wrap.appendChild(seg);
    var lg = el("div", "legend");
    parts.forEach(function (p, i) { var s = el("span"); var sw = el("em"); sw.style.background = cols[i]; s.appendChild(sw); s.appendChild(document.createTextNode(p.label + " · " + p.n + " (" + Math.round(p.n / total * 100) + "%)")); lg.appendChild(s); });
    wrap.appendChild(lg); return wrap;
  }
  function renderOverview() {
    var m = clear($("main"));
    m.appendChild(pageHead("Overview", "How the applications received so far break down. Click a country or type to see its applications."));
    if (!APPS.length) { var e = el("div", "card empty"); e.appendChild(el("b", null, "Nothing to chart yet")); e.appendChild(el("span", null, "Charts appear when the first application arrives.")); m.appendChild(e); return; }
    var g = el("div", "grid2");
    g.appendChild(dayChart());
    g.appendChild(chartCard("Stage and route", "Initial vs Established, and New vs Renewal", function (host) {
      host.appendChild(splitBar("Stage", [{ label: "Initial", n: countBy(function (a) { return a.profile; }, "Initial") }, { label: "Established", n: countBy(function (a) { return a.profile; }, "Established") }]));
      host.appendChild(splitBar("Route", [{ label: "New", n: countBy(function (a) { return a.route; }, "New") }, { label: "Renewal", n: countBy(function (a) { return a.route; }, "Renewal") }]));
    }, [["Group", "g"], ["Value", "v"], ["Applications", "n"]], [
      { g: "Stage", v: "Initial", n: countBy(function (a) { return a.profile; }, "Initial") }, { g: "Stage", v: "Established", n: countBy(function (a) { return a.profile; }, "Established") },
      { g: "Route", v: "New", n: countBy(function (a) { return a.route; }, "New") }, { g: "Route", v: "Renewal", n: countBy(function (a) { return a.route; }, "Renewal") }]));

    var byC = tally(function (a) { return ans(a, "B2"); });
    if (byC.length > 8) { var rest = byC.slice(8); byC = byC.slice(0, 8); byC.push({ label: "Other (" + rest.length + " countries)", n: rest.reduce(function (s, x) { return s + x.n; }, 0), amt: rest.reduce(function (s, x) { return s + x.amt; }, 0), click: false }); }
    g.appendChild(chartCard("Amount requested by country", "Sum of the amount requested (G2)", barList(byC, function (i) { return i.amt; }, compact,
      function (i) { return [money(i.amt), i.label + " · " + plural(i.n, "application")]; },
      function (i) { FILTER = { q: "", profile: "", route: "", country: i.label, type: "", sort: FILTER.sort }; location.hash = "#/"; }),
      [["Country", "label"], ["Requested", "amtf"], ["Applications", "n"]], byC.map(function (i) { return { label: i.label, amtf: money(i.amt), n: i.n }; })));

    var bands = [["Under $10K", 0, 10000], ["$10K – $25K", 10000, 25000], ["$25K – $50K", 25000, 50000], ["$50K and over", 50000, Infinity]].map(function (b) {
      var n = 0, amt = 0; APPS.forEach(function (a) { var v = num(ans(a, "G2")); if (v != null && v >= b[1] && v < b[2]) { n++; amt += v; } }); return { label: b[0], n: n, amt: amt, click: false };
    });
    g.appendChild(countChart("Size of the request", "Applications by amount requested", bands));
    g.appendChild(countChart("Applicant type", "Organization or individual", tally(function (a) { return shortType(ans(a, "A1")); }),
      function (i) { FILTER = { q: "", profile: "", route: "", country: "", type: i.label, sort: FILTER.sort }; location.hash = "#/"; }));
    g.appendChild(countChart("Main measure of success (F1)", "What the project will count", tally(function (a) { return head1(ans(a, "F1")); })));
    g.appendChild(countChart("Target stage (E12)", "Where the project aims to take Bitcoin use", tally(function (a) { return head1(ans(a, "E12")); })));
    g.appendChild(countChart("Payment method preferred (G8)", "How they want to receive the grant", tally(function (a) { return head1(ans(a, "G8")); })));
    m.appendChild(g);
  }

  /* ---------- help ---------- */
  function helpCard(title, items) {
    var c = el("div", "card"); c.appendChild(el("h3", null, title));
    if (typeof items === "string") c.appendChild(el("p", null, items));
    else { var ul = el("ul"); items.forEach(function (t) { ul.appendChild(el("li", null, t)); }); c.appendChild(ul); }
    return c;
  }
  function renderHelp() {
    var m = clear($("main")); m.appendChild(pageHead("Help", "A short guide to reading the applications."));
    var h = el("div", "help");
    h.appendChild(helpCard("Reading an application", ["Open Applications and click a row. Every question the applicant answered is shown, grouped by section (0 and A to K).", "Use the section list on the left to jump around. Previous and Next move through the applications in the order of your list.", "Attached documents open in a new tab with a link that expires after 5 minutes. Open the file again to get a fresh link."]));
    h.appendChild(helpCard("Finding things", ["The search box looks inside every answer, not only the organization name: try a country, a person, an email or a word from the project.", "Combine it with the stage, route, country and type filters. Remove a filter by clicking its tag.", "In Overview, click a country or an applicant type to see just those applications."]));
    h.appendChild(helpCard("What the labels mean", ["NEW: you have not opened that application yet on this browser.", "Initial / Established: the stage the form assigns from the answers to A1 and A2.", "New / Renewal: whether the applicant received a grant in 2026 (question A3)."]));
    h.appendChild(helpCard("Export and print", ["Account menu (your initial, top right) → Export CSV downloads one row per application and one column per question. It respects the filters you have set.", "In an application, Print / PDF gives a clean copy to share with the committee."]));
    h.appendChild(helpCard("What is not here", "This dashboard shows what the applicants answered. Eva's pre-review of each application is in the intake Google Sheet, not here. The committee decides."));
    h.appendChild(helpCard("Access and privacy", ["Your code is personal. Do not share it: applications include identity documents and tax forms.", "The code is kept only while this tab is open. Sign out from the account menu when you finish on a shared computer.", "If you lose access or need a code, ask the person who manages the foundation's applications."]));
    m.appendChild(h);
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
    var lines = [cols.map(function (c) { return csvCell(c[0]); }).join(",")], rows = filtered();
    rows.forEach(function (a) { lines.push(cols.map(function (c) { return csvCell(c[1](a)); }).join(",")); });
    var blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    var link = el("a"); link.href = URL.createObjectURL(blob); link.download = "applications-" + new Date().toISOString().slice(0, 10) + ".csv";
    document.body.appendChild(link); link.click(); link.remove(); toast("Exported " + plural(rows.length, "application"));
  }

  /* ---------- wiring ---------- */
  function closeMenu() { $("menu").hidden = true; $("usermenu").setAttribute("aria-expanded", "false"); }
  $("usermenu").addEventListener("click", function (e) { e.stopPropagation(); var open = $("menu").hidden; $("menu").hidden = !open; $("usermenu").setAttribute("aria-expanded", String(open)); });
  document.addEventListener("click", closeMenu);
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") closeMenu(); });
  $("export").addEventListener("click", function () { closeMenu(); exportCsv(); });
  $("signout").addEventListener("click", function () { closeMenu(); APPS = []; LOADED = false; location.hash = ""; showLogin(""); });
  $("loginform").addEventListener("submit", function (e) {
    e.preventDefault();
    try { sessionStorage.setItem(SS_KEY, $("code").value.trim()); } catch (x) {}
    $("loginerr").textContent = "Checking…";
    load(false).then(function () { $("code").value = ""; $("loginerr").textContent = ""; }).catch(function () {});
  });
  $("refresh").addEventListener("click", function () {
    var b = $("refresh"); b.disabled = true; b.classList.add("spin");
    load(true).then(function () { toast("Up to date"); }).catch(function () {}).then(function () { b.disabled = false; b.classList.remove("spin"); });
  });
  window.addEventListener("hashchange", function () { if (/^#s-/.test(location.hash)) return; route(); });
  window.setInterval(function () {                                  // new applications show up without pressing anything
    if (document.visibilityState === "visible" && !$("app").hidden && !/^#\/APP-/.test(location.hash)) load(true).catch(function () {});
  }, 90000);

  var saved = ""; try { saved = sessionStorage.getItem(SS_KEY) || ""; } catch (e) {}
  if (!CFG.endpoint) { showLogin("The dashboard is not connected (no endpoint in config.js)."); }
  else if (saved) { $("app").hidden = false; renderList(); load(true).catch(function () { showLogin(""); }); }
  else showLogin("");
})();
