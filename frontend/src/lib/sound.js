// Minimal cinematic sound design via Web Audio API (no asset files).
let ctx = null;
function ac() {
  if (typeof window === 'undefined') return null;
  if (!ctx) { const AC = window.AudioContext || window.webkitAudioContext; if (AC) ctx = new AC(); }
  if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}

// short mechanical switch click
export function playSwitch() {
  const c = ac(); if (!c) return;
  const t = c.currentTime;
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = 'square';
  o.frequency.setValueAtTime(180, t);
  o.frequency.exponentialRampToValueAtTime(70, t + 0.05);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.25, t + 0.005);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.09);
  o.connect(g).connect(c.destination);
  o.start(t); o.stop(t + 0.1);
}

// airy whoosh (filtered noise sweep)
export function playWhoosh() {
  const c = ac(); if (!c) return;
  const t = c.currentTime;
  const dur = 0.5;
  const buffer = c.createBuffer(1, c.sampleRate * dur, c.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
  const src = c.createBufferSource(); src.buffer = buffer;
  const filter = c.createBiquadFilter(); filter.type = 'bandpass';
  filter.frequency.setValueAtTime(400, t);
  filter.frequency.exponentialRampToValueAtTime(2600, t + dur);
  filter.Q.value = 0.8;
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.18, t + 0.12);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(g).connect(c.destination);
  src.start(t); src.stop(t + dur);
}

// soft low impact for the reveal
export function playImpact() {
  const c = ac(); if (!c) return;
  const t = c.currentTime;
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = 'sine';
  o.frequency.setValueAtTime(120, t);
  o.frequency.exponentialRampToValueAtTime(45, t + 0.3);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.3, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.35);
  o.connect(g).connect(c.destination);
  o.start(t); o.stop(t + 0.36);
}
