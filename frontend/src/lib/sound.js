// Secret Side audio — plays a selectable ambient track (default "Velluto Nero").
// Web Audio API for a truly GAPLESS loop + reliable iOS/Safari unlock inside the user gesture.
// Falls back to HTMLAudioElement if Web Audio/decode is unavailable.

export const AUDIO_PRESETS = ['velluto-nero'];

const _buffers = {};        // url -> decoded AudioBuffer
const _bufferPromises = {}; // url -> promise

class AudioController {
  constructor() {
    this.ctx = null;
    this.gain = null;
    this.source = null;
    this.muted = false;
    this.vol = 0.22;
    this.unlocked = false;
    this._token = 0;
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

  _loadBuffer(urls) {
    const key = urls.m4a || urls.mp3;
    if (_buffers[key]) return Promise.resolve(_buffers[key]);
    if (_bufferPromises[key]) return _bufferPromises[key];
    const ctx = this.ctx;
    const decode = (url) => fetch(url).then((r) => r.arrayBuffer()).then((ab) => new Promise((res, rej) => {
      const p = ctx.decodeAudioData(ab, res, rej);
      if (p && p.then) p.then(res).catch(rej);
    }));
    _bufferPromises[key] = decode(urls.m4a || urls.mp3)
      .catch(() => decode(urls.mp3 || urls.m4a))
      .then((buf) => { _buffers[key] = buf; return buf; })
      .catch(() => { this.useFallback = true; return null; });
    return _bufferPromises[key];
  }

  // MUST run synchronously inside a user gesture (tap on "NON DOVRESTI PREMERLO").
  unlock() {
    if (this.unlocked) return;
    this.unlocked = true;
    const ctx = this._ensureCtx();
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
      const b = ctx.createBuffer(1, 1, ctx.sampleRate);
      const s = ctx.createBufferSource();
      s.buffer = b; s.connect(ctx.destination); s.start(0);
    } catch (e) { /* noop */ }
  }

  // Extremely discreet micro-click at the press (optional).
  playActivation(volume = 0.6) {
    if (this.muted) return;
    const ctx = this._ensureCtx();
    if (!ctx) return;
    try {
      if (ctx.state === 'suspended') ctx.resume().catch(() => {});
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

  _rampGainOn(gainNode, ctx, target, ms) {
    if (!gainNode || !ctx) return;
    const now = ctx.currentTime;
    try {
      gainNode.gain.cancelScheduledValues(now);
      gainNode.gain.setValueAtTime(Math.max(0.0001, gainNode.gain.value), now);
      gainNode.gain.linearRampToValueAtTime(Math.max(0.0001, target), now + Math.max(0.02, ms / 1000));
    } catch (e) { /* noop */ }
  }

  async startAmbient(urls, volume = 0.22, fadeMs = 2000) {
    if (this.muted) return;
    this.vol = Math.max(0, Math.min(1, volume));
    this.currentUrls = urls;
    const ctx = this._ensureCtx();
    if (!ctx || this.useFallback) return this._fallbackStart(urls, this.vol, fadeMs);
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) { /* noop */ } }
    const token = ++this._token;
    const buf = await this._loadBuffer(urls);
    if (token !== this._token) return undefined;
    if (this.useFallback || !buf) return this._fallbackStart(urls, this.vol, fadeMs);
    if (this.source) { this._rampGainOn(this.gain, this.ctx, this.vol, fadeMs); return undefined; }
    try {
      const src = ctx.createBufferSource();
      src.buffer = buf; src.loop = true;
      const g = ctx.createGain(); g.gain.value = 0.0001;
      src.connect(g).connect(ctx.destination);
      src.start(0);
      this.source = src; this.gain = g;
      this._rampGainOn(g, ctx, this.vol, fadeMs);
    } catch (e) { return this._fallbackStart(urls, this.vol, fadeMs); }
    return undefined;
  }

