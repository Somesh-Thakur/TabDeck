/* TabDeck tools: trackpad, keyboard, gamepad and signature pad (opened from the dock's Tools button). */
(() => {
const Tools = window.Tools = {};       // filled in at the bottom; declared first so every tool can use it
const $ = id => document.getElementById(id);
const buzz = ms => { try { if (!/[?&]preview/.test(location.search) && navigator.vibrate) navigator.vibrate(ms); } catch {} };

/* ------------------------------------------------------------------ input pipe: batched once per frame */
let queue = [], busy = false;
function send(ev) { queue.push(ev); if (!busy) flush(); }
function flush() {
  if (!queue.length) { busy = false; return; }
  busy = true;
  const batch = queue; queue = [];
  fetch('input', { method: 'POST', body: JSON.stringify(batch) }).catch(() => {}).finally(() => requestAnimationFrame(flush));
}

/* ------------------------------------------------------------------ panel */
const TABS = [['trackpad', 'i-mouse', 'Trackpad'], ['keyboard', 'i-kbd', 'Keyboard'], ['gamepad', 'i-pad', 'Gamepad'], ['sign', 'i-pen', 'Sign']];
const root = document.createElement('div');
root.className = 'tools'; root.id = 'tools';
root.innerHTML = `<div class="t-top"><div class="t-side"></div><div class="t-tabs">${TABS.map(([k, ic, n]) =>
  `<button data-tab="${k}"><svg class="ic"><use href="#${ic}"/></svg>${n}</button>`).join('')}</div>
  <button class="t-close" id="tClose" title="Close"><svg class="ic"><use href="#i-x"/></svg></button></div>`;
document.body.appendChild(root);
let current = null;
function show(tab) {
  current = tab;
  root.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
  root.querySelectorAll('.t-body').forEach(b => b.classList.toggle('on', b.id === 'tb-' + tab));
  try { localStorage.setItem('ccTool', tab); } catch {}
  if (tab === 'sign') Sign.resize();
}
root.querySelector('.t-tabs').onclick = e => { const b = e.target.closest('[data-tab]'); if (b) show(b.dataset.tab); };
$('tClose').onclick = () => Tools.close();
function body(tab) { const d = document.createElement('div'); d.className = 't-body'; d.id = 'tb-' + tab; root.appendChild(d); return d; }

/* ================================================================== TRACKPAD */
(() => {
  const el = body('trackpad');
  el.innerHTML = `<div class="tp"><div class="tp-pad" id="tpPad"><i class="tp-dot" id="tpDot"></i>
    <div class="t-hint">1 finger: move · tap: click · 2-finger tap: right-click · 2 fingers: scroll · double-tap &amp; hold: drag</div></div>
    <div class="tp-btns"><button data-b="l">Left click</button><button data-b="m" style="flex:.35">Middle</button><button data-b="r">Right click</button></div>
    <div class="tp-sens">Speed <input type="range" min="0.6" max="4" step="0.1" id="tpSpeed"></div></div>`;
  const pad = $('tpPad'), dot = $('tpDot'), speed = $('tpSpeed');
  let sens = 1.8; try { sens = +localStorage.getItem('ccTpSpeed') || 1.8; } catch {}
  speed.value = sens; speed.oninput = () => { sens = +speed.value; try { localStorage.setItem('ccTpSpeed', sens); } catch {} };
  const P = new Map();                       // active pointers
  let mode = null, moved = 0, t0 = 0, lastTap = 0, dragging = false, scrollAcc = 0, hscrollAcc = 0, fx = 0, fy = 0, maxPts = 0;
  pad.addEventListener('pointerdown', e => {
    pad.setPointerCapture(e.pointerId);
    P.set(e.pointerId, { x: e.clientX, y: e.clientY });
    maxPts = Math.max(maxPts, P.size);
    if (P.size === 1) {
      t0 = performance.now(); moved = 0; mode = 'move';
      if (t0 - lastTap < 280) { dragging = true; send({ t: 'b', b: 'l', d: 1 }); buzz(8); }   // double-tap & hold = drag
    } else if (P.size === 2) { mode = 'scroll'; scrollAcc = hscrollAcc = 0; }
    const r = pad.getBoundingClientRect(); dot.style.left = (e.clientX - r.left) + 'px'; dot.style.top = (e.clientY - r.top) + 'px'; dot.style.opacity = .35;
  });
  pad.addEventListener('pointermove', e => {
    const p = P.get(e.pointerId); if (!p) return;
    const dx = e.clientX - p.x, dy = e.clientY - p.y; p.x = e.clientX; p.y = e.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    const r = pad.getBoundingClientRect(); dot.style.left = (e.clientX - r.left) + 'px'; dot.style.top = (e.clientY - r.top) + 'px';
    if (mode === 'move' && P.size === 1) {
      const v = Math.hypot(dx, dy), accel = sens * (1 + Math.min(v, 30) / 18);   // faster swipe = further
      fx += dx * accel; fy += dy * accel;
      const ix = Math.trunc(fx), iy = Math.trunc(fy); fx -= ix; fy -= iy;
      if (ix || iy) send({ t: 'm', x: ix, y: iy });
    } else if (mode === 'scroll' && P.size === 2) {
      scrollAcc += dy / 2; hscrollAcc += dx / 2;            // two pointers both report, so halve
      const STEP = 22, n = Math.trunc(scrollAcc / STEP), h = Math.trunc(hscrollAcc / STEP);
      if (n) { send({ t: 'w', y: -n }); scrollAcc -= n * STEP; }   // natural scrolling, like a phone
      if (h) { send({ t: 'w', x: -h }); hscrollAcc -= h * STEP; }
    }
  });
  const up = e => {
    if (!P.has(e.pointerId)) return;
    P.delete(e.pointerId);
    if (P.size) return;
    dot.style.opacity = 0;
    const quick = performance.now() - t0 < 230 && moved < 14;
    if (dragging) { send({ t: 'b', b: 'l', d: 0 }); dragging = false; }
    else if (quick && maxPts >= 2) { send({ t: 'b', b: 'r', d: 1 }); send({ t: 'b', b: 'r', d: 0 }); buzz(10); }
    else if (quick) { send({ t: 'b', b: 'l', d: 1 }); send({ t: 'b', b: 'l', d: 0 }); lastTap = performance.now(); buzz(6); }
    mode = null; maxPts = 0;
  };
  pad.addEventListener('pointerup', up); pad.addEventListener('pointercancel', up);
  el.querySelectorAll('.tp-btns button').forEach(b => {
    b.addEventListener('pointerdown', e => { b.setPointerCapture(e.pointerId); b.classList.add('down'); send({ t: 'b', b: b.dataset.b, d: 1 }); buzz(8); });
    const rel = () => { if (!b.classList.contains('down')) return; b.classList.remove('down'); send({ t: 'b', b: b.dataset.b, d: 0 }); };
    b.addEventListener('pointerup', rel); b.addEventListener('pointercancel', rel);
  });
})();

/* ================================================================== KEYBOARD */
(() => {
  const el = body('keyboard');
  // [label, key name, width, class]   (label 'shift:x' shows x when shift is on)
  const R = [
    [['Esc','Esc',1.2,'fn'],...[1,2,3,4,5,6,7,8,9,10,11,12].map(i=>[`F${i}`,`F${i}`,1,'fn']),['Del','Delete',1.2,'fn']],
    [['`','`'],['1','1'],['2','2'],['3','3'],['4','4'],['5','5'],['6','6'],['7','7'],['8','8'],['9','9'],['0','0'],['-','-'],['=','='],['⌫','Backspace',1.8,'mod']],
    [['Tab','Tab',1.5,'mod'],...'QWERTYUIOP'.split('').map(c=>[c,c]),['[','['],[']',']'],['\\','\\',1.3]],
    [['Caps','Caps',1.8,'mod'],...'ASDFGHJKL'.split('').map(c=>[c,c]),[';',';'],["'","'"],['Enter','Enter',2,'mod']],
    [['Shift','Shift',2.3,'mod'],...'ZXCVBNM'.split('').map(c=>[c,c]),[',',','],['.','.'],['/','/'],['↑','Up',1,'mod'],['Shift','Shift',1.4,'mod']],
    [['Ctrl','Ctrl',1.3,'mod'],['Win','Win',1.2,'mod'],['Alt','Alt',1.2,'mod'],['Space','Space',6.2],['Alt','Alt',1.1,'mod'],['Ctrl','Ctrl',1.1,'mod'],['←','Left',1,'mod'],['↓','Down',1,'mod'],['→','Right',1,'mod']],
  ];
  el.innerHTML = `<div class="kb"><div class="kb-type"><input id="kbText" placeholder="Type here with the tablet keyboard (swipe and voice typing work)" autocomplete="off" autocapitalize="off">
    <button id="kbSend">Send</button><button class="pri" id="kbSendEnter">Send ↵</button></div>
    <div class="kb-keys">${R.map(row => `<div class="kb-row">${row.map(([l, k, wd = 1, cls = '']) =>
      `<button class="${cls}" data-k="${k}" style="flex:${wd}">${l}</button>`).join('')}</div>`).join('')}</div></div>`;
  const MODS = ['Shift', 'Ctrl', 'Alt', 'Win'];
  const latched = new Set();
  const paint = () => el.querySelectorAll('[data-k]').forEach(b => {
    b.classList.toggle('latched', latched.has(b.dataset.k));
    if (b.dataset.k.length === 1 && /[A-Z]/.test(b.dataset.k)) b.textContent = latched.has('Shift') ? b.dataset.k : b.dataset.k.toLowerCase();
  });
  paint();
  let rep = null;
  el.querySelectorAll('[data-k]').forEach(b => {
    const k = b.dataset.k;
    b.addEventListener('pointerdown', e => {
      e.preventDefault(); b.setPointerCapture(e.pointerId); b.classList.add('down'); buzz(5);
      if (MODS.includes(k)) {                               // tap a modifier = it applies to the next key
        if (latched.has(k)) { latched.delete(k); send({ t: 'k', k, d: 0 }); } else { latched.add(k); send({ t: 'k', k, d: 1 }); }
        paint(); return;
      }
      send({ t: 'k', k, d: 1 });
      if (['Backspace', 'Delete', 'Left', 'Right', 'Up', 'Down', 'Space'].includes(k)) {
        clearTimeout(rep); rep = setTimeout(function again() { send({ t: 'k', k, d: 1 }); rep = setTimeout(again, 55); }, 420);
      }
    });
    const rel = () => {
      if (!b.classList.contains('down')) return; b.classList.remove('down'); clearTimeout(rep);
      if (MODS.includes(k)) return;
      send({ t: 'k', k, d: 0 });
      if (latched.size) { latched.forEach(m => send({ t: 'k', k: m, d: 0 })); latched.clear(); paint(); }
    };
    b.addEventListener('pointerup', rel); b.addEventListener('pointercancel', rel);
  });
  const sendText = enter => { const v = $('kbText').value; if (v) send({ t: 'txt', s: v });
    if (enter) { send({ t: 'k', k: 'Enter', d: 1 }); send({ t: 'k', k: 'Enter', d: 0 }); } $('kbText').value = ''; buzz(8); };
  $('kbSend').onclick = () => sendText(false);
  $('kbSendEnter').onclick = () => sendText(true);
  $('kbText').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); sendText(true); } });
})();

