/* ============================================================
   CREDARION — Site behaviors
   Number tickers · statement fan · marquee · reveal-on-scroll
   ============================================================ */
(function () {
  "use strict";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---- shared: manual in-view check (robust to embedded iframes) --- */
  function inView(el, factor) {
    var r = el.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    var t = factor == null ? 0.88 : factor;
    return r.top < vh * t && r.bottom > 0;
  }
  var watchers = []; // { el, once, fn, done }
  function watch(el, factor, fn) {
    var w = { el: el, factor: factor, fn: fn, done: false };
    watchers.push(w);
    return w;
  }
  function sweep() {
    for (var i = 0; i < watchers.length; i++) {
      var w = watchers[i];
      if (w.done) continue;
      if (inView(w.el, w.factor)) { w.done = true; w.fn(w.el); }
    }
  }
  var ticking = false;
  function onScroll() {
    if (ticking) return; ticking = true;
    requestAnimationFrame(function () { sweep(); ticking = false; });
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);

  /* ---- 1. Reveal on scroll --------------------------------- */
  document.querySelectorAll(".reveal").forEach(function (el) {
    if (reduce) { el.classList.add("in"); return; }
    watch(el, 0.92, function (t) { t.classList.add("in"); });
  });

  /* ---- 2. Number tickers ----------------------------------- */
  function fmt(n, dec) {
    return n.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function tick(el) {
    var to = parseFloat(el.getAttribute("data-to"));
    var dec = parseInt(el.getAttribute("data-dec") || "0", 10);
    if (reduce) { el.textContent = fmt(to, dec); return; }
    var dur = 1300, t0 = null;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      var e = 1 - Math.pow(1 - p, 3); // ease-out, mechanical settle
      el.textContent = fmt(to * e, dec);
      if (p < 1) requestAnimationFrame(step);
      else el.textContent = fmt(to, dec);
    }
    requestAnimationFrame(step);
  }
  document.querySelectorAll(".ticker").forEach(function (el) {
    watch(el, 0.85, tick);
  });

  /* ---- 3. Rate bar fill ------------------------------------ */
  document.querySelectorAll("[data-fill]").forEach(function (el) {
    watch(el, 0.85, function (t) {
      var v = parseFloat(t.getAttribute("data-fill"));
      requestAnimationFrame(function () { t.style.right = (100 - v) + "%"; });
    });
  });

  // Arm reveal animations only once a real animation frame fires. In a
  // paint-stalled context (rAF never runs) the page stays at its visible
  // base state instead of frozen-hidden.
  requestAnimationFrame(function () {
    document.documentElement.classList.add("js-armed");
    requestAnimationFrame(sweep);
  });
  window.addEventListener("load", function () { requestAnimationFrame(sweep); });

  /* ---- 4. Statement fan ------------------------------------ */
  function layoutFan() {
    var fan = document.getElementById("fan");
    if (!fan) return;
    var cards = fan.querySelectorAll(".stmt");
    var narrow = fan.clientWidth < 420;
    cards.forEach(function (c) {
      var rot = parseFloat(c.getAttribute("data-rot"));
      var x = parseFloat(c.getAttribute("data-x"));
      var y = parseFloat(c.getAttribute("data-y"));
      var z = parseInt(c.getAttribute("data-z"), 10);
      if (narrow) { rot *= 0.55; x *= 0.5; }
      c.style.left = x + "px";
      c.style.bottom = y + "px";
      c.style.zIndex = z;
      c.style.transform = "rotate(" + rot + "deg)";
      c.style.setProperty("--r", rot + "deg");
    });
  }
  layoutFan();
  window.addEventListener("resize", layoutFan);

  // subtle hover: straighten the hovered card
  document.querySelectorAll("#fan .stmt").forEach(function (c) {
    c.addEventListener("mouseenter", function () {
      c.style.transform = "rotate(0deg) translateY(-8px)";
      c.style.zIndex = 20;
    });
    c.addEventListener("mouseleave", function () {
      var rot = parseFloat(c.getAttribute("data-rot"));
      var fan = document.getElementById("fan");
      if (fan && fan.clientWidth < 420) rot *= 0.55;
      c.style.transform = "rotate(" + rot + "deg)";
      c.style.zIndex = c.getAttribute("data-z");
    });
  });

  /* ---- 5. Marquee of supported systems --------------------- */
  var SYSTEMS = [
    ["Kingdee", "金蝶"], ["Yonyou", "用友"], ["SAP", "ERP"], ["Oracle NetSuite", "ERP"],
    ["Xero", "XR"], ["QuickBooks", "QB"], ["MYOB", "AU"], ["Sage", "UK"],
    ["Microsoft Dynamics", "365"], ["HSBC", "BANK"], ["DBS", "BANK"], ["Wise", "FX"]
  ];
  var track = document.getElementById("marq-track");
  if (track) {
    var html = "";
    var build = SYSTEMS.concat(SYSTEMS); // duplicate for seamless loop
    build.forEach(function (s) {
      html += '<span class="mq"><span class="nm">' + s[0] + '</span><span class="cn">' + s[1] + '</span></span>';
    });
    track.innerHTML = html;
  }

  /* ---- 6. Active nav underline on scroll ------------------- */
  var sections = ["mess", "engine", "result", "pricing"].map(function (id) {
    return document.getElementById(id);
  }).filter(Boolean);
  var links = {};
  document.querySelectorAll(".nav-links a").forEach(function (a) {
    var h = a.getAttribute("href");
    if (h && h[0] === "#") links[h.slice(1)] = a;
  });
})();
