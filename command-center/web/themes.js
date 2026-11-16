// Shared by the tablet dashboard and the desktop settings app.
const THEMES = {
  aurora:   { name: 'Aurora',   base: '#06060a', layers: [['8% 0%', 'rgba(94,44,214,.55)'], ['100% 10%', 'rgba(0,122,255,.38)'], ['70% 105%', 'rgba(255,55,95,.32)'], ['20% 100%', 'rgba(255,159,10,.16)']] },
  midnight: { name: 'Midnight', base: '#04060d', layers: [['10% 0%', 'rgba(30,64,175,.55)'], ['95% 20%', 'rgba(14,116,144,.35)'], ['60% 110%', 'rgba(67,56,202,.35)']] },
  ember:    { name: 'Ember',    base: '#0a0605', layers: [['0% 0%', 'rgba(234,88,12,.45)'], ['100% 30%', 'rgba(190,18,60,.4)'], ['50% 110%', 'rgba(250,204,21,.18)']] },
  ocean:    { name: 'Ocean',    base: '#030a0c', layers: [['5% 5%', 'rgba(13,148,136,.5)'], ['100% 0%', 'rgba(2,132,199,.42)'], ['60% 110%', 'rgba(16,185,129,.22)']] },
  bloom:    { name: 'Bloom',    base: '#0b0509', layers: [['10% 0%', 'rgba(219,39,119,.48)'], ['95% 15%', 'rgba(147,51,234,.42)'], ['45% 110%', 'rgba(251,113,133,.25)']] },
  forest:   { name: 'Forest',   base: '#040805', layers: [['0% 10%', 'rgba(22,163,74,.38)'], ['100% 0%', 'rgba(101,163,13,.28)'], ['60% 110%', 'rgba(13,148,136,.3)']] },
  graphite: { name: 'Graphite', base: '#08080a', layers: [['10% 0%', 'rgba(120,120,135,.35)'], ['100% 20%', 'rgba(80,80,95,.3)'], ['50% 110%', 'rgba(60,60,70,.35)']] },
  black:    { name: 'Pure Black', base: '#000000', layers: [] },
};
const themeCss = t => (THEMES[t] || THEMES.aurora).layers
  .map(([at, c]) => `radial-gradient(70% 85% at ${at}, ${c} 0%, transparent 60%)`).join(',') || 'none';

const ACCENTS = { blue: '#0a84ff', purple: '#bf5af2', pink: '#ff375f', orange: '#ff9f0a', green: '#30d158', teal: '#40c8e0', yellow: '#ffd60a' };

const DOCK_ACTIONS = {
  display:     { label: 'Second Screen',   icon: 'i-screens', g: 'g-teal' },
  tools:       { label: 'Tools',           icon: 'i-tools',  g: 'g-indigo' },
  speaker:     { label: 'Tab Speaker',     icon: 'i-volup',  g: 'g-purple' },
  mic:         { label: 'Tab Mic',         icon: 'i-mic',    g: 'g-pink' },
  lock:        { label: 'Lock PC',         icon: 'i-lock',   g: 'g-gray' },
  snip:        { label: 'Snip',            icon: 'i-snip',   g: 'g-pink' },
  screenshot:  { label: 'Screenshot',      icon: 'i-camera', g: 'g-indigo' },
  taskmgr:     { label: 'Task Manager',    icon: 'i-pulse',  g: 'g-green' },
  desktop:     { label: 'Show Desktop',    icon: 'i-desk',   g: 'g-blue' },
  explorer:    { label: 'Files',           icon: 'i-folder', g: 'g-orange' },
  calc:        { label: 'Calculator',      icon: 'i-calc',   g: 'g-gray' },
  emoji:       { label: 'Emoji',           icon: 'i-smile',  g: 'g-orange' },
  clipboard:   { label: 'Clipboard',       icon: 'i-clip',   g: 'g-indigo' },
  monitor_off: { label: 'Screen Off',      icon: 'i-moon',   g: 'g-indigo' },
  mute:        { label: 'Mute Sound',      icon: 'i-mute',   g: 'g-pink' },
  play:        { label: 'Play / Pause',    icon: 'i-play',   g: 'g-green', fill: true },
};

const WIDGETS = {
  perf:  { name: 'Performance', desc: 'CPU, GPU and memory rings', size: 'Large' },
  gpu:   { name: 'GPU Temperature', desc: 'Temperature, power, VRAM', size: 'Small' },
  net:   { name: 'Network', desc: 'Live download and upload', size: 'Small' },
  media: { name: 'Now Playing', desc: 'Song, artwork, seek bar, volume bar', size: 'Full width' },
  mic:   { name: 'Tab Mic', desc: 'Use the tablet as your mic', size: 'Small' },
  hist:  { name: 'History', desc: 'CPU, GPU and RAM graphs (5 or 30 min)', size: 'Wide' },
};

const loadSprite = () => fetch('icons.svg').then(r => r.text()).then(t => {
  const d = document.getElementById('sprite'); if (d) d.innerHTML = t;
});
