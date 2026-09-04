import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getArticle, track, mediaUrl } from '@/lib/api';
import { setSeo, SITE } from '@/lib/seo';
import { getSessionId } from '@/lib/session';
import { ModelCard } from '@/components/ModelCard';
import { ArrowLeft } from 'lucide-react';

export default function ArticlePage() {
  const { slug } = useParams();
  const [a, setA] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setA(null); setNotFound(false);
    getArticle(slug).then((art) => {
      setA(art);
      track({ tipo: 'article_view', article_id: art.id, session_id: getSessionId() });
      setSeo({
        title: art.seo_title || `${art.titolo} | ${SITE.name}`,
        description: art.meta_description || art.estratto,
        image: art.og_image || art.immagine_principale,
        type: 'article', noindex: !art.indicizzabile,
        jsonLd: { '@context': 'https://schema.org', '@type': 'Article', headline: art.titolo, image: art.immagine_principale, datePublished: art.data_pubblicazione, author: { '@type': 'Organization', name: art.autore } },
      });
    }).catch(() => setNotFound(true));
  }, [slug]);

  if (notFound) return <div className="max-w-2xl mx-auto px-4 py-24 text-center"><div className="font-serif text-3xl mb-3">Articolo non trovato</div><Link to="/articoli" className="btn-gold inline-block rounded-xl px-6 py-3 text-sm">Torna alla rivista</Link></div>;
  if (!a) return <div className="max-w-3xl mx-auto px-4 py-10"><div className="h-96 animate-pulse bg-muted/50 rounded-2xl" /></div>;

  return (
    <article className="max-w-3xl mx-auto px-4 lg:px-6 py-8">
      <nav className="text-sm text-muted-foreground mb-4 flex items-center gap-2">
        <Link to="/articoli" className="hover:text-foreground inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" />Rivista</Link>
      </nav>
      <h1 className="text-4xl sm:text-5xl font-serif leading-tight mb-3">{a.titolo}</h1>
      <div className="text-sm text-muted-foreground mb-6">{a.autore} · {(a.data_pubblicazione || '').slice(0, 10)}</div>
      {a.immagine_principale && <div className="rounded-2xl overflow-hidden mb-8 aspect-[16/9]"><img src={mediaUrl(a.immagine_principale)} alt={a.alt_text || a.titolo} className="h-full w-full object-cover" /></div>}
      <div className="prose-invert max-w-none text-foreground/90 leading-relaxed space-y-4"
        style={{ fontSize: '1.05rem' }} dangerouslySetInnerHTML={{ __html: a.contenuto }} />
      {a.modelle_correlate_dettaglio?.length > 0 && (
        <section className="mt-14">
          <div className="caps-label gold-text mb-4">Creator dell'articolo</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {a.modelle_correlate_dettaglio.map((m, i) => <ModelCard key={m.slug} model={m} index={i} />)}
          </div>
        </section>
      )}
    </article>
  );
}
