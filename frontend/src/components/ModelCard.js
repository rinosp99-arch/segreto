import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { MediaImage } from '@/components/MediaImage';
import { isDiscovered } from '@/lib/session';
import { track } from '@/lib/api';
import { setEntry, observeImpression, currentMode } from '@/lib/analytics';
import { Lock, Unlock } from 'lucide-react';

/* placement -> entry_source of the profile opened from this card */
const ENTRY_BY_PLACEMENT = { home: 'home_card', related: 'related_models', category: 'category' };

const BADGE_STYLES = {
  'IN TENDENZA': { bg: 'hsl(var(--primary) / 0.16)', bd: 'hsl(var(--primary) / 0.45)', c: 'hsl(var(--primary))' },
  'NUOVA': { bg: 'hsl(var(--accent) / 0.18)', bd: 'hsl(var(--accent) / 0.5)', c: 'hsl(var(--accent-foreground))' },
  'SCELTA DEL GIORNO': { bg: 'hsl(var(--wine) / 0.22)', bd: 'hsl(var(--wine) / 0.5)', c: 'hsl(38 30% 86%)' },
  'PIÙ VISTA': { bg: 'hsl(var(--primary) / 0.16)', bd: 'hsl(var(--primary) / 0.45)', c: 'hsl(var(--primary))' },
};

export function ModelCard({ model, index = 0, teaser = false, placement = 'home', context = null }) {
  const discovered = isDiscovered(model.slug);
  const badge = model.badge;
  const bs = badge ? BADGE_STYLES[badge] || BADGE_STYLES['IN TENDENZA'] : null;
  const ref = useRef(null);

  // home_model_card_impression: card really visible (>=50% for 500ms), once per visit per card per Home mode
  useEffect(() => {
    if (placement !== 'home') return undefined;
    const mode = teaser ? 'secret' : 'public';
    return observeImpression(ref.current, () => {
      track({ tipo: 'home_model_card_impression', model_slug: model.slug, placement, mode, meta: { position: index, context } });
    }, { threshold: 0.5, minMs: 500, key: `card_imp:${model.slug}:${mode}` });
  }, [model.slug, placement, teaser, index, context]);

  const onOpen = () => {
    setEntry(ENTRY_BY_PLACEMENT[placement] || placement, { position: index });
    track({ tipo: placement === 'home' ? 'home_model_card_click' : 'model_card_click', model_slug: model.slug, placement, mode: placement === 'home' ? (teaser ? 'secret' : 'public') : currentMode(), meta: { position: index, context } });
  };

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '-40px' }}
      transition={{ duration: 0.5, delay: Math.min(index * 0.04, 0.4), ease: [0.2, 0.8, 0.2, 1] }}
    >
      <Link to={`/modelle/${model.slug}`} data-testid="model-card" onClick={onOpen}
        className="group relative block rounded-2xl overflow-hidden border border-border/60 bg-card card-elev hover:card-elev-2 transition-shadow">
        <div className="relative" style={{ aspectRatio: '3 / 4' }}>
          {/* PUBLIC image */}
          <MediaImage src={model.foto_card} alt={model.seo?.alt_default || model.nome_artistico}
            className="absolute inset-0 h-full w-full transition-all duration-500 group-hover:scale-[1.04]"
            style={{ opacity: teaser ? 0 : 1 }} />

          {/* SECRET image (crossfades in when Home is in Lato Segreto) */}
          <div className="absolute inset-0 transition-opacity duration-[600ms] group-hover:scale-[1.04]"
            style={{ opacity: teaser ? 1 : 0 }} aria-hidden={!teaser}>
            <MediaImage src={model.foto_card_teaser || model.foto_card} alt=""
              className="h-full w-full"
              style={{ filter: 'saturate(1.1) contrast(1.04) brightness(0.9)' }} />
            <div className="absolute inset-0" style={{ background: 'radial-gradient(120% 100% at 50% 120%, hsl(350 55% 16% / 0.55), transparent 62%)' }} />
            {!model.foto_card_teaser && (
              <div className="absolute bottom-14 left-3 caps-label text-[9px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(0,0,0,0.5)', color: 'hsl(38 60% 78%)', border: '1px solid hsl(38 60% 78% / 0.3)' }}>
                variante soft
              </div>
            )}
          </div>

          {/* hover peek of the secret side (only in PUBLIC mode) */}
          {!teaser && model.foto_card_teaser && (
            <div className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500">
              <MediaImage src={model.foto_card_teaser} alt="" className="h-full w-full"
                style={{ filter: 'blur(16px) brightness(0.62) saturate(1.1)', transform: 'scale(1.1)' }} />
              <div className="absolute inset-0" style={{ background: 'linear-gradient(to top, rgba(20,0,8,0.7), rgba(0,0,0,0.15))' }} />
            </div>
          )}

          {/* bottom gradient */}
          <div className="absolute inset-x-0 bottom-0 h-2/5 pointer-events-none"
            style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.82), transparent)' }} />

          {/* badge */}
          {bs && (
            <div className="absolute top-2.5 left-2.5 caps-label px-2.5 py-1 rounded-full"
              style={{ background: bs.bg, border: `1px solid ${bs.bd}`, color: bs.c, backdropFilter: 'blur(6px)' }}>
              {badge}
            </div>
          )}

          {/* discovered indicator */}
          <div className="absolute top-2.5 right-2.5">
            {discovered ? (
              <div className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-full"
                style={{ background: 'hsl(var(--primary) / 0.18)', border: '1px solid hsl(var(--primary) / 0.4)', color: 'hsl(var(--primary))' }}>
                <Unlock className="h-3 w-3" /> SCOPERTO
              </div>
            ) : (
              <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-center gap-1 text-[10px] px-2 py-1 rounded-full glass">
                <Lock className="h-3 w-3" /> LATO SEGRETO
              </div>
            )}
          </div>

          {/* meta */}
          <div className="absolute inset-x-0 bottom-0 p-3.5">
            <div className="text-xl md:text-2xl font-serif leading-none mb-1">{model.nome_artistico}</div>
            <div className="text-xs text-white/70 line-clamp-1">{model.frase}</div>
            <div className="mt-2 h-[1px] w-0 group-hover:w-full transition-all duration-500" style={{ background: 'hsl(var(--primary) / 0.6)' }} />
            <div className="overflow-hidden max-h-0 group-hover:max-h-8 transition-all duration-500">
              <div className="pt-2 text-[11px] gold-text caps-label">C'è un lato che non hai ancora visto</div>
            </div>
          </div>
        </div>
      </Link>
    </motion.div>
  );
}
