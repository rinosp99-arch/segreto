import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { motion, AnimatePresence, useReducedMotion } from 'framer-motion';
import { ArrowLeft, Lock, ArrowRight, Mail, X, Sparkles, Volume2, VolumeX } from 'lucide-react';
import { getModel, getModelSecret, getRelated, track, mediaUrl } from '@/lib/api';
import { MediaMorph } from '@/components/MediaMorph';
import { ModelCard } from '@/components/ModelCard';
import { setSeo, SITE } from '@/lib/seo';
import { getAudio } from '@/lib/sound';
import { urlsForAudioCfg } from '@/lib/tracks';
import { Instagram, Music2, Send, Youtube, Facebook, Globe, Twitter, Link2 } from 'lucide-react';
import {
  getSessionId, markDiscovered, messageShownFor, markMessageShown,
  ofClickedFor, markOfClicked,
} from '@/lib/session';

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function fallbackPairs(model) {
  const pairs = [];
  (model.galleria_pubblica || []).forEach((g, i) => pairs.push({ id: `g${i}`, tipo: 'image', pubblico: g, segreto: null }));
  if (pairs.length === 0 && model.foto_copertina) pairs.push({ id: 'h', tipo: 'image', pubblico: { tipo: 'image', url: model.foto_copertina }, segreto: null });
  (model.video_pubblici || []).forEach((v, i) => pairs.push({ id: `v${i}`, tipo: 'video', pubblico: v, segreto: null }));
  return pairs;
}