/* ================================================================== GAMEPAD */
(() => {
  const el = body('gamepad');
  el.innerHTML = `<div class="gp" id="gp">
    <div class="el gp-sh" data-p="lt" style="left:2%;top:2%;width:16%;height:12%">LT</div>
    <div class="el gp-sh" data-p="lb" style="left:19%;top:2%;width:14%;height:12%">LB</div>
    <div class="el gp-sh" data-p="rb" style="right:19%;top:2%;width:14%;height:12%">RB</div>
    <div class="el gp-sh" data-p="rt" style="right:2%;top:2%;width:16%;height:12%">RT</div>
    <div class="el gp-sm" data-p="back" style="left:41%;top:22%;width:8%;height:9%">BACK</div>
    <div class="el gp-sm" data-p="start" style="left:51%;top:22%;width:8%;height:9%">START</div>
    <div class="el gp-stick" id="gpStick" style="left:6%;top:22%;width:300px;height:300px"><i class="gp-knob" id="gpKnob"></i></div>
    <div class="el gp-d" data-p="up" style="left:36%;top:52%;width:76px;height:70px;border-radius:14px 14px 4px 4px"><svg class="ic"><use href="#i-up"/></svg></div>
    <div class="el gp-d" data-p="left" style="left:calc(36% - 76px);top:calc(52% + 70px);width:76px;height:70px;border-radius:14px 4px 4px 14px"><svg class="ic" style="transform:rotate(-90deg)"><use href="#i-up"/></svg></div>
    <div class="el gp-d" data-p="right" style="left:calc(36% + 76px);top:calc(52% + 70px);width:76px;height:70px;border-radius:4px 14px 14px 4px"><svg class="ic" style="transform:rotate(90deg)"><use href="#i-up"/></svg></div>
    <div class="el gp-d" data-p="down" style="left:36%;top:calc(52% + 140px);width:76px;height:70px;border-radius:4px 4px 14px 14px"><svg class="ic"><use href="#i-down"/></svg></div>
    <div class="el gp-btn gp-y" data-p="y" style="right:calc(9% + 92px);top:22%;width:96px;height:96px">Y</div>
    <div class="el gp-btn gp-x" data-p="x" style="right:calc(9% + 184px);top:calc(22% + 92px);width:96px;height:96px">X</div>
    <div class="el gp-btn gp-b" data-p="b" style="right:9%;top:calc(22% + 92px);width:96px;height:96px">B</div>
    <div class="el gp-btn gp-a" data-p="a" style="right:calc(9% + 92px);top:calc(22% + 184px);width:96px;height:96px">A</div>
    <div class="gp-info" id="gpInfo"></div></div>`;
  const held = new Set(); let lx = 0, ly = 0, pending = false;
  const push = () => { if (pending) return; pending = true; requestAnimationFrame(() => { pending = false; send({ t: 'pad', b: [...held], lx: +lx.toFixed(2), ly: +ly.toFixed(2) }); }); };
  el.querySelectorAll('[data-p]').forEach(b => {
    b.addEventListener('pointerdown', e => { b.setPointerCapture(e.pointerId); b.classList.add('down'); held.add(b.dataset.p); buzz(12); push(); });
    const rel = () => { b.classList.remove('down'); held.delete(b.dataset.p); push(); };
    b.addEventListener('pointerup', rel); b.addEventListener('pointercancel', rel);
  });
  const stick = $('gpStick'), knob = $('gpKnob');
  const move = e => { const r = stick.getBoundingClientRect(), R = r.width / 2;
    let x = (e.clientX - r.left - R) / R, y = (e.clientY - r.top - R) / R; const m = Math.hypot(x, y); if (m > 1) { x /= m; y /= m; }
    lx = x; ly = y; knob.style.transform = `translate(${x * R * .6}px,${y * R * .6}px)`; push(); };
  stick.addEventListener('pointerdown', e => { stick.setPointerCapture(e.pointerId); move(e); });
  stick.addEventListener('pointermove', e => { if (stick.hasPointerCapture(e.pointerId)) move(e); });
  const center = () => { lx = ly = 0; knob.style.transform = ''; push(); };
  stick.addEventListener('pointerup', center); stick.addEventListener('pointercancel', center);
  Tools._padInfo = mode => { $('gpInfo').innerHTML = mode === 'xbox'
    ? 'Virtual <b>Xbox controller</b> connected'
    : 'Keyboard mode: stick = <b>WASD</b> · A = Space · B = Ctrl · X = E · Y = Q · LB/RB = 1/2 · LT/RT = R/F · D-pad = arrows · Start = Esc · Back = Tab'; };
  Tools._padRelease = () => { held.clear(); center(); };
})();

