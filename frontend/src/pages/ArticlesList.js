import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getArticles, mediaUrl } from '@/lib/api';
import { setSeo, SITE } from '@/lib/seo';

export default function ArticlesList() {
  const [items, setItems] = useState(null);
  useEffect(() => {
    setSeo({ title: `Rivista | ${SITE.name}`, description: 'Approfondimenti, guide e storie dal mondo LATO SEGRETO.' });
    getArticles().then((d) => setItems(d.items || [])).catch(() => setItems([]));
  }, []);

  return (
    <div className="max-w-5xl mx-auto px-4 lg:px-8 py-8">
      <div className="caps-label gold-text mb-2">La rivista</div>
      <h1 className="text-4xl sm:text-5xl font-serif mb-8">Storie dal Lato Segreto</h1>
      {!items ? (
        <div className="grid sm:grid-cols-2 gap-6">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="h-64 rounded-2xl animate-pulse bg-muted/50" />)}</div>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">Nessun articolo pubblicato al momento.</p>
      ) : (
        <div className="grid sm:grid-cols-2 gap-6">
          {items.map((a) => (
            <Link key={a.slug} to={`/articoli/${a.slug}`} className="group rounded-2xl overflow-hidden border border-border/60 bg-card card-elev hover:card-elev-2 transition-shadow" data-testid="article-card">
              <div className="aspect-[16/9] overflow-hidden"><img src={mediaUrl(a.immagine_principale)} alt={a.alt_text || a.titolo} className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-500" loading="lazy" /></div>
              <div className="p-5">
                <div className="font-serif text-2xl mb-2 leading-tight">{a.titolo}</div>
                <p className="text-sm text-muted-foreground line-clamp-2">{a.estratto}</p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
