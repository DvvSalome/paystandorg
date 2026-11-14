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
  var draftCode = "";      // server-issued code of the saved draft ("" = nothing saved yet)
  var SAVED = {};          // section id -> true while it has no edits since the last save
  var restoring = false;   // true while a saved draft is being poured back into the controls
  var savedFiles = {};     // file names from the saved draft (files themselves cannot be restored)
  var LS_KEY = "ga27-draft-code";
  var secUI = {};          // section id -> { btn, msg, flash }
  var secProg = {};
  var MULTIPART = { composite: 1, titlesummary: 1, datepair: 1, valuedate: 1, baseline: 1,
                    milestones: 1, funders: 1, safeguard: 1 };
  var partNotes = {};      // question id -> the "Still needed: …" note under it
  var touched = {};        // question id -> focus has left it at least once        // section id -> el progreso de su encabezado
  var busySaving = false;
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

  /* ---------- email ----------
     Identical to EMAIL_RE in supabase/functions/_shared/drafts.js, which the
     server enforces. This file cannot import it, so tests/email.test.mjs
     fails if the two differ. */
  var EMAIL_RE = /^[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)*\.[^\s@.]{2,}$/;
  function validEmail(x) { return typeof x === "string" && x.trim().length <= 200 && EMAIL_RE.test(x.trim()); }
  // Characters that can never be part of an address. Typing them is blocked;
  // they are also what appears when someone pastes "Ana <ana@x.org>" or a list.
  var EMAIL_BAD = /[\s,;:<>()\[\]"\\]/g;
  var EMAIL_FIND = /[^\s@<>()\[\],;:"]+@[^\s@<>()\[\],;:"]+\.[^\s@<>()\[\],;:".]{2,}/;
  function cleanEmail(v) {
    v = String(v || "").replace(EMAIL_BAD, "");
    var at = v.indexOf("@");
    if (at !== -1) v = v.slice(0, at + 1) + v.slice(at + 1).replace(/@/g, "");
    return v.slice(0, 200);
  }
  // Format blockers for an email input, so only an address can go in:
  //   - spaces, commas, angle brackets and the like are dropped as typed
  //   - a second @ is dropped as typed
  //   - pasting "Ana Ruiz <ana@x.org>" keeps just ana@x.org
  //   - leaving the field with something that is not an address shows why
  // Changes go through an "input" event so every listener (D1's composite
  // handler, the save card binding) sees the cleaned value.
  function guardEmail(input, errEl) {
    input.maxLength = 200;
    input.spellcheck = false;
    input.setAttribute("autocapitalize", "off");
    function setTo(v) {
      if (input.value === v) return;
      input.value = v;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
    function showErr(msg) {
      if (!errEl) return;
      errEl.textContent = msg || "";
      errEl.hidden = !msg;
      if (msg) input.setAttribute("aria-invalid", "true"); else input.removeAttribute("aria-invalid");
    }
    // Clean on every input instead of refusing keystrokes. Phone keyboards,
    // predictive text and autofill insert whole chunks like "ana " at once;
    // refusing the chunk would leave the field empty with no explanation.
    // Stripping keeps what is valid. This listener is registered before any
    // other on the input (D1's composite handler, the save-card binding), so
    // they all read the cleaned value in the same event.
    input.addEventListener("input", function () {
      var c = cleanEmail(input.value);
      if (c !== input.value) input.value = c;
    });
    input.addEventListener("paste", function (e) {
      var text = (e.clipboardData || window.clipboardData).getData("text") || "";
      var found = text.match(EMAIL_FIND);
      e.preventDefault();
      setTo(found ? found[0].slice(0, 200) : cleanEmail(input.value + text));
    });
    input.addEventListener("input", function () {
      if (errEl && !errEl.hidden && validEmail(input.value)) showErr("");
    });
    input.addEventListener("blur", function () {
      setTo(cleanEmail(input.value));
      showErr(input.value && !validEmail(input.value) ? "Enter a complete email address, like name@example.org." : "");
    });
    return { check: function () {
      setTo(cleanEmail(input.value));
      var bad = input.value && !validEmail(input.value);
      showErr(bad ? "Enter a complete email address, like name@example.org." : "");
      return !bad;
    } };
  }

  /* ---------- rendering ---------- */
  SECTIONS.forEach(function (sec) {
    var box = el("fieldset", "sec");
    box.id = "sec-" + sec.id;
    var head = el("header");
    head.appendChild(el("div", "secid", "Section " + sec.id));
    head.appendChild(el("h3", null, sec.title));
    if (sec.note) head.appendChild(el("p", "secnote", sec.note));
    // Progreso repetido en cada encabezado. La barra de arriba queda fuera
    // de vista en una página de 60 preguntas, y en modo embed su sticky está
    // desactivado a propósito (form/index.html:44) porque dentro de un
    // iframe de altura automática no se pega a nada útil. Un indicador por
    // sección no necesita sticky: siempre está donde la persona acaba de
    // llegar. Y cuando el formulario pase a una sección por página, este
    // mismo elemento se convierte en el encabezado del paso.
    var secprog = el("p", "secprog");
    secprog.setAttribute("aria-live", "polite");
    head.appendChild(secprog);
    secProg[sec.id] = secprog;
    box.appendChild(head);
    F.filter(function (f) { return f.s === sec.id; }).forEach(function (f) {
      box.appendChild(buildField(f));
    });
    box.appendChild(sectionFooter(sec));
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
  var subRow = el("div", "subrow");
  var saveBtm = el("button", "savebtn", "Save progress");
  saveBtm.type = "button";
  subRow.appendChild(sub); subRow.appendChild(saveBtm);
  // The bottom "Save progress" gets the same treatment as a section footer:
  // a host where the save card opens and a flash for the outcome.
  var endHost = el("div", "savehost");
  var endFlash = el("span", "secflash"); endFlash.hidden = true;
  endFlash.setAttribute("role", "status"); endFlash.setAttribute("aria-live", "polite");
  subRow.appendChild(endFlash);
  bar.appendChild(captcha); bar.appendChild(subRow); bar.appendChild(endHost); bar.appendChild(status);
  form.appendChild(bar);
  var savebar = buildSaveBar();
  form.insertBefore(savebar.root, form.firstChild);
  var saveCard = buildSaveCard();
  var codeCard = buildCodeCard();
  savebar.email = saveCard.email;

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
        // Every email field gets the same format blockers as D1 — D4 (copy
        // address) included. Registered before the value listener so it
        // reads the cleaned value.
        var ierr = null;
        if (f.type === "email") {
          inp.autocomplete = "email";
          ierr = el("span", "fielderr"); ierr.hidden = true; ierr.setAttribute("role", "alert");
          guardEmail(inp, ierr);
        }
        inp.addEventListener("input", function () { V[f.id] = inp.value; refresh(); });
        body.appendChild(inp);
        if (ierr) body.appendChild(ierr);
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
            // "YYYY-MM-DD" alone is parsed as UTC midnight, which in the
            // Americas is the previous day locally — 03/01 to 03/31 came out
            // as 1 month. Anchoring to local midnight keeps the day as typed.
            var a = new Date(d1.value + "T00:00:00"), b = new Date(d2.value + "T00:00:00");
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
        var emailErrHosts = [];
        var vals = {};
        f.parts.forEach(function (p) {
          var pi = el("input"); pi.type = p.t; pi.placeholder = p.ph;
          pi.setAttribute("aria-label", f.label + " — " + p.ph);
          if (p.k === "email") {
            pi.autocomplete = "email";
            var perr = el("span", "fielderr"); perr.hidden = true; perr.setAttribute("role", "alert");
            emailErrHosts.push({ input: pi, err: perr });
            guardEmail(pi, perr);
          }
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
        emailErrHosts.forEach(function (h) { body.appendChild(h.err); });
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
        // Today in the applicant's own timezone. valueAsDate uses UTC, so in
        // the Americas after 6 p.m. it showed tomorrow's date.
        var nowL = new Date();
        var sd = el("input"); sd.type = "date"; sd.readOnly = true;
        sd.value = nowL.getFullYear() + "-" + ("0" + (nowL.getMonth() + 1)).slice(-2) + "-" + ("0" + nowL.getDate()).slice(-2);
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
    if (MULTIPART[f.type]) {
      var pn = el("p", "partnote"); pn.hidden = true; pn.setAttribute("aria-live", "polite");
      wrap.appendChild(pn);
      partNotes[f.id] = pn;
      // "Touched" = focus left the whole question, not just moved between
      // its own parts — no nagging while someone is still filling it in.
      wrap.addEventListener("focusout", function (e) {
        if (e.relatedTarget && wrap.contains(e.relatedTarget)) return;
        touched[f.id] = true; refresh();
      });
    }
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
      // A non-empty combined value is not enough for a question with parts:
      // every part it asks for has to be there (questions.js, missingParts).
      else if (partsOf(f).length) out.push(f.id);
    });
    return out;
  }
  function hasFile(id) { return !!FILES[id] || !!savedFiles[id]; }
  function partsOf(f) { return G.missingParts ? G.missingParts(f, V, hasFile) : []; }
  // The message for a required question that is not complete: name what is
  // missing when it was started, so "required" never hides "almost".
  function missingMessage(f) {
    var parts = partsOf(f);
    return parts.length && V[f.id] ? "Still needed: " + parts.join("; ") + "." : "This question is required.";
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
    F.forEach(function (f) {
      if (f.type === "email" && visible(f) && V[f.id] && !validEmail(V[f.id]))
        p[f.id] = "Enter a complete email address, like name@example.org.";
    });
    var d3f = F.filter(function (x) { return x.id === "D3"; })[0];
    if (d3f && visible(d3f) && V.D3__email && !validEmail(V.D3__email))
      p.D3 = "Enter a complete email address for the signer, like name@example.org.";
    // The contact email is required and must be a complete address — the
    // same rule the server enforces on submit.
    var em = V.D1__email;
    // An empty D1 is already reported as missing; this catches a D1 with a
    // name or phone but no email, which "required" alone would let through.
    if (!p.D1 && !em && V.D1) p.D1 = "Add the contact email address.";
    else if (em && !validEmail(em)) p.D1 = "Enter a complete email address, like name@example.org.";
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

    // El mismo número, repetido en cada sección, más lo que falta ahí.
    var pos = {};
    SECTIONS.forEach(function (s2, i) { pos[s2.id] = i + 1; });
    SECTIONS.forEach(function (s2) {
      var node = secProg[s2.id];
      if (!node) return;
      var mine = reqVis.filter(function (f) { return f.s === s2.id; });
      var openHere = missingIds().filter(function (id) {
        return mine.some(function (f) { return f.id === id; });
      }).length;
      node.textContent = "Section " + s2.id + " of " + SECTIONS.length +
        "  ·  " + done + " of " + reqVis.length + " required answered overall" +
        (mine.length ? (openHere ? "  ·  " + openHere + " still open here"
                                 : "  ·  this section is complete") : "");
      node.className = "secprog" + (mine.length && !openHere ? " done" : "");
    });

    syncSaveEmail();
    // Live note under a multi-part question once the person has left it
    // half-answered: "Still needed: phone; title." It clears itself as soon
    // as the last part is filled.
    F.forEach(function (f) {
      var note = partNotes[f.id]; if (!note) return;
      var parts = visible(f) && touched[f.id] && V[f.id] ? partsOf(f) : [];
      note.hidden = !parts.length;
      note.textContent = parts.length ? "Still needed: " + parts.join("; ") + "." : "";
    });
    if (typeof updateSaveUI === "function" && !restoring) updateSaveUI();
  }


  /* ---------- save and resume ---------- */

  function sectionFooter(sec) {
    var row = el("div", "secsave");
    var btn = el("button", "savebtn", "Save section " + sec.id);
    btn.type = "button";
    var msg = el("span", "secmsg");
    msg.setAttribute("aria-live", "polite");
    // The outcome of a save gets its own element. `msg` belongs to
    // updateSaveUI, which keeps the completeness status there ("3 of 7
    // required still open"). Sharing one element meant a successful save
    // read as a six-character text change, and a failed save showed up
    // nowhere at all — the error went to the global bar, far up the page,
    // so the button looked inert either way. Two jobs, two elements.
    var flash = el("span", "secflash");
    flash.setAttribute("role", "status");
    flash.setAttribute("aria-live", "polite");
    flash.hidden = true;
    row.appendChild(btn); row.appendChild(msg); row.appendChild(flash);
    secUI[sec.id] = { btn: btn, msg: msg, flash: flash, row: row };
    btn.addEventListener("click", function () { saveDraft(sec.id); });
    return row;
  }

  // Save feedback next to the button the person actually pressed.
  function flashSection(secId, kind, text) {
    var ui = secId === "__end" ? { flash: endFlash } : (secId && secUI[secId]);
    if (!ui || !ui.flash) return;
    ui.flash.hidden = !text;
    ui.flash.className = "secflash" + (kind ? " " + kind : "");
    ui.flash.textContent = text || "";
  }

  /* ---------- the save experience ----------
     One moment at a time, depending on what the person is doing:

       arriving        a reassuring line, and a quiet "Have a code?" link —
                       or "Welcome back" when this browser remembers a draft
       first save      a card opens next to the button they pressed and asks
                       where to send the code: the moment the email makes sense
       code issued     the code, large, with Copy, in that same place
       later saves     only "Saved at 14:32 ✓"; nothing asks again
       anytime after   a compact chip with the code at the top of the form

     No modals: the form lives in an auto-height iframe, so a fixed overlay
     opens at the top of the content, nowhere near the viewport.

     The email field is bound to D1's email part — one value, V.D1__email,
     two views (docs/email-the-code.md). If D1 already has a valid email,
     the first save does not ask again. */

  function buildSaveBar() {
    var root = el("div", "door");

    // arriving, nothing remembered
    var fresh = el("div", "door-fresh");
    fresh.appendChild(el("p", "door-lead",
      "You don't have to finish in one sitting. Save at the end of any section and come back with your code, from any device."));
    var haveCode = el("button", "linkbtn", "Have a code? Continue your application");
    haveCode.type = "button";
    fresh.appendChild(haveCode);

    // continue with a code
    var resume = el("div", "door-resume"); resume.hidden = true;
    var rl = el("label", null, "Your code"); rl.htmlFor = "ga27-resume";
    var ri = el("input"); ri.type = "text"; ri.id = "ga27-resume"; ri.placeholder = "GA27-XXX-XXX-XXX";
    ri.autocomplete = "off"; ri.maxLength = 20; ri.spellcheck = false;
    var rb = el("button", "savebtn primary", "Continue"); rb.type = "button";
    resume.appendChild(rl); resume.appendChild(ri); resume.appendChild(rb);

    // arriving, this browser remembers a draft
    var back = el("div", "door-back"); back.hidden = true;
    back.appendChild(el("p", "door-title", "Welcome back"));
    var backTxt = el("p", "door-lead", "");
    back.appendChild(backTxt);
    var backRow = el("div", "door-actions");
    var backGo = el("button", "savebtn primary", "Continue where I left off"); backGo.type = "button";
    var backNew = el("button", "linkbtn", "Start a new application"); backNew.type = "button";
    backRow.appendChild(backGo); backRow.appendChild(backNew); back.appendChild(backRow);

    // a draft is active: the code stays at hand
    var chip = el("div", "door-chip"); chip.hidden = true;
    chip.appendChild(el("span", "chip-lab", "Your code"));
    var chipCode = el("strong", "codeval");
    var chipCopy = el("button", "savebtn small", "Copy"); chipCopy.type = "button";
    var chipNote = el("span", "chip-note");
    chip.appendChild(chipCode); chip.appendChild(chipCopy); chip.appendChild(chipNote);

    var msg = el("div", "savemsg"); msg.setAttribute("role", "status"); msg.setAttribute("aria-live", "polite");
    root.appendChild(fresh); root.appendChild(back); root.appendChild(chip);
    root.appendChild(resume); root.appendChild(msg);

    haveCode.addEventListener("click", function () {
      resume.hidden = !resume.hidden;
      if (!resume.hidden) ri.focus();
    });
    rb.addEventListener("click", function () { resumeDraft(ri.value); });
    ri.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); resumeDraft(ri.value); } });
    backGo.addEventListener("click", function () { resumeDraft(rememberedCode); });
    backNew.addEventListener("click", function () {
      rememberedCode = "";
      try { localStorage.removeItem(LS_KEY); } catch (e) {}
      say("", "");
      renderDoor();
    });
    chipCopy.addEventListener("click", function () { copyCode(chipCopy); });
    saveBtm.addEventListener("click", function () { saveDraft("__end"); });

    return {
      root: root, msg: msg, input: ri,
      fresh: fresh, resume: resume, back: back, backTxt: backTxt,
      chip: chip, chipCode: chipCode, chipNote: chipNote,
      email: null      // set by buildSaveCard
    };
  }

  // The card that opens at the first save. One element, moved into
  // whichever footer was clicked.
  function buildSaveCard() {
    var card = el("div", "savecard"); card.hidden = true;
    card.appendChild(el("p", "card-title", "Save your progress"));
    var lead = el("p", "card-lead", "");
    card.appendChild(lead);
    var lab = el("label", null, "Your email"); lab.htmlFor = "ga27-save-email";
    var mi = el("input"); mi.type = "email"; mi.id = "ga27-save-email";
    mi.autocomplete = "email"; mi.placeholder = "you@example.org"; mi.maxLength = 200;
    var hint = el("span", "card-hint", "This is also your contact email in section D. Change it in either place.");
    var err = el("span", "card-err"); err.hidden = true;
    var acts = el("div", "door-actions");
    var go = el("button", "savebtn primary", ""); go.type = "button";
    var skip = el("button", "linkbtn", "Save without email"); skip.type = "button";
    acts.appendChild(go); acts.appendChild(skip);
    card.appendChild(lab); card.appendChild(mi); card.appendChild(hint); card.appendChild(err); card.appendChild(acts);

    var guard = guardEmail(mi, err);
    mi.addEventListener("input", function () { setSaveEmail(mi.value); });
    function confirm() {
      if (!guard.check()) { mi.focus(); return; }
      card.hidden = true;
      saveDraft(card.dataset.host, { confirmed: true });
    }
    go.addEventListener("click", confirm);
    mi.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); confirm(); } });
    skip.addEventListener("click", function () {
      card.hidden = true;
      saveDraft(card.dataset.host, { confirmed: true });
    });
    return { card: card, lead: lead, email: mi, go: go, err: err };
  }

  // The card that shows the code right after it is issued.
  function buildCodeCard() {
    var card = el("div", "codecard"); card.hidden = true;
    card.setAttribute("role", "status");
    card.appendChild(el("p", "card-title", "Your progress is saved"));
    var row = el("div", "code-big");
    var code = el("strong", "codeval big");
    var copy = el("button", "savebtn", "Copy code"); copy.type = "button";
    row.appendChild(code); row.appendChild(copy);
    var note = el("p", "card-lead", "");
    var files = el("p", "card-hint", "Attached files are not saved with your progress — you will attach them again before submitting.");
    var done = el("button", "linkbtn", "Done"); done.type = "button";
    card.appendChild(row); card.appendChild(note); card.appendChild(files); card.appendChild(done);
    copy.addEventListener("click", function () { copyCode(copy); });
    done.addEventListener("click", function () { card.hidden = true; });
    return { card: card, code: code, note: note };
  }

  function hostFor(id) {
    if (id === "__end") return endHost;
    return secUI[id] && secUI[id].row;
  }
  function openSaveCard(id) {
    var host = hostFor(id); if (!host) return;
    codeCard.card.hidden = true;
    saveCard.card.dataset.host = id;
    saveCard.lead.textContent = CFG.emailCodes === true
      ? "We'll email you a code so you can continue from any device."
      : "You'll get a code to continue from any device.";
    saveCard.go.textContent = CFG.emailCodes === true ? "Save and email my code" : "Save and get my code";
    saveCard.err.hidden = true;
    host.appendChild(saveCard.card);
    saveCard.card.hidden = false;
    syncSaveEmail();
    saveCard.email.focus();
  }
  function showCodeCard(id) {
    var host = hostFor(id); if (!host) return;
    codeCard.code.textContent = draftCode;
    codeCard.note.textContent = codeNoteText();
    host.appendChild(codeCard.card);
    codeCard.card.hidden = false;
  }
  function copyCode(btn) {
    var label = btn.textContent;
    var done = function () { btn.textContent = "Copied ✓"; window.setTimeout(function () { btn.textContent = label; }, 1500); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(draftCode).then(done, function () {});
  }

  // The top of the form shows exactly one of: the fresh line, welcome back,
  // or the code chip.
  var rememberedCode = "";
  function renderDoor() {
    var hasCode = !!draftCode, hasMemory = !hasCode && !!rememberedCode;
    savebar.chip.hidden = !hasCode;
    savebar.back.hidden = !hasMemory;
    savebar.fresh.hidden = hasCode || hasMemory;
    if (hasCode) {
      savebar.resume.hidden = true;
      savebar.chipCode.textContent = draftCode;
      savebar.chipNote.textContent = codeWasEmailed()
        ? "Sent to " + V.D1__email
        : "Not emailed — keep it somewhere safe";
    }
    if (hasMemory) savebar.backTxt.textContent =
      "You have an application in progress on this device (" + rememberedCode + ").";
  }

  // Write the bound email through D1's own input, as if typed there, so the
  // composite handler rebuilds V.D1, V.D1__email and the section state the
  // same way it does for typing. One write path, one value.
  function d1EmailInput() { return document.querySelector("#f-D1 input[type=email]"); }
  function setSaveEmail(value) {
    var d = d1EmailInput();
    if (!d || d.value === value) return;
    d.value = value;
    d.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function syncSaveEmail() {
    if (!savebar || !savebar.email) return;
    var v = V.D1__email || "";
    // Never overwrite the field while the person is typing in it.
    if (savebar.email !== document.activeElement && savebar.email.value !== v) savebar.email.value = v;
  }
  // Whether the code was actually emailed. CFG.emailCodes stays false until
  // the server sends mail; until then the honest message is "write it down",
  // never "we sent it" (commit 0effcb5 removed one such promise already).
  function codeWasEmailed() { return CFG.emailCodes === true && validEmail(V.D1__email); }
  function codeNoteText() {
    return codeWasEmailed()
      ? "We sent it to " + V.D1__email + ". Keep it anyway: anyone with this code can open your application."
      : "Copy it or write it down now. There is no way to recover a lost code, and anyone with it can open your application.";
  }

  function say(kind, text) { savebar.msg.className = "savemsg" + (kind ? " " + kind : ""); savebar.msg.textContent = text || ""; }
  function showCode() {
    try { if (draftCode) localStorage.setItem(LS_KEY, draftCode); else localStorage.removeItem(LS_KEY); } catch (e) {}
    renderDoor();
  }

  function draftControls(wrap) {
    return Array.prototype.filter.call(wrap.querySelectorAll("input,textarea,select"), function (c) {
      return c.type !== "file" && !c.readOnly;
    });
  }
  // Snapshot = the value of every control, in document order, per question. Restoring replays them as
  // user input, so the form's own handlers rebuild V and every derived value the same way as typing.
  function snapshot() {
    var fields = {};
    F.forEach(function (f) {
      var wrap = document.getElementById("f-" + f.id); if (!wrap) return;
      var vals = draftControls(wrap).map(function (c) {
        return (c.type === "checkbox" || c.type === "radio") ? (c.checked ? 1 : 0) : c.value;
      });
      if (vals.some(function (x) { return x !== "" && x !== 0; })) fields[f.id] = vals;
    });
    var files = {};
    Object.keys(FILES).forEach(function (id) { files[id] = FILES[id].name; });
    Object.keys(savedFiles).forEach(function (id) { if (!files[id] && !FILES[id]) files[id] = savedFiles[id]; });
    return { v: 1, fields: fields, files: files, g2touched: !!V.__g2touched, email: V.D1__email || "" };
  }

  function fire(n, t) { n.dispatchEvent(new Event(t, { bubbles: true })); }
  function restore(state) {
    restoring = true;
    try {
      F.forEach(function (f) {
        var wrap = document.getElementById("f-" + f.id), vals = state.fields && state.fields[f.id];
        if (!wrap || !vals) return;
        draftControls(wrap).forEach(function (c, i) {
          var x = vals[i]; if (x === undefined) return;
          if (c.type === "checkbox") { c.checked = x === 1; fire(c, "change"); }
          else if (c.type === "radio") { c.checked = x === 1; if (x === 1) fire(c, "change"); }
          else if (c.tagName === "SELECT") { c.value = x; fire(c, "change"); }
          else if (f.type === "country") { c.value = x; V[f.id] = x; }
          else { c.value = x; fire(c, "input"); fire(c, "change"); }
        });
      });
      V.__g2touched = !!state.g2touched;
    } finally { restoring = false; }
    savedFiles = state.files || {};
    Object.keys(savedFiles).forEach(function (id) {
      var body = document.querySelector("#f-" + id + " .body"); if (!body) return;
      var old = body.querySelector(".filenote"); if (old) old.remove();
      body.appendChild(el("p", "help filenote", "You attached “" + savedFiles[id] + "” before. Files are not saved: please attach it again."));
    });
    refresh();
  }

  function saveDraft(secId, opts) {
    if (busySaving) return;
    var firstSave = !draftCode, codeBefore = draftCode;
    // Every message goes to both places: the global bar, and — when a
    // section button was the one pressed — right next to that button.
    // Nothing about saving should be invisible from where you clicked.
    function both(kind, text) { say(kind, text); flashSection(secId, kind, text); }
    if (!CFG.endpoint) {
      both("bad", "Saving is not connected in this preview build. Your answers are not stored.");
      return;
    }
    // The first save is when a code is issued, so it is the moment to ask
    // where to send it — unless D1 already has a valid email.
    if (firstSave && !(opts && opts.confirmed) && !validEmail(V.D1__email)) {
      openSaveCard(secId);
      return;
    }
    busySaving = true; flashSection(secId, "", "Saving…");
    var ids = SECTIONS.map(function (s) { return s.id; });
    postJSON(CFG.endpoint + "/draft/save", { code: draftCode || undefined, state: snapshot(), saved_sections: ids })
      .catch(function (err) {
        if (draftCode && /not found/i.test(err.message)) {          // the code expired: start a new one
          draftCode = "";
          return postJSON(CFG.endpoint + "/draft/save", { state: snapshot(), saved_sections: ids });
        }
        throw err;
      })
      .then(function (res) {
        draftCode = res.code; showCode();
        ids.forEach(function (id) { SAVED[id] = true; });
        var t = new Date(), hh = ("0" + t.getHours()).slice(-2) + ":" + ("0" + t.getMinutes()).slice(-2);
        say("", "");
        // updateSaveUI rewrites secmsg, so the flash goes after it.
        updateSaveUI();
        // A new code — first save, or the old one expired and the server
        // issued another — must be shown, not just acknowledged.
        if (draftCode !== codeBefore) { flashSection(secId, "", ""); showCodeCard(secId); }
        else flashSection(secId, "ok", "Saved at " + hh + " ✓");
      })
      .catch(function (err) { both("bad", "We could not save: " + err.message); })
      .then(function () { busySaving = false; });
  }

  function resumeDraft(raw) {
    var code = String(raw || "").trim();
    if (!code) { say("bad", "Enter the code you got when you saved."); return; }
    if (!CFG.endpoint) { say("bad", "Preview build: saving is not connected."); return; }
    say("", "Looking for your draft…");
    postJSON(CFG.endpoint + "/draft/load", { code: code })
      .then(function (res) {
        restore(res.state || {});
        draftCode = res.code; showCode();
        (res.saved_sections || []).forEach(function (id) { SAVED[id] = true; });
        updateSaveUI();
        rememberedCode = "";
        say("ok", "Your saved answers are back. Attach your files again before submitting.");
        savebar.root.scrollIntoView({ behavior: "smooth", block: "start" });
      })
      .catch(function (err) { say("bad", err.message); });
  }

  function updateSaveUI() {
    SECTIONS.forEach(function (sec) {
      var ui = secUI[sec.id]; if (!ui) return;
      var req = F.filter(function (f) { return f.s === sec.id && f.req && visible(f); });
      var open = missingIds().filter(function (id) { return req.some(function (f) { return f.id === id; }); }).length;
      var txt;
      if (SAVED[sec.id]) txt = open ? "Saved — " + open + " required still open" : "Saved ✓ all required answered";
      else if (!req.length) txt = "Nothing required here";
      else txt = open ? open + " of " + req.length + " required still open" : "All required answered";
      ui.msg.textContent = txt;
      ui.msg.className = "secmsg" + (SAVED[sec.id] ? " saved" : "") + (!open && req.length ? " done" : "");
    });
  }

  // Any edit makes its section "unsaved" again.
  form.addEventListener("input", markDirty);
  form.addEventListener("change", markDirty);
  function markDirty(e) {
    if (restoring) return;
    var sec = e.target && e.target.closest && e.target.closest("fieldset.sec");
    if (sec) {
      var sid = sec.id.replace("sec-", "");
      delete SAVED[sid];
      // The flash said "Saved at 14:32" — after an edit that is no longer
      // true, and a stale confirmation is worse than none.
      flashSection(sid, "", "");
      updateSaveUI();
    }
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
      .then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) { var e = new Error(j.error || "Request failed"); e.fields = j.fields; throw e; }
          return j;
        });
      });
  }

  sub.addEventListener("click", function () {
    clearErrors(); setStatus("", "");
    var miss = missingIds(), probs = problems();
    miss.forEach(function (id) { mark(id, missingMessage(F.filter(function (x) { return x.id === id; })[0])); });
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
          // Same request supabase-js sends for a signed upload URL: multipart PUT.
          var fd = new FormData(); fd.append("cacheControl", "3600"); fd.append("", FILES[u.question]);
          return fetch(u.url, { method: "PUT", headers: { "x-upsert": "false", "apikey": CFG.supabaseKey || "" }, body: fd })
            .then(function (r) { if (!r.ok) throw new Error("A file could not be uploaded (" + u.question + ")."); });
        });
        return Promise.all(ups).then(function () {
          return postJSON(CFG.endpoint + "/finalize", { application_id: res.application_id, token: res.token, draft_code: draftCode || undefined });
        }).then(function () { return res; });
      })
      .then(function (res) {
        setStatus("ok", "Application received. Your application ID is " + res.application_id + ". Please keep it for your records.");
        sub.textContent = "Submitted";
        draftCode = ""; showCode();
      })
      .catch(function (err) {
        if (err.fields) Object.keys(err.fields).forEach(function (id) { mark(id, "Please check this answer (" + err.fields[id] + ")."); });
        setStatus("bad", "We could not submit your application: " + err.message + " Nothing was lost on this page, please try again.");
        sub.disabled = false; sub.textContent = "Submit application";
      });
  });

  if (window.turnstile && CFG.turnstileSiteKey) {
    window.turnstile.render("#captcha", { sitekey: CFG.turnstileSiteKey });
  }

  try {
    var remembered = localStorage.getItem(LS_KEY);
    if (remembered) rememberedCode = remembered;
  } catch (e) {}
  renderDoor();
  refresh();
})();
