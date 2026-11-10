/* Grant Application 2027 — form engine.
   Renders GA27.SECTIONS / GA27.FIELDS, applies conditional logic, validates and submits.
   Nothing on this page mentions screening or scoring: the form only collects answers. */
(function () {
  "use strict";

  var G = window.GA27, CFG = window.GA27_CONFIG || {};
  var SECTIONS = G.SECTIONS, F = G.FIELDS, COUNTRIES = G.COUNTRIES;
  var MAX_BYTES = (CFG.maxFileMB || 10) * 1024 * 1024;
  var EXT = /\.(pdf|jpe?g|png)$/i;

  var V = {};              // answers by question id (+ "__" sub-values)
  var FILES = {};          // File objects by question id
  var ST = { profile: "—" };
  var form = document.getElementById("form");

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  function words(s) { return s && s.trim() ? s.trim().split(/\s+/).length : 0; }
  function num(x) {
    var n = parseFloat(String(x == null ? "" : x).replace(/[$,\s]/g, ""));
    return isNaN(n) ? null : n;
  }
  function money(n) { return "$" + n.toLocaleString("en-US", { maximumFractionDigits: 2 }); }
  function isOrg() { return (V.A1 || "").indexOf("Organization") === 0; }

  /* ---------- rendering ---------- */
  SECTIONS.forEach(function (sec) {
    var box = el("fieldset", "sec");
    box.id = "sec-" + sec.id;
    var head = el("header");
    head.appendChild(el("div", "secid", "Section " + sec.id));
    head.appendChild(el("h3", null, sec.title));
    if (sec.note) head.appendChild(el("p", "secnote", sec.note));
    box.appendChild(head);
    F.filter(function (f) { return f.s === sec.id; }).forEach(function (f) {
      box.appendChild(buildField(f));
    });
    form.appendChild(box);
  });

  // Honeypot: real people never see or fill this; bots often do.
  var hp = el("div", "hp");
  hp.setAttribute("aria-hidden", "true");
  var hpi = el("input"); hpi.type = "text"; hpi.name = "company_website"; hpi.tabIndex = -1;
  hpi.autocomplete = "off";
  hp.appendChild(hpi);
  form.appendChild(hp);

  var bar = el("div", "submitbar");
  var captcha = el("div"); captcha.id = "captcha";
  var sub = el("button", "submit", "Submit application");
  sub.type = "button";
  var status = el("div", "status"); status.id = "status";
  status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
  bar.appendChild(captcha); bar.appendChild(sub); bar.appendChild(status);
  form.appendChild(bar);

  function buildField(f) {
    var wrap = el("div", "f");
    wrap.id = "f-" + f.id;
    wrap.dataset.fid = f.id;
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-labelledby", "l-" + f.id);

    var lab = el("label", "q");
    lab.id = "l-" + f.id;
    lab.appendChild(el("span", "qid", f.id));
    lab.appendChild(el("span", null, f.label));
    if (f.req) lab.appendChild(el("span", "req-star", "*"));
    wrap.appendChild(lab);

    var help = el("p", "help");
    help.id = "h-" + f.id;
    if (f.help) help.textContent = f.help;
    if (f.links) {
      f.links.forEach(function (l) {
        var a = el("a", null, l.t);
        a.href = l.href; a.target = "_blank"; a.rel = "noopener";
        help.appendChild(document.createTextNode(" "));
        help.appendChild(a);
      });
    }
    wrap.appendChild(help);

    var body = el("div", "body");
    wrap.appendChild(body);
    var first = null;                       // control that the label points to
    function reg(node) { if (!first) first = node; return node; }

    switch (f.type) {
      case "checks": {
        var g = el("div", "opts");
        f.options.forEach(function (o) {
          var l = el("label", "opt" + (f.boxed ? " boxed" : ""));
          var cb = el("input"); cb.type = "checkbox"; cb.value = o;
          cb.addEventListener("change", function () {
            V[f.id] = Array.prototype.slice.call(g.querySelectorAll("input:checked"))
              .map(function (x) { return x.value; });
            refresh();
          });
          l.appendChild(cb); l.appendChild(el("span", null, o));
          g.appendChild(l);
        });
        body.appendChild(g);
        break;
      }
      case "radio": {
        var rg = el("div", "opts");
        f.options.forEach(function (o) {
          var l = el("label", "opt" + (f.boxed ? " boxed" : ""));
          var rb = el("input"); rb.type = "radio"; rb.name = f.id; rb.value = o;
          rb.addEventListener("change", function () { V[f.id] = o; refresh(); });
          l.appendChild(rb); l.appendChild(el("span", null, o));
          rg.appendChild(l);
        });
        body.appendChild(rg);
        break;
      }
      case "text": case "email": case "url": {
        var inp = reg(el("input"));
        inp.type = f.type;
        inp.addEventListener("input", function () { V[f.id] = inp.value; refresh(); });
        body.appendChild(inp);
        break;
      }
      case "valuedate": {
        var vr = el("div", "row2");
        var vv = el("input"); vv.type = "text";
        vv.placeholder = "Figure, e.g. 60 merchants or 80%";
        vv.setAttribute("aria-label", f.label + " — figure");
        var vd = el("input"); vd.type = "date";
        vd.setAttribute("aria-label", f.label + " — date");
        var updVD = function () {
          V[f.id] = vv.value && vd.value ? vv.value + " @ " + vd.value : "";
          V[f.id + "__value"] = vv.value; V[f.id + "__date"] = vd.value;
          refresh();
        };
        vv.addEventListener("input", updVD); vd.addEventListener("change", updVD);
        vr.appendChild(vv); vr.appendChild(vd); body.appendChild(vr);
        break;
      }
      case "baseline": {
        var br = el("div", "row2");
        var bv = el("input"); bv.type = "text";
        bv.placeholder = "Figure today, e.g. 40 merchants";
        bv.setAttribute("aria-label", f.label + " — figure today");
        var bd = el("input"); bd.type = "date";
        bd.setAttribute("aria-label", f.label + " — date measured");
        br.appendChild(bv); br.appendChild(bd);
        var tl = el("label", "opt");
        var tc = el("input"); tc.type = "checkbox";
        tl.appendChild(tc);
        tl.appendChild(el("span", null, "I do not have this figure yet — I will collect it"));
        var pw = el("div"); pw.hidden = true;
        var pt = el("textarea"); pt.rows = 2;
        pt.placeholder = "How and when will you collect it?";
        pt.setAttribute("aria-label", "Collection plan");
        pw.appendChild(pt);
        var updBL = function () {
          if (tc.checked) {
            V[f.id] = pt.value ? "Plan: " + pt.value : "";
            V[f.id + "__mode"] = "plan"; V[f.id + "__plan"] = pt.value;
          } else {
            V[f.id] = bv.value && bd.value ? bv.value + " @ " + bd.value : "";
            V[f.id + "__mode"] = "value";
            V[f.id + "__value"] = bv.value; V[f.id + "__date"] = bd.value;
          }
          refresh();
        };
        tc.addEventListener("change", function () {
          pw.hidden = !tc.checked; br.hidden = tc.checked; updBL();
        });
        bv.addEventListener("input", updBL); bd.addEventListener("change", updBL);
        pt.addEventListener("input", updBL);
        body.appendChild(br); body.appendChild(tl); body.appendChild(pw);
        break;
      }
      case "number": {
        var wn = el("div", "bline");
        wn.style.gridTemplateColumns = f.prefix ? "auto 1fr" : "1fr";
        if (f.prefix) wn.appendChild(el("span", "computed", f.prefix));
        var ni = reg(el("input"));
        ni.type = "number"; ni.min = f.min != null ? f.min : 0; ni.step = "1";
        ni.inputMode = "decimal"; ni.id = "i-" + f.id;
        ni.addEventListener("input", function () {
          if (f.id === "G2") V.__g2touched = true;
          V[f.id] = ni.value; refresh();
        });
        wn.appendChild(ni); body.appendChild(wn);
        break;
      }
      case "textarea": {
        var ta = reg(el("textarea"));
        if (f.rows) ta.rows = f.rows;
        var wc = el("div", "wc", "0 / " + f.maxWords + " words");
        ta.addEventListener("input", function () {
          V[f.id] = ta.value;
          var n = words(ta.value);
          wc.textContent = n + " / " + f.maxWords + " words";
          wc.className = "wc" + (n > f.maxWords ? " over" : "");
          refresh();
        });
        body.appendChild(ta); body.appendChild(wc);
        break;
      }
      case "titlesummary": {
        var ti = reg(el("input")); ti.type = "text"; ti.placeholder = "Project title";
        ti.setAttribute("aria-label", "Project title");
        var sm = el("textarea"); sm.rows = 3; sm.placeholder = "Summary in 2–3 sentences";
        sm.setAttribute("aria-label", "Summary");
        var wc2 = el("div", "wc", "0 / " + f.maxWords + " words");
        var upd = function () {
          V[f.id] = (ti.value ? ti.value + " — " : "") + sm.value;
          V[f.id + "__title"] = ti.value; V[f.id + "__summary"] = sm.value;
          var n = words(sm.value);
          wc2.textContent = n + " / " + f.maxWords + " words";
          wc2.className = "wc" + (n > f.maxWords ? " over" : "");
          refresh();
        };
        ti.addEventListener("input", upd); sm.addEventListener("input", upd);
        body.appendChild(ti); body.appendChild(sm); body.appendChild(wc2);
        break;
      }
      case "datepair": {
        var r = el("div", "row2");
        var d1 = el("input"); d1.type = "date"; d1.setAttribute("aria-label", "Start date");
        var d2 = el("input"); d2.type = "date"; d2.setAttribute("aria-label", "End date");
        var dn = el("div", "computed", "Duration will be calculated from these dates.");
        var updD = function () {
          V[f.id] = d1.value && d2.value ? d1.value + " to " + d2.value : "";
          V[f.id + "__start"] = d1.value; V[f.id + "__end"] = d2.value;
          if (d1.value && d2.value) {
            var a = new Date(d1.value), b = new Date(d2.value);
            var m = (b.getFullYear() - a.getFullYear()) * 12 + (b.getMonth() - a.getMonth());
            if (b.getDate() < a.getDate()) m -= 1;
            V[f.id + "__months"] = m;
            if (m > 0) dn.textContent = "Duration: " + m + " months";
            else { dn.textContent = "The end date must be after the start date."; V[f.id] = ""; }
          } else dn.textContent = "Duration will be calculated from these dates.";
          refresh();
        };
        d1.addEventListener("change", updD); d2.addEventListener("change", updD);
        r.appendChild(d1); r.appendChild(d2);
        body.appendChild(r); body.appendChild(dn);
        break;
      }
      case "country": {
        var cs = el("div", "cs");
        var ci = reg(el("input")); ci.type = "text"; ci.autocomplete = "off";
        ci.placeholder = "Start typing a country…";
        ci.setAttribute("role", "combobox"); ci.setAttribute("aria-expanded", "false");
        var list = el("div", "cs-list");
        var render = function (filter) {
          list.textContent = "";
          var ff = (filter || "").toLowerCase();
          var hits = COUNTRIES.filter(function (c) { return c.toLowerCase().indexOf(ff) !== -1; }).slice(0, 60);
          hits.forEach(function (c) {
            var it = el("div", "cs-item", c);
            it.addEventListener("mousedown", function (e) {
              e.preventDefault();
              ci.value = c; V[f.id] = c; list.classList.remove("show");
              ci.setAttribute("aria-expanded", "false"); refresh();
            });
            list.appendChild(it);
          });
          list.classList.toggle("show", hits.length > 0);
          ci.setAttribute("aria-expanded", hits.length > 0 ? "true" : "false");
        };
        ci.addEventListener("input", function () { V[f.id] = ""; render(ci.value); refresh(); });
        ci.addEventListener("focus", function () { render(ci.value); });
        ci.addEventListener("blur", function () {
          window.setTimeout(function () { list.classList.remove("show"); }, 120);
        });
        cs.appendChild(ci); cs.appendChild(list); body.appendChild(cs);
        break;
      }
      case "file": {
        var fi = reg(el("input")); fi.type = "file"; fi.accept = ".pdf,.jpg,.jpeg,.png";
        var fe = el("p", "errmsg"); fe.hidden = true;
        fi.addEventListener("change", function () {
          var file = fi.files && fi.files[0];
          fe.hidden = true; delete FILES[f.id];
          if (file) {
            if (!EXT.test(file.name)) { fe.textContent = "Use a PDF, JPG or PNG file."; fe.hidden = false; fi.value = ""; file = null; }
            else if (file.size > MAX_BYTES) { fe.textContent = "That file is larger than " + (CFG.maxFileMB || 10) + " MB."; fe.hidden = false; fi.value = ""; file = null; }
          }
          if (file) FILES[f.id] = file;
          V[f.id] = file ? file.name : "";
          refresh();
        });
        body.appendChild(fi); body.appendChild(fe);
        break;
      }
      case "composite": {
        var cr = el("div", f.parts.length > 3 ? "row2" : "row3");
        var vals = {};
        f.parts.forEach(function (p) {
          var pi = el("input"); pi.type = p.t; pi.placeholder = p.ph;
          pi.setAttribute("aria-label", f.label + " — " + p.ph);
          if (p.k === "email") pi.autocomplete = "email";
          if (p.k === "name") pi.autocomplete = "name";
          if (p.k === "phone") pi.autocomplete = "tel";
          pi.addEventListener("input", function () {
            vals[p.k] = pi.value;
            V[f.id] = [vals.name, vals.title, vals.email, vals.phone].filter(Boolean).join(", ");
            Object.keys(vals).forEach(function (k) { V[f.id + "__" + k] = vals[k]; });
            refresh();
          });
          if (!first) reg(pi);
          cr.appendChild(pi);
        });
        body.appendChild(cr);
        break;
      }
      case "milestones": {
        var wrapT = el("div", "tblwrap");
        var tb = el("table", "grid");
        var th = el("thead"), hr = el("tr");
        ["Milestone", "Target date", "Evidence"].forEach(function (h) { hr.appendChild(el("th", null, h)); });
        th.appendChild(hr); tb.appendChild(th);
        var tbody = el("tbody");
        var rows = [{}, {}, {}];
        rows.forEach(function (rowv, i) {
          var tr = el("tr");
          [["m", "text"], ["d", "date"], ["e", "text"]].forEach(function (c) {
            var td = el("td");
            var ii = el("input"); ii.type = c[1];
            ii.setAttribute("aria-label", "Milestone " + (i + 1) + " " + c[0]);
            ii.addEventListener("input", function () {
              rowv[c[0]] = ii.value;
              V[f.id] = rows.map(function (rr) { return [rr.m, rr.d, rr.e].filter(Boolean).join(" | "); })
                .filter(Boolean).join("; ");
              V[f.id + "__rows"] = rows.map(function (rr) { return { milestone: rr.m || "", date: rr.d || "", evidence: rr.e || "" }; });
              refresh();
            });
            td.appendChild(ii); tr.appendChild(td);
          });
          tbody.appendChild(tr);
        });
        tb.appendChild(tbody); wrapT.appendChild(tb); body.appendChild(wrapT);
        break;
      }
      case "funders": {
        var rg2 = el("div", "opts");
        var tblWrap = el("div", "tblwrap"); tblWrap.hidden = true;
        var frows = [{}, {}];
        var syncFunders = function () {
          var yn = V[f.id + "__yn"] || "";
          if (yn === "No") V[f.id] = "No";
          else {
            var parts = frows.filter(function (r) { return r.n; }).map(function (r) {
              return r.n + ", " + (r.a || "?") + ", " + (r.s || "status unclear");
            });
            V[f.id] = parts.length ? "Yes. " + parts.join("; ") : (yn === "Yes" ? "Yes" : "");
          }
          V[f.id + "__rows"] = frows.map(function (r) { return { funder: r.n || "", amount: r.a || "", status: r.s || "" }; });
          refresh();
        };
        ["No", "Yes"].forEach(function (o) {
          var l = el("label", "opt");
          var rb = el("input"); rb.type = "radio"; rb.name = f.id; rb.value = o;
          rb.addEventListener("change", function () {
            V[f.id + "__yn"] = o; tblWrap.hidden = o !== "Yes"; syncFunders();
          });
          l.appendChild(rb); l.appendChild(el("span", null, o)); rg2.appendChild(l);
        });
        var ft = el("table", "grid");
        var fth = el("thead"), fhr = el("tr");
        ["Funder", "Amount (USD)", "Status"].forEach(function (h) { fhr.appendChild(el("th", null, h)); });
        fth.appendChild(fhr); ft.appendChild(fth);
        var ftb = el("tbody");
        frows.forEach(function (rv, i) {
          var tr = el("tr");
          var inn = el("input"); inn.type = "text";
          inn.setAttribute("aria-label", "Funder " + (i + 1) + " name");
          inn.addEventListener("input", function () { rv.n = inn.value; syncFunders(); });
          var ina = el("input"); ina.type = "number"; ina.min = "0";
          ina.setAttribute("aria-label", "Funder " + (i + 1) + " amount");
          ina.addEventListener("input", function () { rv.a = ina.value; syncFunders(); });
          var sel = el("select");
          sel.setAttribute("aria-label", "Funder " + (i + 1) + " status");
          ["", "confirmed", "pending"].forEach(function (s) {
            var op = el("option", null, s || "—"); op.value = s; sel.appendChild(op);
          });
          sel.addEventListener("change", function () { rv.s = sel.value; syncFunders(); });
          [inn, ina, sel].forEach(function (c) { var td = el("td"); td.appendChild(c); tr.appendChild(td); });
          ftb.appendChild(tr);
        });
        ft.appendChild(ftb); tblWrap.appendChild(ft);
        body.appendChild(rg2); body.appendChild(tblWrap);
        break;
      }
      case "budget": {
        var bw = el("div", "opts");
        var cvals = {};
        f.cats.forEach(function (c) {
          var line = el("div", "bline");
          line.appendChild(el("span", null, c));
          var bi = el("input"); bi.type = "number"; bi.min = "0"; bi.inputMode = "decimal";
          bi.setAttribute("aria-label", c + " (USD)");
          bi.addEventListener("input", function () {
            cvals[c] = bi.value;
            V[f.id] = f.cats.map(function (k) { return cvals[k] ? k + " " + cvals[k] : null; })
              .filter(Boolean).join(", ");
            V[f.id + "__cats"] = f.cats.reduce(function (o, k) { o[k] = cvals[k] || ""; return o; }, {});
            refresh();
          });
          line.appendChild(bi); bw.appendChild(line);
        });
        var bs = el("div", "bsum", "Sum: $0 — must equal G2");
        bs.id = "bsum-" + f.id;
        bw.appendChild(bs); body.appendChild(bw);
        break;
      }
      case "safeguard": {
        var sgf = el("input"); sgf.type = "file"; sgf.accept = ".pdf,.jpg,.jpeg,.png";
        sgf.setAttribute("aria-label", "Policy file");
        var sgl = el("label", "opt");
        var sgc = el("input"); sgc.type = "checkbox";
        sgl.appendChild(sgc);
        sgl.appendChild(el("span", null, "A policy will be in place before funding"));
        var sgn = el("input"); sgn.type = "text";
        sgn.placeholder = "Name of the person responsible";
        sgn.setAttribute("aria-label", "Person responsible");
        var sge = el("p", "errmsg"); sge.hidden = true;
        var updSG = function () {
          var file = sgf.files && sgf.files[0];
          sge.hidden = true; delete FILES[f.id];
          if (file && (!EXT.test(file.name) || file.size > MAX_BYTES)) {
            sge.textContent = "Use a PDF, JPG or PNG file under " + (CFG.maxFileMB || 10) + " MB.";
            sge.hidden = false; sgf.value = ""; file = null;
          }
          if (file) FILES[f.id] = file;
          var bits = [];
          if (file) bits.push(file.name);
          if (sgc.checked) bits.push("policy committed before funding");
          if (sgn.value) bits.push(sgn.value);
          V[f.id] = bits.join("; ");
          V[f.id + "__committed"] = sgc.checked; V[f.id + "__person"] = sgn.value;
          refresh();
        };
        sgf.addEventListener("change", updSG); sgc.addEventListener("change", updSG);
        sgn.addEventListener("input", updSG);
        body.appendChild(sgf); body.appendChild(sge); body.appendChild(sgl); body.appendChild(sgn);
        break;
      }
      case "submitter": {
        var sr = el("div", "row2");
        var sn = reg(el("input")); sn.type = "text"; sn.placeholder = "Full name";
        sn.autocomplete = "name";
        sn.setAttribute("aria-label", "Name of the person submitting");
        var sd = el("input"); sd.type = "date"; sd.valueAsDate = new Date(); sd.readOnly = true;
        sd.setAttribute("aria-label", "Date");
        sn.addEventListener("input", function () {
          V[f.id] = sn.value ? sn.value + ", " + sd.value : "";
          V[f.id + "__name"] = sn.value; V[f.id + "__date"] = sd.value;
          refresh();
        });
        sr.appendChild(sn); sr.appendChild(sd); body.appendChild(sr);
        break;
      }
    }
    if (first) { first.id = first.id || "c-" + f.id; lab.htmlFor = first.id; }
    return wrap;
  }

  /* ---------- logic ---------- */
  function visible(f) {
    if (!f.showIf) return true;
    try { return !!f.showIf(V, ST); } catch (e) { return true; }
  }

  function missingIds() {
    var out = [];
    F.forEach(function (f) {
      if (!f.req || !visible(f)) return;
      var v = V[f.id];
      if (f.req === "all") { if (!v || v.length < f.options.length) out.push(f.id); }
      else if (typeof f.req === "number") { if (!v || v.length < f.req) out.push(f.id); }
      else if (!v || (typeof v === "string" && !v.trim())) out.push(f.id);
    });
    return out;
  }

  // Extra rules a person can fix: returns { id: message }.
  function problems() {
    var p = {};
    F.forEach(function (f) {
      if (!visible(f)) return;
      if (f.maxWords && words(V[f.id + "__summary"] != null ? V[f.id + "__summary"] : (V[f.id] || "")) > f.maxWords)
        p[f.id] = "Please keep this answer to " + f.maxWords + " words or fewer.";
    });
    var g1 = num(V.G1), g2 = num(V.G2);
    if (g1 != null && g2 != null && g2 > g1) p.G2 = "The amount requested cannot be larger than the total project budget (G1).";
    if (V.G4 !== undefined && visible(F.filter(function (x) { return x.id === "G4"; })[0]) && g2 != null) {
      var cats = V.G4__cats || {}, sum = 0;
      Object.keys(cats).forEach(function (k) { sum += num(cats[k]) || 0; });
      if (V.G4 && Math.abs(sum - g2) >= 1) p.G4 = "The categories add up to " + money(sum) + ", but the amount requested is " + money(g2) + ".";
    }
    var em = V.D1__email;
    if (em && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(em)) p.D1 = "Enter a valid email address.";
    return p;
  }

  function refresh() {
    var a1 = V.A1 || "", a2 = V.A2 || "";
    if (!a1 && !a2) ST.profile = "—";
    else if (a1.indexOf("Individual") === 0 || a2 === "Less than 1 year") ST.profile = "Initial";
    else ST.profile = "Established";

    // G2 starts from A4 until the applicant edits it.
    var g2in = document.getElementById("i-G2");
    if (g2in && V.A4 && !V.__g2touched) { g2in.value = V.A4; V.G2 = V.A4; }

    F.forEach(function (f) {
      var node = document.getElementById("f-" + f.id);
      if (!node) return;
      node.classList.toggle("hidden", !visible(f));
      if (f.helpFn) {
        var h = document.getElementById("h-" + f.id);
        if (h) h.textContent = f.helpFn(V, ST);
      }
    });

    var bs = document.getElementById("bsum-G4");
    if (bs) {
      var cats = V.G4__cats || {}, sum = 0, any = false;
      Object.keys(cats).forEach(function (k) { if (cats[k]) any = true; sum += num(cats[k]) || 0; });
      var g2 = num(V.G2);
      if (!any) { bs.className = "bsum"; bs.textContent = "Sum: $0 — must equal G2"; }
      else if (g2 == null) { bs.className = "bsum"; bs.textContent = "Sum: " + money(sum) + " — enter G2 to check"; }
      else if (Math.abs(sum - g2) < 1) { bs.className = "bsum ok"; bs.textContent = "Sum: " + money(sum) + " — matches G2"; }
      else { bs.className = "bsum bad"; bs.textContent = "Sum: " + money(sum) + " — G2 is " + money(g2) + ", off by " + money(Math.abs(sum - g2)); }
    }

    var reqVis = F.filter(function (f) { return f.req && visible(f); });
    var done = reqVis.length - missingIds().length;
    document.getElementById("pfill").style.width = (reqVis.length ? Math.round(done / reqVis.length * 100) : 0) + "%";
    document.getElementById("plabel").textContent = done + " of " + reqVis.length + " required questions answered";
  }

  /* ---------- submit ---------- */
  function setStatus(kind, msg) {
    status.className = "status" + (kind ? " " + kind : "");
    status.textContent = msg || "";
  }
  function clearErrors() {
    Array.prototype.forEach.call(form.querySelectorAll(".f.error"), function (n) {
      n.classList.remove("error");
      var m = n.querySelector(".errmsg.js"); if (m) m.remove();
    });
  }
  function mark(id, msg) {
    var n = document.getElementById("f-" + id); if (!n) return;
    n.classList.add("error");
    var m = el("p", "errmsg js", msg); m.setAttribute("role", "alert");
    n.querySelector(".body").appendChild(m);
  }

  function payload() {
    var answers = {};
    F.forEach(function (f) {
      if (!visible(f)) return;
      Object.keys(V).forEach(function (k) {
        if (k === f.id || k.indexOf(f.id + "__") === 0) answers[k] = V[k];
      });
    });
    return {
      answers: answers,
      files: Object.keys(FILES).map(function (id) {
        return { question: id, name: FILES[id].name, type: FILES[id].type, size: FILES[id].size };
      }),
      meta: { lang: navigator.language || "", submitted_from: location.origin }
    };
  }

  function postJSON(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.error || "Request failed"); return j; }); });
  }

  sub.addEventListener("click", function () {
    clearErrors(); setStatus("", "");
    var miss = missingIds(), probs = problems();
    miss.forEach(function (id) { mark(id, "This question is required."); });
    Object.keys(probs).forEach(function (id) { if (miss.indexOf(id) === -1) mark(id, probs[id]); });
    var bad = F.filter(function (f) { return miss.indexOf(f.id) !== -1 || probs[f.id]; });
    if (bad.length) {
      setStatus("bad", bad.length + " question" + (bad.length === 1 ? " needs" : "s need") + " your attention. The first one is " + bad[0].id + ".");
      document.getElementById("f-" + bad[0].id).scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    if (hpi.value) { setStatus("ok", "Thank you."); return; }      // bot: pretend success, send nothing
    if (!CFG.endpoint) {
      setStatus("bad", "Preview build: the form is valid, but submissions are not connected yet, so nothing was sent.");
      return;
    }
    sub.disabled = true; sub.textContent = "Sending…";
    var tsToken = window.turnstile && CFG.turnstileSiteKey ? window.turnstile.getResponse() : "";
    var body = payload(); body.captcha = tsToken;
    postJSON(CFG.endpoint + "/submit", body)
      .then(function (res) {
        var ups = (res.uploads || []).map(function (u) {
          return fetch(u.url, { method: "PUT", headers: { "Content-Type": FILES[u.question].type || "application/octet-stream" }, body: FILES[u.question] })
            .then(function (r) { if (!r.ok) throw new Error("A file could not be uploaded (" + u.question + ")."); });
        });
        return Promise.all(ups).then(function () {
          return postJSON(CFG.endpoint + "/finalize", { application_id: res.application_id, token: res.token });
        }).then(function () { return res; });
      })
      .then(function (res) {
        setStatus("ok", "Application received. Your application ID is " + res.application_id + ". We will email you a confirmation.");
        sub.textContent = "Submitted";
      })
      .catch(function (err) {
        setStatus("bad", "We could not submit your application: " + err.message + " Nothing was lost on this page, please try again.");
        sub.disabled = false; sub.textContent = "Submit application";
      });
  });

  if (window.turnstile && CFG.turnstileSiteKey) {
    window.turnstile.render("#captcha", { sitekey: CFG.turnstileSiteKey });
  }

  refresh();
})();
