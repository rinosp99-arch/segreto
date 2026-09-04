import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { admGetModel, admCreateModel, admUpdateModel, admGetCategories } from '@/lib/adminApi';
import { mediaUrl } from '@/lib/api';
import { SectionCard, Field, TextInput, TextArea, SelectInput, Toggle, Btn, UploadField } from '@/pages/admin/ui';
import { Plus, Trash2, ArrowLeft } from 'lucide-react';
import { toast } from 'sonner';

const PRESETS = ['bordeaux', 'tattoo', 'dolce', 'sportiva', 'cosplay'];
const BADGES = ['', 'NUOVA', 'IN TENDENZA', 'PIÙ VISTA', 'SCELTA DEL GIORNO'];

const emptyModel = () => ({
  nome: '', nome_artistico: '', slug: '', frase: '', bio: '', bio_segreta: '',
  foto_copertina: '', foto_card: '', foto_card_teaser: '', foto_segreta_hero: '',
  galleria_pubblica: [], galleria_segreta: [], media_pairs: [],
  categorie: [], tag: [], badge: '', badge_tipo: 'editoriale',
  onlyfans_url: '', cta_testo: 'CONTINUA CON ME',
  tema: { preset: 'bordeaux', colore_primario: '40 55% 60%', colore_secondario: '350 45% 30%', grain: 0.08, glow: true, sfondo_stile: 'vignetta', frase_attivazione: 'NON DOVRESTI PREMERLO', testo_dopo_click: "Te l'avevamo detto.", effetti_touch: true },
  messaggio_35s: { attivo: true, timer: 35, testo: '', foto: '', video: '', cta_testo: 'CONTINUA CON ME' },
  seo: { title: '', meta_description: '', alt_default: '', og_image: '' },
  teaser_copy: 'Qui posso mostrarti solo fino a questo punto.',
  stato: 'bozza', ordine: 0, conferma_maggiorenne: false,
});

