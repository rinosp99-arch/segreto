import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { getModels, getPellicola } from '@/lib/api';
import { ModelCard } from '@/components/ModelCard';
import FilmStrip from '@/components/FilmStrip';
import { GlobalOfMarquee } from '@/components/GlobalOfMarquee';
import { useTheme } from '@/lib/themeContext';
import { setSeo, SITE } from '@/lib/seo';
import { SearchX } from 'lucide-react';

const FILTERS = [
  { key: 'tutte', label: 'Tutte' },
  { key: 'nuove', label: 'Nuove' },
  { key: 'piu-viste', label: 'Più viste' },
  { key: 'in-tendenza', label: 'In tendenza' },
];

function CardSkeleton() {
  return <div className="rounded-2xl overflow-hidden border border-border/60 bg-card" style={{ aspectRatio: '3 / 4' }}>
    <div className="h-full w-full animate-pulse bg-muted/50" /></div>;
}

export default function Home() {
  const { homeMode } = useTheme();
  const [filtro, setFiltro] = useState('tutte');
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [pellicola, setPellicola] = useState(null);

  useEffect(() => {
    setSeo({
      title: 'LATO SEGRETO — Il lato che non hai ancora visto',
      description: 'Creator premium con un lato pubblico elegante e un lato segreto tutto da svelare. Scopri, incuriosisciti, premi.',
      jsonLd: {
        '@context': 'https://schema.org', '@type': 'WebSite', name: SITE.name,
        url: window.location.origin,
        potentialAction: { '@type': 'SearchAction', target: `${window.location.origin}/?q={search_term_string}`, 'query-input': 'required name=search_term_string' },
      },
    });
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (homeMode === 'secret') root.classList.add('theme-secret');
    else root.classList.remove('theme-secret');
    return () => root.classList.remove('theme-secret');
  }, [homeMode]);

  useEffect(() => {
    setLoading(true);
    getModels({ filtro, limit: 60 })
      .then((d) => setItems(d.items || []))
      .finally(() => setLoading(false));
  }, [filtro]);

  useEffect(() => {
    getPellicola().then(setPellicola).catch(() => setPellicola(null));
  }, []);

  const secret = homeMode === 'secret';

  const pelliconaAttiva = pellicola && pellicola.config && pellicola.config.attiva !== false
    && (pellicola.items || []).length > 0;
  const desiredAfter = Math.max(4, (pellicola && pellicola.config && pellicola.config.inserisci_dopo_n) || 10);
  // ensure at least a couple of cards remain after the strip so the grid visibly continues
  const insertAfter = Math.min(desiredAfter, Math.max(4, items.length - 2));
  const showStrip = pelliconaAttiva && filtro === 'tutte' && items.length > insertAfter;
  const firstChunk = showStrip ? items.slice(0, insertAfter) : items;
  const restChunk = showStrip ? items.slice(insertAfter) : [];

  return (
    <div className="max-w-6xl mx-auto px-4 lg:px-8 relative">
      {/* Secret-mode atmosphere wash for the whole Home (fades in/out smoothly, no reload) */}
      <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 transition-opacity duration-700"
        style={{
          opacity: secret ? 1 : 0,
          background: 'radial-gradient(90% 60% at 50% -10%, hsl(340 55% 20% / 0.5), transparent 60%), radial-gradient(70% 50% at 100% 20%, hsl(280 45% 22% / 0.35), transparent 60%), linear-gradient(180deg, hsl(350 45% 6% / 0.55), transparent 40%)',
        }} />
      <div className="relative z-[1]">
      {/* intro */}
      <section className="pt-8 pb-6 sm:pt-12">
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
          <div className="caps-label gold-text mb-3">{secret ? 'Modalità anteprima segreta' : 'Collezione riservata'}</div>
          <h1 className="text-4xl sm:text-5xl lg:text-6xl leading-[0.95] mb-3 text-balance">
            {secret ? 'Un assaggio di ciò che nascondono.' : 'Ognuna ha un lato che non hai ancora visto.'}
          </h1>
          <p className="text-muted-foreground max-w-xl text-sm sm:text-base">
            {secret
              ? 'Questa è solo l’atmosfera. Il vero Lato Segreto si sblocca dentro il profilo di ogni creator.'
              : 'Scegli una creator, esplora il suo lato pubblico… e poi decidi se premere.'}
          </p>
        </motion.div>
      </section>

      {/* filters */}
      <div className="sticky top-14 z-30 -mx-4 px-4 py-3 mb-6 bg-background/80 backdrop-blur-md transition-theme">
        <div className="flex gap-2 overflow-x-auto no-scrollbar" data-testid="filters-toggle-group">
          {FILTERS.map((f) => (
            <button key={f.key} onClick={() => setFiltro(f.key)}
              data-testid={`filter-${f.key}`}
              className={`shrink-0 caps-label px-4 py-2 rounded-full border transition-colors ${filtro === f.key ? 'text-foreground' : 'text-muted-foreground'}`}
              style={filtro === f.key
                ? { background: 'hsl(var(--primary) / 0.16)', borderColor: 'hsl(var(--primary) / 0.45)' }
                : { borderColor: 'hsl(var(--border))' }}>
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {/* grid */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5 pb-10">
          {Array.from({ length: 10 }).map((_, i) => <CardSkeleton key={i} />)}
        </div>
      ) : items.length === 0 ? (
        <div className="py-20 text-center" data-testid="empty-state">
          <SearchX className="h-10 w-10 mx-auto mb-4 text-muted-foreground" />
          <div className="font-serif text-2xl mb-1">Nessuna modella trovata</div>
          <p className="text-sm text-muted-foreground">Prova a cambiare filtro.</p>
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5" data-testid="models-grid">
            {firstChunk.map((m, i) => <ModelCard key={m.slug} model={m} index={i} teaser={secret} />)}
          </div>

          {showStrip && (
            <FilmStrip items={pellicola.items} config={pellicola.config} secret={secret} />
          )}

          {/* canale OnlyFans globale del brand: subito dopo IN MOVIMENTO, occupa il suo spazio */}
          <div className="my-8 sm:my-10">
            <GlobalOfMarquee placement="home" secret={secret} />
          </div>

          {restChunk.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5 pb-10" data-testid="models-grid-rest">
              {restChunk.map((m, i) => <ModelCard key={m.slug} model={m} index={insertAfter + i} teaser={secret} />)}
            </div>
          )}
          {!showStrip && <div className="pb-10" />}
        </>
      )}
      </div>
    </div>
  );
}
