/* Study sessions on the tablet: focus / break timer, phone watch status, today's numbers.
   The PC keeps the timer (so it survives reloads); this file only draws it and sends taps. */
(() => {
  const $ = id => document.getElementById(id);
  const post = (u, b) => fetch(u, { method: 'POST', body: JSON.stringify(b || {}) }).then(r => r.json()).catch(() => null);
  const APP = !!window.CC;
  const FOCUS = [25, 45, 50, 90], BREAK = [5, 10, 15, 0];
  const R = 172, C = 2 * Math.PI * R;

  document.body.insertAdjacentHTML('beforeend', `
<div class="study" id="study" data-phase="idle">
  <header><div class="st-title"><svg class="ic"><use href="#i-book"/></svg>Study</div>
    <button class="st-x" id="stClose" aria-label="Back to the dashboard"><svg class="ic"><use href="#i-down"/></svg></button></header>
  <div class="st-main">
    <div class="st-left">
      <div class="st-ring">
        <svg viewBox="0 0 380 380"><circle class="trk" cx="190" cy="190" r="${R}"/><circle class="val" id="stArc" cx="190" cy="190" r="${R}"
          stroke-dasharray="${C}" stroke-dashoffset="0"/></svg>
        <div class="st-c"><div class="st-ph" id="stPh">Ready</div><div class="st-time" id="stTime">25:00</div><div class="st-sub" id="stSub">&nbsp;</div></div>
      </div>
      <div class="st-setup" id="stSetup">
        <div class="st-row"><span>Focus</span><div class="st-seg" id="stFocus">${FOCUS.map(m => `<button data-v="${m}">${m} min</button>`).join('')}</div></div>
        <div class="st-row"><span>Break</span><div class="st-seg" id="stBreak">${BREAK.map(m => `<button data-v="${m}">${m ? m + ' min' : 'None'}</button>`).join('')}</div></div>
        <button class="st-go" id="stStart">Start focusing</button>
      </div>
      <div class="st-ctl" id="stCtl">
        <button class="st-b" id="stEnd"><svg class="ic"><use href="#i-x"/></svg><span>End</span></button>
        <button class="st-b big" id="stPause"><svg class="ic fill" id="stPauseIc"><use href="#i-pause"/></svg></button>
        <button class="st-b" id="stSkip"><svg class="ic fill"><use href="#i-next"/></svg><span id="stSkipT">Break</span></button>
      </div>
    </div>
    <div class="st-right">
      <div class="st-card watch" id="stWatch"><i class="st-dot"></i><div><b id="stWatchT">Phone watch</b><p id="stWatchD">Starts with focus time.</p></div></div>
      <div class="st-card"><div class="st-k">Focused today</div><div class="st-big" id="stToday">0m</div>
        <div class="st-bar"><i id="stGoal"></i></div><div class="st-s" id="stGoalT">Goal 4h</div></div>
      <div class="st-two">
        <div class="st-card"><div class="st-k">Sessions</div><div class="st-big" id="stSess">0</div></div>
        <div class="st-card"><div class="st-k">Caught</div><div class="st-big" id="stCaught">0</div></div>
      </div>
      <div class="st-card st-this" id="stThis"></div>
    </div>
  </div>
</div>`);

  let st = {}, off = 0, pickF = null, pickB = null;
  const S = () => window.ccGetS ? ccGetS() : {};
  const fmt = s => { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); };
  const hm = s => { const m = Math.floor(s / 60); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };
  const left = () => st.paused_left != null ? st.paused_left : st.ends - (Date.now() + off) / 1000;

  function render() {
    const el = $('study'), phase = st.phase || 'idle', paused = st.paused_left != null;
    el.dataset.phase = phase; el.classList.toggle('paused', paused);
    const f = pickF || S().study_focus_min || 25, b = pickB != null ? pickB : (S().study_break_min ?? 5);
    $('stFocus').querySelectorAll('button').forEach(x => x.classList.toggle('on', +x.dataset.v === f));
    $('stBreak').querySelectorAll('button').forEach(x => x.classList.toggle('on', +x.dataset.v === b));
    const t = st.today || { focus_s: 0, sessions: 0, caught: 0 };
    $('stToday').textContent = hm(t.focus_s); $('stSess').textContent = t.sessions; $('stCaught').textContent = t.caught;
    $('stGoal').style.width = Math.min(100, t.focus_s / 144) + '%';
    $('stGoalT').textContent = t.focus_s >= 14400 ? 'Goal reached. Legend.' : `${hm(Math.max(0, 14400 - t.focus_s))} to the 4h goal`;
    $('stThis').innerHTML = phase === 'idle' ? '<div class="st-k">Tip</div><p>Put the phone face down, out of reach. The camera only watches during focus time, never on breaks.</p>'
      : `<div class="st-k">This session</div><p><b>${hm(st.session_focus || 0)}</b> focused · round ${st.round}${st.session_caught ? ` · caught <b>${st.session_caught}×</b>` : ' · no phone yet'}</p>`;
    const live = window.Vision && Vision.live;
    $('stWatch').className = 'st-card watch ' + (phase === 'focus' && !paused ? (live ? 'on' : 'wait') : '');
    $('stWatchT').textContent = phase === 'focus' && !paused ? (live ? 'Watching for your phone' : 'Starting the camera…') :
      phase === 'break' ? 'Break: phone allowed' : paused ? 'Paused' : 'Phone watch';
    $('stWatchD').textContent = phase === 'focus' && !paused ? 'Pick it up for ~10 s and I will shout.' :
      phase === 'break' ? 'Stretch, drink water, check messages.' : paused ? 'Resume when you are back.' : 'Starts with focus time.';
    $('stPauseIc').innerHTML = `<use href="#${paused ? 'i-play' : 'i-pause'}"/>`;
    $('stSkipT').textContent = phase === 'break' || !(S().study_break_min) ? 'Next' : 'Break';
    tick();
    pill();
  }

  function tick() {
    const phase = st.phase;
    if (!phase) {
      $('stPh').textContent = 'Ready'; $('stTime').textContent = fmt((pickF || S().study_focus_min || 25) * 60);
      $('stSub').textContent = 'Phone watch turns on with focus'; $('stArc').style.strokeDashoffset = 0; return;
    }
    const total = (phase === 'focus' ? st.focus_min : st.break_min) * 60 || 1, l = left();
    $('stPh').textContent = st.paused_left != null ? 'Paused' : phase === 'focus' ? 'Focus' : 'Break';
    $('stTime').textContent = fmt(l);
    const end = new Date(Date.now() + l * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    $('stSub').textContent = `Round ${st.round} · ${phase === 'focus' ? (st.break_min ? 'break' : 'next round') : 'back to focus'} at ${end}`;
    $('stArc').style.strokeDashoffset = C * (1 - Math.max(0, Math.min(1, l / total)));
  }

  function pill() {                       // the dashboard's status pill
    const p = $('vPill'); if (!p) return;
    const on = !!st.phase, away = (S().away_lock_min || 0) > 0;
    p.style.display = on || away ? '' : 'none';
    p.classList.toggle('live', !!(window.Vision && Vision.live));
    p.classList.toggle('studying', on);
    $('vTxt').textContent = on ? `${st.paused_left != null ? 'Paused' : st.phase === 'focus' ? 'Focus' : 'Break'} ${fmt(left())}` : `Away lock ${S().away_lock_min}m`;
  }

  function open() { $('study').classList.add('show'); render(); }
  function close() { $('study').classList.remove('show'); }

  $('stFocus').onclick = e => { const b = e.target.closest('[data-v]'); if (b) { pickF = +b.dataset.v; render(); } };
  $('stBreak').onclick = e => { const b = e.target.closest('[data-v]'); if (b) { pickB = +b.dataset.v; render(); } };
  $('stStart').onclick = () => post('study', { event: 'start', study_focus_min: pickF || S().study_focus_min || 25,
    study_break_min: pickB != null ? pickB : (S().study_break_min ?? 5) });
  $('stPause').onclick = () => post('study', { event: st.paused_left != null ? 'resume' : 'pause' });
  $('stSkip').onclick = () => post('study', { event: 'skip' });
  let endArm = 0;
  $('stEnd').onclick = () => {                   // tap twice: no ending a session by accident
    if (Date.now() - endArm < 3000) { post('study', { event: 'stop' }); return; }
    endArm = Date.now(); $('stEnd').querySelector('span').textContent = 'Sure?';
    setTimeout(() => { $('stEnd').querySelector('span').textContent = 'End'; }, 3000);
  };
  $('stClose').onclick = close;
  $('vPill').onclick = open;

  const SAY = { focus: 'Focus time. Phone away.', break: 'Break time. You can use your phone now.', start: 'Focus time. Phone away. Let\'s go.' };
  window.Study = {
    open, close, render, isOpen: () => $('study').classList.contains('show'),
    set(next) {
      const ev = next.event;
      st = next || {};
      if (st.now) off = st.now * 1000 - Date.now();
      if (ev === 'start') { pickF = pickB = null; open(); }
      if (SAY[ev] && window.Vision) { window.ccChime && ccChime(); setTimeout(() => Vision.say(SAY[ev]), 600); }
      if (ev === 'stop') close();
      window.Vision && Vision.update();
      render();
    },
  };
  setInterval(() => { if (st.phase) { tick(); pill(); } }, 1000);
  if (window.ccStudy) Study.set({ ...window.ccStudy, event: null });   // the hello can arrive before this file loads
  else render();
})();
