import { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { admGetModel, admCreateModel, admUpdateModel, admGetCategories, admGetModels, admCopyConfig } from '@/lib/adminApi';
import { mediaUrl } from '@/lib/api';
import { SectionCard, Field, TextInput, TextArea, SelectInput, Toggle, Btn, UploadField } from '@/pages/admin/ui';
import ImportRapido from '@/components/admin/ImportRapido';
import { getAudio } from '@/lib/sound';
import { TRACKS, urlsForAudioCfg } from '@/lib/tracks';
import { Plus, Trash2, ArrowLeft, Copy, Check, Eye, Upload, CheckCircle2, AlertTriangle, XCircle, Play, Square } from 'lucide-react';
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
  regia: { preset: 'SENSUALE', fumo: 35, luci: 55, glow: 40, movimento: 25, audio: { ambiente: true, traccia: 'sensuale', volume_ambiente: 20, volume_effetto: 60 } },
  cta_temporizzata: { attivo: true, ritardo: 10, testo_intro: 'Vuoi vedere dove continua?', testo_pulsante: 'CONTINUA CON ME' },
  social: { instagram: '', tiktok: '', x: '', telegram: '', youtube: '', facebook: '', threads: '', snapchat: '', sito: '', custom: [] },
  seo: { title: '', meta_description: '', alt_default: '', og_image: '' },
  pellicola_home: { attiva: true, priorita: 5, ordine: null, pubblico: { video_url: '', poster_url: '' }, segreto: { video_url: '', poster_url: '' } },
  content_overrides: {},
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
  const [linkFonte, setLinkFonte] = useState('instagram');
  const [linkCampagna, setLinkCampagna] = useState('');
  const [copied, setCopied] = useState(false);
  const [publishError, setPublishError] = useState(null);
  const [importOpen, setImportOpen] = useState(false);
  const [allModels, setAllModels] = useState([]);
  const [copySource, setCopySource] = useState('');
  const [previewing, setPreviewing] = useState(false);
  const previewRef = useRef(null);

  const promoLink = () => {
    const params = new URLSearchParams({ ref: m.slug || '', fonte: linkFonte });
    if (linkCampagna.trim()) params.set('campagna', linkCampagna.trim());
    return `${window.location.origin}/?${params.toString()}`;
  };
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(promoLink()); setCopied(true); toast.success('Link copiato'); setTimeout(() => setCopied(false), 1800); }
    catch { toast.error('Impossibile copiare'); }
  };

  useEffect(() => { admGetCategories().then((d) => setCats(d.items || [])); admGetModels().then((d) => setAllModels(d.items || [])); }, []);
  useEffect(() => {
    if (id) { admGetModel(id).then((data) => { setM({ ...emptyModel(), ...data }); }).finally(() => setLoading(false)); }
  }, [id]);

  const set = (k, v) => setM((p) => ({ ...p, [k]: v }));
  const setTema = (k, v) => setM((p) => ({ ...p, tema: { ...p.tema, [k]: v } }));
  const setMsg = (k, v) => setM((p) => ({ ...p, messaggio_35s: { ...p.messaggio_35s, [k]: v } }));
  const setSeoF = (k, v) => setM((p) => ({ ...p, seo: { ...p.seo, [k]: v } }));
  const setRegia = (k, v) => setM((p) => ({ ...p, regia: { ...p.regia, [k]: v } }));
  const setAudio = (k, v) => setM((p) => ({ ...p, regia: { ...p.regia, audio: { ...(p.regia.audio || {}), [k]: v } } }));
  const setCtaT = (k, v) => setM((p) => ({ ...p, cta_temporizzata: { ...p.cta_temporizzata, [k]: v } }));
  const setSocial = (k, v) => setM((p) => ({ ...p, social: { ...p.social, [k]: v } }));
  const setPelli = (k, v) => setM((p) => ({ ...p, pellicola_home: { ...(p.pellicola_home || {}), [k]: v } }));
  const setPelliSide = (side, k, v) => setM((p) => ({ ...p, pellicola_home: { ...(p.pellicola_home || {}), [side]: { ...((p.pellicola_home || {})[side] || {}), [k]: v } } }));
  const setOverride = (key, val) => setM((p) => ({ ...p, content_overrides: { ...(p.content_overrides || {}), [key]: val } }));
  const ovr = m.content_overrides || {};

  const rid = () => Math.random().toString(36).slice(2, 9);
  const applyAssets = (assets) => setM((p) => {
    const next = { ...p };
    const pairs = [...(next.media_pairs || [])];
    const ensureImagePair = (idx) => {
      let imgs = pairs.filter((x) => x.tipo === 'image');
      while (imgs.length <= idx) { pairs.push({ id: rid(), tipo: 'image', pubblico: { tipo: 'image', url: '' }, segreto: { tipo: 'image', url: '' } }); imgs = pairs.filter((x) => x.tipo === 'image'); }
      return pairs.indexOf(imgs[idx]);
    };
    const ensureVideoPair = () => { let v = pairs.find((x) => x.tipo === 'video'); if (!v) { v = { id: rid(), tipo: 'video', pubblico: { tipo: 'video', url: '' }, segreto: { tipo: 'video', url: '' } }; pairs.push(v); } return pairs.indexOf(v); };
    assets.forEach((a) => {
      if (!a.url || a.slot === 'ignora') return;
      if (a.slot === 'foto_card') next.foto_card = a.url;
      else if (a.slot.startsWith('foto_pub_')) { const pi = ensureImagePair(+a.slot.split('_')[2] - 1); pairs[pi] = { ...pairs[pi], pubblico: { tipo: 'image', url: a.url } }; }
      else if (a.slot.startsWith('foto_sec_')) { const pi = ensureImagePair(+a.slot.split('_')[2] - 1); pairs[pi] = { ...pairs[pi], segreto: { tipo: 'image', url: a.url } }; }
      else if (a.slot === 'video_pub') { const vi = ensureVideoPair(); pairs[vi] = { ...pairs[vi], pubblico: { tipo: 'video', url: a.url } }; }
      else if (a.slot === 'video_sec') { const vi = ensureVideoPair(); pairs[vi] = { ...pairs[vi], segreto: { tipo: 'video', url: a.url } }; }
      else if (a.slot === 'pel_pub') next.pellicola_home = { ...next.pellicola_home, pubblico: { ...(next.pellicola_home?.pubblico || {}), video_url: a.url } };
      else if (a.slot === 'pel_sec') next.pellicola_home = { ...next.pellicola_home, segreto: { ...(next.pellicola_home?.segreto || {}), video_url: a.url } };
    });
    next.media_pairs = pairs;
    return next;
  });

  const openPreview = () => { if (m.slug) window.open(`/modelle/${m.slug}?anteprima=1`, '_blank', 'noopener'); };
  const previewAudio = () => {
    const audio = getAudio(); if (!audio) return;
    if (previewing && previewRef.current) { previewRef.current.stop(); previewRef.current = null; setPreviewing(false); return; }
    const vol = ((m.regia.audio || {}).volume_ambiente ?? 22) / 100;
    previewRef.current = audio.preview(urlsForAudioCfg(m.regia.audio), Math.max(0.15, vol), 12);
    setPreviewing(true);
    setTimeout(() => setPreviewing(false), 12000);
  };
  const doCopyConfig = async () => {
    if (!copySource) { toast.error('Seleziona una modella'); return; }
    try { const fresh = await admCopyConfig(id, copySource); setM({ ...emptyModel(), ...fresh }); toast.success('Impostazioni copiate'); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); }
  };
  const REGIA_PRESETS = { DELICATO: { fumo: 20, luci: 60, glow: 30, movimento: 15 }, SENSUALE: { fumo: 35, luci: 55, glow: 40, movimento: 25 }, INTENSO: { fumo: 60, luci: 50, glow: 65, movimento: 45 } };
  const applyRegiaPreset = (name) => setM((p) => ({ ...p, regia: { ...p.regia, preset: name, ...REGIA_PRESETS[name] } }));

  const toggleCat = (slug) => setM((p) => ({ ...p, categorie: p.categorie.includes(slug) ? p.categorie.filter((c) => c !== slug) : [...p.categorie, slug] }));

  // media pairs
  const addPair = (tipo) => setM((p) => ({ ...p, media_pairs: [...p.media_pairs, { id: Math.random().toString(36).slice(2), tipo, pubblico: { tipo, url: '' }, segreto: { tipo, url: '' } }] }));
  const setPair = (i, side, url) => setM((p) => { const mp = [...p.media_pairs]; mp[i] = { ...mp[i], [side]: { ...mp[i][side], url, tipo: mp[i].tipo } }; return { ...p, media_pairs: mp }; });
  const setPairPoster = (i, side, poster) => setM((p) => { const mp = [...p.media_pairs]; mp[i] = { ...mp[i], [side]: { ...mp[i][side], poster, tipo: mp[i].tipo } }; return { ...p, media_pairs: mp }; });
  const delPair = (i) => setM((p) => ({ ...p, media_pairs: p.media_pairs.filter((_, j) => j !== i) }));

  const save = async () => {
    setBusy(true);
    try {
      const payload = { ...m, tag: Array.isArray(m.tag) ? m.tag : String(m.tag).split(',').map((t) => t.trim()).filter(Boolean) };
      if (id) { const res = await admUpdateModel(id, payload); const fresh = await admGetModel(id); setM({ ...emptyModel(), ...fresh });
        if (res && res._auto) {
          if (res._auto.type === 'bozza') toast.warning('MODELLA RIPORTATA IN BOZZA', { description: `È stato rimosso un elemento obbligatorio (${res._auto.missing.join(', ')}). Il profilo non è più visibile pubblicamente.`, duration: 8000 });
          else if (res._auto.type === 'pellicola_off') toast.warning('PELLICOLA DISATTIVATA', { description: `Manca ${res._auto.missing.join(', ')}. Il profilo resta pubblicato ma è stato rimosso dalla Pellicola Home.`, duration: 8000 });
        } else { toast.success('Modifiche salvate'); }
      }
      else { const created = await admCreateModel(payload); toast.success('Modella creata'); navigate(`/admin/modelle/${created.id}`); }
    } catch (e) {
      const det = e?.response?.data?.detail;
      if (det && det.missing_required) { setPublishError(det); }
      else { toast.error(det || 'Errore nel salvataggio'); }
    }
    finally { setBusy(false); }
  };

  if (loading) return <div className="h-96 animate-pulse bg-muted/40 rounded-2xl" />;

  return (
    <div className="max-w-3xl">
      <button onClick={() => navigate('/admin/modelle')} className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground mb-4"><ArrowLeft className="h-4 w-4" /> Modelle</button>
      <div className="flex items-center justify-between mb-5 gap-3 flex-wrap">
        <h1 className="font-serif text-3xl">{id ? m.nome_artistico || 'Modifica modella' : 'Nuova modella'}</h1>
        <div className="flex items-center gap-2">
          <Btn variant="ghost" onClick={() => setImportOpen(true)} data-testid="open-import-button"><Upload className="h-4 w-4" /> Import Rapido</Btn>
          {id && m.slug && <Btn variant="ghost" onClick={openPreview} data-testid="preview-button"><Eye className="h-4 w-4" /> Anteprima sito</Btn>}
          <Btn onClick={save} disabled={busy} data-testid="save-model-button">{busy ? 'Salvataggio…' : 'Salva'}</Btn>
        </div>
      </div>

      {id && m.readiness && (
        <SectionCard title="Checklist pubblicazione" desc="Elementi obbligatori per pubblicare (i social sono opzionali). Lo stato si aggiorna dopo il salvataggio.">
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5">
            {(m.readiness.checklist || []).map((c) => (
              <div key={c.label} className="flex items-center gap-2 text-sm py-0.5" data-testid="checklist-item">
                {c.ok
                  ? <CheckCircle2 className="h-4 w-4 shrink-0" style={{ color: 'hsl(150 45% 58%)' }} />
                  : (c.required ? <XCircle className="h-4 w-4 shrink-0" style={{ color: 'hsl(0 65% 62%)' }} /> : <AlertTriangle className="h-4 w-4 shrink-0" style={{ color: 'hsl(38 75% 60%)' }} />)}
                <span className={c.ok ? '' : 'text-muted-foreground'}>{c.label}{!c.required && !c.ok ? ' — opzionale' : ''}</span>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-3 border-t border-border/50">
            {m.readiness.is_ready
              ? <span className="caps-label px-3 py-1.5 rounded-full text-xs" style={{ color: 'hsl(150 45% 58%)', border: '1px solid hsl(150 45% 58% / 0.45)' }} data-testid="ready-badge">Pronta alla pubblicazione</span>
              : <span className="caps-label px-3 py-1.5 rounded-full text-xs" style={{ color: 'hsl(38 75% 60%)', border: '1px solid hsl(38 75% 60% / 0.45)' }} data-testid="notready-badge">Mancano {m.readiness.missing_count} elementi obbligatori</span>}
          </div>
        </SectionCard>
      )}

      {id && allModels.length > 1 && (
        <SectionCard title="Copia impostazioni da un'altra modella" desc="Copia SOLO la configurazione (tema, regia, CTA, timer messaggio, impostazioni pellicola). NON copia foto, video, descrizioni, claim, OnlyFans o social.">
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex-1 min-w-[220px]">
              <SelectInput value={copySource} onChange={(e) => setCopySource(e.target.value)} data-testid="copy-source-select">
                <option value="">— Scegli modella sorgente —</option>
                {allModels.filter((x) => x.id !== id).map((x) => <option key={x.id} value={x.id}>{x.nome_artistico}</option>)}
              </SelectInput>
            </div>
            <Btn variant="ghost" onClick={doCopyConfig} disabled={!copySource} data-testid="copy-config-button"><Copy className="h-4 w-4" /> Copia impostazioni</Btn>
          </div>
        </SectionCard>
      )}

      {id && m.content_status && (
        <SectionCard title="Stato contenuti (DEMO / REALE)" desc="Riepilogo dei contenuti ancora demo per questa modella. Sostituiscili con i tuoi file reali dai campi qui sotto: il sito pubblico si aggiorna automaticamente. Il badge si ricalcola dopo il salvataggio.">
          {m.content_status.is_demo ? (
            <div>
              <div className="inline-flex items-center gap-2 caps-label px-3 py-1.5 rounded-full text-xs mb-3" style={{ color: 'hsl(38 75% 60%)', border: '1px solid hsl(38 75% 60% / 0.45)' }} data-testid="editor-content-demo">
                Contenuti DEMO · {m.content_status.demo_count} da sostituire
              </div>
              <div className="flex flex-wrap gap-2">
                {m.content_status.demo_fields.map((f) => (
                  <span key={f} className="text-[11px] px-2.5 py-1 rounded-lg border border-border/60 text-muted-foreground">{f}</span>
                ))}
              </div>
            </div>
          ) : (
            <div className="inline-flex items-center gap-2 caps-label px-3 py-1.5 rounded-full text-xs" style={{ color: 'hsl(150 45% 58%)', border: '1px solid hsl(150 45% 58% / 0.45)' }} data-testid="editor-content-real">
              Tutti i contenuti sono REALI
            </div>
          )}
        </SectionCard>
      )}

      <SectionCard title="Dati principali">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Nome"><TextInput value={m.nome} onChange={(e) => set('nome', e.target.value)} data-testid="model-nome" /></Field>
          <Field label="Nome artistico"><TextInput value={m.nome_artistico} onChange={(e) => set('nome_artistico', e.target.value)} /></Field>
          <Field label="Slug (URL)" hint="Lasciare vuoto per generarlo dal nome"><TextInput value={m.slug} onChange={(e) => set('slug', e.target.value)} /></Field>
          <Field label="Link OnlyFans"><TextInput value={m.onlyfans_url} onChange={(e) => set('onlyfans_url', e.target.value)} placeholder="https://onlyfans.com/…" data-testid="model-onlyfans" /></Field>
        </div>
        <Field label="Frase breve"><TextInput value={m.frase} onChange={(e) => set('frase', e.target.value)} placeholder="Es. Dolce finché non premi." /></Field>
        <Field label="Testo CTA principale" hint="Es. CONTINUA CON ME"><TextInput value={m.cta_testo || ''} onChange={(e) => set('cta_testo', e.target.value)} data-testid="model-cta-testo" /></Field>
        <Field label="Bio pubblica"><TextArea value={m.bio} onChange={(e) => set('bio', e.target.value)} /></Field>
        <Field label="Bio segreta"><TextArea value={m.bio_segreta} onChange={(e) => set('bio_segreta', e.target.value)} /></Field>
        <Field label="Testo teaser (limite)"><TextInput value={m.teaser_copy} onChange={(e) => set('teaser_copy', e.target.value)} /></Field>
      </SectionCard>

      <SectionCard title="Immagini principali">
        <div className="grid sm:grid-cols-2 gap-x-4">
          <UploadField label="Foto card (pubblica)" value={m.foto_card} onChange={(v) => set('foto_card', v)} accept="image/*" statusKey="foto_card" overrides={ovr} onOverride={setOverride} />
          <UploadField label="Foto copertina (hero pubblico)" value={m.foto_copertina} onChange={(v) => set('foto_copertina', v)} accept="image/*" statusKey="foto_copertina" overrides={ovr} onOverride={setOverride} />
          <UploadField label="Foto teaser card (segreta, sfocata)" value={m.foto_card_teaser} onChange={(v) => set('foto_card_teaser', v)} accept="image/*" statusKey="foto_card_teaser" overrides={ovr} onOverride={setOverride} />
          <UploadField label="Foto hero segreta" value={m.foto_segreta_hero} onChange={(v) => set('foto_segreta_hero', v)} accept="image/*" statusKey="foto_segreta_hero" overrides={ovr} onOverride={setOverride} />
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
              <UploadField label="Pubblico" value={p.pubblico?.url} onChange={(v) => setPair(i, 'pubblico', v)} accept={p.tipo === 'video' ? 'video/*' : 'image/*'} statusKey={`pair:${p.id}:pubblico`} overrides={ovr} onOverride={setOverride} />
              <UploadField label="Segreto" value={p.segreto?.url} onChange={(v) => setPair(i, 'segreto', v)} accept={p.tipo === 'video' ? 'video/*' : 'image/*'} statusKey={`pair:${p.id}:segreto`} overrides={ovr} onOverride={setOverride} />
            </div>
            {p.tipo === 'video' && (
              <div className="grid sm:grid-cols-2 gap-4 mt-3">
                <UploadField label="Poster video pubblico" value={p.pubblico?.poster} onChange={(v) => setPairPoster(i, 'pubblico', v)} accept="image/*" />
                <UploadField label="Poster video segreto" value={p.segreto?.poster} onChange={(v) => setPairPoster(i, 'segreto', v)} accept="image/*" />
              </div>
            )}
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

      <SectionCard title="Regista del Lato Segreto" desc="Regola l'atmosfera del Lato Segreto per questa modella. Preset rapidi + rifinitura manuale.">
        <div className="flex gap-2 mb-4">
          {['DELICATO', 'SENSUALE', 'INTENSO'].map((pr) => (
            <button key={pr} type="button" onClick={() => applyRegiaPreset(pr)} data-testid={`regia-preset-${pr}`}
              className="caps-label px-3 py-1.5 rounded-full border text-xs transition-colors"
              style={m.regia.preset === pr ? { background: 'hsl(var(--primary)/0.16)', borderColor: 'hsl(var(--primary)/0.45)', color: 'hsl(var(--primary))' } : { borderColor: 'hsl(var(--border))', color: 'hsl(var(--muted-foreground))' }}>{pr}</button>
          ))}
        </div>
        {[['fumo', 'Intensità fumo'], ['luci', 'Intensità luci'], ['glow', 'Intensità glow'], ['movimento', 'Intensità movimento']].map(([k, label]) => (
          <label key={k} className="block mb-3">
            <span className="caps-label text-muted-foreground flex justify-between"><span>{label}</span><span className="gold-text">{m.regia[k]}</span></span>
            <input type="range" min="0" max="100" value={m.regia[k]} onChange={(e) => setRegia(k, parseInt(e.target.value, 10))} data-testid={`regia-${k}`} className="w-full accent-[hsl(var(--primary))]" />
          </label>
        ))}
        <div className="mt-4 rounded-xl border border-border/60 p-4">
          <div className="caps-label gold-text mb-1">Audio</div>
          <p className="text-xs text-muted-foreground mb-3">Ambiente musicale sensuale che entra in dissolvenza dopo l'attivazione (parte solo dopo il tap dell'utente). Volume di sottofondo.</p>
          <div className="flex items-center gap-6 mb-3">
            <Toggle checked={(m.regia.audio || {}).ambiente !== false} onChange={(v) => setAudio('ambiente', v)} label="Ambiente sonoro attivo" />
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Traccia (atmosfera)">
              <div className="flex gap-2 items-center">
                <SelectInput value={(m.regia.audio || {}).traccia || 'velluto-nero'} onChange={(e) => setAudio('traccia', e.target.value)} data-testid="regia-audio-traccia">
                  {TRACKS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
                </SelectInput>
                <button type="button" onClick={previewAudio} data-testid="regia-audio-preview"
                  className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border text-sm hover:border-primary/60 transition-colors">
                  {previewing ? <Square className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />} {previewing ? 'Stop' : 'Ascolta'}
                </button>
              </div>
            </Field>
            <UploadField label="Melodia personalizzata (opzionale)" hint="Carica un tuo file audio: se presente, sostituisce la traccia selezionata" value={(m.regia.audio || {}).custom_url} onChange={(v) => setAudio('custom_url', v)} accept="audio/*" />
            <div />
            <Field label={`Volume ambiente — ${(m.regia.audio || {}).volume_ambiente ?? 20}%`}>
              <input type="range" min="0" max="100" value={(m.regia.audio || {}).volume_ambiente ?? 20} onChange={(e) => setAudio('volume_ambiente', parseInt(e.target.value, 10))} data-testid="regia-audio-vol-amb" className="w-full accent-[hsl(var(--primary))]" />
            </Field>
            <Field label={`Volume click attivazione — ${(m.regia.audio || {}).volume_effetto ?? 60}%`}>
              <input type="range" min="0" max="100" value={(m.regia.audio || {}).volume_effetto ?? 60} onChange={(e) => setAudio('volume_effetto', parseInt(e.target.value, 10))} data-testid="regia-audio-vol-eff" className="w-full accent-[hsl(var(--primary))]" />
            </Field>
          </div>
        </div>
        {id && m.slug && <a href={`/modelle/${m.slug}?anteprima=1`} target="_blank" rel="noreferrer" className="inline-block mt-4 text-sm gold-text underline">Apri anteprima reale del Lato Segreto →</a>}
      </SectionCard>

      <SectionCard title="CTA temporizzata" desc="Compare dal basso dopo un ritardo configurabile (default 10s), senza popup aggressivo.">
        <div className="flex items-center gap-6 mb-3">
          <Toggle checked={m.cta_temporizzata.attivo} onChange={(v) => setCtaT('attivo', v)} label="Attiva" />
          <div className="flex items-center gap-2"><span className="text-sm text-muted-foreground">Ritardo (s)</span><TextInput type="number" value={m.cta_temporizzata.ritardo} onChange={(e) => setCtaT('ritardo', parseInt(e.target.value || '10', 10))} className="w-20" /></div>
        </div>
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Testo introduttivo"><TextInput value={m.cta_temporizzata.testo_intro} onChange={(e) => setCtaT('testo_intro', e.target.value)} /></Field>
          <Field label="Testo pulsante"><TextInput value={m.cta_temporizzata.testo_pulsante} onChange={(e) => setCtaT('testo_pulsante', e.target.value)} /></Field>
        </div>
      </SectionCard>

      <SectionCard title="Social e link" desc="Mostrati nella sezione «Scoprimi anche qui». Solo i campi compilati verranno visualizzati. OnlyFans resta la CTA principale.">
        <div className="grid sm:grid-cols-2 gap-x-4">
          {[['instagram', 'Instagram'], ['tiktok', 'TikTok'], ['x', 'X'], ['telegram', 'Telegram'], ['youtube', 'YouTube'], ['facebook', 'Facebook'], ['threads', 'Threads'], ['snapchat', 'Snapchat'], ['sito', 'Sito personale']].map(([k, label]) => (
            <Field key={k} label={label}><TextInput value={m.social[k] || ''} onChange={(e) => setSocial(k, e.target.value)} placeholder="https://…" data-testid={`social-input-${k}`} /></Field>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="PELLICOLA HOME (IN MOVIMENTO)" desc="Configura la presenza di questa modella nella fascia cinematografica della Home. Consigliati teaser verticali 10–15s. Se i video non sono impostati, viene usato il primo video delle coppie di contenuti.">
        <div className="flex items-center gap-6 mb-3">
          <Toggle checked={(m.pellicola_home || {}).attiva !== false} onChange={(v) => setPelli('attiva', v)} label="Mostra nella pellicola" />
        </div>
        <div className="grid sm:grid-cols-2 gap-x-4">
          <Field label="Priorità (1–10)" hint="Più alta = più in evidenza">
            <TextInput type="number" min="1" max="10" value={(m.pellicola_home || {}).priorita ?? 5} onChange={(e) => setPelli('priorita', Math.max(1, Math.min(10, parseInt(e.target.value || '5', 10))))} data-testid="pellicola-priorita" />
          </Field>
          <Field label="Ordine manuale (opzionale)" hint="Lascia vuoto per usare la priorità">
            <TextInput type="number" value={(m.pellicola_home || {}).ordine ?? ''} onChange={(e) => setPelli('ordine', e.target.value === '' ? null : parseInt(e.target.value, 10))} />
          </Field>
        </div>
        <div className="grid sm:grid-cols-2 gap-4 mt-1">
          <div className="rounded-xl border border-border/60 p-3">
            <div className="caps-label text-muted-foreground mb-2">Versione pubblica</div>
            <UploadField label="Video pubblico" value={(m.pellicola_home || {}).pubblico?.video_url} onChange={(v) => setPelliSide('pubblico', 'video_url', v)} accept="video/*" statusKey="pel_pub_video" overrides={ovr} onOverride={setOverride} />
            <UploadField label="Poster pubblico" value={(m.pellicola_home || {}).pubblico?.poster_url} onChange={(v) => setPelliSide('pubblico', 'poster_url', v)} accept="image/*" />
          </div>
          <div className="rounded-xl border border-border/60 p-3">
            <div className="caps-label text-muted-foreground mb-2">Versione segreta</div>
            <UploadField label="Video segreto" value={(m.pellicola_home || {}).segreto?.video_url} onChange={(v) => setPelliSide('segreto', 'video_url', v)} accept="video/*" statusKey="pel_sec_video" overrides={ovr} onOverride={setOverride} />
            <UploadField label="Poster segreto" value={(m.pellicola_home || {}).segreto?.poster_url} onChange={(v) => setPelliSide('segreto', 'poster_url', v)} accept="image/*" />
          </div>
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

      {id && m.slug && (
        <SectionCard title="Crea link promozionale" desc="Genera un link con attribuzione da dare alla creator per i suoi social. Gli eventi (visite, Lato Segreto, click OnlyFans) verranno attribuiti a questa fonte/campagna.">
          <div className="grid sm:grid-cols-2 gap-x-4">
            <Field label="Fonte"><SelectInput value={linkFonte} onChange={(e) => setLinkFonte(e.target.value)}>{['instagram', 'tiktok', 'facebook', 'telegram', 'x', 'altro'].map((f) => <option key={f} value={f}>{f}</option>)}</SelectInput></Field>
            <Field label="Campagna (facoltativa)"><TextInput value={linkCampagna} onChange={(e) => setLinkCampagna(e.target.value)} placeholder="es. settembre" /></Field>
          </div>
          <div className="flex items-center gap-2 p-3 rounded-lg border border-border/60 bg-background">
            <span className="flex-1 text-xs font-mono break-all" data-testid="promo-link">{promoLink()}</span>
            <Btn onClick={copyLink} variant="ghost" data-testid="copy-promo-link">{copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />} Copia</Btn>
          </div>
        </SectionCard>
      )}

      <div className="flex justify-end pb-10"><Btn onClick={save} disabled={busy}>{busy ? 'Salvataggio…' : 'Salva'}</Btn></div>

      {importOpen && <ImportRapido onApply={applyAssets} onClose={() => setImportOpen(false)} />}

      {publishError && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" data-testid="publish-block-modal">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setPublishError(null)} />
          <div className="relative z-10 w-full max-w-md rounded-2xl border border-border/60 bg-card p-6 card-elev-2">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="h-6 w-6" style={{ color: 'hsl(38 75% 60%)' }} />
              <h3 className="font-serif text-2xl">{publishError.message || 'NON PUOI ANCORA PUBBLICARE'}</h3>
            </div>
            <p className="text-sm text-muted-foreground mb-3">Mancano {publishError.missing_count} elementi obbligatori:</p>
            <ul className="space-y-1.5 mb-5">
              {(publishError.missing_required || []).map((f) => (
                <li key={f} className="flex items-center gap-2 text-sm"><XCircle className="h-4 w-4 shrink-0" style={{ color: 'hsl(0 65% 62%)' }} /> {f}</li>
              ))}
            </ul>
            <div className="flex justify-end"><Btn onClick={() => setPublishError(null)} data-testid="complete-profile-button">Completa profilo</Btn></div>
          </div>
        </div>
      )}
    </div>
  );
}