export default function ModelProfile() {
  const { slug } = useParams();
  const reduced = useReducedMotion();
  const [model, setModel] = useState(null);
  const [secretData, setSecretData] = useState(null);
  const [related, setRelated] = useState([]);
  const [notFound, setNotFound] = useState(false);

  const [secret, setSecret] = useState(false);
  const [phase, setPhase] = useState('idle');
  const [transforming, setTransforming] = useState(false);
  const [soundOn, setSoundOn] = useState(true);

  const [envelopeVisible, setEnvelopeVisible] = useState(false);
  const [envelopeOpen, setEnvelopeOpen] = useState(false);
  const [ctaTimed, setCtaTimed] = useState(false);
  const ctaTimer = useRef(null);

  const pageLoadedAt = useRef(Date.now());
  const secretEnteredAt = useRef(null);
  const interacted = useRef(false);
  const msgTimer = useRef(null);
  const gridRef = useRef(null);

  useEffect(() => {
    let alive = true;
    setModel(null); setSecretData(null); setSecret(false); setNotFound(false);
    setEnvelopeVisible(false); setEnvelopeOpen(false);
    pageLoadedAt.current = Date.now();
    getModel(slug).then((m) => {
      if (!alive) return;
      setModel(m);
      track({ tipo: 'page_view', model_slug: slug, model_id: m.id, session_id: getSessionId() });
      setSeo({
        title: m.seo?.title || `${m.nome_artistico} | ${SITE.name}`,
        description: m.seo?.meta_description || m.bio,
        image: m.seo?.og_image || m.foto_card, type: 'profile',
        noindex: !!m.anteprima,
        jsonLd: { '@context': 'https://schema.org', '@type': 'Person', name: m.nome_artistico, description: m.bio, image: m.foto_card },
      });
      getModelSecret(slug).then((s) => {
        if (!alive) return;
        setSecretData(s);
        // preload secret media
        (s.media_pairs || []).forEach((p) => {
          if (p.segreto?.url) {
            if (p.tipo === 'image') { const im = new Image(); im.src = mediaUrl(p.segreto.url); }
            else if (p.segreto.poster) { const im = new Image(); im.src = mediaUrl(p.segreto.poster); }
          }
        });
      }).catch(() => {});
      getRelated(slug).then((d) => { if (alive) setRelated(d.items || []); }).catch(() => {});
    }).catch(() => { if (alive) setNotFound(true); });
    return () => {
      alive = false;
      if (msgTimer.current) clearTimeout(msgTimer.current);
      if (ctaTimer.current) clearTimeout(ctaTimer.current);
      getAudio()?.cleanup();
      if (secretEnteredAt.current) {
        const secs = Math.round((Date.now() - secretEnteredAt.current) / 1000);
        track({ tipo: 'secret_time', model_slug: slug, session_id: getSessionId(), valore: secs, _beacon: true });
      }
      document.documentElement.classList.remove('theme-secret');
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug]);

  const startEnvelopeTimer = useCallback(() => {
    // timed CTA (default 10s)
    const ct = secretData?.cta_temporizzata;
    if (ct?.attivo !== false && !ofClickedFor(slug)) {
      const d = ((ct?.ritardo ?? 10)) * 1000;
      ctaTimer.current = setTimeout(() => { if (!ofClickedFor(slug)) setCtaTimed(true); }, d);
    }
    // 35s envelope
    if (!secretData?.messaggio_35s?.attivo) return;
    if (messageShownFor(slug) || ofClickedFor(slug)) return;
    const timer = (secretData.messaggio_35s.timer || 35) * 1000;
    msgTimer.current = setTimeout(() => {
      if (ofClickedFor(slug)) return;
      setEnvelopeVisible(true);
      markMessageShown(slug);
      track({ tipo: 'message_shown', model_slug: slug, session_id: getSessionId() });
    }, timer);
  }, [secretData, slug, soundOn]);

  const applyTheme = (on) => {
    const root = document.documentElement;
    if (on) root.classList.add('theme-secret'); else root.classList.remove('theme-secret');
  };

  const audioCfg = () => {
    const a = (secretData && secretData.regia && secretData.regia.audio) || {};
    return {
      ambiente: a.ambiente !== false,
      urls: urlsForAudioCfg(a),
      volAmb: Math.max(0, Math.min(1, (a.volume_ambiente ?? 22) / 100)),
    };
  };

  const activate = async () => {
    if (transforming || secret) return;
    const audio = getAudio();
    // Unlock audio SYNCHRONOUSLY within the user gesture (critical for iOS Safari)
    if (soundOn && audio) { audio.unlock(); audio.playActivation(0.6); }
    let sd = secretData;
    if (!sd) { try { sd = await getModelSecret(slug); setSecretData(sd); } catch { return; } }
    setTransforming(true);
    const elapsed = Math.round((Date.now() - pageLoadedAt.current) / 1000);
    const acfg = {
      ambiente: (sd?.regia?.audio?.ambiente) !== false,
      urls: urlsForAudioCfg(sd?.regia?.audio),
      volAmb: Math.max(0, Math.min(1, (sd?.regia?.audio?.volume_ambiente ?? 22) / 100)),
    };

    const startAmb = () => { if (soundOn && audio && acfg.ambiente) audio.startAmbient(acfg.urls, acfg.volAmb, 2200); };

    if (reduced) {
      applyTheme(true); setSecret(true);
      secretEnteredAt.current = Date.now();
      startAmb();
      track({ tipo: 'secret_activate', model_slug: slug, session_id: getSessionId(), valore: elapsed });
      markDiscovered(slug); startEnvelopeTimer(); setTransforming(false); return;
    }

    setPhase('blackout');
    await wait(300);
    applyTheme(true); setSecret(true);
    // ambient music enters gradually, accompanying the longer photo dissolve
    setTimeout(startAmb, 500);
    setPhase('flash');
    await wait(110);
    setPhase('reveal');
    await wait(240);
    setPhase('idle');
    setTransforming(false);
    secretEnteredAt.current = Date.now();
    track({ tipo: 'secret_activate', model_slug: slug, session_id: getSessionId(), valore: elapsed });
    markDiscovered(slug);
    startEnvelopeTimer();
  };

  const revert = async () => {
    if (transforming) return;
    if (secretEnteredAt.current) {
      const secs = Math.round((Date.now() - secretEnteredAt.current) / 1000);
      track({ tipo: 'secret_time', model_slug: slug, session_id: getSessionId(), valore: secs });
      secretEnteredAt.current = null;
    }
    track({ tipo: 'secret_return', model_slug: slug, session_id: getSessionId() });
    if (msgTimer.current) clearTimeout(msgTimer.current);
    if (ctaTimer.current) clearTimeout(ctaTimer.current);
    getAudio()?.stopImmediate();
    setEnvelopeVisible(false); setEnvelopeOpen(false); setCtaTimed(false);
    if (reduced) { applyTheme(false); setSecret(false); return; }
    setTransforming(true);
    setPhase('blackout');
    await wait(200);
    applyTheme(false); setSecret(false);
    setPhase('reveal');
    await wait(140);
    setPhase('idle');
    setTransforming(false);
  };

  const toggleSound = () => {
    setSoundOn((v) => {
      const next = !v;
      const audio = getAudio();
      if (audio) {
        audio.setMuted(!next);
        if (next && secret) { const c = audioCfg(); if (c.ambiente) audio.startAmbient(c.urls, c.volAmb, 1200); }
      }
      return next;
    });
  };

  const registerInteraction = () => {
    if (secret && !interacted.current) { interacted.current = true; track({ tipo: 'interazione', model_slug: slug, session_id: getSessionId() }); }
  };

  const openOnlyFans = (source) => {
    const url = secretData?.onlyfans_url || model?.onlyfans_url;
    if (!url) return;
    track({ tipo: 'cta_click', model_slug: slug, session_id: getSessionId(), cta_source: source });
    track({ tipo: 'of_click', model_slug: slug, session_id: getSessionId(), cta_source: source });
    markOfClicked(slug); setEnvelopeVisible(false); setCtaTimed(false);
    const sep = url.includes('?') ? '&' : '?';
    window.open(`${url}${sep}utm_source=lato_segreto&utm_medium=profilo&utm_campaign=lato_segreto&creator=${slug}&cta=${source}`, '_blank', 'noopener');
  };

  const openSocial = (key, url) => {
    if (!url) return;
    track({ tipo: `social_click_${key}`, model_slug: slug, session_id: getSessionId(), cta_source: key });
    window.open(url, '_blank', 'noopener');
  };

  const onGridMove = (e) => {
    if (!secret || reduced) return;
    const el = gridRef.current; if (!el) return;
    const rect = el.getBoundingClientRect();
    const cx = e.touches ? e.touches[0].clientX : e.clientX;
    const cy = e.touches ? e.touches[0].clientY : e.clientY;
    el.style.setProperty('--mx', `${((cx - rect.left) / rect.width) * 100}%`);
    el.style.setProperty('--my', `${((cy - rect.top) / rect.height) * 100}%`);
  };

  if (notFound) return (
    <div className="max-w-2xl mx-auto px-4 py-24 text-center">
      <div className="font-serif text-3xl mb-2">Qui non c'è nessun Lato Segreto.</div>
      <p className="text-muted-foreground mb-6">La modella che cerchi non esiste o non è più disponibile.</p>
      <Link to="/" className="btn-gold inline-block rounded-xl px-6 py-3 text-sm" data-testid="not-found-home-button">Torna alle modelle</Link>
    </div>
  );
  if (!model) return <div className="max-w-5xl mx-auto px-4 py-10"><div className="grid grid-cols-2 gap-3">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="animate-pulse bg-muted/50 rounded-2xl" style={{ aspectRatio: '3/4' }} />)}</div></div>;

  const pairs = (secretData?.media_pairs?.length ? secretData.media_pairs : fallbackPairs(model));
  const imagePairs = pairs.filter((p) => p.tipo === 'image').slice(0, 3);
  const videoPairs = pairs.filter((p) => p.tipo === 'video').slice(0, 2);
  const topTiles = [
    { pair: imagePairs[0], effect: 'flash', delay: 0 },
    { pair: imagePairs[1], effect: 'blur', delay: 150 },
    { pair: videoPairs[0], effect: 'glitch', delay: 300 },
    { pair: imagePairs[2], effect: 'sweep', delay: 450 },
  ].filter((t) => t.pair);
  const wideTile = videoPairs[1] ? { pair: videoPairs[1], effect: 'fadeblack', delay: 600 } : null;
  const tema = secretData?.tema || {};
  const regia = secretData?.regia || {};
  const inten = ((Number(regia.fumo ?? 35) + Number(regia.luci ?? 55) + Number(regia.glow ?? 40)) / 3) / 100;
  const move = Number(regia.movimento ?? 25) / 100;
  const ambOpacity = 0.3 + inten * 0.7;
  const blobDur = `${(22 - move * 13).toFixed(1)}s`;
  const beamDur = `${(13 - move * 7).toFixed(1)}s`;
  const socialData = (secret ? secretData?.social : model.social) || {};
  const themeStyle = secret ? { '--primary': tema.colore_primario, '--accent': tema.colore_secondario } : {};
  const ctaLabel = secretData?.cta_testo || model.cta_testo || 'CONTINUA CON ME';

  return (
    <div style={themeStyle} onScroll={registerInteraction} onPointerDown={registerInteraction}>
      {/* secret ambience: fumo, luci da palco, glow bordeaux */}
      {secret && (
        <div className="secret-ambience" data-testid="secret-ambience" aria-hidden style={{ opacity: ambOpacity }}>
          <div className="blob b1" style={{ animationDuration: blobDur }} /><div className="blob b2" style={{ animationDuration: blobDur }} /><div className="blob b3" style={{ animationDuration: blobDur }} />
          <div className="beam" style={{ left: '18%', animationDuration: beamDur }} /><div className="beam beam2" style={{ left: '62%', animationDuration: beamDur }} />
          <div className="grainlayer" />
        </div>
      )}
      {/* transformation overlays */}
      <div className="fixed inset-0 z-[95] pointer-events-none" style={{ background: 'rgba(4,2,6,1)', opacity: (phase === 'blackout' || phase === 'flash') ? 1 : 0, transition: 'opacity 200ms ease' }} data-testid="theme-blackout-overlay" />
      <div className="fixed inset-0 z-[96] pointer-events-none" style={{ background: 'radial-gradient(circle at 50% 40%, hsl(38 40% 88% / 0.9), hsl(350 40% 40% / 0.2))', opacity: phase === 'flash' ? 0.8 : 0, transition: 'opacity 90ms ease' }} />
      <AnimatePresence>
        {phase !== 'idle' && (
          <motion.div className="fixed inset-0 z-[97] pointer-events-none flex items-center justify-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <span className="font-serif text-2xl sm:text-3xl text-white/90">{tema.testo_dopo_click || "Te l'avevamo detto."}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative z-10 max-w-5xl mx-auto px-4 lg:px-8 pt-4 pb-16">
        <div className="flex items-center justify-between mb-4">
          <Link to="/" className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors"><ArrowLeft className="h-4 w-4" /> Tutte le modelle</Link>
          <button onClick={toggleSound} data-testid="sound-toggle" className="h-9 w-9 flex items-center justify-center rounded-full border border-border text-muted-foreground hover:text-foreground transition-colors" aria-label="Audio">
            {soundOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
          </button>
        </div>

        {/* header */}
        <div className="mb-5">
          <div className="flex items-center gap-3 mb-2">
            <div className="caps-label px-3 py-1.5 rounded-full glass inline-flex items-center gap-2" data-testid="secret-mode-indicator">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: secret ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }} />
              {secret ? 'Lato Segreto' : 'Lato Pubblico'}
            </div>
            {model.badge && <span className="caps-label px-3 py-1.5 rounded-full text-[10px]" style={{ background: 'hsl(var(--primary) / 0.16)', border: '1px solid hsl(var(--primary) / 0.45)', color: 'hsl(var(--primary))' }}>{model.badge}</span>}
          </div>
          <h1 className="text-4xl sm:text-6xl font-serif leading-none mb-1">{model.nome_artistico}</h1>
          <AnimatePresence mode="wait">
            <motion.p key={secret ? 's' : 'p'} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.4 }} className="text-muted-foreground text-sm sm:text-base">
              {secret ? (secretData?.teaser_copy || 'Adesso vedi un altro lato di me.') : model.frase}
            </motion.p>
          </AnimatePresence>
        </div>

        {/* TRIGGER / REVERT — posizione premium sopra la griglia */}
        <div className="flex justify-center mb-6">
          {!secret ? (
            <div className="text-center w-full sm:w-auto">
              <motion.button onClick={activate} onPointerDown={() => { const a = getAudio(); if (soundOn && a) a.unlock(); }} disabled={transforming} data-testid="secret-trigger-button"
                whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.94, y: 2 }}
                className="group relative inline-flex items-center gap-3 rounded-2xl px-8 sm:px-10 py-5 overflow-hidden w-full sm:w-auto justify-center"
                style={{ background: 'linear-gradient(180deg, hsl(var(--card)), hsl(var(--secondary)))', border: '1px solid hsl(var(--primary) / 0.55)', boxShadow: '0 0 0 1px hsl(var(--primary)/0.15), 0 0 40px hsl(var(--primary)/0.28), inset 0 1px 0 hsl(40 40% 80% / 0.15)' }}>
                <span className="absolute inset-0 opacity-70 group-hover:opacity-100 transition-opacity" style={{ background: 'radial-gradient(120% 140% at 50% 0%, hsl(var(--primary)/0.18), transparent 65%)' }} />
                <span className="h-10 w-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'hsl(var(--wine) / 0.4)', border: '1px solid hsl(var(--primary)/0.5)' }}><Lock className="h-5 w-5" style={{ color: 'hsl(var(--primary))' }} /></span>
                <span className="relative font-serif text-2xl sm:text-3xl tracking-wide">{tema?.frase_attivazione || 'NON DOVRESTI PREMERLO'}</span>
              </motion.button>
              <div className="text-[11px] text-muted-foreground mt-2.5">…e infatti non dovresti.</div>
            </div>
          ) : (
            <button onClick={revert} data-testid="revert-button" className="inline-flex items-center gap-2 text-sm px-6 py-3 rounded-full transition-colors" style={{ border: '1px solid hsl(var(--primary)/0.4)', color: 'hsl(var(--primary))', background: 'hsl(var(--primary)/0.08)' }}>
              <ArrowLeft className="h-4 w-4" /> Ritorna al Lato Pubblico
            </button>
          )}
        </div>

        {/* MEDIA GRID (vetrina) */}
        <div ref={gridRef} onMouseMove={onGridMove} onTouchMove={onGridMove} className="relative" data-testid="media-grid">
          <div className="grid grid-cols-2 gap-3 sm:gap-4">
            {topTiles.map((t, i) => (
              <MediaMorph key={t.pair.id || i} pub={t.pair.pubblico} sec={t.pair.segreto} secret={secret} reduced={reduced} effect={t.effect} delay={t.delay} ambient={secret} ratio="3 / 4" className="rounded-2xl border border-border/60 card-elev" />
            ))}
            {wideTile && (
              <div className="col-span-2">
                <MediaMorph pub={wideTile.pair.pubblico} sec={wideTile.pair.segreto} secret={secret} reduced={reduced} effect={wideTile.effect} delay={wideTile.delay} ambient={secret} fit="contain" maxVh={70} ratio="16 / 9" className="rounded-2xl border border-border/60 card-elev" />
              </div>
            )}
          </div>
          {secret && !reduced && (
            <div className="absolute inset-0 pointer-events-none rounded-2xl" style={{ background: 'radial-gradient(260px circle at var(--mx,50%) var(--my,40%), hsl(var(--primary)/0.15), transparent 60%)' }} />
          )}
        </div>

        {/* DESCRIZIONE (cambia con la modalità) */}
        <section className="max-w-2xl mx-auto text-center mt-8">
          <AnimatePresence mode="wait">
            <motion.p key={secret ? 'sd' : 'pd'} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.5 }}
              className="text-base leading-relaxed text-foreground/85">
              {secret ? (secretData?.bio_segreta || model.bio) : model.bio}
            </motion.p>
          </AnimatePresence>
        </section>

        {/* SOCIAL — lato pubblico (secondari, non rubano attenzione alla CTA OF) */}
        {!secret && <SocialLinks social={socialData} secret={false} onOpen={openSocial} />}

        {/* CONVERSION (secret) */}
        {secret && (
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="text-center max-w-xl mx-auto">
            <div className="font-serif text-2xl sm:text-3xl mb-3">{secretData?.teaser_copy || 'Qui posso mostrarti solo fino a questo punto.'}</div>
            <p className="text-sm text-muted-foreground mb-6">Il resto — e molto altro — è solo sul mio profilo.</p>
            <button onClick={() => openOnlyFans('of_click_gallery')} data-testid="cta-gallery" className="btn-gold rounded-full px-8 py-4 text-sm inline-flex items-center gap-2">{ctaLabel} <ArrowRight className="h-4 w-4" /></button>
            <div className="text-[11px] text-muted-foreground mt-3">Apri il mio profilo OnlyFans</div>
          </motion.div>
        )}

        {/* SOCIAL — lato segreto in fondo, dopo la CTA OnlyFans */}
        {secret && <SocialLinks social={socialData} secret onOpen={openSocial} />}

        {/* RELATED */}
        {related.length > 0 && (
          <section className="mt-16">
            <div className="caps-label gold-text mb-4">Potrebbero piacerti anche</div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">{related.map((m, i) => <ModelCard key={m.slug} model={m} index={i} />)}</div>
          </section>
        )}
      </div>

      {/* TIMED CTA (compare dopo il ritardo, default 10s) */}
      <AnimatePresence>
        {secret && ctaTimed && (
          <motion.div initial={{ opacity: 0, y: 40 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 40 }}
            className="fixed bottom-0 inset-x-0 z-[55] p-3 glass border-t border-border/60" data-testid="cta-timed">
            <div className="max-w-md mx-auto text-center">
              <div className="text-xs text-muted-foreground mb-1.5">{secretData?.cta_temporizzata?.testo_intro || 'Vuoi vedere dove continua?'}</div>
              <button onClick={() => openOnlyFans('of_click_timed')} className="btn-gold w-full rounded-xl py-3.5 text-sm inline-flex items-center justify-center gap-2">
                {secretData?.cta_temporizzata?.testo_pulsante || ctaLabel} <ArrowRight className="h-4 w-4" />
              </button>
              <div className="text-[11px] text-muted-foreground mt-1.5">Apri il mio profilo OnlyFans</div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {envelopeVisible && (
          <motion.div initial={{ opacity: 0, y: 30, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 30 }} className="fixed bottom-20 sm:bottom-5 right-3 sm:right-5 z-[60] w-[calc(100%-1.5rem)] sm:w-80" data-testid="envelope-message-card">
            <div className="glass rounded-2xl card-elev-2 overflow-hidden">
              {!envelopeOpen ? (
                <button onClick={() => { setEnvelopeOpen(true); track({ tipo: 'message_open', model_slug: slug, session_id: getSessionId() }); }} data-testid="envelope-open-button" className="w-full flex items-center gap-3 p-4 text-left hover:bg-muted/30 transition-colors">
                  <div className="h-10 w-10 rounded-full flex items-center justify-center shrink-0" style={{ background: 'hsl(var(--primary) / 0.16)', border: '1px solid hsl(var(--primary)/0.4)' }}><Mail className="h-5 w-5" style={{ color: 'hsl(var(--primary))' }} /></div>
                  <div className="flex-1"><div className="text-sm font-semibold">Ti ha lasciato qualcosa…</div><div className="text-xs text-muted-foreground">Tocca per aprire</div></div>
                </button>
              ) : (
                <div className="p-4">
                  <div className="flex justify-between items-start mb-3"><span className="caps-label gold-text inline-flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" /> Messaggio</span><button onClick={() => setEnvelopeVisible(false)} className="h-7 w-7 flex items-center justify-center rounded-full hover:bg-muted/50"><X className="h-4 w-4" /></button></div>
                  {secretData?.messaggio_35s?.foto && <div className="rounded-xl overflow-hidden mb-3" style={{ aspectRatio: '16/10' }}><img src={mediaUrl(secretData.messaggio_35s.foto)} alt="" className="h-full w-full object-cover" style={{ filter: 'saturate(0.82) hue-rotate(-12deg)', objectPosition: 'center 20%' }} /></div>}
                  <p className="text-sm leading-relaxed mb-4">{secretData?.messaggio_35s?.testo}</p>
                  <button onClick={() => openOnlyFans('of_click_message')} data-testid="envelope-cta" className="btn-gold w-full rounded-xl py-3 text-sm inline-flex items-center justify-center gap-2">{secretData?.messaggio_35s?.cta_testo || ctaLabel} <ArrowRight className="h-4 w-4" /></button>
                  <div className="text-center text-[11px] text-muted-foreground mt-2">Apri il mio profilo OnlyFans</div>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

const SOCIAL_DEFS = [
  ['instagram', 'Instagram', Instagram],
  ['tiktok', 'TikTok', Music2],
  ['x', 'X', Twitter],
  ['telegram', 'Telegram', Send],
  ['youtube', 'YouTube', Youtube],
  ['facebook', 'Facebook', Facebook],
  ['threads', 'Threads', Link2],
  ['snapchat', 'Snapchat', Link2],
  ['sito', 'Sito', Globe],
];

function SocialLinks({ social, secret, onOpen }) {
  if (!social) return null;
  const items = SOCIAL_DEFS.filter(([k]) => social[k]).map(([k, label, Icon]) => ({ k, label, Icon, url: social[k] }));
  (social.custom || []).forEach((c, i) => {
    if (c && c.visibile !== false && c.url) items.push({ k: `custom_${i}`, label: c.nome || 'Link', Icon: Link2, url: c.url });
  });
  if (items.length === 0) return null;
  return (
    <section className="mt-10 text-center" data-testid="social-section">
      <div className="caps-label gold-text mb-3">Scoprimi anche qui</div>
      <div className="flex flex-wrap justify-center gap-2">
        {items.map((it) => (
          <button key={it.k} onClick={() => onOpen(it.k.startsWith('custom') ? 'custom' : it.k, it.url)} data-testid={`social-${it.k}`}
            className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs transition-colors"
            style={{ border: `1px solid hsl(var(--border))`, background: secret ? 'hsl(var(--primary) / 0.08)' : 'transparent', color: 'hsl(var(--muted-foreground))' }}>
            <it.Icon className="h-4 w-4" /> {it.label}
          </button>
        ))}
      </div>
    </section>
  );
}
