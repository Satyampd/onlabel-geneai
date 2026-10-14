/* =====================================================================
   OnLabel — reviewer console (vanilla JS, no build step)

   Rendering rule: every value that comes from the server is written with
   textContent (or as an <img> src built from an encoded id). innerHTML is
   only ever used for the static SVG icon strings below.
   All URLs are relative, so the console works behind path-prefix proxies.
   ===================================================================== */
(function () {
  "use strict";

  var REQUEST_TIMEOUT_MS = 30000;
  var POLL_MS = 10000;
  var STORE_KEY = "onlabel_reviewer";
  var PLACEHOLDER_RE = /\[[^\]]+\]/g;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  /* ---------- Static SVG icons (only static strings go through innerHTML) ---------- */
  var SVG_OPEN = '<svg viewBox="0 0 24 24" width="WS" height="WS" fill="none" stroke="currentColor" stroke-width="SW" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  function svg(paths, size, sw) {
    return SVG_OPEN.replace(/WS/g, String(size || 16)).replace("SW", String(sw || 2)) + paths + "</svg>";
  }
  var P = {
    inbox: '<path d="M3 13h5l1.5 2.5h5L16 13h5"/><path d="M5.5 5h13L21 13v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-5l2.5-8Z"/>',
    siren: '<path d="M7 18v-6a5 5 0 0 1 10 0v6"/><path d="M5 21h14"/><path d="M5 18h14"/><path d="M12 3V2"/><path d="m19.5 5.5.7-.7"/><path d="m4.5 5.5-.7-.7"/><path d="M21 11h1"/><path d="M2 11h1"/>',
    sparkle: '<path d="M12 3c.5 3.8 2.2 5.5 6 6-3.8.5-5.5 2.2-6 6-.5-3.8-2.2-5.5-6-6 3.8-.5 5.5-2.2 6-6Z"/><path d="M19 15c.2 1.6.9 2.3 2.5 2.5-1.6.2-2.3.9-2.5 2.5-.2-1.6-.9-2.3-2.5-2.5 1.6-.2 2.3-.9 2.5-2.5Z"/>',
    pulse: '<path d="M3 12h4l2.5-6 4 12 2.5-6H21"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12"/><path d="M18 6 6 18"/>',
    warn: '<path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 10v4.5"/><path d="M12 17.5h.01"/>',
    lock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3"/>',
    unlock: '<rect x="4.5" y="10.5" width="15" height="10" rx="2.5"/><path d="M8 10.5V7.5a4 4 0 0 1 7.6-1.7"/>',
    expand: '<path d="M15 3h6v6"/><path d="M9 21H3v-6"/><path d="M21 3l-7 7"/><path d="M3 21l7-7"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z"/><path d="M14 3v5h5"/><path d="M9 13h6"/><path d="M9 17h4"/>',
    quote: '<path d="M9.5 7C6.5 8 5 10.3 5 13.5V17h4.5v-4.5H7c0-2 .9-3.3 2.5-4Z"/><path d="M18.5 7c-3 1-4.5 3.3-4.5 6.5V17h4.5v-4.5H16c0-2 .9-3.3 2.5-4Z"/>',
    gemini: '<path d="M12 2.5c.9 5 3.6 8.4 9.5 9.5-5.9 1.1-8.6 4.5-9.5 9.5-.9-5-3.6-8.4-9.5-9.5 5.9-1.1 8.6-4.5 9.5-9.5Z"/>',
    target: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r=".8"/>',
    shieldCheck: '<path d="M12 2.8 4.5 5.6v5.7c0 4.6 3.1 8.6 7.5 9.9 4.4-1.3 7.5-5.3 7.5-9.9V5.6L12 2.8Z"/><path d="m8.6 12.1 2.4 2.4 4.6-4.8"/>',
    bulb: '<path d="M9 18h6"/><path d="M10 21h4"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.4 1.1 2.2h5c0-.8.4-1.6 1.1-2.2A6 6 0 0 0 12 3Z"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    user: '<circle cx="12" cy="8" r="3.8"/><path d="M4.5 20.5c.8-3.7 3.9-6 7.5-6s6.7 2.3 7.5 6"/>',
    section: '<path d="M4 6h16"/><path d="M4 12h10"/><path d="M4 18h13"/>',
    tag: '<path d="M3 12V4.5A1.5 1.5 0 0 1 4.5 3H12l9 9-9 9-9-9Z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
    refresh: '<path d="M3 12a9 9 0 0 1 15.4-6.4L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.4 6.4L3 16"/><path d="M3 21v-5h5"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12Z"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.5h.01"/>',
    stamp: '<path d="M9 3h6l-1 7h-4L9 3Z"/><path d="M5 14a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3H5v-3Z"/><path d="M5 21h14"/>',
    clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>'
  };
  function icon(name, size, sw) { return svg(P[name] || "", size, sw); }

  /* ---------- DOM ---------- */
  var $ = function (id) { return document.getElementById(id); };
  var els = {
    banner: $("bannerText"),
    view: $("view"),
    main: $("main"),
    badgePending: $("badgePending"),
    badgeReports: $("badgeReports"),
    reviewer: $("reviewerInput"),
    whoAvatar: $("whoAvatar"),
    whoState: $("whoState"),
    whoHint: $("whoHint"),
    whoCard: $("whoCard"),
    live: $("liveIndicator"),
    liveText: $("liveText"),
    modal: $("modal"),
    modalTitle: $("modalTitle"),
    modalSub: $("modalSub"),
    modalBody: $("modalBody"),
    modalClose: $("modalClose"),
    toasts: $("toasts")
  };

  /* ---------- State ---------- */
  var state = {
    view: "review",
    reviewer: loadReviewer(),
    items: null,            // array, once loaded
    itemsError: null,
    summary: null,
    rejectCodes: [],
    builtAt: "",
    buildSeconds: 0,
    filter: { status: "pending", doc: "all", q: "" },
    selectedId: null,
    keepId: null,           // a just-decided item stays in the list until the filter changes
    busy: false,
    reports: null,
    reportsError: null,
    seenReports: null,      // ids already rendered once (new ones get an entrance animation)
    activity: null,
    activityError: null,
    seenTurns: null,
    gaps: null,             // {loading, error, data}
    lastFocus: null,
    lastSync: null
  };

  /* =====================================================================
     Helpers
     ===================================================================== */
  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function iconEl(name, className, size, sw) {
    var span = el("span", "ico" + (className ? " " + className : ""));
    span.innerHTML = icon(name, size, sw); // static SVG string only
    span.setAttribute("aria-hidden", "true");
    return span;
  }
  function append(parent) {
    for (var i = 1; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === false) continue;
      parent.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return parent;
  }
  function isStr(v) { return typeof v === "string" && v.length > 0; }
  function str(v) { return v === null || v === undefined ? "" : String(v); }
  function human(v) { return str(v).replace(/_/g, " "); }
  function num(v) { return typeof v === "number" && isFinite(v) ? v : 0; }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  /** "2026-10-14T13:19:22" → "14 Oct, 13:19". Unparseable values are shown as given. */
  function fmtTime(ts) {
    if (!isStr(ts)) return "";
    var m = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(ts);
    if (m) {
      var mo = parseInt(m[2], 10);
      if (mo >= 1 && mo <= 12) {
        var d = parseInt(m[3], 10) + " " + MONTHS[mo - 1];
        return m[4] ? d + ", " + m[4] + ":" + m[5] : d + " " + m[1];
      }
    }
    return ts;
  }
  function fmtClock(ts) {
    var m = /[T ](\d{2}):(\d{2}):(\d{2})/.exec(str(ts));
    return m ? m[1] + ":" + m[2] + ":" + m[3] : fmtTime(ts);
  }

  function docLabel(doc) { return doc === "medication_guide" ? "Medication Guide" : doc === "brochure" ? "Brochure" : human(doc) || "Unknown"; }
  function docTag(doc, small) {
    var t = el("span", "doctag doctag--" + (doc === "medication_guide" ? "mg" : "br") + (small ? " doctag--sm" : ""), docLabel(doc));
    return t;
  }

  function initials(name) {
    var parts = str(name).trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    var s = parts[0].charAt(0) + (parts.length > 1 ? parts[parts.length - 1].charAt(0) : "");
    return s.toUpperCase();
  }

  function loadReviewer() {
    try { return (localStorage.getItem(STORE_KEY) || "").trim().slice(0, 80); } catch (e) { return ""; }
  }
  function saveReviewer(v) {
    try { if (v) localStorage.setItem(STORE_KEY, v); else localStorage.removeItem(STORE_KEY); } catch (e) { /* private mode */ }
  }

  /** Relative image URL for an item id (the id is encoded, never trusted as a path). */
  function itemImg(kind, id) {
    if (!isStr(id)) return null;
    return "api/console/" + (kind === "page" ? "page" : "snippet") + "/" + encodeURIComponent(id) + ".png";
  }

  /* ---------- Fetch with timeout; errors carry the server's detail ---------- */
  function request(url, opts) {
    opts = opts || {};
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, REQUEST_TIMEOUT_MS);
    var init = { method: opts.method || "GET", headers: { "Accept": "application/json" }, cache: "no-store" };
    if (controller) init.signal = controller.signal;
    if (opts.body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(url, init).then(function (res) {
      return res.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (!res.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail)) detail = detail.map(function (d) { return d && d.msg; }).filter(isStr).join("; ");
          var err = new Error(isStr(detail) ? detail : "The server answered " + res.status);
          err.status = res.status;
          throw err;
        }
        return data;
      });
    }, function (e) {
      throw new Error(e && e.name === "AbortError" ? "The request timed out. Please try again." : "Can't reach the server. Check the connection and try again.");
    }).then(function (d) { clearTimeout(timer); return d; }, function (e) { clearTimeout(timer); throw e; });
  }

  /* ---------- Toasts ---------- */
  function toast(text, kind) {
    var t = el("div", "toast toast--" + (kind === "err" ? "err" : "ok"));
    t.setAttribute("role", kind === "err" ? "alert" : "status");
    append(t, iconEl(kind === "err" ? "warn" : "check", "", 17, 2.4), el("span", "", text));
    els.toasts.appendChild(t);
    setTimeout(function () {
      t.classList.add("toast--out");
      setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 400);
    }, kind === "err" ? 6000 : 3800);
  }

  /* =====================================================================
     Reviewer identity
     ===================================================================== */
  function renderWho() {
    var name = state.reviewer;
    els.whoAvatar.textContent = initials(name);
    els.whoCard.classList.toggle("who--set", !!name);
    els.whoState.textContent = name ? "Signed decisions" : "Name required";
    els.whoHint.textContent = name
      ? "Recorded with every approval, rejection and acknowledgement."
      : "Enter your name to approve, reject or acknowledge.";
  }
  function onReviewerInput() {
    var v = els.reviewer.value.replace(/\s+/g, " ").trim().slice(0, 80);
    var changed = (!!v) !== (!!state.reviewer);
    state.reviewer = v;
    saveReviewer(v);
    renderWho();
    if (changed) refreshGatedControls();
    else updateNameBound();
  }
  function focusReviewer() {
    els.reviewer.focus();
    els.whoCard.classList.remove("who--nudge");
    void els.whoCard.offsetWidth;
    els.whoCard.classList.add("who--nudge");
  }
  /** Re-render the parts whose enabled state depends on having a name. */
  function refreshGatedControls() {
    if (state.view === "review") renderDecisionBar();
    if (state.view === "reports") renderReports();
  }
  function updateNameBound() {
    var nodes = document.querySelectorAll("[data-name-bound]");
    for (var i = 0; i < nodes.length; i++) nodes[i].textContent = state.reviewer;
  }
  function needNameHint(text) {
    var h = el("button", "needname");
    h.type = "button";
    append(h, iconEl("user", "", 14), el("span", "", text || "Enter your name under “Reviewing as” to decide"));
    h.addEventListener("click", focusReviewer);
    return h;
  }

  /* =====================================================================
     Badges + polling
     ===================================================================== */
  function setBadge(node, n, cls) {
    n = num(n);
    node.hidden = n <= 0;
    var prev = node.textContent;
    node.textContent = String(n);
    if (cls) node.classList.toggle(cls, n > 0);
    if (prev !== String(n) && !node.hidden) {
      node.classList.remove("bump");
      void node.offsetWidth;
      node.classList.add("bump");
    }
  }
  function updateBadges() {
    if (state.summary) setBadge(els.badgePending, state.summary.pending);
    if (state.reports) setBadge(els.badgeReports, state.reports.open, "side__badge--alarm");
  }
  function markSynced(ok) {
    state.lastSync = new Date();
    els.live.classList.toggle("live--off", !ok);
    var hh = ("0" + state.lastSync.getHours()).slice(-2), mm = ("0" + state.lastSync.getMinutes()).slice(-2), ss = ("0" + state.lastSync.getSeconds()).slice(-2);
    els.liveText.textContent = ok ? "Updated " + hh + ":" + mm + ":" + ss : "Offline";
  }

  var polling = false;
  function poll() {
    if (polling || document.hidden) return;
    polling = true;
    var jobs = [loadReports(true), loadItemsQuiet()];
    if (state.view === "activity" || state.view === "gaps") jobs.push(loadActivity(true));
    Promise.all(jobs).then(function (r) {
      markSynced(r.every(Boolean));
    }).then(function () { polling = false; }, function () { polling = false; });
  }

  /* =====================================================================
     Data loading
     ===================================================================== */
  function applyItemsPayload(d) {
    state.items = Array.isArray(d.items) ? d.items.filter(function (it) { return it && isStr(it.id); }) : [];
    state.summary = d.summary || null;
    state.rejectCodes = Array.isArray(d.reject_codes) ? d.reject_codes.filter(isStr) : [];
    state.builtAt = str(d.built_at);
    state.buildSeconds = num(d.build_seconds);
    state.itemsError = null;
  }
  function loadItems() {
    return request("api/console/items").then(function (d) {
      applyItemsPayload(d || {});
      updateBadges();
      return true;
    }, function (e) {
      state.itemsError = e.message;
      return false;
    });
  }
  /** Background refresh: only re-render if something actually changed, keeping the selection. */
  function loadItemsQuiet() {
    if (state.busy) return Promise.resolve(true);
    return request("api/console/items").then(function (d) {
      if (!d || state.busy) return true;
      var before = signature(state.items);
      var after = signature(d.items);
      if (before === after) { state.summary = d.summary || state.summary; updateBadges(); return true; }
      applyItemsPayload(d);
      updateBadges();
      if (state.view === "review") { renderKpis(); renderList(); renderDetail(true); }
      return true;
    }, function () { return false; });
  }
  function signature(items) {
    if (!Array.isArray(items)) return "";
    return items.map(function (it) { return it.id + ":" + it.status + ":" + (it.review && it.review.ts); }).join("|");
  }

  function loadReports(quiet) {
    return request("api/console/reports").then(function (d) {
      var prev = state.reports;
      state.reports = { open: num(d && d.open), reports: Array.isArray(d && d.reports) ? d.reports : [] };
      state.reportsError = null;
      updateBadges();
      if (state.view === "reports") {
        if (!quiet || !prev || reportsSig(prev) !== reportsSig(state.reports)) renderReports();
      }
      return true;
    }, function (e) {
      state.reportsError = e.message;
      if (state.view === "reports" && !quiet) renderReports();
      return false;
    });
  }
  function reportsSig(r) {
    return r.reports.map(function (x) {
      return x.id + ":" + x.report_status + ":" + (x.ae_form ? (x.ae_form.submitted_at || "ae") : "");
    }).join("|");
  }

  function loadActivity(quiet) {
    return request("api/console/activity").then(function (d) {
      var prev = state.activity;
      state.activity = { unanswered: num(d && d.unanswered), turns: Array.isArray(d && d.turns) ? d.turns : [] };
      state.activityError = null;
      var changed = !prev || turnsSig(prev) !== turnsSig(state.activity) || prev.unanswered !== state.activity.unanswered;
      if (state.view === "activity" && (!quiet || changed)) renderActivity();
      if (state.view === "gaps" && (!quiet || changed)) renderGapsStat();
      return true;
    }, function (e) {
      state.activityError = e.message;
      if (state.view === "activity" && !quiet) renderActivity();
      if (state.view === "gaps" && !quiet) renderGapsStat();
      return false;
    });
  }
  function turnsSig(a) { return a.turns.slice(0, 30).map(function (t) { return t.ts + t.message; }).join("|"); }

  /* =====================================================================
     Routing
     ===================================================================== */
  var VIEWS = ["review", "reports", "gaps", "activity"];
  function parseHash() {
    var h = (location.hash || "").replace(/^#/, "");
    var slash = h.indexOf("/");
    var view = slash === -1 ? h : h.slice(0, slash);
    var arg = slash === -1 ? "" : h.slice(slash + 1);
    if (VIEWS.indexOf(view) === -1) view = "review";
    try { arg = decodeURIComponent(arg); } catch (e) { arg = ""; }
    return { view: view, arg: arg };
  }
  function route() {
    var r = parseHash();
    var changedView = r.view !== state.view || !els.view.firstChild;
    state.view = r.view;
    var links = document.querySelectorAll(".side__link");
    for (var i = 0; i < links.length; i++) {
      var on = links[i].getAttribute("data-view") === r.view;
      if (on) links[i].setAttribute("aria-current", "page"); else links[i].removeAttribute("aria-current");
    }
    document.title = "OnLabel Review";
    if (r.view === "review") {
      if (r.arg && r.arg !== state.selectedId) {
        state.selectedId = r.arg;
        state.keepId = r.arg;
      }
      if (changedView) showReview(); else { renderList(); renderDetail(); }
    } else if (changedView) {
      if (r.view === "reports") showReports();
      if (r.view === "gaps") showGaps();
      if (r.view === "activity") showActivity();
    }
  }
  function setHashQuiet(h) {
    if (location.hash === h) return;
    try { history.replaceState(null, "", h); } catch (e) { location.hash = h; }
  }

  /* =====================================================================
     Review queue
     ===================================================================== */
  var R = {}; // review view nodes

  function showReview() {
    var v = els.view;
    clear(v);
    v.className = "view view--review";
    R.kpis = el("section", "kpis");
    R.kpis.setAttribute("aria-label", "Review summary");
    R.panes = el("div", "panes");
    R.listPane = el("section", "listpane glass");
    R.listPane.setAttribute("aria-label", "Items to review");
    R.detailPane = el("section", "detailpane glass");
    R.detailPane.setAttribute("aria-label", "Selected item");
    append(R.panes, R.listPane, R.detailPane);
    append(v, R.kpis, R.panes);
    buildListChrome();

    if (!state.items) {
      renderKpiSkeleton();
      R.rows.appendChild(skeletonRows(6));
      R.detailPane.appendChild(el("div", "detail-skel shimmer"));
      loadItems().then(function () {
        if (state.view !== "review") return;
        if (state.itemsError) { renderItemsError(); return; }
        renderKpis(); renderList(); renderDetail();
      });
    } else {
      renderKpis(); renderList(); renderDetail();
    }
  }

  function renderItemsError() {
    clear(R.kpis);
    clear(R.rows);
    clear(R.detailPane);
    var box = errorState("Couldn't load the review queue", state.itemsError, function () { state.items = null; showReview(); });
    R.detailPane.appendChild(box);
  }

  /* ---------- KPIs + GAR funnel ---------- */
  function renderKpiSkeleton() {
    clear(R.kpis);
    for (var i = 0; i < 4; i++) R.kpis.appendChild(el("div", "kpi glass kpi--skel shimmer"));
    R.kpis.appendChild(el("div", "funnel glass kpi--skel shimmer"));
  }
  function kpi(key, label, value, sub, tone, iconName) {
    var c = el("div", "kpi glass kpi--" + tone);
    c.setAttribute("data-kpi", key);
    var head = el("div", "kpi__head");
    append(head, el("span", "kpi__dot"), el("span", "kpi__label", label));
    var val = el("div", "kpi__value", value);
    val.setAttribute("data-val", key);
    append(c, head, val, sub ? el("div", "kpi__sub", sub) : null);
    return c;
  }
  function renderKpis() {
    var s = state.summary || {};
    var total = num(s.total), verified = num(s.verified), approved = num(s.approved);
    var prev = R.lastKpi || {};
    clear(R.kpis);
    append(R.kpis,
      kpi("pending", "Pending", num(s.pending), "awaiting a person", "amber", "clock"),
      kpi("approved", "Approved", approved, "served to patients", "green", "shieldCheck"),
      kpi("rejected", "Rejected", num(s.rejected), "never served", "red", "x"),
      kpi("verified", "Verified", verified + "/" + total, "word for word, by code", "brand", "target")
    );

    var f = el("div", "funnel glass");
    var head = el("div", "funnel__head");
    append(head, el("span", "eyebrow", "Generate → Approve → Retrieve"));
    if (buildMeta()) f.title = "Items " + buildMeta();
    var steps = el("div", "funnel__steps");
    append(steps,
      funnelStep("Generated", total, "gen"),
      iconEl("arrow", "funnel__arrow", 14),
      funnelStep("Verified", verified, "ver"),
      iconEl("arrow", "funnel__arrow", 14),
      funnelStep("Approved", approved, "app"));
    var track = el("div", "funnel__track");
    track.setAttribute("role", "img");
    track.setAttribute("aria-label", "Generated " + total + ", verified " + verified + ", approved " + approved);
    var fv = el("span", "funnel__bar funnel__bar--ver");
    var fa = el("span", "funnel__bar funnel__bar--app");
    append(track, fv, fa);
    append(f, head, steps, track);
    R.kpis.appendChild(f);
    var pv = total ? (verified / total) * 100 : 0, pa = total ? (approved / total) * 100 : 0;
    var pvPrev = prev.pv === undefined ? 0 : prev.pv, paPrev = prev.pa === undefined ? 0 : prev.pa;
    fv.style.width = pvPrev + "%"; fa.style.width = paPrev + "%";
    requestAnimationFrame(function () { requestAnimationFrame(function () { fv.style.width = pv + "%"; fa.style.width = pa + "%"; }); });

    // Animate the numbers that changed since the last render
    var cur = { pending: num(s.pending), approved: approved, rejected: num(s.rejected), pv: pv, pa: pa };
    ["pending", "approved", "rejected"].forEach(function (k) {
      if (prev[k] !== undefined && prev[k] !== cur[k]) {
        var node = R.kpis.querySelector('[data-kpi="' + k + '"]');
        if (node) { node.classList.add("kpi--tick"); }
      }
    });
    R.lastKpi = cur;
  }
  function funnelStep(label, n, cls) {
    var s = el("span", "funnel__step funnel__step--" + cls);
    append(s, el("span", "funnel__n", n), el("span", "funnel__l", label));
    return s;
  }
  function buildMeta() {
    var parts = [];
    if (state.buildSeconds) parts.push("drafted in " + (state.buildSeconds >= 90 ? (state.buildSeconds / 60).toFixed(1) + " min" : Math.round(state.buildSeconds) + " s"));
    if (state.builtAt) parts.push("built " + fmtTime(state.builtAt));
    return parts.join(" · ");
  }

  /* ---------- List ---------- */
  function buildListChrome() {
    var head = el("div", "listpane__head");
    R.tabs = el("div", "tabs");
    R.tabs.setAttribute("role", "tablist");
    R.tabs.setAttribute("aria-label", "Filter by status");
    var row2 = el("div", "listpane__row");
    R.docSeg = el("div", "seg");
    R.docSeg.setAttribute("role", "group");
    R.docSeg.setAttribute("aria-label", "Filter by document");
    [["all", "All docs"], ["brochure", "Brochure"], ["medication_guide", "Med Guide"]].forEach(function (d) {
      var b = el("button", "seg__btn seg__btn--" + d[0], d[1]);
      b.type = "button";
      b.setAttribute("data-doc", d[0]);
      b.addEventListener("click", function () { state.filter.doc = d[0]; state.keepId = null; renderList(); });
      R.docSeg.appendChild(b);
    });
    var search = el("label", "search");
    var input = el("input", "search__input");
    input.type = "search";
    input.placeholder = "Search questions";
    input.setAttribute("aria-label", "Search questions");
    input.value = state.filter.q;
    input.addEventListener("input", function () { state.filter.q = input.value; renderList(); });
    append(search, iconEl("search", "search__icon", 15), input);
    append(row2, R.docSeg, search);
    append(head, R.tabs, row2);
    R.rows = el("div", "rows");
    R.rows.setAttribute("role", "list");
    R.rows.addEventListener("keydown", onRowsKey);
    append(R.listPane, head, R.rows);
  }

  function statusOf(it) { return it.status === "approved" || it.status === "rejected" ? it.status : "pending"; }
  function matchesQ(it, q) {
    if (!q) return true;
    q = q.toLowerCase();
    return str(it.question).toLowerCase().indexOf(q) !== -1 || str(it.id).toLowerCase().indexOf(q) !== -1 ||
      (Array.isArray(it.paraphrases) && it.paraphrases.some(function (p) { return str(p).toLowerCase().indexOf(q) !== -1; }));
  }
  function sortedItems() {
    var rank = { pending: 0, approved: 1, rejected: 2 };
    return state.items.map(function (it, i) { return { it: it, i: i }; }).sort(function (a, b) {
      var s = rank[statusOf(a.it)] - rank[statusOf(b.it)];
      if (s) return s;
      var d = (a.it.doc === "brochure" ? 0 : 1) - (b.it.doc === "brochure" ? 0 : 1);
      if (d) return d;
      return a.i - b.i;
    }).map(function (x) { return x.it; });
  }
  function visibleItems() {
    var f = state.filter;
    return sortedItems().filter(function (it) {
      var keep = it.id === state.keepId;
      if (f.doc !== "all" && it.doc !== f.doc) return false;
      if (!matchesQ(it, f.q.trim())) return false;
      if (f.status !== "all" && statusOf(it) !== f.status && !keep) return false;
      return true;
    });
  }

  function renderTabs() {
    clear(R.tabs);
    var counts = { pending: 0, approved: 0, rejected: 0, all: 0 };
    state.items.forEach(function (it) {
      if (state.filter.doc !== "all" && it.doc !== state.filter.doc) return;
      counts[statusOf(it)]++; counts.all++;
    });
    [["pending", "Pending"], ["approved", "Approved"], ["rejected", "Rejected"], ["all", "All"]].forEach(function (t) {
      var b = el("button", "tab tab--" + t[0]);
      b.type = "button";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", state.filter.status === t[0] ? "true" : "false");
      append(b, el("span", "", t[1]), el("span", "tab__n", counts[t[0]]));
      b.addEventListener("click", function () { state.filter.status = t[0]; state.keepId = null; renderList(); });
      R.tabs.appendChild(b);
    });
    var segs = R.docSeg.querySelectorAll(".seg__btn");
    for (var i = 0; i < segs.length; i++) segs[i].setAttribute("aria-pressed", segs[i].getAttribute("data-doc") === state.filter.doc ? "true" : "false");
  }

  function gateDots(it) {
    var g = el("span", "gates");
    var c = it.checks || {};
    var ok = c.found_in_source === true;
    var v = el("span", "gate " + (ok ? "gate--ok" : "gate--bad"));
    v.title = ok ? "Verified word for word" : "Not found word for word";
    v.innerHTML = icon(ok ? "check" : "x", 10, 3);
    g.appendChild(v);
    if (c.placeholder || (it.placeholders && it.placeholders.length)) {
      var p = el("span", "gate gate--bad gate--ph");
      p.title = "Draft placeholder";
      p.innerHTML = icon("warn", 10, 2.6);
      g.appendChild(p);
    }
    var verdict = str(it.judge && it.judge.verdict).toLowerCase();
    if (verdict) {
      var j = el("span", "gate gate--judge gate--" + (verdict === "pass" ? "ok" : verdict === "fail" ? "bad" : "warn"));
      j.title = "Gemini review: " + verdict;
      j.innerHTML = '<svg viewBox="0 0 24 24" width="10" height="10" aria-hidden="true"><path fill="currentColor" d="M12 1.5c1 5.6 4 9.4 10.5 10.5C16 13.1 13 16.9 12 22.5 11 16.9 8 13.1 1.5 12 8 10.9 11 7.1 12 1.5Z"/></svg>';
      g.appendChild(j);
    }
    var sr = el("span", "sr-only", (ok ? "verified" : "not verified") + (verdict ? ", Gemini " + verdict : ""));
    g.appendChild(sr);
    return g;
  }

  function renderList() {
    if (!state.items || !R.rows) return;
    renderTabs();
    var scroll = R.rows.scrollTop;
    clear(R.rows);
    var list = visibleItems();
    if (!list.length) {
      var empty = el("div", "rows__empty");
      append(empty, iconEl(state.filter.status === "pending" && !state.filter.q ? "shieldCheck" : "search", "rows__emptyicon", 26),
        el("strong", "", state.filter.status === "pending" && !state.filter.q ? "Queue clear" : "No items match"),
        el("span", "", state.filter.status === "pending" && !state.filter.q ? "Every drafted item has a human decision." : "Try another filter or search."));
      R.rows.appendChild(empty);
      return;
    }
    list.forEach(function (it) {
      var b = el("button", "row row--" + statusOf(it) + (it.id === state.selectedId ? " is-selected" : ""));
      b.type = "button";
      b.setAttribute("role", "listitem");
      b.setAttribute("data-id", it.id);
      if (it.id === state.selectedId) b.setAttribute("aria-current", "true");
      var top = el("span", "row__top");
      var dot = el("span", "sdot sdot--" + statusOf(it));
      dot.title = human(statusOf(it));
      append(top, dot, el("span", "row__q", it.question || it.id));
      var bottom = el("span", "row__meta");
      append(bottom, docTag(it.doc, true), el("span", "row__status", human(statusOf(it))), gateDots(it));
      append(b, top, bottom);
      b.addEventListener("click", function () { select(it.id); });
      R.rows.appendChild(b);
    });
    R.rows.scrollTop = scroll;
  }

  function skeletonRows(n) {
    var f = document.createDocumentFragment();
    for (var i = 0; i < n; i++) f.appendChild(el("div", "row row--skel shimmer"));
    return f;
  }

  function onRowsKey(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    var rows = Array.prototype.slice.call(R.rows.querySelectorAll(".row[data-id]"));
    if (!rows.length) return;
    var idx = rows.indexOf(document.activeElement);
    var next = idx === -1 ? 0 : Math.max(0, Math.min(rows.length - 1, idx + (e.key === "ArrowDown" ? 1 : -1)));
    e.preventDefault();
    rows[next].focus();
    select(rows[next].getAttribute("data-id"), true);
  }

  function select(id, keepFocus) {
    state.selectedId = id;
    setHashQuiet("#review/" + encodeURIComponent(id));
    var rows = R.rows.querySelectorAll(".row[data-id]");
    for (var i = 0; i < rows.length; i++) {
      var on = rows[i].getAttribute("data-id") === id;
      rows[i].classList.toggle("is-selected", on);
      if (on) rows[i].setAttribute("aria-current", "true"); else rows[i].removeAttribute("aria-current");
    }
    renderDetail();
    if (!keepFocus && window.innerWidth < 760 && R.detailPane) R.detailPane.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
  }

  function findItem(id) {
    if (!state.items) return null;
    for (var i = 0; i < state.items.length; i++) if (state.items[i].id === id) return state.items[i];
    return null;
  }

  /* ---------- Detail ---------- */
  function renderDetail(keepScroll) {
    if (!R.detailPane || !state.items) return;
    var it = findItem(state.selectedId);
    if (!it) {
      var first = visibleItems()[0];
      if (state.selectedId && !first) { /* nothing to show */ }
      if (first && !state.selectedId) {
        state.selectedId = first.id;
        it = first;
        var r = R.rows.querySelector('.row[data-id="' + cssEsc(first.id) + '"]');
        if (r) { r.classList.add("is-selected"); r.setAttribute("aria-current", "true"); }
      }
    }
    var prevScroll = R.scroll ? R.scroll.scrollTop : 0;
    clear(R.detailPane);
    if (!it) {
      var empty = el("div", "detail-empty");
      append(empty, iconEl("inbox", "detail-empty__icon", 34, 1.6),
        el("strong", "", state.selectedId ? "Item not found" : "Select an item"),
        el("span", "", state.selectedId ? "It may have been removed from the build." : "Pick a question from the queue to review it."));
      R.detailPane.appendChild(empty);
      R.bar = null;
      return;
    }

    R.scroll = el("div", "detail");
    R.scroll.setAttribute("tabindex", "-1");
    R.stampLayer = el("div", "stamp-layer");
    R.stampLayer.setAttribute("aria-hidden", "true");
    R.bar = el("div", "decision");
    R.bar.setAttribute("aria-label", "Decision");
    append(R.detailPane, R.scroll, R.stampLayer, R.bar);

    R.scroll.appendChild(detailHeader(it));
    R.scroll.appendChild(answerBlock(it));
    var grid = el("div", "detail__grid");
    append(grid, evidenceCard(it), gatesCard(it));
    R.scroll.appendChild(grid);
    renderDecisionBar();
    if (keepScroll) R.scroll.scrollTop = prevScroll;
    else R.scroll.scrollTop = 0;
  }
  function cssEsc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : String(s).replace(/["\\]/g, "\\$&"); }

  function detailHeader(it) {
    var h = el("header", "dhead");
    var top = el("div", "dhead__top");
    var idEl = el("code", "dhead__id", it.id);
    append(top, docTag(it.doc), statusPill(it), idEl);
    var title = el("h1", "dhead__q", it.question || it.id);
    var cite = it.citation || {};
    var tags = el("div", "dhead__tags");
    if (isStr(it.topic)) append(tags, tagChip("tag", human(it.topic)));
    var pages = [];
    if (cite.pdf_page !== undefined && cite.pdf_page !== null) pages.push("PDF p. " + cite.pdf_page);
    if (cite.printed_pages !== undefined && cite.printed_pages !== null && str(cite.printed_pages)) pages.push("printed p. " + cite.printed_pages);
    if (pages.length) append(tags, tagChip("doc", pages.join(" · ")));
    if (isStr(cite.section)) append(tags, tagChip("section", cite.section, "chip--section"));
    append(h, top, title, tags, reviewInfo(it), gateStrip(it));
    return h;
  }
  function tagChip(iconName, text, extra) {
    var c = el("span", "chip" + (extra ? " " + extra : ""));
    c.title = text;
    append(c, iconEl(iconName, "", 12, 2.2), el("span", "chip__t", text));
    return c;
  }
  function statusPill(it) {
    var s = statusOf(it);
    var map = { pending: ["pill--amber", "clock", "Pending review"], approved: ["pill--verified", "check", "Approved"], rejected: ["pill--red", "x", "Rejected"] };
    var p = el("span", "pill " + map[s][0]);
    append(p, iconEl(map[s][1], "", 12, 2.8), el("span", "", map[s][2]));
    return p;
  }
  function reviewInfo(it) {
    var r = it.review || {};
    if (statusOf(it) === "pending" || !isStr(r.reviewer)) return null;
    var box = el("div", "rinfo rinfo--" + statusOf(it));
    var who = el("span", "rinfo__who");
    append(who, el("span", "rinfo__avatar", initials(r.reviewer)),
      el("span", "", (statusOf(it) === "approved" ? "Approved by " : "Rejected by ")),
      el("strong", "", r.reviewer));
    append(box, who);
    if (isStr(r.ts)) append(box, el("span", "rinfo__sep", "·"), el("span", "", fmtTime(r.ts)));
    if (isStr(r.reason_code)) append(box, el("span", "rinfo__sep", "·"), el("code", "rinfo__code", r.reason_code));
    if (isStr(r.note)) append(box, el("span", "rinfo__note", "“" + r.note + "”"));
    return box;
  }

  /** Compact at-a-glance strip: the same gates as the card below. */
  function gateStrip(it) {
    var g = gateResults(it);
    var strip = el("div", "gstrip");
    g.forEach(function (x) {
      var c = el("span", "gchip gchip--" + x.state);
      append(c, iconEl(x.state === "pass" ? "check" : x.state === "fail" ? "x" : "warn", "", 11, 3), el("span", "", x.short));
      strip.appendChild(c);
    });
    return strip;
  }

  function gateResults(it) {
    var c = it.checks || {};
    var out = [];
    var found = c.found_in_source === true;
    out.push({ key: "found", state: found ? "pass" : "fail", short: found ? "Word for word" : "Not in source", title: "Found word for word in the source" });
    var ph = (Array.isArray(it.placeholders) && it.placeholders.length) || c.placeholder;
    out.push({ key: "ph", state: ph ? "fail" : "pass", short: ph ? "Placeholder" : "No placeholders", title: "No draft placeholders" });
    if (c.section_verified !== undefined && c.section_verified !== null) {
      out.push({ key: "sec", state: c.section_verified ? "pass" : "warn", short: c.section_verified ? "Section ok" : "Section unverified", title: "Section verified" });
    }
    var verdict = str(it.judge && it.judge.verdict).toLowerCase();
    out.push({ key: "judge", state: verdict === "pass" ? "pass" : verdict === "fail" ? "fail" : "warn", short: "Gemini " + (verdict || "n/a"), title: "Gemini review" });
    var st = c.retrieval_self_test || {};
    var passed = num(st.passed), total = num(st.total);
    out.push({ key: "rt", state: total && passed === total ? "pass" : passed === 0 && total ? "fail" : "warn", short: "Self-test " + passed + "/" + total, title: "Retrieval self-test" });
    return out;
  }

  function answerBlock(it) {
    var found = it.checks && it.checks.found_in_source === true;
    var hasPh = Array.isArray(it.placeholders) && it.placeholders.length > 0;
    var box = el("section", "answer" + (found ? " answer--ok" : " answer--bad") + (hasPh ? " answer--ph" : ""));
    var head = el("div", "answer__head");
    var title = el("h2", "answer__title");
    append(title, el("span", "", "Answer"), el("span", "answer__dot", "·"), el("span", "answer__wfw", "word for word"));
    var badge = el("span", "pill " + (found ? "pill--soft-green" : "pill--soft-red"));
    append(badge, iconEl(found ? "check" : "x", "", 12, 2.8), el("span", "", found ? "Verified in source" : "Not found in source"));
    append(head, title, badge);
    if (hasPh) {
      var phb = el("span", "pill pill--red pill--loud");
      append(phb, iconEl("warn", "", 12, 2.6), el("span", "", it.placeholders.length + " draft placeholder" + (it.placeholders.length > 1 ? "s" : "")));
      head.appendChild(phb);
    }
    var body = el("div", "answer__text");
    renderWithPlaceholders(body, str(it.answer));
    var paras = Array.isArray(it.paraphrases) ? it.paraphrases.filter(isStr) : [];
    var pbox = null;
    if (paras.length) {
      pbox = el("div", "paras");
      append(pbox, el("span", "paras__label", "Also matches"));
      paras.forEach(function (p) { pbox.appendChild(el("span", "para", p)); });
    }
    append(box, head, body, pbox);
    return box;
  }

  /** Text with every [placeholder] wrapped in a red span. Built from text nodes only. */
  function renderWithPlaceholders(node, text) {
    var last = 0, m;
    PLACEHOLDER_RE.lastIndex = 0;
    while ((m = PLACEHOLDER_RE.exec(text)) !== null) {
      if (m.index > last) node.appendChild(document.createTextNode(text.slice(last, m.index)));
      var ph = el("mark", "ph", m[0]);
      ph.title = "Draft placeholder: must be replaced before approval";
      node.appendChild(ph);
      last = m.index + m[0].length;
    }
    if (last < text.length) node.appendChild(document.createTextNode(text.slice(last)));
  }

  function evidenceCard(it) {
    var cite = it.citation || {};
    var found = it.checks && it.checks.found_in_source === true;
    var card = el("section", "card evidence");
    var head = el("div", "card__head");
    var t = el("h3", "card__title");
    append(t, iconEl("doc", "", 15), el("span", "", "Source evidence"));
    var full = el("button", "btn btn--sm btn--ghostline");
    full.type = "button";
    append(full, iconEl("expand", "", 13), el("span", "", "Full page"));
    full.addEventListener("click", function () { openPage(it, full); });
    append(head, t, full);

    var meta = el("p", "evidence__meta");
    append(meta, el("strong", "", cite.doc_title || docLabel(it.doc)));
    if (isStr(cite.section)) append(meta, " · ", el("span", "", cite.section));

    var paper = el("button", "paper" + (found ? "" : " paper--plain"));
    paper.type = "button";
    paper.setAttribute("aria-label", "Open the full source page");
    paper.addEventListener("click", function () { openPage(it, paper); });
    var skel = el("span", "paper__skel shimmer");
    var img = el("img", "paper__img");
    img.alt = found ? "Source passage, highlighted in the approved PDF" : "Source page (passage not verified, so nothing is highlighted)";
    img.decoding = "async";
    img.loading = "lazy";
    img.addEventListener("load", function () { paper.classList.add("is-loaded"); });
    img.addEventListener("error", function () {
      paper.classList.add("is-error");
      clear(paper);
      append(paper, iconEl("doc", "", 22, 1.6), el("span", "", "Source image unavailable"));
    });
    var src = itemImg("snippet", it.id);
    if (src) img.src = src;
    var fold = el("span", "paper__fold");
    var pageTag = el("span", "paper__tag", cite.pdf_page ? "p. " + (cite.printed_pages || cite.pdf_page) : docLabel(it.doc));
    append(paper, skel, img, fold, pageTag);

    var cap = el("p", "evidence__cap");
    append(cap, iconEl(found ? "check" : "info", "", 12, 2.6),
      el("span", "", found ? "Highlighted by code, straight from the approved PDF." : "Not verified, so nothing is highlighted on the page."));
    cap.classList.add(found ? "evidence__cap--ok" : "evidence__cap--bad");
    append(card, head, meta, paper, cap);
    return card;
  }

  function gatesCard(it) {
    var c = it.checks || {};
    var res = gateResults(it);
    var passed = res.filter(function (x) { return x.state === "pass"; }).length;
    var card = el("section", "card gatescard");
    var head = el("div", "card__head");
    var t = el("h3", "card__title");
    append(t, iconEl("shieldCheck", "", 15), el("span", "", "Quality gates"));
    var score = el("span", "gscore" + (passed === res.length ? " gscore--all" : ""), passed + " of " + res.length + " passed");
    append(head, t, score);
    var ul = el("ul", "checklist");

    res.forEach(function (g) {
      var li = el("li", "check check--" + g.state);
      var mark = el("span", "check__mark");
      mark.innerHTML = icon(g.state === "pass" ? "check" : g.state === "fail" ? "x" : "warn", 13, 3);
      var bodyEl = el("div", "check__body");
      var tl = el("div", "check__title");
      append(tl, el("span", "", g.title));
      bodyEl.appendChild(tl);

      if (g.key === "found") {
        var parts = Array.isArray(c.not_found_parts) ? c.not_found_parts.filter(isStr) : [];
        if (g.state === "pass") bodyEl.appendChild(el("p", "check__note", "Code matched every part of the answer in the PDF text."));
        else {
          bodyEl.appendChild(el("p", "check__note", parts.length ? "These parts were not found in the source:" : "The answer could not be matched in the source."));
          parts.forEach(function (p) { bodyEl.appendChild(el("blockquote", "check__quote", p.replace(/\s+/g, " ").trim())); });
        }
      } else if (g.key === "ph") {
        if (g.state === "pass") bodyEl.appendChild(el("p", "check__note", "No bracketed draft values in the text."));
        else {
          var loud = el("span", "pill pill--red pill--loud");
          append(loud, iconEl("warn", "", 12, 2.6), el("span", "", "Placeholder found"));
          tl.appendChild(loud);
          var list = el("div", "phlist");
          (it.placeholders || []).forEach(function (p) { list.appendChild(el("mark", "ph", p)); });
          bodyEl.appendChild(list);
          bodyEl.appendChild(el("p", "check__note", "Draft values from the brochure template. They must never reach a patient."));
        }
      } else if (g.key === "sec") {
        bodyEl.appendChild(el("p", "check__note", c.section_verified ? "The cited section heading was found on the page." : "The cited section heading could not be confirmed."));
      } else if (g.key === "judge") {
        var j = it.judge || {};
        var vp = el("span", "pill " + (g.state === "pass" ? "pill--soft-green" : g.state === "fail" ? "pill--soft-red" : "pill--soft-amber"), str(j.verdict || "n/a"));
        tl.appendChild(vp);
        if (isStr(j.reason)) bodyEl.appendChild(el("p", "check__note", j.reason));
        if (isStr(j.suggestion)) {
          var sug = el("p", "check__sug");
          append(sug, el("strong", "", "Suggestion "), el("span", "", j.suggestion));
          bodyEl.appendChild(sug);
        }
        var jc = j.checks && typeof j.checks === "object" ? j.checks : null;
        if (jc) {
          var bad = { placeholder: true, advice_risk: true, overlap: true };
          var flags = el("div", "jflags");
          Object.keys(jc).forEach(function (k) {
            if (typeof jc[k] !== "boolean") return;
            var good = bad[k] ? !jc[k] : jc[k];
            var f = el("span", "jflag " + (good ? "jflag--ok" : "jflag--bad"));
            var lbl = bad[k] ? (jc[k] ? human(k) : "no " + human(k)) : human(k);
            append(f, iconEl(good ? "check" : "x", "", 10, 3), el("span", "", lbl));
            flags.appendChild(f);
          });
          if (flags.firstChild) bodyEl.appendChild(flags);
        }
      } else if (g.key === "rt") {
        var st = c.retrieval_self_test || {};
        bodyEl.appendChild(el("p", "check__note", "Each paraphrase was searched; " + num(st.passed) + " of " + num(st.total) + " found this item first."));
        var misses = Array.isArray(st.misses) ? st.misses : [];
        if (misses.length) {
          var ml = el("ul", "misses");
          misses.forEach(function (m) {
            if (!m) return;
            var li2 = el("li", "");
            append(li2, el("span", "misses__q", "“" + str(m.paraphrase) + "”"), iconEl("arrow", "", 11),
              el("code", "", str(m.best_item)), el("span", "misses__s", typeof m.score === "number" ? m.score.toFixed(2) : ""));
            ml.appendChild(li2);
          });
          bodyEl.appendChild(ml);
        }
      }
      append(li, mark, bodyEl);
      ul.appendChild(li);
    });
    append(card, head, ul);
    return card;
  }

  /* ---------- Decision bar ---------- */
  function renderDecisionBar() {
    if (!R.bar) return;
    var it = findItem(state.selectedId);
    if (!it) return;
    var bar = R.bar;
    clear(bar);
    var hasName = !!state.reviewer;
    var block = str(it.approve_block);
    var s = statusOf(it);

    var left = el("div", "decision__approve");
    var approve = el("button", "btn btn--success btn--approve");
    approve.type = "button";
    append(approve, iconEl("check", "", 15, 2.8), el("span", "", s === "approved" ? "Approved" : "Approve"));
    approve.disabled = !!block || !hasName || state.busy || s === "approved";
    approve.addEventListener("click", function () { decide(it, "approved"); });
    left.appendChild(approve);
    if (block) {
      var lock = el("span", "blocked");
      append(lock, iconEl("lock", "blocked__icon", 14, 2.4), el("span", "", block));
      left.appendChild(lock);
      approve.setAttribute("aria-describedby", "approveBlock");
      lock.id = "approveBlock";
    } else if (!hasName) {
      left.appendChild(needNameHint("Enter your name under “Reviewing as” to decide"));
    } else if (s === "approved") {
      var done = el("span", "decided decided--ok");
      append(done, iconEl("shieldCheck", "", 14), el("span", "", "Live for patients · reject to withdraw"));
      left.appendChild(done);
    } else {
      var ready = el("span", "ready");
      append(ready, iconEl("unlock", "", 14, 2.4), el("span", "", "All blocking gates passed"));
      left.appendChild(ready);
    }

    var right = el("div", "decision__reject");
    var sel = el("select", "rsel");
    sel.setAttribute("aria-label", "Reason code");
    var opt0 = el("option", "", "Reason code…");
    opt0.value = "";
    sel.appendChild(opt0);
    var pre = "";
    if (s === "rejected" && it.review && isStr(it.review.reason_code)) pre = it.review.reason_code;
    else if ((it.placeholders && it.placeholders.length) || (it.checks && it.checks.placeholder)) pre = "PLACEHOLDER_TEXT";
    else if (!(it.checks && it.checks.found_in_source === true)) pre = "NOT_IN_SOURCE";
    state.rejectCodes.forEach(function (code) {
      var o = el("option", "", code);
      o.value = code;
      if (code === pre) o.selected = true;
      sel.appendChild(o);
    });
    var note = el("input", "rnote");
    note.type = "text";
    note.maxLength = 500;
    note.placeholder = "Note (optional)";
    note.setAttribute("aria-label", "Note (optional)");
    var reject = el("button", "btn btn--danger btn--reject");
    reject.type = "button";
    append(reject, iconEl("x", "", 14, 2.8), el("span", "", s === "rejected" ? "Reject again" : "Reject"));
    function sync() { reject.disabled = !hasName || state.busy || !sel.value; }
    sel.addEventListener("change", sync);
    sel.disabled = !hasName || state.busy;
    note.disabled = !hasName || state.busy;
    sync();
    reject.addEventListener("click", function () { decide(it, "rejected", sel.value, note.value); });
    note.addEventListener("keydown", function (e) { if (e.key === "Enter" && !reject.disabled) reject.click(); });
    append(right, sel, note, reject);

    append(bar, left, right);
    bar.classList.toggle("decision--locked", !hasName);
  }

  function decide(it, decision, code, note) {
    if (state.busy) return;
    if (!state.reviewer) { focusReviewer(); return; }
    state.busy = true;
    renderDecisionBar();
    R.detailPane.classList.add("is-busy");
    request("api/console/items/" + encodeURIComponent(it.id) + "/decision", {
      method: "POST",
      body: { decision: decision, reviewer: state.reviewer, reason_code: decision === "rejected" ? (code || "") : "", note: str(note).trim() }
    }).then(function (d) {
      state.busy = false;
      R.detailPane.classList.remove("is-busy");
      if (d && d.item && isStr(d.item.id)) {
        for (var i = 0; i < state.items.length; i++) if (state.items[i].id === d.item.id) state.items[i] = d.item;
      }
      if (d && d.summary) state.summary = d.summary;
      state.keepId = it.id;
      updateBadges();
      if (state.view !== "review") return;
      renderKpis();
      renderList();
      renderDetail(true);
      stamp(decision, state.reviewer);
      toast((decision === "approved" ? "Approved by " : "Rejected by ") + state.reviewer + (decision === "rejected" && code ? " · " + code : ""), "ok");
    }, function (e) {
      state.busy = false;
      R.detailPane.classList.remove("is-busy");
      renderDecisionBar();
      toast(e.message || "Couldn't save the decision", "err");
    });
  }

  function stamp(decision, name) {
    if (!R.stampLayer) return;
    clear(R.stampLayer);
    var ok = decision === "approved";
    var s = el("div", "stamp stamp--" + (ok ? "ok" : "bad"));
    var now = new Date();
    var hh = ("0" + now.getHours()).slice(-2) + ":" + ("0" + now.getMinutes()).slice(-2);
    append(s, el("span", "stamp__word", ok ? "APPROVED" : "REJECTED"), el("span", "stamp__by", name + " · " + now.getDate() + " " + MONTHS[now.getMonth()] + ", " + hh));
    R.stampLayer.appendChild(s);
    R.stampLayer.classList.add("is-on");
    R.detailPane.classList.remove("flash-ok", "flash-bad");
    void R.detailPane.offsetWidth;
    R.detailPane.classList.add(ok ? "flash-ok" : "flash-bad");
    setTimeout(function () { s.classList.add("stamp--out"); }, 1900);
    setTimeout(function () { if (s.parentNode) s.parentNode.removeChild(s); R.stampLayer && R.stampLayer.classList.remove("is-on"); }, 2500);
  }

  /* ---------- Full-page modal ---------- */
  function openPage(it, opener) {
    var cite = it.citation || {};
    state.lastFocus = opener || document.activeElement;
    els.modalTitle.textContent = cite.doc_title || docLabel(it.doc);
    var sub = [];
    if (cite.pdf_page) sub.push("PDF page " + cite.pdf_page);
    if (cite.printed_pages) sub.push("printed page " + cite.printed_pages);
    if (isStr(cite.section)) sub.push(cite.section);
    els.modalSub.textContent = sub.join(" · ");
    clear(els.modalBody);
    var frame = el("div", "modal__paper");
    var skel = el("div", "modal__skel shimmer");
    var img = el("img", "modal__img");
    img.alt = "Full source page" + (it.checks && it.checks.found_in_source === true ? ", with the answer passage highlighted" : "");
    img.addEventListener("load", function () { frame.classList.add("is-loaded"); });
    img.addEventListener("error", function () { clear(frame); frame.appendChild(el("p", "modal__err", "The page image could not be loaded.")); });
    var src = itemImg("page", it.id);
    if (src) img.src = src;
    append(frame, skel, img);
    els.modalBody.appendChild(frame);
    els.modal.hidden = false;
    document.body.classList.add("has-modal");
    requestAnimationFrame(function () { els.modal.classList.add("is-open"); els.modalClose.focus(); });
  }
  function closeModal() {
    if (els.modal.hidden) return;
    els.modal.classList.remove("is-open");
    els.modal.hidden = true;
    document.body.classList.remove("has-modal");
    clear(els.modalBody);
    if (state.lastFocus && typeof state.lastFocus.focus === "function") state.lastFocus.focus();
    state.lastFocus = null;
  }
  function trapFocus(e) {
    if (e.key !== "Tab" || els.modal.hidden) return;
    var f = els.modal.querySelectorAll("button, [href], input, select, [tabindex]:not([tabindex='-1'])");
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    else if (!els.modal.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  }

  /* =====================================================================
     Shared view chrome
     ===================================================================== */
  function viewHeader(eyebrow, title, sub, extra) {
    var h = el("header", "vhead");
    var t = el("div", "vhead__titles");
    append(t, el("span", "eyebrow", eyebrow), el("h1", "vhead__title", title), sub ? el("p", "vhead__sub", sub) : null);
    append(h, t, extra || null);
    return h;
  }
  function errorState(title, detail, retry) {
    var box = el("div", "estate estate--err");
    append(box, iconEl("warn", "estate__icon", 26), el("strong", "", title), el("span", "", detail || ""));
    if (retry) {
      var b = el("button", "btn btn--sm");
      b.type = "button";
      append(b, iconEl("refresh", "", 13), el("span", "", "Try again"));
      b.addEventListener("click", retry);
      box.appendChild(b);
    }
    return box;
  }
  function emptyState(iconName, title, text, tone) {
    var box = el("div", "estate" + (tone ? " estate--" + tone : ""));
    append(box, iconEl(iconName, "estate__icon", 28, 1.8), el("strong", "", title), el("span", "", text));
    return box;
  }

  /* =====================================================================
     Safety reports
     ===================================================================== */
  var RED_LABEL = { side_effect: "Side effect", urgent: "Urgent", pregnancy: "Pregnancy", complaint: "Product complaint" };
  var S = {};

  function showReports() {
    var v = els.view;
    clear(v);
    v.className = "view view--reports";
    S.head = el("div", "");
    S.list = el("div", "reports");
    append(v, S.head, S.list);
    if (state.reports) renderReports();
    else {
      renderReportsHead();
      for (var i = 0; i < 2; i++) S.list.appendChild(el("div", "report report--skel shimmer"));
    }
    loadReports(false);
  }
  function renderReportsHead() {
    clear(S.head);
    var open = state.reports ? state.reports.open : null;
    var count = el("div", "opencount" + (open ? " opencount--hot" : ""));
    append(count, el("span", "opencount__n", open === null ? "–" : open), el("span", "opencount__l", open === 1 ? "open report" : "open reports"));
    S.head.appendChild(viewHeader("Pharmacovigilance", "Safety reports", "Reports stay open until a named person acknowledges them.", count));
  }
  function renderReports() {
    if (state.view !== "reports" || !S.list) return;
    renderReportsHead();
    clear(S.list);
    if (state.reportsError && !state.reports) {
      S.list.appendChild(errorState("Couldn't load safety reports", state.reportsError, function () { loadReports(false); }));
      return;
    }
    var reports = (state.reports && state.reports.reports || []).slice();
    if (!reports.length) {
      S.list.appendChild(emptyState("shieldCheck", "No safety reports", "Red-zone chats appear here the moment they happen.", "ok"));
      state.seenReports = {};
      return;
    }
    reports = reports.map(function (r, i) { return { r: r, i: i }; }).sort(function (a, b) {
      var ao = a.r.report_status === "open" ? 0 : 1, bo = b.r.report_status === "open" ? 0 : 1;
      return ao - bo || a.i - b.i;
    }).map(function (x) { return x.r; });
    var firstRender = !state.seenReports;
    var seen = state.seenReports || {};
    var next = {};
    reports.forEach(function (r, i) {
      var card = reportCard(r);
      var key = str(r.id);
      if (firstRender) { card.classList.add("enter"); card.style.animationDelay = Math.min(i, 8) * 60 + "ms"; }
      else if (!seen[key]) card.classList.add("enter", "is-new");
      next[key] = true;
      S.list.appendChild(card);
    });
    state.seenReports = next;
  }
  function reportCard(r) {
    var open = r.report_status === "open";
    var card = el("article", "report " + (open ? "report--open" : "report--ack"));
    var main = el("div", "report__main");
    var top = el("div", "report__top");
    var type = el("span", "pill pill--red");
    append(type, iconEl("siren", "", 12, 2.4), el("span", "", RED_LABEL[r.red_type] || human(r.red_type || r.route || "Safety")));
    append(top, type, el("span", "report__time", fmtTime(r.ts)));
    if (isStr(r.session_id)) {
      var sid = el("code", "report__sid", "session " + r.session_id.slice(0, 8));
      top.appendChild(sid);
    }
    if (r.ae_form) {
      var aebadge = el("span", "pill pill--ae");
      append(aebadge, iconEl("clipboard", "", 12, 2), el("span", "", "AE Form Attached"));
      top.appendChild(aebadge);
    }
    var q = el("blockquote", "report__msg");
    append(q, iconEl("quote", "report__qicon", 26, 1.6), el("span", "", str(r.message)));
    var terms = Array.isArray(r.scan_terms) ? r.scan_terms.filter(isStr) : [];
    var chips = null;
    if (terms.length) {
      chips = el("div", "report__terms");
      append(chips, el("span", "report__termslabel", "Safety words"));
      terms.forEach(function (t) { chips.appendChild(el("span", "sterm", t)); });
    }
    var aeBox = null;
    if (r.ae_form) {
      var ae = r.ae_form;
      aeBox = el("div", "report__ae");
      var aeHead = el("div", "report__aehead");
      append(aeHead, iconEl("clipboard", "report__aeicon", 14), el("span", "report__aetitle", "Patient Adverse Event Intake Form"));
      if (ae.submitted_at) aeHead.appendChild(el("span", "report__aetime", "Submitted " + fmtTime(ae.submitted_at)));

      var aelist = el("div", "report__aegrid");
      var addF = function(lbl, val, cls) {
        if (!val) return;
        var f = el("div", "report__aefield");
        append(f, el("span", "report__aelabel", lbl + ": "), el("span", "report__aeval" + (cls ? " " + cls : ""), val));
        aelist.appendChild(f);
      };
      var reporterStr = (ae.patient_name ? ae.patient_name + " · " : "") + (ae.reporter_type || "Patient");
      addF("Reporter", reporterStr);
      addF("Onset date", ae.onset_date);
      addF("Severity", ae.severity, "sterm sterm--sev");
      addF("Doctor contacted", ae.doctor_contacted);
      if (ae.contact) addF("Contact", ae.contact);
      if (ae.product_pen_issue) addF("Pen / Lot issue", ae.product_pen_issue);

      var aedesc = el("div", "report__aedesc");
      append(aedesc, el("span", "report__aelabel", "Event description: "), el("span", "report__aetext", ae.description || ""));

      append(aeBox, aeHead, aelist, aedesc);
    }
    var foot = el("div", "report__foot");
    var bits = [];
    if (isStr(r.zone)) bits.push("zone " + r.zone);
    if (isStr(r.route)) bits.push(human(r.route));
    if (typeof r.latency_ms === "number") bits.push(Math.round(r.latency_ms) + " ms");
    append(foot, el("span", "", "Escalated automatically · " + bits.join(" · ")));
    if (isStr(r.model_reason)) append(foot, el("span", "report__reason", "Gemini: " + r.model_reason));
    append(main, top, q, chips, aeBox, foot);

    var side = el("div", "report__side");
    if (open) {
      var st = el("span", "rstatus rstatus--open");
      append(st, el("span", "rdot", ""), el("span", "", "Open · awaiting a person"));
      var ack = el("button", "btn btn--ack");
      ack.type = "button";
      append(ack, iconEl("check", "", 15, 2.8), el("span", "", "Acknowledge"));
      ack.disabled = !state.reviewer;
      ack.addEventListener("click", function () { acknowledge(r, ack, card); });
      append(side, st, ack);
      if (!state.reviewer) side.appendChild(needNameHint("Enter your name to acknowledge"));
      else {
        var as = el("span", "report__as");
        append(as, el("span", "", "as "), el("strong", "", state.reviewer));
        as.lastChild.setAttribute("data-name-bound", "1");
        side.appendChild(as);
      }
    } else {
      var done = el("span", "rstatus rstatus--ack");
      append(done, iconEl("shieldCheck", "", 16, 2.2), el("span", "rstatus__t", "Acknowledged"));
      var by = el("span", "rstatus__by");
      append(by, el("span", "", "by "), el("strong", "", str(r.ack_by) || "unknown"), el("span", "", r.ack_ts ? " · " + fmtTime(r.ack_ts) : ""));
      append(side, done, by);
    }
    append(card, main, side);
    return card;
  }
  function acknowledge(r, btn, card) {
    if (!state.reviewer) { focusReviewer(); return; }
    btn.disabled = true;
    btn.classList.add("is-loading");
    request("api/console/reports/ack", { method: "POST", body: { id: str(r.id), reviewer: state.reviewer } }).then(function (d) {
      if (state.reports) {
        state.reports.reports = state.reports.reports.map(function (x) { return x.id === r.id ? (d && d.id ? d : x) : x; });
        state.reports.open = state.reports.reports.filter(function (x) { return x.report_status === "open"; }).length;
      }
      updateBadges();
      toast("Report acknowledged by " + state.reviewer, "ok");
      card.classList.add("report--acking");
      setTimeout(function () { renderReports(); }, reducedMotion() ? 0 : 450);
    }, function (e) {
      btn.disabled = false;
      btn.classList.remove("is-loading");
      toast(e.message || "Couldn't acknowledge the report", "err");
    });
  }

  /* =====================================================================
     Content gaps
     ===================================================================== */
  var G = {};
  function showGaps() {
    var v = els.view;
    clear(v);
    v.className = "view view--gaps";
    var tag = el("span", "aitag");
    append(tag, iconEl("gemini", "", 12, 2.2), el("span", "", "AI-generated · internal analytics, never shown to patients"));
    v.appendChild(viewHeader("Content team", "Content gaps", "Questions OnLabel could not answer from approved text, grouped into themes to write next.", tag));

    var hero = el("section", "gaphero glass");
    G.stat = el("div", "gaphero__stat");
    var act = el("div", "gaphero__act");
    G.btn = el("button", "btn btn--primary btn--lg");
    G.btn.type = "button";
    append(G.btn, iconEl("sparkle", "", 16, 2), el("span", "", "Find content gaps"));
    G.btn.addEventListener("click", findGaps);
    append(act, G.btn, el("span", "gaphero__cap", "Gemini groups unanswered questions into themes"));
    append(hero, G.stat, act);
    G.results = el("div", "gapresults");
    append(v, hero, G.results);
    renderGapsStat();
    renderGapsResults();
    loadActivity(false);
  }
  function renderGapsStat() {
    if (!G.stat || state.view !== "gaps") return;
    clear(G.stat);
    var n = state.activity ? state.activity.unanswered : null;
    append(G.stat, el("span", "gaphero__n", n === null ? (state.activityError ? "!" : "–") : n),
      el("span", "gaphero__l", "unanswered questions logged"),
      el("span", "gaphero__s", state.activityError && n === null ? state.activityError : "No answer or only related content, from real chats"));
  }
  function renderGapsResults() {
    if (!G.results) return;
    clear(G.results);
    var g = state.gaps;
    if (!g) return;
    if (g.loading) {
      var load = el("div", "gaploading");
      append(load, el("div", "gaploading__bar"), el("span", "", "Gemini is reading the unanswered questions…"));
      G.results.appendChild(load);
      var grid = el("div", "themes");
      for (var i = 0; i < 3; i++) grid.appendChild(el("div", "theme theme--skel shimmer"));
      G.results.appendChild(grid);
      return;
    }
    if (g.error) {
      G.results.appendChild(errorState("Couldn't find content gaps", g.error, findGaps));
      return;
    }
    var d = g.data || {};
    var themes = Array.isArray(d.themes) ? d.themes.filter(function (t) { return t && typeof t === "object"; }) : [];
    if (!num(d.count) || !themes.length) {
      G.results.appendChild(emptyState("shieldCheck", num(d.count) ? "No themes found" : "No content gaps yet",
        num(d.count) ? "Gemini didn't find any themes in the unanswered questions." : "Every logged question had an approved answer. Ask the chat something it can't answer to see a gap here.", "ok"));
      return;
    }
    var sum = el("p", "gapsum");
    append(sum, el("strong", "", themes.length + " theme" + (themes.length === 1 ? "" : "s")), el("span", "", " from " + num(d.count) + " unanswered question" + (num(d.count) === 1 ? "" : "s")));
    G.results.appendChild(sum);
    var grid2 = el("div", "themes");
    themes.forEach(function (t, i) {
      var c = el("article", "theme glass enter");
      c.style.animationDelay = i * 90 + "ms";
      var head = el("div", "theme__head");
      append(head, el("h3", "theme__label", str(t.label) || "Untitled theme"),
        el("span", "theme__count", num(t.count) + (num(t.count) === 1 ? " question" : " questions")));
      c.appendChild(head);
      var ex = Array.isArray(t.example_messages) ? t.example_messages.filter(isStr).slice(0, 4) : [];
      if (ex.length) {
        var qs = el("div", "theme__examples");
        ex.forEach(function (m) {
          var q = el("blockquote", "theme__q");
          append(q, iconEl("chat", "", 13, 2), el("span", "", m));
          qs.appendChild(q);
        });
        c.appendChild(qs);
      }
      if (isStr(t.suggested_content)) {
        var s = el("div", "theme__sug");
        var sh = el("span", "theme__sughead");
        append(sh, iconEl("bulb", "", 14, 2), el("span", "", "Suggested content"));
        append(s, sh, el("p", "", t.suggested_content));
        c.appendChild(s);
      }
      grid2.appendChild(c);
    });
    G.results.appendChild(grid2);
  }
  function findGaps() {
    if (state.gaps && state.gaps.loading) return;
    state.gaps = { loading: true };
    G.btn.disabled = true;
    G.btn.classList.add("is-loading");
    renderGapsResults();
    request("api/console/gaps", { method: "POST", body: {} }).then(function (d) {
      state.gaps = { data: d || {} };
    }, function (e) {
      state.gaps = { error: e.message };
    }).then(function () {
      if (G.btn) { G.btn.disabled = false; G.btn.classList.remove("is-loading"); }
      if (state.view === "gaps") renderGapsResults();
    });
  }

  /* =====================================================================
     Activity log
     ===================================================================== */
  var ROUTES = {
    answer: ["Approved answer", "ok"],
    related: ["Related info", "cyan"],
    advice: ["Advice declined", "amber"],
    red_urgent: ["Safety · urgent", "red"],
    red_side_effect: ["Safety · side effect", "red"],
    red_pregnancy: ["Safety · pregnancy", "red"],
    red_complaint: ["Safety · complaint", "red"],
    no_answer: ["No answer", "grey"],
    off_topic: ["Off-topic", "grey"],
    error: ["Error", "dark"]
  };
  var A = {};
  function showActivity() {
    var v = els.view;
    clear(v);
    v.className = "view view--activity";
    A.head = el("div", "");
    A.body = el("div", "");
    append(v, A.head, A.body);
    A.head.appendChild(viewHeader("Audit trail", "Activity log", "Every patient chat turn: what was asked, how it was routed, and proof the reply was served word for word."));
    if (state.activity) renderActivity();
    else A.body.appendChild(el("div", "table-skel shimmer"));
    loadActivity(false);
  }
  function renderActivity() {
    if (state.view !== "activity" || !A.body) return;
    clear(A.body);
    if (state.activityError && !state.activity) {
      A.body.appendChild(errorState("Couldn't load the activity log", state.activityError, function () { loadActivity(false); }));
      return;
    }
    var turns = state.activity ? state.activity.turns : [];
    var answered = 0, safety = 0, vfail = 0;
    turns.forEach(function (t) {
      if (t.route === "answer") answered++;
      if (str(t.route).indexOf("red_") === 0 || t.zone === "red") safety++;
      if (t.verbatim_ok === false) vfail++;
    });
    var stats = el("div", "astats");
    append(stats,
      astat(turns.length, "Chat turns", "brand", "chat"),
      astat(answered, "Approved answers", "green", "check"),
      astat(safety, "Safety escalations", "red", "siren"),
      astat(vfail, "Verbatim failures", vfail ? "red" : "proud", "shieldCheck"));
    A.body.appendChild(stats);
    if (!turns.length) {
      A.body.appendChild(emptyState("chat", "No chat turns yet", "Turns from the patient chat show up here every 10 seconds."));
      state.seenTurns = {};
      return;
    }
    var wrap = el("div", "tablewrap glass");
    var table = el("table", "atable");
    var thead = el("thead", "");
    var hr = el("tr", "");
    ["Time", "Question", "Outcome", "Zone", "Matched item", "Confidence", "Latency", "Verbatim"].forEach(function (h, i) {
      var th = el("th", i >= 5 ? "num" : "", h);
      th.scope = "col";
      hr.appendChild(th);
    });
    thead.appendChild(hr);
    var tb = el("tbody", "");
    var first = !state.seenTurns;
    var seen = state.seenTurns || {};
    var next = {};
    turns.forEach(function (t) {
      var key = str(t.ts) + "|" + str(t.message);
      var tr = el("tr", !first && !seen[key] ? "is-new" : "");
      next[key] = true;
      var r = ROUTES[t.route] || [human(t.route) || "Unknown", "grey"];
      var tdT = el("td", "atime", fmtClock(t.ts));
      tdT.title = fmtTime(t.ts);
      var tdQ = el("td", "aq");
      var qspan = el("span", "aq__t", str(t.message));
      qspan.title = str(t.message);
      tdQ.appendChild(qspan);
      var tdO = el("td", "");
      tdO.appendChild(el("span", "opill opill--" + r[1], r[0]));
      var tdZ = el("td", "");
      var z = el("span", "zone zone--" + (["green", "yellow", "red", "off_topic", "error"].indexOf(t.zone) !== -1 ? t.zone : "none"));
      append(z, el("span", "zone__dot", ""), el("span", "", human(t.zone) || "—"));
      tdZ.appendChild(z);
      var tdM = el("td", "amatch");
      if (isStr(t.matched_id)) {
        var a = el("a", "amatch__a", t.matched_id);
        a.href = "#review/" + encodeURIComponent(t.matched_id);
        a.title = "Open " + t.matched_id + " in the review queue";
        tdM.appendChild(a);
      } else tdM.appendChild(el("span", "muted", "—"));
      var tdC = el("td", "num", typeof t.score === "number" ? Math.round(t.score * 100) + "%" : "—");
      var tdL = el("td", "num", typeof t.latency_ms === "number" ? (t.latency_ms >= 1000 ? (t.latency_ms / 1000).toFixed(1) + " s" : Math.round(t.latency_ms) + " ms") : "—");
      var tdV = el("td", "num");
      var vb = el("span", "vb " + (t.verbatim_ok === true ? "vb--ok" : t.verbatim_ok === false ? "vb--bad" : "vb--na"));
      if (t.verbatim_ok === true || t.verbatim_ok === false) {
        vb.innerHTML = icon(t.verbatim_ok ? "check" : "x", 12, 3);
        vb.setAttribute("aria-label", t.verbatim_ok ? "verbatim" : "not verbatim");
      } else vb.textContent = "—";
      tdV.appendChild(vb);
      append(tr, tdT, tdQ, tdO, tdZ, tdM, tdC, tdL, tdV);
      tb.appendChild(tr);
    });
    state.seenTurns = next;
    append(table, thead, tb);
    wrap.appendChild(table);
    A.body.appendChild(wrap);
  }
  function astat(n, label, tone, iconName) {
    var c = el("div", "astat glass astat--" + tone);
    append(c, el("span", "astat__l", label), el("span", "astat__n", n));
    return c;
  }

  /* =====================================================================
     Init
     ===================================================================== */
  function decorateIcons() {
    var nodes = document.querySelectorAll("[data-icon]");
    for (var i = 0; i < nodes.length; i++) nodes[i].innerHTML = icon(nodes[i].getAttribute("data-icon"), 18, 2); // static
  }
  function loadMeta() {
    request("api/meta").then(function (m) {
      if (m && isStr(m.banner)) els.banner.textContent = m.banner;
    }, function () { /* keep the static fallback */ });
  }

  function init() {
    decorateIcons();
    els.reviewer.value = state.reviewer;
    renderWho();
    els.reviewer.addEventListener("input", onReviewerInput);
    els.reviewer.addEventListener("keydown", function (e) { if (e.key === "Enter") els.reviewer.blur(); });
    els.modal.addEventListener("click", function (e) { if (e.target && e.target.getAttribute && e.target.getAttribute("data-close")) closeModal(); });
    els.modalClose.addEventListener("click", closeModal);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !els.modal.hidden) { e.preventDefault(); closeModal(); }
      trapFocus(e);
    });
    window.addEventListener("hashchange", route);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) poll(); });
    loadMeta();
    route();
    Promise.all([loadReports(true), state.items ? Promise.resolve(true) : (state.view === "review" ? Promise.resolve(true) : loadItems())])
      .then(function (r) { markSynced(r.every(Boolean)); });
    setInterval(poll, POLL_MS);
  }

  init();
})();
