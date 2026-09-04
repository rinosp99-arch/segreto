import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { admGetModels, admSetStatus, admDeleteModel, admReorder, admCopyConfigBulk } from '@/lib/adminApi';
import { mediaUrl } from '@/lib/api';
import { Btn, SelectInput, Toggle } from '@/pages/admin/ui';
import { Plus, ChevronUp, ChevronDown, Pencil, Trash2, Copy, X } from 'lucide-react';
import { toast } from 'sonner';

const STATO_STYLE = {
  pubblicata: { c: 'hsl(150 40% 55%)', b: 'hsl(150 40% 55% / 0.4)' },
  bozza: { c: 'hsl(38 70% 60%)', b: 'hsl(38 70% 60% / 0.4)' },
  disattivata: { c: 'hsl(0 55% 60%)', b: 'hsl(0 55% 60% / 0.4)' },
};

const OP_STYLE = {
  pubblicata: { c: 'hsl(150 45% 58%)', l: 'PUBBLICATA' },
  pronta: { c: 'hsl(190 55% 60%)', l: 'PRONTA' },
  incompleta: { c: 'hsl(38 75% 60%)', l: 'INCOMPLETA' },
};

const FILTERS = [
  { k: 'tutte', l: 'Tutte' },
  { k: 'demo', l: 'Solo Demo' },
  { k: 'reali', l: 'Solo Reali' },
  { k: 'incomplete', l: 'Incomplete' },
  { k: 'pronte', l: 'Pronte alla pubblicazione' },
];

