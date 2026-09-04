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

// warm, sensual whoosh (low filtered noise sweep with soft tail)
export function playWhoosh() {
  const c = ac(); if (!c) return;
  const t = c.currentTime;
  const dur = 0.85;
  const buffer = c.createBuffer(1, c.sampleRate * dur, c.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
  const src = c.createBufferSource(); src.buffer = buffer;
  const filter = c.createBiquadFilter(); filter.type = 'lowpass';
  filter.frequency.setValueAtTime(240, t);
  filter.frequency.exponentialRampToValueAtTime(1400, t + dur * 0.6);
  filter.frequency.exponentialRampToValueAtTime(300, t + dur);
  filter.Q.value = 1.2;
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.16, t + 0.15);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  src.connect(filter).connect(g).connect(c.destination);
  src.start(t); src.stop(t + dur);
  // sultry low sine underlay
  const o = c.createOscillator(); const og = c.createGain();
  o.type = 'sine'; o.frequency.setValueAtTime(90, t); o.frequency.exponentialRampToValueAtTime(60, t + dur);
  og.gain.setValueAtTime(0.0001, t); og.gain.exponentialRampToValueAtTime(0.12, t + 0.2); og.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(og).connect(c.destination); o.start(t); o.stop(t + dur);
}

// warm impact + soft shimmer (two detuned sines)
export function playImpact() {
  const c = ac(); if (!c) return;
  const t = c.currentTime;
  [110, 55].forEach((f, i) => {
    const o = c.createOscillator(); const g = c.createGain();
    o.type = 'sine';
    o.frequency.setValueAtTime(f * (i ? 1 : 1.5), t);
    o.frequency.exponentialRampToValueAtTime(f * 0.5, t + 0.45);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(i ? 0.32 : 0.2, t + 0.03);
    g.gain.exponentialRampToValueAtTime(0.0001, t + 0.5);
    o.connect(g).connect(c.destination); o.start(t); o.stop(t + 0.52);
  });
  // brief warm shimmer
  const s = c.createOscillator(); const sg = c.createGain();
  s.type = 'triangle'; s.frequency.setValueAtTime(900, t + 0.05); s.frequency.exponentialRampToValueAtTime(1500, t + 0.35);
  sg.gain.setValueAtTime(0.0001, t + 0.05); sg.gain.exponentialRampToValueAtTime(0.06, t + 0.12); sg.gain.exponentialRampToValueAtTime(0.0001, t + 0.4);
  s.connect(sg).connect(c.destination); s.start(t + 0.05); s.stop(t + 0.42);
}
