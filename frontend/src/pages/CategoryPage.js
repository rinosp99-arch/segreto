import DOMPurify from 'dompurify';
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { getCategory } from '@/lib/api';
import { ModelCard } from '@/components/ModelCard';
import { setSeo, setNotFoundSeo, SITE } from '@/lib/seo';
import { ArrowLeft, SearchX } from 'lucide-react';

export default function CategoryPage() {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    setData(null); setNotFound(false);
    getCategory(slug).then((d) => {
      setData(d);
      const c = d.categoria;
      setSeo({
        title: c.seo_title || `${c.nome} | ${SITE.name}`,
        description: c.meta_description || c.descrizione,
        noindex: !c.indicizzabile,
        jsonLd: {
          '@context': 'https://schema.org', '@type': 'BreadcrumbList',
          itemListElement: [
            { '@type': 'ListItem', position: 1, name: 'Inizio', item: window.location.origin },
            { '@type': 'ListItem', position: 2, name: c.nome, item: window.location.href },
          ],
        },
      });
    }).catch(() => { setNotFoundSeo(); setNotFound(true); });
  }, [slug]);

  if (notFound) return (
    <div className="max-w-2xl mx-auto px-4 py-24 text-center" data-testid="category-not-found">
      <div className="font-serif text-3xl mb-2">Categoria non trovata</div>
      <Link to="/" className="btn-gold inline-block rounded-xl px-6 py-3 text-sm mt-4">Torna alla home</Link>
    </div>
  );
  if (!data) return <div className="max-w-6xl mx-auto px-4 py-10"><div className="h-40 animate-pulse bg-muted/50 rounded-2xl" /></div>;

  const { categoria, items } = data;
  return (
    <div className="max-w-6xl mx-auto px-4 lg:px-8 py-6">
      <nav className="text-sm text-muted-foreground mb-4 flex items-center gap-2">
        <Link to="/" className="hover:text-foreground inline-flex items-center gap-1"><ArrowLeft className="h-4 w-4" />Inizio</Link>
        <span>/</span><span className="text-foreground">{categoria.nome}</span>
      </nav>
      <h1 className="text-4xl sm:text-5xl font-serif mb-3">{categoria.nome}</h1>
      {categoria.descrizione && <p className="text-muted-foreground max-w-2xl mb-8">{categoria.descrizione}</p>}
      {items.length === 0 ? (
        <div className="py-20 text-center"><SearchX className="h-10 w-10 mx-auto mb-3 text-muted-foreground" /><p className="text-muted-foreground">Questa categoria non contiene ancora profili.</p></div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5">
          {items.map((m, i) => <ModelCard key={m.slug} model={m} index={i} placement="category" context={slug} />)}
        </div>
      )}
      {categoria.testo_seo && (
        <section className="article-body max-w-3xl mt-16 mb-6 text-foreground/85 leading-relaxed"
          dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(categoria.testo_seo, { USE_PROFILES: { html: true }, FORBID_TAGS: ['style', 'iframe', 'object', 'embed', 'form'], FORBID_ATTR: ['onerror', 'onload'] }) }} />
      )}
    </div>
  );
}
