import { useEffect, useState } from 'react';
import { admGetCategories, admCreateCategory, admUpdateCategory, admDeleteCategory } from '@/lib/adminApi';
import { SectionCard, Field, TextInput, TextArea, Toggle, Btn } from '@/pages/admin/ui';
import { Plus, Trash2, Pencil, X } from 'lucide-react';
import { toast } from 'sonner';

const empty = { nome: '', slug: '', descrizione: '', seo_title: '', meta_description: '', ordine: 0, indicizzabile: true, stato: 'pubblicata' };

export default function AdminCategories() {
  const [items, setItems] = useState([]);
  const [editing, setEditing] = useState(null);

  const load = () => admGetCategories().then((d) => setItems(d.items || []));
  useEffect(() => { load(); }, []);

  const save = async () => {
    try {
      if (editing.id) await admUpdateCategory(editing.id, editing);
      else await admCreateCategory(editing);
      toast.success('Salvata'); setEditing(null); load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); }
  };
  const del = async (c) => { if (!window.confirm(`Eliminare ${c.nome}?`)) return; await admDeleteCategory(c.id); toast.success('Eliminata'); load(); };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">Categorie</h1>
        <Btn onClick={() => setEditing({ ...empty })} data-testid="new-category-button"><Plus className="h-4 w-4" /> Nuova</Btn>
      </div>

      {editing && (
        <SectionCard title={editing.id ? 'Modifica categoria' : 'Nuova categoria'}>
          <div className="grid sm:grid-cols-2 gap-x-4">
            <Field label="Nome"><TextInput value={editing.nome} onChange={(e) => setEditing({ ...editing, nome: e.target.value })} data-testid="category-nome" /></Field>
            <Field label="Slug"><TextInput value={editing.slug} onChange={(e) => setEditing({ ...editing, slug: e.target.value })} /></Field>
          </div>
          <Field label="Descrizione"><TextArea value={editing.descrizione} onChange={(e) => setEditing({ ...editing, descrizione: e.target.value })} /></Field>
          <div className="grid sm:grid-cols-2 gap-x-4">
            <Field label="SEO title"><TextInput value={editing.seo_title} onChange={(e) => setEditing({ ...editing, seo_title: e.target.value })} /></Field>
            <Field label="Meta description"><TextInput value={editing.meta_description} onChange={(e) => setEditing({ ...editing, meta_description: e.target.value })} /></Field>
          </div>
          <div className="flex items-center gap-6 mb-3"><Toggle checked={editing.indicizzabile} onChange={(v) => setEditing({ ...editing, indicizzabile: v })} label="Indicizzabile" /></div>
          <div className="flex gap-2"><Btn onClick={save} data-testid="save-category-button">Salva</Btn><Btn variant="ghost" onClick={() => setEditing(null)}><X className="h-4 w-4" /> Annulla</Btn></div>
        </SectionCard>
      )}

      <div className="space-y-2">
        {items.map((c) => (
          <div key={c.id} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3">
            <div className="flex-1"><div className="font-serif text-lg leading-none">{c.nome}</div><div className="text-xs text-muted-foreground">/{c.slug} · {c.conteggio ?? 0} modelle {c.indicizzabile ? '' : '· no-index'}</div></div>
            <button onClick={() => setEditing(c)} className="h-9 w-9 flex items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"><Pencil className="h-4 w-4" /></button>
            <button onClick={() => del(c)} className="h-9 w-9 flex items-center justify-center rounded-lg border text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.4)' }}><Trash2 className="h-4 w-4" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
