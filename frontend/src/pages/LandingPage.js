import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { api } from '@/lib/api';
import { ModelCard } from '@/components/ModelCard';
import { setSeo, SITE } from '@/lib/seo';
import { ArrowLeft, SearchX } from 'lucide-react';

/**
 * Public landing page /l/{slug} (Phase 13 - GOOGLE SEO CORE).
 * The backend returns 404 unless the landing is published AND the admin flag public_landing_routes is ON,
 * so only really public landings are reachable/indexable. SEO meta + canonical + JSON-LD (WebPage/CollectionPage,
 * FAQPage only when real FAQ exist) are set from the landing document: nothing invented.
 */
export default function LandingPage() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setData(null); setNotFound(false);
    api.get(`/landings/${slug}`).then((r) => {
      const l = r.data;
      setData(l);
      const seo = l.seo || {};
      const url = `${window.location.origin}/l/${l.slug}`;
      const cards = l.model_cards || [];
      const jsonLd = [{
        '@context': 'https://schema.org', '@type': cards.length ? 'CollectionPage' : 'WebPage',
        name: l.headline || l.titolo, description: seo.meta_description || l.subtitle || undefined, url,
        isPartOf: { '@type': 'WebSite', name: SITE.name, url: window.location.origin },
        ...(cards.length ? { hasPart: cards.map((m) => ({ '@type': 'ProfilePage', name: m.nome_artistico, url: `${window.location.origin}/modelle/${m.slug}` })) } : {}),
      }];
      if (Array.isArray(l.faq) && l.faq.length) {
        jsonLd.push({ '@context': 'https://schema.org', '@type': 'FAQPage', mainEntity: l.faq.filter((f) => f.domanda && f.risposta).map((f) => ({ '@type': 'Question', name: f.domanda, acceptedAnswer: { '@type': 'Answer', text: f.risposta } })) });
      }
      setSeo({
        title: seo.title || `${l.headline || l.titolo} | ${SITE.name}`,
        description: seo.meta_description || l.subtitle || '',
        canonical: seo.canonical || url,
        noindex: seo.indexable === false || /noindex/i.test(seo.robots || ''),
        image: seo.og_image || (l.hero && l.hero.media_tipo === 'image' ? l.hero.media_url : '') || (cards[0] && cards[0].foto_card) || '',
        type: 'website',
        jsonLd,
      });
    }).catch(() => setNotFound(true));
  }, [slug]);

  if (notFound) return (
    <div className="max-w-2xl mx-auto px-4 py-24 text-center" data-testid="landing-not-found">
      <div className="font-serif text-3xl mb-2">Pagina non trovata</div>
      <Link to="/" className="btn-gold inline-block rounded-xl px-6 py-3 text-sm mt-4">Torna alla home</Link>
    </div>
  );
  if (!data) return <div className="max-w-6xl mx-auto px-4 py-10"><div className="h-40 animate-pulse bg-muted/50 rounded-2xl" /></div>;

  const cards = data.model_cards || [];
  const hero = data.hero || {};
  const cta = data.cta || {};
  const secret = (data.tema || {}).modalita === 'segreto';
  return (
    <div className={`max-w-6xl mx-auto px-4 lg:px-8 py-6 ${secret ? 'landing-secret' : ''}`} data-testid="landing-page">
      <nav className="text-sm text-muted-foreground mb-4 flex items-center gap-2">
        <Link to="/" className="hover:text-foreground inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" />Inizio</Link>
        <span>/</span><span className="text-foreground">{data.titolo}</span>
      </nav>
      {hero.media_url && (
        <div className="relative rounded-3xl overflow-hidden mb-8 aspect-[21/9] bg-muted/40" data-testid="landing-hero">
          {hero.media_tipo === 'video'
            ? <video className="w-full h-full object-cover" src={hero.media_url} poster={hero.poster || undefined} muted playsInline autoPlay loop />
            : <img className="w-full h-full object-cover" src={hero.media_url} alt={data.headline || data.titolo} loading="eager" />}
          {hero.overlay !== 'none' && <div className="absolute inset-0 bg-gradient-to-t from-background/90 via-background/30 to-transparent" />}
        </div>
      )}
      <h1 className="text-4xl sm:text-5xl font-serif mb-3" data-testid="landing-h1">{data.headline || data.titolo}</h1>
      {data.subtitle && <p className="text-muted-foreground max-w-2xl mb-6" data-testid="landing-subtitle">{data.subtitle}</p>}
      {cta.testo && cta.posizione !== 'footer' && (
        <a href={cta.url || '/'} className="btn-gold inline-block rounded-xl px-6 py-3 text-sm mb-8" data-testid="landing-cta">{cta.testo}</a>
      )}
      {cards.length === 0 ? (
        <div className="py-16 text-center"><SearchX className="h-10 w-10 mx-auto mb-3 text-muted-foreground" /><p className="text-muted-foreground">Nessun profilo collegato a questa pagina.</p></div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5" data-testid="landing-models">
          {cards.map((m, i) => <ModelCard key={m.slug} model={m} index={i} teaser={secret} />)}
        </div>
      )}
      {Array.isArray(data.faq) && data.faq.length > 0 && (
        <section className="mt-12 max-w-3xl" data-testid="landing-faq">
          <h2 className="font-serif text-2xl mb-4">Domande frequenti</h2>
          <div className="space-y-4">
            {data.faq.filter((f) => f.domanda && f.risposta).map((f, i) => (
              <div key={i} className="rounded-2xl border border-border/60 p-4">
                <h3 className="font-medium mb-1">{f.domanda}</h3>
                <p className="text-sm text-muted-foreground">{f.risposta}</p>
              </div>
            ))}
          </div>
        </section>
      )}
      {cta.testo && cta.posizione === 'footer' && (
        <div className="mt-12"><a href={cta.url || '/'} className="btn-gold inline-block rounded-xl px-6 py-3 text-sm" data-testid="landing-cta">{cta.testo}</a></div>
      )}
    </div>
  );
}