export default function ModelEditor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [m, setM] = useState(emptyModel());
  const [cats, setCats] = useState([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(!!id);
  const [previewSecret, setPreviewSecret] = useState(false);

  useEffect(() => { admGetCategories().then((d) => setCats(d.items || [])); }, []);
  useEffect(() => {
    if (id) { admGetModel(id).then((data) => { setM({ ...emptyModel(), ...data }); }).finally(() => setLoading(false)); }
  }, [id]);

  const set = (k, v) => setM((p) => ({ ...p, [k]: v }));
  const setTema = (k, v) => setM((p) => ({ ...p, tema: { ...p.tema, [k]: v } }));
  const setMsg = (k, v) => setM((p) => ({ ...p, messaggio_35s: { ...p.messaggio_35s, [k]: v } }));
  const setSeoF = (k, v) => setM((p) => ({ ...p, seo: { ...p.seo, [k]: v } }));

  const toggleCat = (slug) => setM((p) => ({ ...p, categorie: p.categorie.includes(slug) ? p.categorie.filter((c) => c !== slug) : [...p.categorie, slug] }));

  // media pairs
  const addPair = (tipo) => setM((p) => ({ ...p, media_pairs: [...p.media_pairs, { id: Math.random().toString(36).slice(2), tipo, pubblico: { tipo, url: '' }, segreto: { tipo, url: '' } }] }));
  const setPair = (i, side, url) => setM((p) => { const mp = [...p.media_pairs]; mp[i] = { ...mp[i], [side]: { ...mp[i][side], url, tipo: mp[i].tipo } }; return { ...p, media_pairs: mp }; });
  const delPair = (i) => setM((p) => ({ ...p, media_pairs: p.media_pairs.filter((_, j) => j !== i) }));

  const save = async () => {
    setBusy(true);
    try {
      const payload = { ...m, tag: Array.isArray(m.tag) ? m.tag : String(m.tag).split(',').map((t) => t.trim()).filter(Boolean) };
      if (id) { await admUpdateModel(id, payload); toast.success('Modifiche salvate'); }
      else { const created = await admCreateModel(payload); toast.success('Modella creata'); navigate(`/admin/modelle/${created.id}`); }
    } catch (e) { toast.error(e?.response?.data?.detail || 'Errore nel salvataggio'); }
    finally { setBusy(false); }
  };

  if (loading) return <div className="h-96 animate-pulse bg-muted/40 rounded-2xl" />;

  return (
    <div className="max-w-3xl">
      <button onClick={() => navigate('/admin/modelle')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-4"><ArrowLeft className="h-4 w-4" /> Modelle</button>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">{id ? m.nome_artistico || 'Modifica modella' : 'Nuova modella'}</h1>
        <Btn onClick={save} disabled={busy} data-testid="save-model-button">{busy ? 'Salvataggio…' : 'Salva'}</Btn>
      </div>

      <SectionCard title="Dati principali">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Nome"><TextInput value={m.nome} onChange={(e) => set('nome', e.target.value)} data-testid="model-nome" /></Field>
          <Field label="Nome artistico"><TextInput value={m.nome_artistico} onChange={(e) => set('nome_artistico', e.target.value)} /></Field>
          <Field label="Slug (URL)" hint="Lasciare vuoto per generarlo dal nome"><TextInput value={m.slug} onChange={(e) => set('slug', e.target.value)} /></Field>
          <Field label="Link OnlyFans"><TextInput value={m.onlyfans_url} onChange={(e) => set('onlyfans_url', e.target.value)} placeholder="https://onlyfans.com/…" data-testid="model-onlyfans" /></Field>
        </div>
        <Field label="Frase breve"><TextInput value={m.frase} onChange={(e) => set('frase', e.target.value)} placeholder="Es. Dolce finché non premi." /></Field>
        <Field label="Bio pubblica"><TextArea value={m.bio} onChange={(e) => set('bio', e.target.value)} /></Field>
        <Field label="Bio segreta"><TextArea value={m.bio_segreta} onChange={(e) => set('bio_segreta', e.target.value)} /></Field>
        <Field label="Testo teaser (limite)"><TextInput value={m.teaser_copy} onChange={(e) => set('teaser_copy', e.target.value)} /></Field>
      </SectionCard>

      <SectionCard title="Immagini principali">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <UploadField label="Foto card (pubblica)" value={m.foto_card} onChange={(v) => set('foto_card', v)} accept="image/*" />
          <UploadField label="Foto copertina (hero pubblico)" value={m.foto_copertina} onChange={(v) => set('foto_copertina', v)} accept="image/*" />
          <UploadField label="Foto teaser card (segreta, sfocata)" value={m.foto_card_teaser} onChange={(v) => set('foto_card_teaser', v)} accept="image/*" />
          <UploadField label="Foto hero segreta" value={m.foto_segreta_hero} onChange={(v) => set('foto_segreta_hero', v)} accept="image/*" />
        </div>
      </SectionCard>

      <SectionCard title="Coppie di contenuti (trasformazione)" desc="Ogni posizione della griglia ha una versione pubblica e una segreta. Consigliato: 3 foto + 2 video. Stesso formato per evitare salti.">
        <div className="mb-4 flex items-center justify-between">
          <span className="caps-label text-muted-foreground">Anteprima</span>
          <div className="flex gap-1 bg-background border border-border/60 rounded-full p-1">
            <button type="button" onClick={() => setPreviewSecret(false)} className={`px-3 py-1 text-xs rounded-full ${!previewSecret ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`}>Pubblico</button>
            <button type="button" onClick={() => setPreviewSecret(true)} className={`px-3 py-1 text-xs rounded-full ${previewSecret ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`}>Segreto</button>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-2 mb-5" data-testid="transform-preview">
          {m.media_pairs.map((p, i) => {
            const url = previewSecret ? p.segreto?.url : p.pubblico?.url;
            const isVid = p.tipo === 'video';
            return (
              <div key={`prev-${i}`} className="relative rounded-lg overflow-hidden border border-border/60 bg-muted/40" style={{ aspectRatio: '3/4' }}>
                {url ? (isVid ? <video src={mediaUrl(url)} muted className="h-full w-full object-cover" style={previewSecret ? { filter: 'saturate(0.82) hue-rotate(-12deg)' } : {}} /> : <img src={mediaUrl(url)} alt="" className="h-full w-full object-cover" style={previewSecret ? { filter: 'saturate(0.82) hue-rotate(-12deg)' } : {}} />) : <div className="h-full w-full flex items-center justify-center text-[10px] text-muted-foreground">vuoto</div>}
                <span className="absolute bottom-1 left-1 text-[9px] px-1.5 py-0.5 rounded bg-black/60">{isVid ? 'Video' : 'Foto'} {i + 1}</span>
              </div>
            );
          })}
        </div>
        {m.media_pairs.map((p, i) => (
          <div key={p.id || i} className="rounded-xl border border-border/60 p-3 mb-3">
            <div className="flex items-center justify-between mb-2">
              <span className="caps-label text-muted-foreground">Posizione {i + 1} · {p.tipo === 'video' ? 'video' : 'foto'}</span>
              <button onClick={() => delPair(i)} className="text-red-300"><Trash2 className="h-4 w-4" /></button>
            </div>
            <div className="grid sm:grid-cols-2 gap-4">
              <UploadField label="Pubblico" value={p.pubblico?.url} onChange={(v) => setPair(i, 'pubblico', v)} accept={p.tipo === 'video' ? 'video/*' : 'image/*'} />
              <UploadField label="Segreto" value={p.segreto?.url} onChange={(v) => setPair(i, 'segreto', v)} accept={p.tipo === 'video' ? 'video/*' : 'image/*'} />
            </div>
          </div>
        ))}
        <div className="flex gap-2">
          <Btn variant="ghost" onClick={() => addPair('image')}><Plus className="h-4 w-4" /> Coppia immagini</Btn>
          <Btn variant="ghost" onClick={() => addPair('video')}><Plus className="h-4 w-4" /> Coppia video</Btn>
        </div>
      </SectionCard>

      <SectionCard title="Categorie, tag e badge">
        <Field label="Categorie">
          <div className="flex flex-wrap gap-2">
            {cats.map((c) => (
              <button key={c.slug} onClick={() => toggleCat(c.slug)} className="caps-label px-3 py-1.5 rounded-full border text-xs transition-colors"
                style={m.categorie.includes(c.slug) ? { background: 'hsl(var(--primary)/0.16)', borderColor: 'hsl(var(--primary)/0.45)', color: 'hsl(var(--primary))' } : { borderColor: 'hsl(var(--border))', color: 'hsl(var(--muted-foreground))' }}>{c.nome}</button>
            ))}
          </div>
        </Field>
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Tag (separati da virgola)"><TextInput value={Array.isArray(m.tag) ? m.tag.join(', ') : m.tag} onChange={(e) => set('tag', e.target.value.split(',').map((t) => t.trim()))} /></Field>
          <Field label="Badge"><SelectInput value={m.badge || ''} onChange={(e) => set('badge', e.target.value || null)}>{BADGES.map((b) => <option key={b} value={b}>{b || '— nessuno —'}</option>)}</SelectInput></Field>
        </div>
      </SectionCard>

      <SectionCard title="Personalizzazione Lato Segreto (tema)">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Preset"><SelectInput value={m.tema.preset} onChange={(e) => setTema('preset', e.target.value)}>{PRESETS.map((p) => <option key={p} value={p}>{p}</option>)}</SelectInput></Field>
          <Field label="Colore primario (HSL)" hint="es. 40 55% 60%"><TextInput value={m.tema.colore_primario} onChange={(e) => setTema('colore_primario', e.target.value)} /></Field>
          <Field label="Colore secondario (HSL)"><TextInput value={m.tema.colore_secondario} onChange={(e) => setTema('colore_secondario', e.target.value)} /></Field>
          <Field label="Grana (0-1)"><TextInput type="number" step="0.01" value={m.tema.grain} onChange={(e) => setTema('grain', parseFloat(e.target.value))} /></Field>
          <Field label="Frase di attivazione"><TextInput value={m.tema.frase_attivazione} onChange={(e) => setTema('frase_attivazione', e.target.value)} /></Field>
          <Field label="Testo dopo il click"><TextInput value={m.tema.testo_dopo_click} onChange={(e) => setTema('testo_dopo_click', e.target.value)} /></Field>
        </div>
        <div className="flex gap-6 mt-1">
          <Toggle checked={m.tema.glow} onChange={(v) => setTema('glow', v)} label="Glow" />
          <Toggle checked={m.tema.effetti_touch} onChange={(v) => setTema('effetti_touch', v)} label="Effetti touch" />
        </div>
      </SectionCard>

      <SectionCard title="Messaggio dopo 35 secondi">
        <div className="flex items-center gap-6 mb-3">
          <Toggle checked={m.messaggio_35s.attivo} onChange={(v) => setMsg('attivo', v)} label="Attivo" />
          <div className="flex items-center gap-2"><span className="text-sm text-muted-foreground">Timer (s)</span><TextInput type="number" value={m.messaggio_35s.timer} onChange={(e) => setMsg('timer', parseInt(e.target.value || '35', 10))} className="w-20" /></div>
        </div>
        <Field label="Testo del messaggio"><TextArea value={m.messaggio_35s.testo} onChange={(e) => setMsg('testo', e.target.value)} /></Field>
        <div className="grid sm:grid-cols-2 gap-x-4">
          <UploadField label="Foto (opzionale)" value={m.messaggio_35s.foto} onChange={(v) => setMsg('foto', v)} accept="image/*" />
          <Field label="Testo CTA"><TextInput value={m.messaggio_35s.cta_testo} onChange={(e) => setMsg('cta_testo', e.target.value)} /></Field>
        </div>
      </SectionCard>

      <SectionCard title="SEO">
        <Field label="SEO Title"><TextInput value={m.seo.title} onChange={(e) => setSeoF('title', e.target.value)} /></Field>
        <Field label="Meta description"><TextArea value={m.seo.meta_description} onChange={(e) => setSeoF('meta_description', e.target.value)} /></Field>
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Alt text predefinito"><TextInput value={m.seo.alt_default} onChange={(e) => setSeoF('alt_default', e.target.value)} /></Field>
          <UploadField label="Immagine OG (social)" value={m.seo.og_image} onChange={(v) => setSeoF('og_image', v)} accept="image/*" />
        </div>
      </SectionCard>

      <SectionCard title="Pubblicazione">
        <div className="grid sm:grid-cols-2 gap-x-4 items-end">
          <Field label="Stato"><SelectInput value={m.stato} onChange={(e) => set('stato', e.target.value)}><option value="bozza">Bozza</option><option value="pubblicata">Pubblicata</option><option value="disattivata">Disattivata</option></SelectInput></Field>
          <Field label="Ordine"><TextInput type="number" value={m.ordine} onChange={(e) => set('ordine', parseInt(e.target.value || '0', 10))} /></Field>
        </div>
        <div className="mt-2 p-3 rounded-lg border border-border/60 flex items-center justify-between">
          <span className="text-sm">Conferma creator maggiorenne <span className="text-muted-foreground">(obbligatorio per pubblicare)</span></span>
          <Toggle checked={m.conferma_maggiorenne} onChange={(v) => set('conferma_maggiorenne', v)} />
        </div>
      </SectionCard>

      <div className="flex justify-end pb-10"><Btn onClick={save} disabled={busy}>{busy ? 'Salvataggio…' : 'Salva'}</Btn></div>
    </div>
  );
}
