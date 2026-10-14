/* =====================================================================
   OnLabel: patient chat UI (vanilla JS, no build step)

   Rendering rule: every value that comes from the server is written with
   textContent (or as an attribute on an <img>/<a> after URL checks).
   innerHTML is only ever used for the static SVG icon strings below.
   All URLs are relative (the app runs behind path-prefix proxies).
   ===================================================================== */
(function () {
  "use strict";

  /* ---------- Static fallbacks (used only if api/meta is unavailable) ---------- */
  var FALLBACK_BANNER =
    "Prototype for a hackathon demo — not for patient use. Uses public KESIMPTA information only. " +
    "Reports entered here are not sent to Novartis.";
  var FALLBACK_ERROR =
    "Sorry, I can't answer right now. Please try again in a moment. " +
    "If you're having side effects or need medical help, contact your healthcare provider.";

  var REQUEST_TIMEOUT_MS = 30000;
  var MAX_LEN = 1000;
  var BULLET = "• ";

  /* ---------- Allow-lists ---------- */
  var ZONES = ["green", "yellow", "red", "off_topic", "error"];
  var RED_TYPES = ["urgent", "side_effect", "pregnancy", "complaint"];
  var INTENTS = [
    "about", "how_to_use", "dosing_schedule", "missed_dose", "storage_travel",
    "side_effects", "serious_warnings", "pregnancy_breastfeeding", "vaccines",
    "who_should_not_use", "ingredients", "support_cost", "comparison", "other", "error"
  ];

  /* ---------- Static SVG icons (only static strings go through innerHTML) ---------- */
  var SVG_OPEN = '<svg viewBox="0 0 24 24" width="WS" height="WS" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">';
  var P = {
    mark: '<path d="M12 2.8 4.5 5.6v5.7c0 4.6 3.1 8.6 7.5 9.9 4.4-1.3 7.5-5.3 7.5-9.9V5.6L12 2.8Z"/><path d="m8.6 12.1 2.4 2.4 4.6-4.8"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    external: '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/>',
    arrow: '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>',
    log: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 11h6"/><path d="M9 15h4"/>',
    image: '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    clipboard: '<path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1"/>',
    send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>'
  };
  function icon(name, size) { return SVG_OPEN.replace(/WS/g, String(size || 16)) + P[name] + "</svg>"; }

  /* ---------- Reply kind → status pill (UI chrome only; reply wording comes from the server) ---------- */
  var KINDS = {
    answer:          { label: "Approved answer",         tone: "green" },
    related:         { label: "Related approved answer", tone: "violet" },
    advice:          { label: "Advice declined",         tone: "amber" },
    red_urgent:      { label: "Safety message",          tone: "red", sub: "Urgent" },
    red_side_effect: { label: "Safety message",          tone: "red", sub: "Possible side effect" },
    red_pregnancy:   { label: "Safety message",          tone: "red", sub: "Pregnancy" },
    red_complaint:   { label: "Safety message",          tone: "red", sub: "Product issue" },
    no_answer:       { label: "No approved answer",      tone: "grey" },
    off_topic:       { label: "Off-topic",               tone: "grey" },
    error:           { label: "Unavailable",             tone: "grey" }
  };
  function isRedKind(k) { return k.indexOf("red_") === 0; }
  function isMatchKind(k) { return k === "answer" || k === "related"; }


  /* ---------- DOM ---------- */
  var $ = function (id) { return document.getElementById(id); };
  var els = {
    banner: $("bannerText"),
    scroller: $("scroller"),
    hero: $("hero"),
    starters: $("starters"),
    messages: $("messages"),
    form: $("composerForm"),
    input: $("input"),
    send: $("sendBtn"),
    whyToggle: $("whyToggle"),
    newChat: $("newChatBtn"),
    isiBtn: $("isiBtn"),
    backdrop: $("backdrop"),
    drawer: $("drawer"),
    drawerTitle: $("drawerTitle"),
    drawerSubtitle: $("drawerSubtitle"),
    drawerBody: $("drawerBody"),
    drawerClose: $("drawerClose")
  };

  /* ---------- State ---------- */
  var state = {
    meta: { banner: FALLBACK_BANNER, safety_panel: "", starters: [], error_text: FALLBACK_ERROR },
    busy: false,
    sessionId: getSessionId(),
    lastFocus: null
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

  function append(parent) {
    for (var i = 1; i < arguments.length; i++) {
      if (arguments[i]) parent.appendChild(arguments[i]);
    }
    return parent;
  }

  function iconEl(name, size, className) {
    var span = el("span", "ico" + (className ? " " + className : ""));
    span.innerHTML = icon(name, size); // static SVG string only
    span.setAttribute("aria-hidden", "true");
    return span;
  }

  function isStr(v) { return typeof v === "string" && v.length > 0; }
  function isNum(v) { return typeof v === "number" && isFinite(v); }

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") return window.crypto.randomUUID();
    var bytes = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return Array.prototype.map.call(bytes, function (b) { return ("0" + b.toString(16)).slice(-2); }).join("");
  }

  function getSessionId(forceNew) {
    var key = "onlabel_session_id";
    try {
      var id = forceNew ? null : sessionStorage.getItem(key);
      if (!id) { id = randomId(); sessionStorage.setItem(key, id); }
      return id;
    } catch (e) {
      return randomId();
    }
  }

  /** Only same-origin paths, relative api/ paths or https URLs may become an img src / link href. */
  function safeUrl(u) {
    if (typeof u !== "string" || !u) return null;
    if (/[\s\\]/.test(u)) return null;
    if (/^\/(?!\/)/.test(u)) return u;
    if (/^api\/[\w.\-\/%?=&]+$/.test(u)) return u;
    if (/^https:\/\//i.test(u)) return u;
    return null;
  }

  function formatLatency(ms) {
    if (!isNum(ms)) return null;
    return ms < 1000 ? Math.round(ms) + " ms" : (ms / 1000).toFixed(1) + " s";
  }

  function allow(value, list) {
    return typeof value === "string" && list.indexOf(value) !== -1 ? value : null;
  }

  function human(v) { return v.replace(/_/g, " "); }

  function kindOf(data) {
    return data && Object.prototype.hasOwnProperty.call(KINDS, data.kind) ? data.kind : "error";
  }

  var squash = function (s) { return s.replace(/\s+/g, ""); };

  /* =====================================================================
     Scrolling
     ===================================================================== */
  /** Bring a new message into view; for a reply, keep its question visible when both do not fit. */
  function reveal(node) {
    var s = els.scroller;
    requestAnimationFrame(function () {
      if (!node) return;
      var anchor = node;
      var prev = node.previousElementSibling;
      if (node.classList.contains("msg--bot") && prev && prev.classList.contains("msg--user")) anchor = prev;
      var span = node.offsetTop + node.offsetHeight - anchor.offsetTop;
      if (span > s.clientHeight - 150) {
        s.scrollTo({ top: Math.max(0, anchor.offsetTop - 16), behavior: "smooth" });
      } else {
        s.scrollTo({ top: s.scrollHeight, behavior: "smooth" });
      }
    });
  }

  /* =====================================================================
     Text blocks: paragraphs, and lines starting with "• " as a real list.
     The rendered text is the same characters; only the "• " marker becomes
     the list bullet. Returns { node, text } where text is what was rendered.
     ===================================================================== */
  function textBlocks(text, className) {
    var frag = document.createDocumentFragment();
    var rendered = [];
    var para = [];
    var list = null;
    function flushPara() {
      if (!para.length) return;
      var t = para.join("\n").trim();
      if (t) { frag.appendChild(el("p", className, t)); rendered.push(t); }
      para = [];
    }
    function flushList() { list = null; }
    text.split("\n").forEach(function (line) {
      var trimmed = line.replace(/^\s+/, "");
      if (trimmed.indexOf(BULLET) === 0) {
        flushPara();
        if (!list) { list = el("ul", className + " reply-list"); frag.appendChild(list); }
        var item = trimmed.slice(BULLET.length).trim();
        list.appendChild(el("li", "", item));
        rendered.push(BULLET + item);
      } else if (!trimmed.trim()) {
        flushPara(); flushList();
      } else {
        flushList();
        para.push(line);
      }
    });
    flushPara();
    return { node: frag, text: rendered.join("") };
  }

  /* =====================================================================
     Messages
     ===================================================================== */
  function hideHero() { els.hero.hidden = true; }

  function addUserMessage(text) {
    var row = el("div", "msg msg--user");
    var bubble = el("div", "bubble-user");
    bubble.appendChild(el("span", "sr-only", "You said: "));
    bubble.appendChild(document.createTextNode(text));
    row.appendChild(bubble);
    els.messages.appendChild(row);
    reveal(row);
  }

  function avatar() {
    var a = el("div", "avatar");
    a.innerHTML = icon("mark", 15); // static
    a.setAttribute("aria-hidden", "true");
    return a;
  }

  function addTyping() {
    var row = el("div", "msg msg--bot msg--loading");
    row.appendChild(avatar());
    var main = el("div", "bot");
    main.setAttribute("role", "status");
    main.appendChild(el("span", "loading__text", "Checking approved answers…"));
    var lines = el("div", "loading__lines");
    lines.setAttribute("aria-hidden", "true");
    ["92%", "100%", "64%"].forEach(function (w) {
      var l = el("span", "shimmer");
      l.style.width = w;
      lines.appendChild(l);
    });
    main.appendChild(lines);
    row.appendChild(main);
    els.messages.appendChild(row);
    reveal(row);
    return row;
  }

  function statusPill(kindKey) {
    var k = KINDS[kindKey];
    var pill = el("span", "status status--" + k.tone);
    pill.appendChild(el("span", "status__dot"));
    pill.appendChild(el("span", "status__label", k.label));
    if (k.sub) pill.appendChild(el("span", "status__sub", k.sub));
    return pill;
  }

  function buildAEFormCard(data) {
    var card = el("div", "ae-card");
    var header = el("div", "ae-card__header");
    var titleRow = el("div", "ae-card__title-row");
    append(titleRow, iconEl("clipboard", 15, "ae-card__icon"), el("span", "ae-card__title", "Report Adverse Event (AE) · Demo Form"), el("span", "ae-card__pill", "Intake Form"));
    var sub = el("p", "ae-card__sub", "Record details for pharmacovigilance safety follow-up. For medical emergencies, call 911 or your doctor immediately.");
    append(header, titleRow, sub);

    var form = el("form", "ae-form");

    // Row 1: Reporter role, Patient name
    var row1 = el("div", "ae-grid ae-grid--2");
    
    var fRole = el("div", "ae-field");
    var lRole = el("label", "ae-label", "Reporter role");
    var selRole = el("select", "ae-select");
    [["Patient", "Patient"], ["Caregiver", "Caregiver / Family"], ["HCP", "Healthcare Provider"]].forEach(function (opt) {
      var o = el("option", "", opt[1]);
      o.value = opt[0];
      selRole.appendChild(o);
    });
    append(fRole, lRole, selRole);

    var fName = el("div", "ae-field");
    var lName = el("label", "ae-label");
    append(lName, el("span", "", "Patient name / initials "), el("span", "ae-muted", "(optional)"));
    var inName = el("input", "ae-input");
    inName.type = "text";
    inName.placeholder = "e.g. Jane D.";
    append(fName, lName, inName);
    append(row1, fRole, fName);

    // Row 2: When did symptoms start?, Severity level
    var row2 = el("div", "ae-grid ae-grid--2");
    
    var fDate = el("div", "ae-field");
    var lDate = el("label", "ae-label", "When did symptoms start?");
    var inDate = el("input", "ae-input");
    inDate.type = "date";
    try {
      inDate.value = new Date().toISOString().slice(0, 10);
    } catch (e) {}
    append(fDate, lDate, inDate);

    var fSev = el("div", "ae-field");
    var lSev = el("label", "ae-label", "Severity level");
    var selSev = el("select", "ae-select");
    [
      ["Mild", "Mild (bothersome, daily life unaffected)"],
      ["Moderate", "Moderate (interfered with daily activities)"],
      ["Severe", "Severe (prevented daily activities / sought care)"],
      ["Urgent / Emergency", "Urgent / Emergency (sought immediate care)"]
    ].forEach(function (opt, idx) {
      var o = el("option", "", opt[1]);
      o.value = opt[0];
      if (idx === 1) o.selected = true;
      selSev.appendChild(o);
    });
    append(fSev, lSev, selSev);
    append(row2, fDate, fSev);

    // Row 3: HCP contacted?, Contact phone/email
    var row3 = el("div", "ae-grid ae-grid--2");
    
    var fHcp = el("div", "ae-field");
    var lHcp = el("label", "ae-label", "Doctor / clinic contacted?");
    var selHcp = el("select", "ae-select");
    [
      ["No", "No"],
      ["Yes, called doctor", "Yes, called doctor / clinic"],
      ["Yes, visited ER / Urgent Care", "Yes, visited ER / Urgent Care"],
      ["Planning to contact", "Planning to contact today"]
    ].forEach(function (opt) {
      var o = el("option", "", opt[1]);
      o.value = opt[0];
      selHcp.appendChild(o);
    });
    append(fHcp, lHcp, selHcp);

    var fContact = el("div", "ae-field");
    var lContact = el("label", "ae-label");
    append(lContact, el("span", "", "Contact phone or email "), el("span", "ae-muted", "(optional)"));
    var inContact = el("input", "ae-input");
    inContact.type = "text";
    inContact.placeholder = "e.g. jane@example.com";
    append(fContact, lContact, inContact);
    append(row3, fHcp, fContact);

    // Row 4: Event description (required)
    var fDesc = el("div", "ae-field");
    var lDesc = el("label", "ae-label");
    append(lDesc, el("span", "", "Symptom / event description "), el("span", "ae-req", "*"));
    var txtDesc = el("textarea", "ae-textarea");
    txtDesc.rows = 3;
    txtDesc.placeholder = "Describe what happened or what you experienced...";
    if (data && data.user_message) {
      txtDesc.value = data.user_message;
    }
    append(fDesc, lDesc, txtDesc);

    // Row 5: Pen / Lot note (optional)
    var fPen = el("div", "ae-field");
    var lPen = el("label", "ae-label");
    append(lPen, el("span", "", "Sensoready pen / lot issue "), el("span", "ae-muted", "(optional)"));
    var inPen = el("input", "ae-input");
    inPen.type = "text";
    inPen.placeholder = "e.g. Pen cracked / lot # if known";
    append(fPen, lPen, inPen);

    // Actions
    var actions = el("div", "ae-actions");
    var submitBtn = el("button", "ae-submit");
    submitBtn.type = "submit";
    append(submitBtn, iconEl("send", 14), el("span", "", "Submit AE Report"));

    var disclaimer = el("p", "ae-disclaimer", "Demo prototype: reports submitted here are saved to the reviewer safety queue for demonstration and are not sent to Novartis or FDA.");
    append(actions, submitBtn, disclaimer);

    append(form, row1, row2, row3, fDesc, fPen, actions);
    append(card, header, form);

    // Handle submit
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var descVal = txtDesc.value.trim();
      if (!descVal) {
        txtDesc.focus();
        txtDesc.classList.add("ae-input--error");
        return;
      }
      txtDesc.classList.remove("ae-input--error");
      submitBtn.disabled = true;
      submitBtn.classList.add("is-loading");
      submitBtn.lastChild.textContent = "Submitting report...";

      var payload = {
        report_id: (data && data.report_id) ? data.report_id : null,
        session_id: state.sessionId,
        reporter_type: selRole.value,
        patient_name: inName.value.trim(),
        contact: inContact.value.trim(),
        onset_date: inDate.value.trim(),
        severity: selSev.value,
        doctor_contacted: selHcp.value,
        description: descVal,
        product_pen_issue: inPen.value.trim()
      };

      fetch("api/report/ae", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function () {
        card.replaceChildren();
        card.classList.add("ae-card--confirmed");
        var confHead = el("div", "ae-conf__head");
        append(confHead, iconEl("check", 18, "ae-conf__check"), el("div", "ae-conf__title", "Adverse Event Report Logged"));
        
        var confBody = el("div", "ae-conf__body");
        var line1 = el("p", "ae-conf__line");
        append(line1, el("strong", "", "Report Status: "), el("span", "ae-conf__tag", "Open in Safety Queue"));
        
        var line2 = el("p", "ae-conf__line");
        append(line2, el("strong", "", "Reporter: "), el("span", "", (payload.patient_name || "Anonymous") + " (" + payload.reporter_type + ")"));
        
        var line3 = el("p", "ae-conf__line");
        append(line3, el("strong", "", "Severity: "), el("span", "ae-conf__sev", payload.severity), el("span", "", " · Onset: " + (payload.onset_date || "today")));
        
        var line4 = el("p", "ae-conf__desc");
        append(line4, el("strong", "", "Recorded description: "), el("span", "", "“" + payload.description + "”"));
        
        var confFoot = el("p", "ae-conf__foot", "This report is now logged for pharmacovigilance review in the Reviewer Console. If your symptoms worsen, seek medical attention immediately.");
        
        append(confBody, line1, line2, line3, line4, confFoot);
        append(card, confHead, confBody);
        reveal(card);
      })
      .catch(function (err) {
        submitBtn.disabled = false;
        submitBtn.classList.remove("is-loading");
        submitBtn.lastChild.textContent = "Submit AE Report";
        alert("Could not submit the report: " + (err.message || "Unknown error"));
      });
    });

    return card;
  }

  /** Render one assistant reply from the API payload (or a client-side error). */
  function addBotMessage(data) {
    var kindKey = kindOf(data);
    var k = KINDS[kindKey];
    var replyText = data && isStr(data.reply_text) ? data.reply_text : state.meta.error_text;

    var row = el("div", "msg msg--bot msg--" + k.tone);
    row.appendChild(avatar());
    var main = el("article", "bot");
    main.setAttribute("aria-label", k.label + " reply");

    var box = main;
    if (isRedKind(kindKey)) {
      box = el("div", "safety-box");
      main.appendChild(box);
    }
    box.appendChild(statusPill(kindKey));
    renderReply(box, replyText, data, kindKey);
    if (isRedKind(kindKey)) {
      var foot = el("p", "safety-box__foot");
      foot.appendChild(iconEl("log", 14));
      foot.appendChild(el("span", "", "Logged for review by a person"));
      box.appendChild(foot);
      box.appendChild(buildAEFormCard(data));
    }

    var why = buildWhy(data);
    if (why) main.appendChild(why);
    row.appendChild(main);
    els.messages.appendChild(row);
    reveal(row);
  }

  /**
   * Show reply_text exactly, in three parts when the approved answer is a substring:
   * the lead (muted), the approved answer (full size), then the evidence, a hairline,
   * and the closing lines (muted, including the "Source: …" line). Only whitespace at
   * the joins is trimmed and "• " markers become list bullets; a self-check falls back
   * to one plain block if the rendered text does not reproduce every other character.
   */
  function renderReply(container, replyText, data, kindKey) {
    var answer = data && isStr(data.answer) ? data.answer : null;
    var idx = answer ? replyText.indexOf(answer) : -1;
    var plainFallback = function () {
      var b = textBlocks(replyText, "reply");
      if (squash(b.text) !== squash(replyText)) container.appendChild(el("p", "reply", replyText));
      else container.appendChild(b.node);
      if (data && data.figure) {
        var figCard = buildFigure(data.figure);
        if (figCard) container.appendChild(figCard);
      }
      if (data && isMatchKind(kindKey)) {
        var ev = buildEvidence(data);
        if (ev) container.appendChild(ev);
      }
    };
    if (idx < 0) { plainFallback(); return; }

    var lead = textBlocks(replyText.slice(0, idx), "reply reply--lead");
    var body = textBlocks(answer, "reply reply--answer");
    var close = textBlocks(replyText.slice(idx + answer.length), "reply reply--close");
    if (squash(lead.text + body.text + close.text) !== squash(replyText)) {
      container.appendChild(el("p", "reply", replyText));
      return;
    }

    var parts = el("div", "reply-parts");
    if (lead.text) parts.appendChild(lead.node);
    var ans = el("div", "answer" + (kindKey === "related" ? " answer--related" : ""));
    ans.appendChild(body.node);
    parts.appendChild(ans);
    if (data && data.figure) {
      var figCard = buildFigure(data.figure);
      if (figCard) parts.appendChild(figCard);
    }
    if (data && isMatchKind(kindKey)) {
      var ev = buildEvidence(data);
      if (ev) parts.appendChild(ev);
    }
    if (close.text) {
      var c = el("div", "closing");
      c.appendChild(close.node);
      parts.appendChild(c);
    }
    container.appendChild(parts);
  }

  /** Grey reply for network failures / timeouts / bad responses. */
  function addErrorMessage() {
    addBotMessage({ kind: "error", reply_text: state.meta.error_text });
  }

  /* ---------- Figure card: official document diagram/illustration ---------- */
  function buildFigure(fig) {
    if (!fig || !fig.image_url) return null;
    var rawUrl = fig.image_url;
    var imgUrl = rawUrl.indexOf("/") === 0 || rawUrl.indexOf("http") === 0 ? rawUrl : ("/" + rawUrl);

    var wrap = el("figure", "fig-card");
    var a = el("a", "fig-card__link");
    a.href = imgUrl;
    a.setAttribute("aria-label", "View official figure full size: " + (fig.caption || "Illustration"));

    var img = document.createElement("img");
    img.className = "fig-card__img";
    img.alt = fig.caption || "Official brochure figure";
    img.decoding = "sync";

    // Clicking image zooms inside the drawer
    a.addEventListener("click", function (e) {
      e.preventDefault();
      openSourceDrawer(imgUrl, fig.caption || "Official Document Figure", a);
    });

    img.addEventListener("error", function () {
      console.warn("Figure image failed to render directly:", imgUrl);
      img.remove();
      var errNotice = el("div", "fig-card__error");
      errNotice.appendChild(iconEl("image", 16));
      errNotice.appendChild(el("span", "", "Diagram available: "));
      var link = el("a", "textlink", "Open diagram full size");
      link.href = imgUrl;
      link.target = "_blank";
      errNotice.appendChild(link);
      a.appendChild(errNotice);
    });

    img.src = imgUrl;
    a.appendChild(img);
    wrap.appendChild(a);
    return wrap;
  }

  /* ---------- Evidence: source snippet crop and citation line ---------- */
  function buildEvidence(data) {
    var rawPage = safeUrl(data.source_page_url);
    var rawSnippet = safeUrl(data.snippet_url);
    if (!rawPage && !rawSnippet && !isStr(data.source_label)) return null;

    var page = rawPage ? (rawPage.indexOf("/") === 0 || rawPage.indexOf("http") === 0 ? rawPage : ("/" + rawPage)) : null;
    var snippet = rawSnippet ? (rawSnippet.indexOf("/") === 0 || rawSnippet.indexOf("http") === 0 ? rawSnippet : ("/" + rawSnippet)) : null;
    var label = isStr(data.source_label) ? data.source_label : null;

    var wrap = el("section", "evidence");
    wrap.setAttribute("aria-label", "Source evidence");

    // If snippet crop exists and item doesn't have an official figure (or along with it)
    if (snippet && (!data.figure || !data.figure.image_url)) {
      var btn = el("button", "snippet");
      btn.type = "button";
      btn.setAttribute("aria-label", "Open full source page with highlighted passage");
      var sImg = document.createElement("img");
      sImg.alt = label ? "Approved source snippet: " + label : "Approved source snippet";
      sImg.addEventListener("load", function () { btn.classList.add("is-loaded"); });
      sImg.addEventListener("error", function () {
        console.warn("Snippet image unavailable:", snippet);
        btn.remove();
      });
      sImg.src = snippet;
      btn.appendChild(sImg);
      if (page) {
        btn.addEventListener("click", function () { openSourceDrawer(page, label, btn); });
      }
      wrap.appendChild(btn);
    }

    // Source line: name (medium) · pages (muted) · View page
    var src = el("div", "source");
    if (label) {
      var cut = label.lastIndexOf(" · ");
      if (cut > 0) {
        src.appendChild(el("span", "source__name", label.slice(0, cut)));
        src.appendChild(el("span", "source__pages", label.slice(cut + 3)));
      } else {
        src.appendChild(el("span", "source__name", label));
      }
    } else {
      src.appendChild(el("span", "source__name", "Approved source"));
    }
    if (page) {
      var textBtn = el("button", "textlink");
      textBtn.type = "button";
      textBtn.appendChild(el("span", "", "View page"));
      textBtn.appendChild(iconEl("arrow", 13));
      textBtn.addEventListener("click", function () { openSourceDrawer(page, label, textBtn); });
      src.appendChild(textBtn);
    }
    wrap.appendChild(src);

    return wrap;
  }

  /* ---------- Decision details: one quiet footnote line ---------- */
  function buildWhy(data) {
    var why = data && data.why && typeof data.why === "object" ? data.why : null;
    if (!why) return null;
    var line = el("p", "why");
    line.appendChild(el("span", "sr-only", "Decision details: "));
    var parts = [];
    var zone = allow(why.zone, ZONES);
    parts.push(["zone", zone ? human(zone) : "—", zone ? "zone-" + zone : null]);
    var rt = allow(why.red_type, RED_TYPES);
    if (rt) parts.push(["safety", human(rt)]);
    var intent = allow(why.intent, INTENTS);
    if (intent) parts.push(["topic", human(intent)]);
    if (isStr(why.matched_id)) parts.push(["item", why.matched_id, null, true]);
    if (isNum(why.score)) parts.push(["confidence", why.score.toFixed(3), null, true]);
    var lat = formatLatency(data.latency_ms);
    if (lat) parts.push(["time", lat, null, true]);
    if (Array.isArray(why.scan_terms)) {
      var terms = why.scan_terms.filter(isStr);
      if (terms.length) parts.push(["safety words", terms.join(", "), "flag"]);
    }
    parts.forEach(function (p, i) {
      if (i) line.appendChild(el("span", "why__sep", " · "));
      var s = el("span", "why__part" + (p[2] ? " why__part--" + p[2] : ""));
      s.appendChild(el("span", "why__k", p[0] + " "));
      s.appendChild(el("span", "why__v" + (p[3] ? " why__v--mono" : ""), p[1]));
      line.appendChild(s);
    });
    return line;
  }

  /* =====================================================================
     Drawer (safety information / source page)
     ===================================================================== */
  function openDrawer(title, subtitle, bodyNode, opener, variant) {
    state.lastFocus = opener || document.activeElement;
    els.drawer.className = "drawer" + (variant ? " drawer--" + variant : "");
    els.drawerTitle.textContent = title;
    els.drawerSubtitle.textContent = subtitle || "";
    els.drawerSubtitle.hidden = !subtitle;
    els.drawerBody.replaceChildren(bodyNode);
    els.drawerBody.scrollTop = 0;
    els.backdrop.hidden = false;
    els.drawer.hidden = false;
    els.drawerClose.focus();
  }

  function closeDrawer() {
    if (els.drawer.hidden) return;
    els.drawer.hidden = true;
    els.backdrop.hidden = true;
    els.drawerBody.replaceChildren();
    if (state.lastFocus && typeof state.lastFocus.focus === "function") state.lastFocus.focus();
  }

  function openSafetyDrawer() {
    var text = state.meta.safety_panel;
    var body = isStr(text)
      ? el("p", "drawer__text", text)
      : el("p", "drawer__empty", "Safety information could not be loaded.");
    openDrawer("Important Safety Information", "", body, els.isiBtn, "isi");
  }

  function openSourceDrawer(url, label, opener) {
    if (url && typeof url === "string" && !url.startsWith("/") && !url.startsWith("http")) {
      url = "/" + url;
    }
    var wrap = el("div", "pagewrap");
    var a = el("a", "page-link");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.setAttribute("aria-label", "Open the full source page in a new tab");
    var img = document.createElement("img");
    img.alt = label ? "Full source page: " + label : "Full source page";
    var hint = el("p", "page-hint");
    img.addEventListener("error", function () {
      a.replaceWith(el("p", "drawer__empty", "Source page could not be loaded."));
      hint.remove();
    });
    img.src = url;
    a.appendChild(img);
    wrap.appendChild(a);
    hint.appendChild(iconEl("external", 14));
    hint.appendChild(el("span", "", "The approved passage is highlighted. Select the page to open it full size."));
    wrap.appendChild(hint);
    openDrawer("Source page", label, wrap, opener || document.activeElement, "wide");
  }

  function trapFocus(e) {
    if (e.key !== "Tab" || els.drawer.hidden) return;
    var f = els.drawer.querySelectorAll('button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1];
    if (!els.drawer.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }

  /* =====================================================================
     Busy state
     ===================================================================== */
  function setBusy(b) {
    state.busy = b;
    els.input.disabled = b;
    els.newChat.disabled = b;
    els.scroller.setAttribute("aria-busy", b ? "true" : "false");
    var chips = els.starters.querySelectorAll("button");
    for (var i = 0; i < chips.length; i++) chips[i].disabled = b;
    updateSend();
    if (!b && els.drawer.hidden) els.input.focus();
  }

  function updateSend() {
    els.send.disabled = state.busy || els.input.value.trim().length === 0;
  }

  /* =====================================================================
     Chat request
     ===================================================================== */
  function send(text) {
    var message = (text || "").trim().slice(0, MAX_LEN);
    if (!message || state.busy) return;

    hideHero();
    addUserMessage(message);
    els.input.value = "";
    setBusy(true);
    var typing = addTyping();

    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, REQUEST_TIMEOUT_MS);

    fetch("api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, session_id: state.sessionId }),
      signal: controller ? controller.signal : undefined
    })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        typing.remove();
        if (!data || typeof data !== "object" || !isStr(data.reply_text)) addErrorMessage();
        else {
          data.user_message = message;
          addBotMessage(data);
        }
      })
      .catch(function () {
        typing.remove();
        addErrorMessage();
      })
      .then(function () {
        clearTimeout(timer);
        setBusy(false);
      });
  }

  /* =====================================================================
     Meta (banner, safety panel, starters, error text)
     ===================================================================== */
  function renderStarters() {
    els.starters.replaceChildren();
    state.meta.starters.forEach(function (q, i) {
      var b = el("button", "starter");
      b.type = "button";
      b.style.setProperty("--i", String(i));
      b.appendChild(el("span", "starter__text", q));
      b.appendChild(iconEl("arrow", 16, "starter__arrow"));
      b.disabled = state.busy;
      b.addEventListener("click", function () { send(q); });
      els.starters.appendChild(b);
    });
  }

  function loadMeta() {
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timer = setTimeout(function () { if (controller) controller.abort(); }, REQUEST_TIMEOUT_MS);
    return fetch("api/meta", { signal: controller ? controller.signal : undefined })
      .then(function (res) { if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function (m) {
        if (!m || typeof m !== "object") return;
        if (isStr(m.banner)) state.meta.banner = m.banner;
        if (isStr(m.safety_panel)) state.meta.safety_panel = m.safety_panel;
        if (isStr(m.error_text)) state.meta.error_text = m.error_text;
        if (Array.isArray(m.starters)) state.meta.starters = m.starters.filter(isStr).slice(0, 6);
      })
      .catch(function () { /* keep static fallbacks */ })
      .then(function () {
        clearTimeout(timer);
        els.banner.textContent = state.meta.banner;
        renderStarters();
      });
  }

  /* =====================================================================
     Details toggle & new chat
     ===================================================================== */
  function setWhy(on) {
    els.whyToggle.setAttribute("aria-checked", on ? "true" : "false");
    document.body.classList.toggle("hide-why", !on);
    try { localStorage.setItem("onlabel_show_why", on ? "1" : "0"); } catch (e) { /* ignore */ }
  }

  function newChat() {
    if (state.busy) return;
    els.messages.replaceChildren();
    state.sessionId = getSessionId(true);
    els.hero.hidden = false;
    els.input.value = "";
    updateSend();
    els.scroller.scrollTop = 0;
    els.input.focus();
  }

  /* =====================================================================
     Wire-up
     ===================================================================== */
  els.form.addEventListener("submit", function (e) {
    e.preventDefault();
    send(els.input.value);
  });
  els.input.addEventListener("input", updateSend);
  els.whyToggle.addEventListener("click", function () {
    setWhy(els.whyToggle.getAttribute("aria-checked") !== "true");
  });
  els.newChat.addEventListener("click", newChat);
  els.isiBtn.addEventListener("click", openSafetyDrawer);
  els.drawerClose.addEventListener("click", closeDrawer);
  els.backdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeDrawer();
    trapFocus(e);
  });

  (function initWhy() {
    var on = true;
    try { on = localStorage.getItem("onlabel_show_why") !== "0"; } catch (e) { /* default on */ }
    setWhy(on);
  })();

  els.banner.textContent = FALLBACK_BANNER;
  loadMeta();
  updateSend();
  els.input.focus();
})();