  /* Profile-to-profile switch (swipe) while in Lato Segreto: same track -> keep playing untouched;
     different track -> short crossfade (old fades out while the new one fades in); never two loops left running. */
  isPlayingUrls(urls) {
    const cur = this.currentUrls || {};
    const same = !!urls && (cur.m4a || cur.mp3) && ((urls.m4a && urls.m4a === cur.m4a) || (urls.mp3 && urls.mp3 === cur.mp3));
    const playing = this.useFallback ? !!(this.fallbackEl && !this.fallbackEl.paused) : !!this.source;
    return same && playing;
  }

  async switchAmbient(urls, volume = 0.22, fadeMs = 600) {
    if (this.muted) return undefined;
    if (this.isPlayingUrls(urls)) {
      this.vol = Math.max(0, Math.min(1, volume));
      if (!this.useFallback && this.gain && this.ctx) this._rampGainOn(this.gain, this.ctx, this.vol, fadeMs);
      else if (this.fallbackEl) this.fallbackEl.volume = this.vol;
      return undefined;
    }
    if (this.useFallback) { this._fallbackStop(0); return this.startAmbient(urls, volume, fadeMs); }   // single <audio>: swap src cleanly
    this.stopAmbient(Math.min(350, fadeMs));           // detaches this.source -> startAmbient creates the new one
    return this.startAmbient(urls, volume, fadeMs);
  }

  stopAmbient(fadeMs = 1500) {
    this._token++;
    if (this.useFallback) return this._fallbackStop(fadeMs);
    if (!this.source || !this.gain || !this.ctx) return;
    const src = this.source; const g = this.gain; const ctx = this.ctx;
    this.source = null; this.gain = null;
    this._rampGainOn(g, ctx, 0, fadeMs);
    const stopAt = ctx.currentTime + Math.max(0.05, fadeMs / 1000) + 0.05;
    try { src.stop(stopAt); } catch (e) { /* noop */ }
    setTimeout(() => { try { src.disconnect(); g.disconnect(); } catch (e) { /* noop */ } }, fadeMs + 120);
  }

  setMuted(m) { this.muted = !!m; if (this.muted) this.stopAmbient(500); }

  // Immediate hard stop (no fade): return to public / model change / leave page.
  stopImmediate() {
    this._token++;
    try { if (this.source) this.source.stop(0); } catch (e) { /* noop */ }
    try { if (this.source) this.source.disconnect(); if (this.gain) this.gain.disconnect(); } catch (e) { /* noop */ }
    this.source = null; this.gain = null;
    const a = this.fallbackEl;
    if (a) { try { a.pause(); a.currentTime = 0; } catch (e) { /* noop */ } }
  }

  cleanup() {
    this._token++;
    try { if (this.source) this.source.stop(); } catch (e) { /* noop */ }
    try { if (this.source) this.source.disconnect(); if (this.gain) this.gain.disconnect(); } catch (e) { /* noop */ }
    this.source = null; this.gain = null;
    this._fallbackStop(0);
    this.unlocked = false;
  }

  _fallbackStart(urls, volume, fadeMs) {
    try {
      if (!this.fallbackEl) {
        const a = new Audio();
        a.src = urls.m4a || urls.mp3; a.loop = true; a.preload = 'auto';
        a.setAttribute('playsinline', ''); a.playsInline = true;
        a.onerror = () => { if (urls.mp3 && a.src.indexOf(urls.mp3) === -1) { a.src = urls.mp3; a.play().catch(() => {}); } };
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

  // Admin-only preview (desktop): play a track briefly with fade in/out.
  preview(urls, volume = 0.5, seconds = 10) {
    const a = new Audio();
    a.src = urls.m4a || urls.mp3; a.loop = true; a.preload = 'auto';
    a.onerror = () => { if (urls.mp3 && a.src.indexOf(urls.mp3) === -1) { a.src = urls.mp3; a.play().catch(() => {}); } };
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
