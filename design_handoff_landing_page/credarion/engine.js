/* ============================================================
   CREDARION — The Engine
   Animated 4-gate reconciliation pipeline.
   Messy sources (left) → matching gates (middle) → ledger (right).
   Mechanical motion: tokens SNAP into alignment.
   ============================================================ */
(function () {
  "use strict";

  var board   = document.getElementById("engine-board");
  if (!board) return;
  var beamsEl = document.getElementById("beams");
  var tokensEl= document.getElementById("tokens");
  var ledgerRows = document.getElementById("ledger-rows");
  var discrep = document.getElementById("discrep");
  var runBtn  = document.getElementById("run-btn");
  var reduce  = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---- distribution: where each row resolves -----------------
  // gate index 0 Exact, 1 Fuzzy, 2 Multi-PO, 3 AI(amber)
  var PLAN = [];
  function buildPlan() {
    PLAN = [];
    var spec = [ [0,24], [1,4], [2,1], [3,1] ]; // [gate, count]
    spec.forEach(function (s) { for (var i=0;i<s[1];i++) PLAN.push(s[0]); });
    // interleave: keep AI/multi toward the end, lightly shuffle the exacts
    for (var k = PLAN.length - 1; k > 0; k--) {
      // only shuffle within the "exact" majority to keep a natural stream
      if (PLAN[k] === 0) {
        var j = Math.floor(Math.random() * (k + 1));
        if (PLAN[j] === 0) { var t = PLAN[k]; PLAN[k] = PLAN[j]; PLAN[j] = t; }
      }
    }
  }

  var TOTAL = 30;
  var GATE_MAX = [24, 4, 1, 1];

  // ---- PO label pool -----------------------------------------
  var POOL = ["428759","428760","428762","428765","428771","428780","428781",
              "428790","428803","428804","429001","429014","429022","429038",
              "429041","429055","429067","429072","429088","429090"];
  function po(i){ return "PO-" + POOL[i % POOL.length]; }
  function amt(){ return (Math.random()*5000+400).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ","); }

  // ---- geometry ----------------------------------------------
  var G = {}; // resolved coordinate points
  function pt(el){
    if (!el) return null;
    var b = el.getBoundingClientRect(), r = board.getBoundingClientRect();
    return { x: b.left - r.left + b.width/2, y: b.top - r.top + b.height/2,
             right: b.right - r.left, left: b.left - r.left };
  }
  function measure(){
    var srcEls = board.querySelectorAll(".src-anchor");
    G.src = [];
    srcEls.forEach(function(s){ var p = pt(s); if(p) G.src.push({x:p.x, y:p.y}); });
    G.gate = [];
    G.gateIn = [];
    for (var i=0;i<4;i++){
      var ge = board.querySelector('.gate[data-gate="'+i+'"]');
      var pc = pt(ge);
      G.gate.push({ x: pc.x, y: pc.y });
      G.gateIn.push({ x: pc.left, y: pc.y });
      G.gateRight = pc.right;
    }
    var led = board.querySelector("[data-ledger]");
    var lp = pt(led);
    G.ledger = lp ? { x: lp.x, y: lp.y } : { x: G.gate[0].x + 240, y: G.gate[0].y };
  }

  // ---- beams (SVG) -------------------------------------------
  function curve(a, b, k){
    k = k || 0.5;
    var mx = a.x + (b.x - a.x) * k;
    return "M "+a.x+" "+a.y+" C "+mx+" "+a.y+" "+mx+" "+b.y+" "+b.x+" "+b.y;
  }
  function drawBeams(){
    if (reduce) return;
    var w = board.clientWidth, h = board.clientHeight;
    beamsEl.setAttribute("viewBox", "0 0 "+w+" "+h);
    var html = "";
    // sources -> gate 1 entry (convergence)
    var entry = G.gateIn[0];
    G.src.forEach(function(s){
      html += '<path class="beam" d="'+curve({x:s.x+4,y:s.y}, entry, 0.55)+'"/>';
    });
    // a couple of flowing arteries source-cluster -> entry
    html += '<path class="beam-flow" d="'+curve({x:G.src[0].x+4,y:G.src[0].y}, entry, 0.55)+'"/>';
    html += '<path class="beam-flow" d="'+curve({x:G.src[3].x+4,y:G.src[3].y}, entry, 0.55)+'"/>';
    // gates right edge -> ledger
    var gx = G.gateRight;
    [0,1,2].forEach(function(i){
      html += '<path class="beam" d="'+curve({x:gx,y:G.gate[i].y}, G.ledger, 0.5)+'"/>';
    });
    html += '<path class="beam-flow" d="'+curve({x:gx,y:G.gate[0].y}, G.ledger, 0.5)+'"/>';
    beamsEl.innerHTML = html;
  }

  // ---- counters ----------------------------------------------
  var gc = [0,0,0,0], tally = 0, processed = 0;
  function setText(sel, v){ var e = board.querySelector(sel); if(e) e.textContent = v; }
  function refreshCounts(){
    for (var i=0;i<4;i++){
      board.querySelector('[data-gc="'+i+'"]').textContent = gc[i];
      var fill = Math.min(1, gc[i]/GATE_MAX[i]);
      board.querySelector('[data-gbar="'+i+'"]').style.right = (100 - fill*100) + "%";
    }
    board.querySelector("[data-tally]").textContent = tally;
    board.querySelector("[data-total]").textContent = processed;
    setText("#gate-progress", processed + " / " + TOTAL);
  }

  // ---- ledger rows -------------------------------------------
  var TICK = '<svg class="tick" viewBox="0 0 12 12" fill="none"><path d="M2.5 6.2 5 8.7 9.6 3.4" stroke="currentColor" stroke-width="1.6" stroke-linecap="square"/></svg>';
  var FLAG = '<svg class="tick" viewBox="0 0 12 12" fill="none"><path d="M6 1.5 V8 M6 10.4 v.1" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="6" cy="6" r="5" stroke="currentColor" stroke-width="1"/></svg>';
  function addLedgerRow(label, amber){
    var row = document.createElement("div");
    row.className = "lrow" + (amber ? " amber" : "");
    row.innerHTML = '<span class="po">'+label+'</span><span class="amt">¥'+amt()+'</span>'+
      '<span class="st">'+(amber?FLAG:TICK)+(amber?'review':'matched')+'</span>';
    ledgerRows.insertBefore(row, ledgerRows.firstChild);
    while (ledgerRows.children.length > 9) ledgerRows.removeChild(ledgerRows.lastChild);
  }

  // ---- token motion ------------------------------------------
  function place(el, p){ el.style.transform = "translate("+p.x+"px,"+p.y+"px) translate(-50%,-50%)"; }
  function jitter(p, ry){ return { x: p.x, y: p.y + (Math.random()*2-1)*(ry||14) }; }

  function gateFlash(i){
    var g = board.querySelector('.gate[data-gate="'+i+'"]');
    g.classList.add("active");
    clearTimeout(g._t);
    g._t = setTimeout(function(){ g.classList.remove("active"); }, 420);
  }

  function runToken(targetGate, idx, done){
    var el = document.createElement("div");
    el.className = "token";
    el.textContent = po(idx);
    tokensEl.appendChild(el);
    var spawn = jitter(G.src[idx % G.src.length], 8);
    place(el, spawn);

    var amber = targetGate === 3;
    // step through gates up to the target
    var step = 0;
    function next(){
      if (step <= targetGate){
        var g = jitter(G.gate[step], 12);
        place(el, g);
        gateFlash(step);
        step++;
        setTimeout(next, 300);
      } else {
        // resolve
        el.classList.add(amber ? "amber" : "green", "pop");
        gc[targetGate]++;
        if (!amber) tally++;
        refreshCounts();
        setTimeout(function(){
          place(el, jitter(G.ledger, 10));
          el.style.opacity = "0";
          setTimeout(function(){
            el.remove();
            processed++;
            addLedgerRow(po(idx), amber);
            refreshCounts();
            if (amber && discrep) discrep.style.display = "";
            done && done();
          }, 320);
        }, 160);
      }
    }
    requestAnimationFrame(function(){ requestAnimationFrame(next); });
  }

  // ---- run cycle ---------------------------------------------
  var running = false;
  function reset(){
    gc = [0,0,0,0]; tally = 0; processed = 0;
    tokensEl.innerHTML = ""; ledgerRows.innerHTML = "";
    if (discrep) discrep.style.display = "none";
    refreshCounts();
  }
  function fillFinal(){
    // reduced-motion / instant end state
    gc = GATE_MAX.slice(); tally = 29; processed = TOTAL;
    refreshCounts();
    for (var i=0;i<8;i++) addLedgerRow(po(i), false);
    addLedgerRow("PO-428804", true);
    if (discrep) discrep.style.display = "";
  }
  function run(){
    if (running) return;
    measure(); drawBeams();
    if (reduce){ reset(); fillFinal(); return; }
    running = true;
    reset();
    buildPlan();
    var i = 0;
    (function spawn(){
      if (i >= PLAN.length){ running = false; return; }
      runToken(PLAN[i], i);
      i++;
      setTimeout(spawn, 150 + Math.random()*70);
    })();
    // running flag releases shortly after last token settles
    setTimeout(function(){ running = false; }, PLAN.length*220 + 1400);
  }

  // ---- triggers ----------------------------------------------
  if (runBtn) runBtn.addEventListener("click", run);

  var started = false;
  function inView(el){
    var r = el.getBoundingClientRect();
    var vh = window.innerHeight || document.documentElement.clientHeight;
    return r.top < vh * 0.7 && r.bottom > vh * 0.2;
  }
  function maybeStart(){
    if (started) return;
    if (inView(board)){
      started = true;
      measure(); drawBeams();
      setTimeout(run, 300);
    }
  }
  var et = false;
  window.addEventListener("scroll", function(){
    if (et) return; et = true;
    requestAnimationFrame(function(){ maybeStart(); et = false; });
  }, { passive: true });

  var rt;
  window.addEventListener("resize", function(){
    clearTimeout(rt);
    rt = setTimeout(function(){ measure(); drawBeams(); }, 160);
  });

  // initial geometry pass once fonts/layout settle
  window.addEventListener("load", function(){ setTimeout(function(){ measure(); drawBeams(); maybeStart(); }, 120); });
  setTimeout(maybeStart, 400);
})();