export default function AdminModels() {
  const [items, setItems] = useState([]);
  const [counts, setCounts] = useState({ tutte: 0, demo: 0, reali: 0, incomplete: 0, pronte: 0 });
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('tutte');
  const [selected, setSelected] = useState(new Set());
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkSource, setBulkSource] = useState('');
  const [bulkSections, setBulkSections] = useState({ regista: true, conversione: false, pellicola: false });
  const [bulkBusy, setBulkBusy] = useState(false);

  const load = () => {
    setLoading(true);
    admGetModels().then((d) => { setItems(d.items || []); setCounts(d.counts || counts); }).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const filtered = useMemo(() => items.filter((m) => {
    const cs = m.content_status || {}; const rd = m.readiness || {}; const op = m.stato_operativo;
    if (filter === 'demo') return cs.is_demo;
    if (filter === 'reali') return !cs.is_demo;
    if (filter === 'incomplete') return op === 'incompleta';
    if (filter === 'pronte') return rd.is_ready && m.stato !== 'pubblicata';
    return true;
  }), [items, filter]);

  const toggleStatus = async (m) => {
    const next = m.stato === 'pubblicata' ? 'bozza' : 'pubblicata';
    try { await admSetStatus(m.id, next); toast.success(next === 'pubblicata' ? 'Pubblicata' : 'Messa in bozza'); load(); }
    catch (e) {
      const det = e?.response?.data?.detail;
      if (det && det.missing_required) toast.error(`${det.message}: mancano ${det.missing_count} elementi obbligatori`);
      else toast.error(det || 'Errore');
    }
  };
  const del = async (m) => { if (!window.confirm(`Eliminare ${m.nome_artistico}?`)) return; await admDeleteModel(m.id); toast.success('Eliminata'); load(); };
  const move = async (idx, dir) => {
    const arr = [...items]; const j = idx + dir; if (j < 0 || j >= arr.length) return;
    [arr[idx], arr[j]] = [arr[j], arr[idx]]; setItems(arr);
    await admReorder(arr.map((x) => x.id));
  };

  const toggleSel = (mid) => setSelected((prev) => { const n = new Set(prev); if (n.has(mid)) n.delete(mid); else n.add(mid); return n; });
  const clearSel = () => setSelected(new Set());
  const sectionLabels = { regista: 'Regista (tema, fumo, luci, glow, movimento, suoni)', conversione: 'Conversione (CTA, timer messaggio)', pellicola: 'Pellicola (priorità, impostazioni)' };
  const runBulk = async () => {
    if (!bulkSource) { toast.error('Scegli una modella sorgente'); return; }
    const targets = [...selected].filter((tid) => tid !== bulkSource);
    if (!targets.length) { toast.error('Nessuna destinataria valida'); return; }
    setBulkBusy(true);
    try {
      const r = await admCopyConfigBulk(bulkSource, targets, bulkSections);
      toast.success(`Configurazione applicata a ${r.updated} modelle`);
      setBulkOpen(false); clearSel(); load();
    } catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); }
    finally { setBulkBusy(false); }
  };
  const srcName = (id) => (items.find((x) => x.id === id) || {}).nome_artistico || '';
  const targetCount = [...selected].filter((tid) => tid !== bulkSource).length;

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">Modelle</h1>
        <Link to="/admin/modelle/nuova"><Btn data-testid="new-model-button"><Plus className="h-4 w-4" /> Nuova modella</Btn></Link>
      </div>

      {!loading && (
        <div className="mb-4" data-testid="demo-summary">
          <div className="text-sm mb-3">
            <span className="caps-label text-muted-foreground mr-2">Stato contenuti</span>
            TUTTE <span className="font-semibold">{counts.tutte}</span>
            <span className="text-muted-foreground"> · </span>DEMO <span style={{ color: 'hsl(38 75% 60%)' }} className="font-semibold" data-testid="demo-count">{counts.demo}</span>
            <span className="text-muted-foreground"> · </span>REALI <span style={{ color: 'hsl(150 45% 58%)' }} className="font-semibold">{counts.reali}</span>
            <span className="text-muted-foreground"> · </span>INCOMPLETE <span style={{ color: 'hsl(38 75% 60%)' }} className="font-semibold">{counts.incomplete}</span>
            <span className="text-muted-foreground"> · </span>PRONTE <span style={{ color: 'hsl(190 55% 60%)' }} className="font-semibold">{counts.pronte}</span>
          </div>
          <div className="flex gap-2 overflow-x-auto no-scrollbar" data-testid="models-filters">
            {FILTERS.map((f) => (
              <button key={f.k} onClick={() => setFilter(f.k)} data-testid={`filter-${f.k}`}
                className="shrink-0 caps-label px-3 py-1.5 rounded-full border text-xs transition-colors"
                style={filter === f.k ? { background: 'hsl(var(--primary)/0.16)', borderColor: 'hsl(var(--primary)/0.45)', color: 'hsl(var(--primary))' } : { borderColor: 'hsl(var(--border))', color: 'hsl(var(--muted-foreground))' }}>
                {f.l}
              </button>
            ))}
          </div>
        </div>
      )}

      {selected.size > 0 && (
        <div className="sticky top-2 z-30 flex items-center gap-3 mb-3 p-3 rounded-xl border bg-card card-elev" style={{ borderColor: 'hsl(var(--primary)/0.45)' }} data-testid="bulk-bar">
          <span className="text-sm"><span className="gold-text font-semibold">{selected.size}</span> selezionate</span>
          <Btn onClick={() => setBulkOpen(true)} data-testid="bulk-apply-open"><Copy className="h-4 w-4" /> Applica configurazione</Btn>
          <button onClick={clearSel} className="text-xs text-muted-foreground hover:text-foreground ml-auto">Deseleziona</button>
        </div>
      )}

      {loading ? <div className="h-40 animate-pulse bg-muted/40 rounded-2xl" /> : (
        <div className="space-y-2" data-testid="admin-models-list">
          {filtered.length === 0 && <div className="py-14 text-center text-muted-foreground">Nessuna modella per questo filtro.</div>}
          {filtered.map((m) => {
            const i = items.indexOf(m);
            const ss = STATO_STYLE[m.stato] || STATO_STYLE.bozza;
            const op = OP_STYLE[m.stato_operativo] || OP_STYLE.incompleta;
            return (
              <div key={m.id} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3" data-testid="admin-model-row">
                <input type="checkbox" checked={selected.has(m.id)} onChange={() => toggleSel(m.id)} data-testid="model-select-checkbox"
                  className="h-4 w-4 accent-[hsl(var(--primary))] cursor-pointer" aria-label={`Seleziona ${m.nome_artistico}`} />
                <div className="flex flex-col">
                  <button onClick={() => move(i, -1)} className="text-muted-foreground hover:text-foreground"><ChevronUp className="h-4 w-4" /></button>
                  <button onClick={() => move(i, 1)} className="text-muted-foreground hover:text-foreground"><ChevronDown className="h-4 w-4" /></button>
                </div>
                <img src={mediaUrl(m.foto_card)} alt="" className="h-14 w-14 rounded-lg object-cover" style={{ objectPosition: 'center 20%' }} />
                <div className="flex-1 min-w-0">
                  <div className="font-serif text-lg leading-none">{m.nome_artistico}</div>
                  <div className="text-xs text-muted-foreground truncate">/{m.slug} {m.badge ? `· ${m.badge}` : ''}</div>
                </div>
                {m.content_status && (
                  m.content_status.is_demo
                    ? <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" title={`Demo: ${m.content_status.demo_fields.join(', ')}`} style={{ color: 'hsl(38 75% 60%)', border: '1px solid hsl(38 75% 60% / 0.4)' }} data-testid="content-badge-demo">DEMO</span>
                    : <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: 'hsl(150 45% 58%)', border: '1px solid hsl(150 45% 58% / 0.4)' }} data-testid="content-badge-real">REALE</span>
                )}
                <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: op.c, border: `1px solid ${op.c.replace(')', ' / 0.4)')}` }} data-testid="op-badge">{op.l}</span>
                <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: ss.c, border: `1px solid ${ss.b}` }}>{m.stato}</span>
                <button onClick={() => toggleStatus(m)} className="text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">{m.stato === 'pubblicata' ? 'Bozza' : 'Pubblica'}</button>
                <Link to={`/admin/modelle/${m.id}`} className="h-9 w-9 flex items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"><Pencil className="h-4 w-4" /></Link>
                <button onClick={() => del(m)} className="h-9 w-9 flex items-center justify-center rounded-lg border text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.4)' }}><Trash2 className="h-4 w-4" /></button>
              </div>
            );
          })}
        </div>
      )}

      {bulkOpen && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" data-testid="bulk-modal">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setBulkOpen(false)} />
          <div className="relative z-10 w-full max-w-lg rounded-2xl border border-border/60 bg-card p-6 card-elev-2">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-serif text-2xl">Applica configurazione</h3>
              <button onClick={() => setBulkOpen(false)} className="h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50"><X className="h-5 w-5" /></button>
            </div>
            <div className="mb-4">
              <span className="caps-label text-muted-foreground block mb-1.5">Copia impostazioni da</span>
              <SelectInput value={bulkSource} onChange={(e) => setBulkSource(e.target.value)} data-testid="bulk-source-select">
                <option value="">— Scegli modella sorgente —</option>
                {items.map((x) => <option key={x.id} value={x.id}>{x.nome_artistico}</option>)}
              </SelectInput>
            </div>
            <div className="mb-4 space-y-2">
              <span className="caps-label text-muted-foreground block">Cosa copiare</span>
              {Object.keys(sectionLabels).map((k) => (
                <div key={k} className="flex items-center justify-between p-2.5 rounded-lg border border-border/60">
                  <span className="text-sm">{sectionLabels[k]}</span>
                  <Toggle checked={!!bulkSections[k]} onChange={(v) => setBulkSections((p) => ({ ...p, [k]: v }))} />
                </div>
              ))}
            </div>
            <div className="p-3 rounded-lg mb-4 text-sm" style={{ background: 'hsl(var(--primary)/0.08)', border: '1px solid hsl(var(--primary)/0.3)' }}>
              Stai per applicare le impostazioni di <span className="gold-text font-semibold">{srcName(bulkSource) || '—'}</span> a <span className="font-semibold">{targetCount}</span> modelle.
              <div className="text-xs text-muted-foreground mt-1">Non verranno mai sostituiti foto, video, descrizioni, claim, OnlyFans o social.</div>
            </div>
            <div className="flex justify-end gap-2">
              <Btn variant="ghost" onClick={() => setBulkOpen(false)}>Annulla</Btn>
              <Btn onClick={runBulk} disabled={bulkBusy || !bulkSource || targetCount === 0} data-testid="bulk-apply-confirm">{bulkBusy ? 'Applico…' : `Applica a ${targetCount} modelle`}</Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