/* ================================================================== SIGNATURE PAD */
const Sign = (() => {
  const el = body('sign');
  el.innerHTML = `<div class="sg"><div class="sg-paper" id="sgPaper"><div class="sg-line"></div><div class="sg-x">×</div>
      <div class="sg-ph" id="sgPh">Sign here with your finger</div><canvas id="sgCanvas"></canvas></div>
    <div class="sg-bar">
      <button class="sg-ink on" data-ink="#111111" style="background:#111"></button>
      <button class="sg-ink" data-ink="#1838c4" style="background:#1838c4"></button>
      <button class="sg-ink" data-ink="#b3261e" style="background:#b3261e"></button>
      <i class="sg-sep"></i>
      <button class="sg-w" data-w="2.2">Fine</button><button class="sg-w on" data-w="3.4">Medium</button><button class="sg-w" data-w="5">Bold</button>
      <i class="sg-sep"></i>
      <button id="sgUndo"><svg class="ic"><use href="#i-undo"/></svg>Undo</button>
      <button id="sgClear"><svg class="ic"><use href="#i-trash"/></svg>Clear</button>
      <button class="pri" id="sgSave"><svg class="ic"><use href="#i-check"/></svg>Save &amp; copy</button></div></div>`;
  const cv = $('sgCanvas'), ctx = cv.getContext('2d'), paper = $('sgPaper');
  let strokes = [], cur = null, ink = '#111111', width = 3.4, dpr = 1;
  function resize() { const r = paper.getBoundingClientRect(); if (!r.width) return; dpr = window.devicePixelRatio || 1;
    cv.width = r.width * dpr; cv.height = r.height * dpr; redraw(); }
  window.addEventListener('resize', resize);
  // smooth ink: quadratic curves through midpoints, thinner when moving fast
  function drawStroke(c, s, scale = 1, ox = 0, oy = 0) {
    const p = s.pts; if (!p.length) return;
    c.strokeStyle = c.fillStyle = s.ink; c.lineCap = c.lineJoin = 'round';
    if (p.length < 3) { c.beginPath(); c.arc((p[0].x - ox) * scale, (p[0].y - oy) * scale, s.w * scale * .55, 0, 7); c.fill(); return; }
    for (let i = 1; i < p.length - 1; i++) {
      const a = p[i - 1], b = p[i], n = p[i + 1];
      const m1x = (a.x + b.x) / 2, m1y = (a.y + b.y) / 2, m2x = (b.x + n.x) / 2, m2y = (b.y + n.y) / 2;
      c.lineWidth = Math.max(s.w * .45, s.w * b.k) * scale;
      c.beginPath(); c.moveTo((m1x - ox) * scale, (m1y - oy) * scale);
      c.quadraticCurveTo((b.x - ox) * scale, (b.y - oy) * scale, (m2x - ox) * scale, (m2y - oy) * scale); c.stroke();
    }
  }
  function redraw() { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, cv.width, cv.height);
    strokes.forEach(s => drawStroke(ctx, s, dpr)); $('sgPh').style.display = strokes.length ? 'none' : ''; }
  const pos = e => { const r = cv.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top, t: performance.now() }; };
  cv.addEventListener('pointerdown', e => { cv.setPointerCapture(e.pointerId); const p = pos(e); p.k = 1; cur = { ink, w: width, pts: [p] }; strokes.push(cur); redraw(); });
  cv.addEventListener('pointermove', e => {
    if (!cur) return;
    const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [e];
    for (const ev of evs) { const p = pos(ev), l = cur.pts[cur.pts.length - 1];
      const v = Math.hypot(p.x - l.x, p.y - l.y) / Math.max(1, p.t - l.t);     // px per ms
      p.k = l.k * .7 + Math.max(.45, Math.min(1.25, 1.3 - v * .35)) * .3;   // smoothed speed -> thickness
      if (Math.hypot(p.x - l.x, p.y - l.y) > 0.8) cur.pts.push(p); }
    redraw();
  });
  const end = () => { cur = null; };
  cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
  el.querySelectorAll('[data-ink]').forEach(b => b.onclick = () => { ink = b.dataset.ink; el.querySelectorAll('[data-ink]').forEach(x => x.classList.toggle('on', x === b)); });
  el.querySelectorAll('[data-w]').forEach(b => b.onclick = () => { width = +b.dataset.w; el.querySelectorAll('[data-w]').forEach(x => x.classList.toggle('on', x === b)); });
  $('sgUndo').onclick = () => { strokes.pop(); redraw(); };
  $('sgClear').onclick = () => { strokes = []; redraw(); };
  $('sgSave').onclick = async () => {
    if (!strokes.length) return;
    // crop to the signature, export at 3x for a sharp, transparent PNG
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    strokes.forEach(s => s.pts.forEach(p => { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }));
    const pad = 14, S = 3, out = document.createElement('canvas');
    out.width = Math.ceil((x1 - x0 + pad * 2) * S); out.height = Math.ceil((y1 - y0 + pad * 2) * S);
    const c = out.getContext('2d'); strokes.forEach(s => drawStroke(c, s, S, x0 - pad, y0 - pad));
    $('sgSave').disabled = true;
    const r = await fetch('signature', { method: 'POST', body: JSON.stringify({ png: out.toDataURL('image/png') }) }).then(r => r.json()).catch(() => ({}));
    $('sgSave').disabled = false;
    if (r.ok) { buzz([20, 40, 20]); strokes = []; redraw(); }
  };
  return { resize };
})();

/* ------------------------------------------------------------------ public */
Object.assign(Tools, {
  open(tab) {
    let t = tab; try { t = t || localStorage.getItem('ccTool'); } catch {}
    root.classList.add('on'); show(TABS.some(x => x[0] === t) ? t : 'trackpad');
    fetch('input', { method: 'POST', body: '[]' }).then(r => r.json()).then(r => Tools._padInfo && Tools._padInfo(r.pad || 'keyboard')).catch(() => {});
    Tools._padInfo && Tools._padInfo('keyboard');
  },
  close() { root.classList.remove('on'); Tools._padRelease && Tools._padRelease(); },
  isOpen() { return root.classList.contains('on'); },
});
})();
