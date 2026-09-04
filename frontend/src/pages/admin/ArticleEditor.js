import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { admGetArticle, admCreateArticle, admUpdateArticle } from '@/lib/adminApi';
import { SectionCard, Field, TextInput, TextArea, SelectInput, Toggle, Btn, UploadField } from '@/pages/admin/ui';
import { ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';

const empty = () => ({ titolo: '', slug: '', estratto: '', contenuto: '', immagine_principale: '', autore: 'Redazione', stato: 'bozza', categorie: [], tag: [], keyword_principale: '', keyword_secondarie: [], seo_title: '', meta_description: '', indicizzabile: true, modelle_correlate: [] });

export default function ArticleEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [a, setA] = useState(empty());
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (id) admGetArticle(id).then((d) => setA({ ...empty(), ...d })); }, [id]);
  const set = (k, v) => setA((p) => ({ ...p, [k]: v }));

  const save = async () => {
    setBusy(true);
    try {
      const payload = { ...a,
        tag: Array.isArray(a.tag) ? a.tag : String(a.tag).split(',').map((t) => t.trim()).filter(Boolean),
        keyword_secondarie: Array.isArray(a.keyword_secondarie) ? a.keyword_secondarie : String(a.keyword_secondarie).split(',').map((t) => t.trim()).filter(Boolean),
        modelle_correlate: Array.isArray(a.modelle_correlate) ? a.modelle_correlate : String(a.modelle_correlate).split(',').map((t) => t.trim()).filter(Boolean),
      };
      if (id) { await admUpdateArticle(id, payload); toast.success('Salvato'); }
      else { const c = await admCreateArticle(payload); toast.success('Creato'); navigate(`/admin/articoli/${c.id}`); }
    } catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); } finally { setBusy(false); }
  };

  return (
    <div className="max-w-3xl">
      <button onClick={() => navigate('/admin/articoli')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-4"><ArrowLeft className="h-4 w-4" /> Contenuti SEO</button>
      <div className="flex items-center justify-between mb-5"><h1 className="font-serif text-3xl">{id ? 'Modifica articolo' : 'Nuovo articolo'}</h1><Btn onClick={save} disabled={busy} data-testid="save-article-button">{busy ? 'Salvataggio…' : 'Salva'}</Btn></div>
      <SectionCard title="Contenuto">
        <Field label="Titolo"><TextInput value={a.titolo} onChange={(e) => set('titolo', e.target.value)} data-testid="article-titolo" /></Field>
        <Field label="Slug"><TextInput value={a.slug} onChange={(e) => set('slug', e.target.value)} /></Field>
        <Field label="Estratto"><TextArea value={a.estratto} onChange={(e) => set('estratto', e.target.value)} /></Field>
        <Field label="Contenuto (HTML)" hint="Gli script vengono rimossi automaticamente."><TextArea value={a.contenuto} onChange={(e) => set('contenuto', e.target.value)} className="min-h-[200px] font-mono text-xs" /></Field>
        <UploadField label="Immagine principale" value={a.immagine_principale} onChange={(v) => set('immagine_principale', v)} accept="image/*" />
      </SectionCard>
      <SectionCard title="SEO e collegamenti">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Keyword principale"><TextInput value={a.keyword_principale} onChange={(e) => set('keyword_principale', e.target.value)} /></Field>
          <Field label="Autore"><TextInput value={a.autore} onChange={(e) => set('autore', e.target.value)} /></Field>
          <Field label="SEO title"><TextInput value={a.seo_title} onChange={(e) => set('seo_title', e.target.value)} /></Field>
          <Field label="Tag (virgola)"><TextInput value={Array.isArray(a.tag) ? a.tag.join(', ') : a.tag} onChange={(e) => set('tag', e.target.value)} /></Field>
        </div>
        <Field label="Meta description"><TextArea value={a.meta_description} onChange={(e) => set('meta_description', e.target.value)} /></Field>
        <Field label="Modelle correlate (slug, virgola)" hint="Es. francesca-rossi, martina-conte"><TextInput value={Array.isArray(a.modelle_correlate) ? a.modelle_correlate.join(', ') : a.modelle_correlate} onChange={(e) => set('modelle_correlate', e.target.value)} /></Field>
      </SectionCard>
      <SectionCard title="Pubblicazione">
        <div className="grid sm:grid-cols-2 gap-x-4 items-center">
          <Field label="Stato"><SelectInput value={a.stato} onChange={(e) => set('stato', e.target.value)}><option value="bozza">Bozza</option><option value="pubblicato">Pubblicato</option></SelectInput></Field>
          <div className="pt-4"><Toggle checked={a.indicizzabile} onChange={(v) => set('indicizzabile', v)} label="Indicizzabile" /></div>
        </div>
      </SectionCard>
      <div className="flex justify-end pb-10"><Btn onClick={save} disabled={busy}>Salva</Btn></div>
    </div>
  );
}
