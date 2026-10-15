import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCategories } from '@/lib/api';

/* Links to every indexable category, worded like the searches ("OnlyFans bionde italiane").
   The server writes the same links into its HTML: categoryLinks() in server/seo.js. */
export const categoryLabel = (c) => `OnlyFans ${String(c.nome || c.slug).toLowerCase()} italiane`;

export function CategoryLinks({ title = 'Esplora per categoria', className = '' }) {
  const [cats, setCats] = useState([]);
  useEffect(() => { getCategories().then((d) => setCats((d.items || []).filter((c) => c.indicizzabile !== false))).catch(() => {}); }, []);
  if (!cats.length) return null;
  return (
    <nav aria-label={title} className={className} data-testid="category-links">
      <div className="caps-label gold-text mb-2">{title}</div>
      <p className="text-sm leading-relaxed">
        {cats.map((c, i) => (
          <span key={c.slug}>{i > 0 && <span className="text-muted-foreground"> · </span>}<Link to={`/categorie/${c.slug}`} className="underline-offset-4 hover:underline" style={{ color: 'hsl(var(--primary))' }}>{categoryLabel(c)}</Link></span>
        ))}
      </p>
    </nav>
  );
}
