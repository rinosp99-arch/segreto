// Secret Side audio — single protagonist track "Velluto Nero".
// Web Audio API for a truly GAPLESS loop + reliable iOS/Safari unlock inside the user gesture.
// Falls back to HTMLAudioElement if Web Audio/decode is unavailable.
// Source: AAC/M4A primary (mobile-friendly) with MP3 fallback.

const BASE = '/audio/';
const TRACK_M4A = BASE + 'velluto-nero.m4a';
const TRACK_MP3 = BASE + 'velluto-nero.mp3';
// kept for API compatibility (admin selector shows a single track now)
export const AUDIO_PRESETS = ['velluto-nero'];

let _sharedBuffer = null;      // decoded AudioBuffer (shared across models — same track)
let _bufferPromise = null;

class AudioController {
  constructor() {
    this.ctx = null;
    this.gain = null;
    this.source = null;
    this.muted = false;
    this.vol = 0.22;
    this.unlocked = false;
    this._token = 0;
    // HTMLAudio fallback
    this.fallbackEl = null;
    this.useFallback = false;
  }

  _ensureCtx() {
    if (this.ctx) return this.ctx;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { this.useFallback = true; return null; }
    try { this.ctx = new AC(); } catch (e) { this.useFallback = true; return null; }
    return this.ctx;
  }

  _loadBuffer() {
    if (_sharedBuffer) return Promise.resolve(_sharedBuffer);
    if (_bufferPromise) return _bufferPromise;
    const ctx = this.ctx;
    const decode = (url) => fetch(url).then((r) => r.arrayBuffer()).then((ab) => new Promise((res, rej) => {
      const p = ctx.decodeAudioData(ab, res, rej);
      if (p && p.then) p.then(res).catch(rej);
    }));
    _bufferPromise = decode(TRACK_M4A)
      .catch(() => decode(TRACK_MP3))
      .then((buf) => { _sharedBuffer = buf; return buf; })
      .catch(() => { this.useFallback = true; return null; });
    return _bufferPromise;
  }

