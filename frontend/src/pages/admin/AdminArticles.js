import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { admGetArticles, admDeleteArticle } from '@/lib/adminApi';
import { Btn } from '@/pages/admin/ui';
import { Plus, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

export default function AdminArticles() {
  const [items, setItems] = useState([]);
  const load = () => admGetArticles().then((d) => setItems(d.items || []));
  useEffect(() => { load(); }, []);
  const del = async (a) => { if (!window.confirm(`Eliminare "${a.titolo}"?`)) return; await admDeleteArticle(a.id); toast.success('Eliminato'); load(); };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div><h1 className="font-serif text-3xl">Contenuti SEO</h1><p className="text-xs text-muted-foreground mt-1">Articoli editoriali. I contenuti da integrazioni esterne arrivano come bozza.</p></div>
        <Link to="/admin/articoli/nuovo"><Btn data-testid="new-article-button"><Plus className="h-4 w-4" /> Nuovo</Btn></Link>
      </div>
      <div className="space-y-2">
        {items.map((a) => (
          <div key={a.id} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3">
            <div className="flex-1 min-w-0"><div className="font-serif text-lg leading-none truncate">{a.titolo}</div><div className="text-xs text-muted-foreground">/{a.slug} · {a.fonte || 'manuale'}</div></div>
            <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: a.stato === 'pubblicato' ? 'hsl(150 40% 55%)' : 'hsl(38 70% 60%)', border: '1px solid hsl(var(--border))' }}>{a.stato}</span>
            <Link to={`/admin/articoli/${a.id}`} className="h-9 w-9 flex items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"><Pencil className="h-4 w-4" /></Link>
            <button onClick={() => del(a)} className="h-9 w-9 flex items-center justify-center rounded-lg border text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.4)' }}><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
        {items.length === 0 && <p className="text-sm text-muted-foreground">Nessun articolo.</p>}
      </div>
    </div>
  );
}
