/* TabDeck camera: study-session phone watch (phone in your hand -> shout) and away lock.
   Google MediaPipe runs right here on the tablet (WASM + GPU). No image is stored or sent anywhere: the PC only
   gets tiny events (/presence {present}, /study {event:"caught"}). The camera is only on while a study session is
   in focus time, or while away lock is switched on. */
const V = 'vision/';
const $ = id => document.getElementById(id);
const S = () => window.ccGetS ? window.ccGetS() : {};
const ST = () => window.ccStudy || {};
const post = (u, b) => fetch(u, { method: 'POST', body: JSON.stringify(b || {}) }).then(r => r.json()).catch(() => null);
const APP = !!window.CC, PREVIEW = /[?&]preview/.test(location.search);
const log = m => post('vlog', { m });
const focusing = () => ST().phase === 'focus' && ST().paused_left == null;
const awayOn = () => (S().away_lock_min || 0) > 0;
const want = () => !PREVIEW && (focusing() || awayOn());

let mp = null, video = null, stream = null, running = false, starting = false;
const models = {};
const DELEGATE = localStorage.getItem('vDelegate') || 'GPU';   // measured ~3x faster than CPU on a Helio P22 tablet
const fileset = { wasmLoaderPath: V + 'vision_wasm_internal.js', wasmBinaryPath: V + 'vision_wasm_internal.wasm' };
const timing = {};
function timed(kind, fn) {
  const t = performance.now(), r = fn(), a = timing[kind] || (timing[kind] = { n: 0, ms: 0 });
  a.n++; a.ms += performance.now() - t;
  return r;
}
setInterval(() => {
  const k = Object.keys(timing);
  if (k.length) log('avg ms ' + k.map(x => `${x}=${(timing[x].ms / timing[x].n).toFixed(0)} (${timing[x].n}x)`).join(' '));
  for (const x of k) delete timing[x];
}, 60000);

/* ------------------------------------------------------------------ camera + models (created only when needed) */
async function make(kind) {
  if (models[kind]) return models[kind];
  if (!mp) mp = await import('./' + V + 'vision_bundle.mjs');
  const file = { hand: 'hand_landmarker.task', face: 'blaze_face_short_range.tflite', phone: 'efficientdet_lite0.tflite' }[kind];
  const opts = d => ({ baseOptions: { modelAssetPath: V + file, delegate: d }, runningMode: 'VIDEO' });
  const build = d => kind === 'hand'
    ? mp.HandLandmarker.createFromOptions(fileset, { ...opts(d), numHands: 2, minHandDetectionConfidence: 0.5 })
    : kind === 'face'
      ? mp.FaceDetector.createFromOptions(fileset, { ...opts(d), minDetectionConfidence: 0.5 })
      : mp.ObjectDetector.createFromOptions(fileset, { ...opts(d), runningMode: 'IMAGE', scoreThreshold: 0.05, maxResults: 3, categoryAllowlist: ['cell phone'] });
  const t0 = performance.now();
  // the phone model is int8-quantised: the tablet's GPU path returns garbage for it (didn't even see a person),
  // so it always runs on the CPU. Hand + face models are float16 and are fine (and faster) on the GPU.
  const dev = kind === 'phone' ? 'CPU' : DELEGATE;
  try { models[kind] = await build(dev); }
  catch (e) { log(`${kind}: ${dev} failed (${e && e.message}), using CPU`); models[kind] = await build('CPU'); }
  log(`${kind} model ready in ${Math.round(performance.now() - t0)} ms`);
  return models[kind];
}

async function startCam() {
  if (running || starting) return;
  starting = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: false,
      video: { facingMode: 'user', width: { ideal: 480 }, height: { ideal: 360 }, frameRate: { ideal: 15, max: 15 } } });
    video = Object.assign(document.createElement('video'), { muted: true, playsInline: true, className: 'vcam', srcObject: stream });
    document.body.appendChild(video);
    await video.play();
    running = true;
    loop();
  } catch (e) {
    log('camera error: ' + (e && (e.name + ' ' + e.message)));
    window.ccBanner && ccBanner({ title: 'Camera unavailable', body: String(e && e.message || e).slice(0, 80), level: 'warn' });
  } finally { starting = false; window.Study && Study.render(); }
}

function stopCam() {
  running = false;
  stream && stream.getTracks().forEach(t => t.stop());
  video && video.remove();
  stream = video = null;
  Object.values(models).forEach(m => { try { m.close(); } catch {} });
  for (const k in models) delete models[k];
  window.Study && Study.render();
}