  // MUST run synchronously inside a user gesture (tap on "NON DOVRESTI PREMERLO").
  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    const ctx = this._ensureCtx();
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      // silent 1-frame buffer to fully unlock iOS audio
      const b = ctx.createBuffer(1, 1, ctx.sampleRate);
      const s = ctx.createBufferSource();
      s.buffer = b; s.connect(ctx.destination); s.start(0);
    } catch (e) { /* noop */ }
    this._loadBuffer(); // begin fetching/decoding immediately
  }

  // Extremely discreet micro-click at the press (optional). NOT the invasive old design.
  playActivation(volume = 0.6) {
    if (this.muted) return;
    const ctx = this._ensureCtx();
    if (!ctx) return;
    try {
      const t = ctx.currentTime;
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      const lp = ctx.createBiquadFilter();
      lp.type = 'lowpass'; lp.frequency.value = 520;
      o.type = 'sine'; o.frequency.setValueAtTime(420, t);
      const peak = Math.max(0.01, Math.min(0.06, 0.05 * volume));
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(peak, t + 0.012);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
      o.connect(lp).connect(g).connect(ctx.destination);
      o.start(t); o.stop(t + 0.16);
    } catch (e) { /* noop */ }
  }

  _rampGain(target, ms) {
    if (!this.gain || !this.ctx) return;
    const now = this.ctx.currentTime;
    const g = this.gain.gain;
    try {
      g.cancelScheduledValues(now);
      g.setValueAtTime(Math.max(0.0001, g.value), now);
      g.linearRampToValueAtTime(Math.max(0.0001, target), now + Math.max(0.02, ms / 1000));
    } catch (e) { /* noop */ }
  }

  // Start the Velluto Nero loop with a gentle fade-in (gapless via AudioBufferSourceNode.loop).
  async startAmbient(_preset, volume = 0.22, fadeMs = 2000) {
    if (this.muted) return;
    this.vol = Math.max(0, Math.min(1, volume));
    const ctx = this._ensureCtx();
    if (!ctx || this.useFallback) return this._fallbackStart(this.vol, fadeMs);
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) { /* noop */ } }
    const token = ++this._token;
    const buf = await this._loadBuffer();
    if (token !== this._token) return undefined; // superseded (stopped / model changed)
    if (this.useFallback || !buf) return this._fallbackStart(this.vol, fadeMs);
    // already playing -> just adjust volume
    if (this.source) { this._rampGain(this.vol, fadeMs); return undefined; }
    try {
      const src = ctx.createBufferSource();
      src.buffer = buf; src.loop = true; // sample-accurate gapless loop
      const g = ctx.createGain(); g.gain.value = 0.0001;
      src.connect(g).connect(ctx.destination);
      src.start(0);
      this.source = src; this.gain = g;
      this._rampGain(this.vol, fadeMs);
    } catch (e) { return this._fallbackStart(this.vol, fadeMs); }
    return undefined;
  }

  stopAmbient(fadeMs = 1500) {
    this._token++; // cancel any pending start
    if (this.useFallback) return this._fallbackStop(fadeMs);
    if (!this.source || !this.gain || !this.ctx) return;
    const src = this.source; const g = this.gain;
    this.source = null; this.gain = null;
    this._rampGain.call({ ctx: this.ctx, gain: g }, 0, fadeMs);
    const stopAt = this.ctx.currentTime + Math.max(0.05, fadeMs / 1000) + 0.05;
    try { src.stop(stopAt); } catch (e) { /* noop */ }
    setTimeout(() => { try { src.disconnect(); g.disconnect(); } catch (e) { /* noop */ } }, fadeMs + 120);
  }

  setMuted(m) {
    this.muted = !!m;
    if (this.muted) this.stopAmbient(500);
  }

  cleanup() {
    this._token++;
    try { if (this.source) this.source.stop(); } catch (e) { /* noop */ }
    try { if (this.source) this.source.disconnect(); if (this.gain) this.gain.disconnect(); } catch (e) { /* noop */ }
    this.source = null; this.gain = null;
    this._fallbackStop(0);
    this.unlocked = false;
  }

  // ---- HTMLAudioElement fallback (loop attribute) ----
  _fallbackStart(volume, fadeMs) {
    try {
      if (!this.fallbackEl) {
        const a = new Audio();
        a.src = TRACK_M4A; a.loop = true; a.preload = 'auto';
        a.setAttribute('playsinline', ''); a.playsInline = true;
        a.onerror = () => { if (a.src.indexOf('.mp3') === -1) { a.src = TRACK_MP3; a.play().catch(() => {}); } };
        document.body.appendChild(a); a.style.display = 'none';
        this.fallbackEl = a;
      }
      const a = this.fallbackEl;
      a.volume = 0.0001;
      const p = a.play(); if (p && p.catch) p.catch(() => {});
      const t0 = performance.now(); const target = Math.max(0, Math.min(1, volume));
      const step = (now) => { const k = Math.min(1, (now - t0) / Math.max(1, fadeMs)); a.volume = Math.max(0, Math.min(1, target * k)); if (k < 1) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    } catch (e) { /* noop */ }
    return undefined;
  }

  _fallbackStop(fadeMs) {
    const a = this.fallbackEl; if (!a) return;
    const t0 = performance.now(); const sv = a.volume;
    const step = (now) => { const k = Math.min(1, (now - t0) / Math.max(1, fadeMs)); a.volume = Math.max(0, sv * (1 - k)); if (k < 1) requestAnimationFrame(step); else { try { a.pause(); a.currentTime = 0; } catch (e) { /* noop */ } } };
    if (fadeMs <= 0) { try { a.pause(); a.currentTime = 0; a.removeAttribute('src'); a.remove && a.remove(); } catch (e) { /* noop */ } this.fallbackEl = null; return; }
    requestAnimationFrame(step);
  }

  // Admin-only preview (desktop): play the track briefly with fade in/out.
  preview(_preset, volume = 0.5, seconds = 10) {
    const a = new Audio();
    a.src = TRACK_M4A; a.loop = true; a.preload = 'auto';
    a.onerror = () => { if (a.src.indexOf('.mp3') === -1) { a.src = TRACK_MP3; a.play().catch(() => {}); } };
    a.volume = 0.0001;
    const p = a.play(); if (p && p.catch) p.catch(() => {});
    const t0 = performance.now();
    const fin = (now) => { const k = Math.min(1, (now - t0) / 800); a.volume = Math.min(volume, volume * k); if (k < 1) requestAnimationFrame(fin); };
    requestAnimationFrame(fin);
    const stop = () => {
      const s0 = performance.now(); const sv = a.volume;
      const fo = (now) => { const k = Math.min(1, (now - s0) / 800); a.volume = Math.max(0, sv * (1 - k)); if (k < 1) requestAnimationFrame(fo); else { try { a.pause(); a.removeAttribute('src'); } catch (e) { /* noop */ } } };
      requestAnimationFrame(fo);
    };
    const to = setTimeout(stop, seconds * 1000);
    return { stop: () => { clearTimeout(to); stop(); }, el: a };
  }
}

let _ctrl = null;
export function getAudio() {
  if (typeof window === 'undefined') return null;
  if (!_ctrl) _ctrl = new AudioController();
  return _ctrl;
}