/* ------------------------------------------------------------------ the loop */
let lastFace = 0, lastPhone = 0, faceSeenAt = Date.now();
async function loop() {
  while (running) {
    const now = Date.now();
    try {
      if (video.readyState >= 2) {
        if (focusing() && now - lastPhone > (alarmOn ? 1500 : 3000)) { lastPhone = now; await phoneCheck(); }
        if (awayOn() && now - lastFace > 2000) {
          lastFace = now;
          const fm = await make('face');
          if (timed('face', () => fm.detectForVideo(video, performance.now())).detections.length) faceSeenAt = now;
          presence(now);
        }
      }
    } catch (e) { log('loop error: ' + (e && e.message)); await sleep(1000); }
    await sleep(300);
    if (!want()) { stopCam(); return; }
  }
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ------------------------------------------------------------------ phone in hand -> shout */
const hist = [];            // last checks: true = a phone with a hand on it
let alarmOn = false, snoozeUntil = 0, clearChecks = 0;
/* Hand first, then zoom: a phone held in front of the tablet camera is usually small, at the edge of the frame and
   seen from the back, so the whole-frame model barely sees it (0.16 on a real frame). Cut a square around your hand(s)
   and look there: on the same frame the phone scored 0.26, while hands without a phone (typing, resting) stayed under
   0.08 in ~100 checks. Only the small model: the bigger Lite2 froze this tablet. */
const crop = Object.assign(document.createElement('canvas'), { width: 320, height: 320 });
const PHONE_MIN = 0.18;
let noHandChecks = 0;
function cropAround(points, W, H) {
  const xs = points.map(p => p.x * W), ys = points.map(p => p.y * H);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const side = Math.max(x1 - x0, y1 - y0) * 2.2, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2 - (y1 - y0) * 0.3;
  const g = crop.getContext('2d');
  g.fillStyle = '#000'; g.fillRect(0, 0, 320, 320);
  g.drawImage(video, cx - side / 2, cy - side / 2, side, side, 0, 0, 320, 320);
  return crop;
}
async function phoneCheck() {
  const W = video.videoWidth, H = video.videoHeight;
  const hm = await make('hand'), pm = await make('phone');
  const hands = timed('hand', () => hm.detectForVideo(video, performance.now())).landmarks;
  let best = 0;
  const score = r => { for (const d of r.detections) best = Math.max(best, d.categories[0].score); };
  if (hands.length) {
    noHandChecks = 0; faceSeenAt = Date.now();
    // two hands close together = probably holding one thing: one crop around both; otherwise one per hand
    const both = hands.length === 2 && Math.hypot(hands[0][9].x - hands[1][9].x, hands[0][9].y - hands[1][9].y) < 0.35;
    for (const pts of both ? [hands[0].concat(hands[1])] : hands.slice(0, 2))
      score(timed('phone', () => pm.detect(cropAround(pts, W, H))));
  } else if (++noHandChecks % 3 === 0) {      // hand hidden behind the phone? look at the whole frame now and then
    const r = timed('phone', () => pm.detect(video));
    for (const d of r.detections) best = Math.max(best, d.categories[0].score - 0.12);   // stricter without a hand
  }
  const inHand = best >= PHONE_MIN;
  if (best >= 0.08) log(`phone score ${best.toFixed(2)} (${hands.length} hand${hands.length === 1 ? '' : 's'})${inHand ? ' -> counts' : ''}`);
  hist.push(inHand); if (hist.length > 6) hist.shift();
  if (alarmOn) {
    clearChecks = inHand ? 0 : clearChecks + 1;
    if (clearChecks >= 3) alarmStop(true);
  } else if (Date.now() > snoozeUntil && hist.filter(Boolean).length >= 3) {
    alarmStart('phone');
    post('study', { event: 'caught', where: 'phone' });
  }
}

const LINES = {
  phone: ['Hey! Put the phone down. You are in study mode.', 'No reels right now. Back to studying!',
    'Phone down. Your exams will not pass themselves.', 'Drop it. Reels can wait. Study first.',
    'I can see you scrolling. Put it away!'],
  laptop: w => [`Close ${w}. You are in study mode.`, `No ${w} right now. Back to work!`, `Hey! ${w} can wait. Study first.`],
};
let shoutTimer = null, sirenCtx = null, laptopTimer = null;
function alarmStart(where, what) {
  const box = $('vAlarm');
  box.querySelector('h2').textContent = where === 'phone' ? 'Put the phone down' : `Close ${what || 'that'}`;
  box.querySelector('p').textContent = where === 'phone' ? 'Focus time. I can see you scrolling.' : 'Focus time. Reels can wait.';
  box.classList.add('show');
  if (alarmOn) return;
  alarmOn = true; clearChecks = 0;
  if (APP) { CC.alarm(true); if (CC.isDisplay()) CC.setDisplay(false); }
  const lines = where === 'phone' ? LINES.phone : LINES.laptop(what || 'that');
  let i = Math.floor(Math.random() * lines.length);
  const shout = () => {               // tablet AND laptop: siren, then the voice
    const line = lines[i++ % lines.length];
    siren(); setTimeout(() => say(line), 1100);
    post('study', { event: 'shout', text: line });
  };
  shout(); shoutTimer = setInterval(shout, 7000);
}
function alarmStop(good) {
  if (!alarmOn) return;
  alarmOn = false; clearInterval(shoutTimer); shoutTimer = null; hist.length = 0;
  $('vAlarm').classList.remove('show');
  if (APP) CC.alarm(false);
  post('study', { event: 'alarm_off', text: good ? 'Good. Back to studying.' : '' });
  if (good) say('Good. Back to studying.');
}
function say(t) {
  if (APP && CC.say) return CC.say(t);
  try { speechSynthesis.speak(Object.assign(new SpeechSynthesisUtterance(t), { rate: 1.05, volume: 1 })); } catch {}
}
function siren() {
  try {
    sirenCtx = sirenCtx || new AudioContext(); sirenCtx.resume();
    const t = sirenCtx.currentTime, o = sirenCtx.createOscillator(), g = sirenCtx.createGain();
    o.type = 'sawtooth';
    for (let k = 0; k < 4; k++) { o.frequency.setValueAtTime(700, t + k * 0.25); o.frequency.linearRampToValueAtTime(1300, t + k * 0.25 + 0.22); }
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.5, t + 0.03); g.gain.setValueAtTime(0.5, t + 0.95);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 1.05);
    o.connect(g).connect(sirenCtx.destination); o.start(t); o.stop(t + 1.1);
  } catch {}
}

/* ------------------------------------------------------------------ away: tell the PC when nobody's at the desk */
let reported = null, reportedAt = 0;
function presence(now) {
  const present = now - faceSeenAt < 30000;          // 30 s without a face = away (the PC applies your threshold)
  if (present !== reported || now - reportedAt > 30000) {
    reported = present; reportedAt = now;
    post('presence', { present, for: present ? 0 : 30 });
  }
}

$('vSnooze').addEventListener('click', () => { snoozeUntil = Date.now() + 2 * 60000; alarmStop(false); say('Okay. Two minutes.'); });

window.Vision = {
  say,
  get live() { return running; },
  update() {                                  // settings or study state changed
    if (!focusing()) alarmStop(false);
    if (want()) startCam(); else if (running) stopCam();
  },
  async debug() {                             // one annotated frame + every object the model sees (troubleshooting)
    const was = running;
    if (!running) { await startCam(); await sleep(1500); }
    if (!video) return;
    if (!mp) mp = await import('./' + V + 'vision_bundle.mjs');
    const all = await mp.ObjectDetector.createFromOptions(fileset, { baseOptions: { modelAssetPath: V + 'efficientdet_lite0.tflite', delegate: 'CPU' },
      runningMode: 'IMAGE', scoreThreshold: 0.1, maxResults: 15 });
    const c = Object.assign(document.createElement('canvas'), { width: video.videoWidth, height: video.videoHeight });
    const g = c.getContext('2d'); g.drawImage(video, 0, 0);
    const r = all.detect(c); all.close();
    const hands = (await make('hand')).detectForVideo(video, performance.now());
    g.lineWidth = 2; g.font = '14px sans-serif';
    for (const d of r.detections) { const b = d.boundingBox, k = d.categories[0];
      g.strokeStyle = g.fillStyle = k.categoryName === 'cell phone' ? '#ff3b30' : '#ffd60a';
      g.strokeRect(b.originX, b.originY, b.width, b.height); g.fillText(`${k.categoryName} ${k.score.toFixed(2)}`, b.originX + 3, b.originY + 15); }
    g.fillStyle = '#30d158';
    for (const l of hands.landmarks) for (const q of l) g.fillRect(q.x * c.width - 2, q.y * c.height - 2, 4, 4);
    log(`debug ${c.width}x${c.height} objects: ` + r.detections.map(d => `${d.categories[0].categoryName} ${d.categories[0].score.toFixed(2)}`).join(', ') + ` | hands: ${hands.landmarks.length}`);
    await post('vsnap', { jpg: c.toDataURL('image/jpeg', 0.8) });
    if (!was && !want()) stopCam();
  },
  laptopAlarm(d) {                            // the PC saw a reel site in the front window (or "Test the alarm")
    if (PREVIEW || (!d.test && (!focusing() || Date.now() < snoozeUntil))) return;
    alarmStart(d.where === 'phone' ? 'phone' : 'laptop', d.what);
    clearTimeout(laptopTimer); laptopTimer = setTimeout(() => alarmStop(false), 9000);
  },
};
Vision.update();
