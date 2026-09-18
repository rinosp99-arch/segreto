/* ADMIN → ANALYTICS — control center of everything the site really tracks (global + per creator).
   Robust by design: every widget is wrapped in its own error boundary (a broken chart never blanks the page),
   explicit LOADING / EMPTY / ERROR (+ Riprova) / PARTIAL states, no chart ever receives null data. */
import { Component, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AlertTriangle, ArrowLeft, Download, RefreshCw, Search, ChevronUp, ChevronDown } from 'lucide-react';
import { SectionCard, Btn, SelectInput, TextInput } from '@/pages/admin/ui';
import { an2Summary, an2Models, an2Model, an2Timeseries, an2Compare, an2Events, an2Filters, an2ExportUrl } from '@/lib/adminApi';
import { api } from '@/lib/api';

// ------------------------------------------------------------------------------------------------ helpers
const N = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('it-IT'));
const P = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : `${Number(v).toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`);
const S = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)}s`);
const D = (iso) => { if (!iso) return '—'; const d = new Date(iso); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); };
const arr = (x) => (Array.isArray(x) ? x : []);
const GOLD = 'hsl(42 45% 62%)';
const WINE = 'hsl(350 55% 45%)';
const RANGES = [['oggi', 'Oggi'], ['ieri', 'Ieri'], ['7g', '7 giorni'], ['30g', '30 giorni'], ['mese', 'Questo mese'], ['mese_scorso', 'Mese scorso'], ['custom', 'Personalizzato']];

class WidgetBoundary extends Component {
  constructor(p) { super(p); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  componentDidCatch(error) { if (process.env.NODE_ENV !== 'production') console.debug('[analytics widget]', this.props.name, error?.message); }
  render() {
    if (this.state.error) {
      return (
        <div className="rounded-xl border border-border/60 bg-card/40 p-4 text-sm" data-testid={`widget-error-${this.props.name}`}>
          <div className="flex items-center gap-2 text-muted-foreground"><AlertTriangle className="h-4 w-4" /> Widget "{this.props.title || this.props.name}" non disponibile.</div>
          <button type="button" className="mt-2 text-xs underline text-primary" onClick={() => this.setState({ error: null })}>Riprova widget</button>
        </div>
      );
    }
    return this.props.children;
  }
}

function useAsync(fn, deps) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const run = useCallback(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve().then(fn).then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e?.response?.data?.detail || e?.message || 'Errore' }));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => run(), [run]);
  return { ...state, retry: run };
}

function Skeleton({ h = 80, n = 1 }) {
  return <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(n, 4)}, minmax(0, 1fr))` }}>{Array.from({ length: n }).map((_, i) => <div key={i} className="rounded-xl bg-muted/30 animate-pulse" style={{ height: h }} />)}</div>;
}
function ErrorPanel({ error, onRetry, title = 'Impossibile caricare Analytics' }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card/50 p-6" data-testid="analytics-error">
      <div className="flex items-center gap-2 font-serif text-lg"><AlertTriangle className="h-5 w-5 text-primary" /> {title}</div>
      <div className="text-sm text-muted-foreground mt-1 break-words">{String(error)}</div>
      <Btn className="mt-4" onClick={onRetry} data-testid="analytics-retry"><RefreshCw className="h-4 w-4 mr-2" /> Riprova</Btn>
    </div>
  );
}
function Empty({ text = 'Non ci sono ancora dati per questo periodo.' }) {
  return <div className="rounded-xl border border-dashed border-border/60 p-6 text-sm text-muted-foreground text-center" data-testid="analytics-empty">{text}</div>;
}
function Kpi({ label, value, sub, testid }) {
  return (
    <div className="rounded-xl border border-border/60 bg-card/50 p-3 min-w-0" data-testid={testid}>
      <div className="text-[10px] caps-label text-muted-foreground truncate">{label}</div>
      <div className="text-xl sm:text-2xl font-serif mt-1 truncate">{value}</div>
      {sub ? <div className="text-[11px] text-muted-foreground truncate">{sub}</div> : null}
    </div>
  );
}
function MiniTable({ cols, rows, onRow, testid, emptyText }) {
  if (!rows.length) return <Empty text={emptyText || 'Nessun dato.'} />;
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm min-w-[420px]" data-testid={testid}>
        <thead><tr className="text-left text-[10px] caps-label text-muted-foreground">{cols.map((c) => <th key={c.key} className={`py-2 px-2 ${c.right ? 'text-right' : ''}`}>{c.label}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.key ?? r.slug ?? r.id ?? i} className={`border-t border-border/40 ${onRow ? 'cursor-pointer hover:bg-muted/20' : ''}`} onClick={onRow ? () => onRow(r) : undefined}>
              {cols.map((c) => <td key={c.key} className={`py-2 px-2 ${c.right ? 'text-right tabular-nums' : ''}`}>{c.render ? c.render(r) : (r[c.key] ?? '—')}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const TT = { contentStyle: { background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 10, fontSize: 12 } };

// ------------------------------------------------------------------------------------------------ filters
function Filters({ f, setF, options }) {
  const set = (k, v) => setF({ ...f, [k]: v });
  return (
    <div className="flex flex-wrap items-end gap-2" data-testid="analytics-filters">
      <div className="flex flex-wrap gap-1" role="tablist" aria-label="Periodo">
        {RANGES.map(([k, l]) => (
          <button key={k} type="button" onClick={() => set('range_key', k)} data-testid={`range-${k}`}
            className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${f.range_key === k ? 'bg-primary text-primary-foreground border-primary' : 'border-border/60 text-muted-foreground hover:text-foreground'}`}>{l}</button>
        ))}
      </div>
      {f.range_key === 'custom' && (
        <div className="flex items-center gap-1">
          <TextInput type="date" value={f.from || ''} onChange={(e) => set('from', e.target.value)} data-testid="range-from" className="w-[150px]" />
          <span className="text-muted-foreground text-xs">→</span>
          <TextInput type="date" value={f.to || ''} onChange={(e) => set('to', e.target.value)} data-testid="range-to" className="w-[150px]" />
        </div>
      )}
      <SelectInput value={f.model || 'all'} onChange={(e) => set('model', e.target.value)} className="w-[180px]" data-testid="filter-model">
        <option value="all">Tutte le modelle</option>
        {arr(options?.modelle).map((m) => <option key={m.slug} value={m.slug}>{m.nome}</option>)}
      </SelectInput>
      <SelectInput value={f.mode || 'all'} onChange={(e) => set('mode', e.target.value)} className="w-[130px]" data-testid="filter-mode">
        <option value="all">Pubblico + Segreto</option><option value="public">Pubblico</option><option value="secret">Segreto</option>
      </SelectInput>
      <SelectInput value={f.source || 'all'} onChange={(e) => set('source', e.target.value)} className="w-[140px]" data-testid="filter-source">
        <option value="all">Ogni origine</option>{arr(options?.sources).map((s) => <option key={s} value={s}>{s}</option>)}
      </SelectInput>
      <SelectInput value={f.campagna || 'all'} onChange={(e) => set('campagna', e.target.value)} className="w-[150px]" data-testid="filter-campagna">
        <option value="all">Ogni campagna</option>{arr(options?.campagne).map((s) => <option key={s} value={s}>{s}</option>)}
      </SelectInput>
      <SelectInput value={f.fonte || 'all'} onChange={(e) => set('fonte', e.target.value)} className="w-[130px]" data-testid="filter-fonte">
        <option value="all">Ogni fonte</option>{arr(options?.fonti).map((s) => <option key={s} value={s}>{s}</option>)}
      </SelectInput>
      <SelectInput value={f.device || 'all'} onChange={(e) => set('device', e.target.value)} className="w-[130px]" data-testid="filter-device">
        <option value="all">Ogni dispositivo</option>{arr(options?.devices).map((s) => <option key={s} value={s}>{s}</option>)}
      </SelectInput>
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ sections
function Scorecard({ sc }) {
  const items = [
    ['Visitatori / sessioni', N(sc.sessioni), 'sessioni anonime con ≥1 evento', 'kpi-sessioni'], ['Eventi', N(sc.eventi)], ['Profili aperti', N(sc.profili_aperti), `${N(sc.sessioni_con_profilo)} sessioni con ≥1 profilo`, 'kpi-profili'],
    ['Lato Segreto attivato', N(sc.secret_attivazioni), `${P(sc.secret_rate)} delle sessioni con profilo`, 'kpi-secret'], ['Click CTA', N(sc.cta_click), `CTR CTA ${P(sc.ctr_cta)} (su attivazioni)`],
    ['Click OnlyFans personali', N(sc.of_click_personali), `CTR OF ${P(sc.ctr_of)} (su profili aperti)`, 'kpi-of'], ['Click OnlyFans globale', N(sc.of_click_globale), 'marquee Home + profili', 'kpi-of-global'],
    ['Click social', N(sc.social_click)], ['Swipe tra profili', N(sc.swipe)], ['Sorprendimi', N(sc.sorprendimi)], ['FilmStrip / In movimento', N(sc.filmstrip_interazioni), 'impression + video + click'],
    ['Profili per sessione', sc.profili_per_sessione ?? '—', 'media (sessioni con profilo)'], ['Tempo medio in Secret', S(sc.tempo_medio_secret_s)], ['Tempo medio sul sito', S(sc.tempo_medio_sito_s), 'non tracciato'], ['Tempo medio per profilo', S(sc.tempo_medio_profilo_s), 'non tracciato'],
  ];
  return <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2" data-testid="analytics-scorecard">{items.map(([l, v, s, t]) => <Kpi key={l} label={l} value={v} sub={s} testid={t} />)}</div>;
}

function Funnel({ steps }) {
  const rows = arr(steps);
  const max = Math.max(1, ...rows.map((s) => s.n || 0));
  if (!rows.length || !rows[0].n) return <Empty />;
  return (
    <div className="space-y-2" data-testid="analytics-funnel">
      {rows.map((s, i) => (
        <div key={s.step} className="grid grid-cols-[1fr_auto] sm:grid-cols-[220px_1fr_220px] items-center gap-2 text-sm">
          <div className="truncate">{s.step}</div>
          <div className="hidden sm:block h-6 rounded-md bg-muted/30 overflow-hidden"><div className="h-full rounded-md" style={{ width: `${Math.max(2, (100 * (s.n || 0)) / max)}%`, background: i < 2 ? GOLD : WINE, opacity: 0.85 }} /></div>
          <div className="text-right tabular-nums text-muted-foreground"><span className="text-foreground font-medium">{N(s.n)}</span>{i > 0 && <> · dal passo prec. <span className="text-foreground">{P(s.conv_prev)}</span> · dalla visita <span className="text-foreground">{P(s.conv_first)}</span></>}</div>
        </div>
      ))}
    </div>
  );
}

function Timeseries({ filters }) {
  const [gran, setGran] = useState('day');
  const [metric, setMetric] = useState('visite');
  const { loading, data, error, retry } = useAsync(() => an2Timeseries(filters, gran), [JSON.stringify(filters), gran]);
  const items = arr(data?.items);
  const metrics = [['visite', 'Visite (sessioni)'], ['profili', 'Profili aperti'], ['secret', 'Secret activation'], ['of_click', 'Click OF'], ['swipe', 'Swipe'], ['social', 'Social'], ['marquee', 'Marquee OF']];
  return (
    <SectionCard title="Andamento" desc="Sta salendo o scendendo? Ora / giorno / settimana / mese (fuso Europa/Roma).">
      <div className="flex flex-wrap gap-1 mb-3">
        {metrics.map(([k, l]) => <button key={k} type="button" onClick={() => setMetric(k)} className={`px-2.5 py-1 rounded-full text-[11px] border ${metric === k ? 'bg-primary text-primary-foreground border-primary' : 'border-border/60 text-muted-foreground'}`} data-testid={`ts-metric-${k}`}>{l}</button>)}
        <span className="mx-2 text-muted-foreground">·</span>
        {[['hour', 'Ora'], ['day', 'Giorno'], ['week', 'Settimana'], ['month', 'Mese']].map(([k, l]) => <button key={k} type="button" onClick={() => setGran(k)} className={`px-2.5 py-1 rounded-full text-[11px] border ${gran === k ? 'bg-secondary text-foreground border-border' : 'border-border/60 text-muted-foreground'}`} data-testid={`ts-gran-${k}`}>{l}</button>)}
      </div>
      {loading ? <Skeleton h={220} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Andamento non disponibile" /> : !items.length ? <Empty /> : (
        <div style={{ height: 240 }} data-testid="analytics-timeseries">
          <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 200 }}>
            <AreaChart data={items} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="hsl(var(--border) / 0.4)" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" />
              <YAxis tick={{ fontSize: 10 }} stroke="hsl(var(--muted-foreground))" allowDecimals={false} width={32} />
              <Tooltip {...TT} />
              <Area type="monotone" dataKey={metric} stroke={GOLD} fill={GOLD} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </SectionCard>
  );
}

function ModelsTable({ filters, onOpen, onCompare }) {
  const { loading, data, error, retry } = useAsync(() => an2Models(filters), [JSON.stringify(filters)]);
  const [sort, setSort] = useState({ key: 'visite', dir: 'desc' });
  const [q, setQ] = useState('');
  const [sel, setSel] = useState([]);
  const items = useMemo(() => {
    const list = arr(data?.items).filter((r) => !q || String(r.modella || '').toLowerCase().includes(q.toLowerCase()) || String(r.slug || '').includes(q.toLowerCase()));
    const v = (r) => { const x = r[sort.key]; return x === null || x === undefined ? -Infinity : (typeof x === 'string' ? x : Number(x)); };
    return [...list].sort((a, b) => { const A = v(a), B = v(b); if (A === B) return 0; const c = A > B ? 1 : -1; return sort.dir === 'desc' ? -c : c; });
  }, [data, sort, q]);
  const cols = [
    ['modella', 'Modella'], ['visite', 'Visite', 1], ['visitatori_unici', 'Unici', 1], ['quota_traffico', '% traffico', 1, P], ['secret', 'Secret', 1], ['secret_rate', 'Secret %', 1, P], ['cta_click', 'CTA', 1], ['of_click', 'Click OF', 1], ['ctr_of', 'CTR OF', 1, P],
    ['social_click', 'Social', 1], ['swipe_in', 'Swipe in', 1], ['swipe_out', 'Swipe out', 1], ['via_home', 'Da Home', 1, () => '—'], ['via_filmstrip', 'Da FilmStrip', 1], ['via_surprise', 'Da Sorprendimi', 1], ['via_swipe', 'Da swipe', 1], ['marquee_click', 'Marquee OF', 1],
    ['tempo_medio_profilo_s', 'T. profilo', 1, S], ['tempo_medio_secret_s', 'T. Secret', 1, S], ['ultimo_evento', 'Ultimo evento', 1, D],
  ];
  const th = (k, l, right) => (
    <th key={k} className={`py-2 px-2 whitespace-nowrap cursor-pointer select-none ${right ? 'text-right' : 'text-left'}`} onClick={() => setSort((s) => ({ key: k, dir: s.key === k && s.dir === 'desc' ? 'asc' : 'desc' }))} data-testid={`sort-${k}`}>
      {l} {sort.key === k ? (sort.dir === 'desc' ? <ChevronDown className="inline h-3 w-3" /> : <ChevronUp className="inline h-3 w-3" />) : null}
    </th>
  );
  const toggle = (slug) => setSel((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : s.length >= 5 ? s : [...s, slug]));
  return (
    <SectionCard title="Tutte le modelle" desc="Una riga per modella pubblicata. Ordinabile per ogni metrica, ricercabile, esportabile. Clicca il nome per il dettaglio; spunta 2–5 modelle per confrontarle.">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="relative"><Search className="h-4 w-4 absolute left-2 top-2.5 text-muted-foreground" /><TextInput placeholder="Cerca modella" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8 w-[220px]" data-testid="models-search" /></div>
        <Btn variant="ghost" onClick={() => onCompare(sel)} disabled={sel.length < 2} data-testid="models-compare-btn">Confronta ({sel.length})</Btn>
        <a href={an2ExportUrl('models', filters)} className="text-xs underline text-muted-foreground inline-flex items-center gap-1" target="_blank" rel="noreferrer" data-testid="export-models"><Download className="h-3 w-3" /> CSV</a>
      </div>
      {loading ? <Skeleton h={200} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Tabella modelle non disponibile" /> : !items.length ? <Empty text={q ? 'Nessuna modella corrisponde alla ricerca.' : 'Nessuna modella pubblicata.'} /> : (
        <div className="overflow-x-auto -mx-2">
          <table className="text-sm min-w-[1500px]" data-testid="models-table">
            <thead><tr className="text-[10px] caps-label text-muted-foreground"><th className="px-2" />{cols.map(([k, l, r]) => th(k, l, r))}</tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.slug} className="border-t border-border/40 hover:bg-muted/20" data-testid={`model-row-${r.slug}`}>
                  <td className="px-2"><input type="checkbox" checked={sel.includes(r.slug)} onChange={() => toggle(r.slug)} aria-label={`Confronta ${r.modella}`} data-testid={`compare-${r.slug}`} /></td>
                  {cols.map(([k, , right, fmt]) => (
                    <td key={k} className={`py-2 px-2 whitespace-nowrap ${right ? 'text-right tabular-nums' : ''}`}>
                      {k === 'modella' ? <button type="button" className="underline decoration-primary/40 hover:text-primary" onClick={() => onOpen(r.slug)} data-testid={`open-model-${r.slug}`}>{r.modella}{r.non_pubblicata ? <span className="ml-1 text-[10px] text-muted-foreground">(non pubblicata)</span> : null}</button>
                        : fmt ? fmt(r[k]) : N(r[k])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SectionCard>
  );
}

function Rankings({ models }) {
  const list = arr(models);
  const top = (key, fmt = N, label) => ({ label, rows: [...list].filter((r) => (r[key] || 0) > 0).sort((a, b) => (b[key] || 0) - (a[key] || 0)).slice(0, 5).map((r) => ({ key: r.slug, modella: r.modella, val: fmt(r[key]) })) });
  const blocks = [top('visite', N, 'Più visualizzate'), top('secret', N, 'Più Secret activation'), top('of_click', N, 'Più click OF'), top('ctr_of', P, 'CTR OF più alto'), top('social_click', N, 'Più click social'), top('swipe_in', N, 'Più traffico da swipe'), top('via_filmstrip', N, 'Più traffico FilmStrip'), top('marquee_click', N, 'Più click marquee globale')];
  return (
    <SectionCard title="Classifiche (dati oggettivi)" desc="Ordinate per metrica reale nel periodo: nessun voto, nessun punteggio inventato.">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3" data-testid="analytics-rankings">
        {blocks.map((b) => (
          <div key={b.label} className="rounded-xl border border-border/60 p-3">
            <div className="text-[10px] caps-label text-muted-foreground mb-2">{b.label}</div>
            {b.rows.length ? b.rows.map((r, i) => <div key={r.key} className="flex justify-between text-sm py-0.5"><span className="truncate">{i + 1}. {r.modella}</span><span className="tabular-nums text-muted-foreground">{r.val}</span></div>) : <div className="text-xs text-muted-foreground">Nessun dato.</div>}
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

function OnlyFans({ of, filters }) {
  const p = of?.personali || {}; const g = of?.globale || {};
  return (
    <SectionCard title="OnlyFans" desc="A) link personali delle creator · B) pagina globale LATO SEGRETO (onlyfans.com/latosegreto/c28) — separati.">
      <div className="grid lg:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center justify-between mb-2"><div className="font-medium">A · OnlyFans personali <span className="text-muted-foreground text-sm">— {N(p.totale)} click, {N(p.sessioni)} sessioni</span></div><a href={an2ExportUrl('of_clicks', filters)} target="_blank" rel="noreferrer" className="text-xs underline text-muted-foreground" data-testid="export-of">CSV click OF</a></div>
          <MiniTable testid="of-personal-by-model" cols={[{ key: 'key', label: 'Modella' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(p.per_modella)} />
          <div className="text-[10px] caps-label text-muted-foreground mt-3 mb-1">Provenienza del click (cta_source)</div>
          <MiniTable testid="of-personal-by-source" cols={[{ key: 'key', label: 'Provenienza' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(p.per_provenienza)} />
          <div className="text-xs text-muted-foreground mt-2">Click OF dopo uno swipe: <b className="text-foreground">{N(p.dopo_swipe)}</b> (attribuzione disponibile su {N(p.con_attribuzione_swipe)} click recenti). Pubblico/Segreto: la CTA personale vive nel Lato Segreto; i click con meta.mode esplicito sono nel dettaglio modella.</div>
        </div>
        <div>
          <div className="font-medium mb-2">B · OnlyFans globale <span className="text-muted-foreground text-sm">— {N(g.totale)} click · Home {N(g.home)} · Profili {N(g.profili)}</span></div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Da quale modella</div><MiniTable testid="of-global-by-model" cols={[{ key: 'key', label: 'Modella' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(g.per_modella)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Public / Secret</div><MiniTable cols={[{ key: 'key', label: 'Modalità' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(g.per_modalita)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable cols={[{ key: 'key', label: 'Campagna' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(g.per_campagna)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Fonte</div><MiniTable cols={[{ key: 'key', label: 'Fonte' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(g.per_fonte)} /></div>
          </div>
          {arr(g.per_ora).length > 0 && (
            <div className="mt-3" style={{ height: 120 }} data-testid="of-global-by-hour">
              <div className="text-[10px] caps-label text-muted-foreground mb-1">Per ora (UTC)</div>
              <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 200 }}><BarChart data={arr(g.per_ora)}><XAxis dataKey="ora" tick={{ fontSize: 10 }} /><Tooltip {...TT} /><Bar dataKey="n" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function SwipeSecretHome({ sw, sec, home }) {
  const d = sw?.per_direzione || {};
  return (
    <div className="grid lg:grid-cols-3 gap-4">
      <SectionCard title="Swipe tra profili" desc="profile_swipe_next / previous (uscite) · profile_swipe_public / secret (arrivi).">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Kpi label="Swipe totali" value={N(sw?.totali)} sub={`${N(sw?.sessioni)} sessioni`} /><Kpi label="Media per sessione" value={sw?.media_swipe_per_sessione ?? '—'} />
          <Kpi label="→ Prossima / ← Precedente" value={`${N(d.next)} / ${N(d.previous)}`} /><Kpi label="Arrivi in Pubblico / Segreto" value={`${N(d.arrivi_public)} / ${N(d.arrivi_secret)}`} />
        </div>
        <div className="text-[10px] caps-label text-muted-foreground mb-1">Modelle raggiunte tramite swipe</div>
        <MiniTable testid="swipe-reached" cols={[{ key: 'key', label: 'Modella' }, { key: 'n', label: 'Arrivi', right: true, render: (r) => N(r.n) }]} rows={arr(sw?.modelle_raggiunte)} />
        <div className="text-xs text-muted-foreground mt-2">Click OF dopo swipe: <b className="text-foreground">{N(sw?.of_click_dopo_swipe)}</b></div>
      </SectionCard>
      <SectionCard title="Lato Segreto" desc="Attivazioni, quota visitatori, tempo medio (secret_time), CTA/OF avvenuti in Secret.">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Kpi label="Attivazioni" value={N(sec?.attivazioni)} sub={`${N(sec?.sessioni)} sessioni`} /><Kpi label="% visitatori che attivano" value={P(sec?.rate_visitatori)} sub={`${P(sec?.rate_profili)} di chi apre un profilo`} />
          <Kpi label="Tempo medio in Secret" value={S(sec?.tempo_medio_s)} sub={`${N(sec?.ritorni_public)} ritorni al Pubblico`} /><Kpi label="CTA / OF in Secret" value={`${N(sec?.cta_click)} / ${N(sec?.of_click)}`} />
        </div>
        <div className="text-[10px] caps-label text-muted-foreground mb-1">Per modella</div>
        <MiniTable testid="secret-by-model" cols={[{ key: 'key', label: 'Modella' }, { key: 'n', label: 'Attivazioni', right: true, render: (r) => N(r.n) }]} rows={arr(sec?.per_modella)} />
      </SectionCard>
      <SectionCard title="Home" desc="Quali elementi della Home portano ai profili e a OnlyFans (solo eventi già tracciati).">
        <div className="grid grid-cols-2 gap-2">
          <Kpi label="Switch Pubblico/Segreto" value={N(home?.toggle_totali)} sub={`${N(home?.toggle_secret_on)} verso Segreto`} /><Kpi label="Sorprendimi" value={N(home?.sorprendimi_click)} sub={`${N(home?.sorprendimi_profili_aperti)} profili aperti`} />
          <Kpi label="FilmStrip impression" value={N(home?.filmstrip_impression)} /><Kpi label="FilmStrip video / click profilo" value={`${N(home?.filmstrip_video_view)} / ${N(home?.filmstrip_click_profilo)}`} />
          <Kpi label="Marquee OF (Home)" value={N(home?.marquee_home_click)} /><Kpi label="Profili via swipe" value={N(home?.profili_via_swipe)} />
          <Kpi label="Landing da campagna" value={N(home?.landing_da_campagna)} /><Kpi label="Card griglia cliccate" value="—" sub="non tracciato (vedi metriche mancanti)" />
        </div>
      </SectionCard>
    </div>
  );
}

function Sources({ src }) {
  return (
    <SectionCard title="Origine del traffico e campagne" desc="source (enrichment referrer: direct / instagram / tiktok / google / …), dispositivo, fonte / campagna / ref dei link tracciati.">
      <div className="grid lg:grid-cols-2 gap-4">
        <MiniTable testid="sources-detail" cols={[{ key: 'source', label: 'Origine' }, { key: 'sessioni', label: 'Sessioni', right: true, render: (r) => N(r.sessioni) }, { key: 'profili', label: 'Profili', right: true, render: (r) => N(r.profili) }, { key: 'secret', label: 'Secret', right: true, render: (r) => N(r.secret) }, { key: 'of_click', label: 'OF', right: true, render: (r) => N(r.of_click) }, { key: 'ctr_of', label: 'CTR', right: true, render: (r) => P(r.ctr_of) }]} rows={arr(src?.dettaglio).map((r) => ({ ...r, key: r.source }))} />
        <div className="grid sm:grid-cols-3 gap-3">
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable cols={[{ key: 'key', label: 'Campagna' }, { key: 'n', label: 'Eventi', right: true, render: (r) => N(r.n) }]} rows={arr(src?.per_campagna)} /></div>
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Fonte</div><MiniTable cols={[{ key: 'key', label: 'Fonte' }, { key: 'n', label: 'Eventi', right: true, render: (r) => N(r.n) }]} rows={arr(src?.per_fonte)} /></div>
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Dispositivo</div><MiniTable cols={[{ key: 'key', label: 'Device' }, { key: 'n', label: 'Eventi', right: true, render: (r) => N(r.n) }]} rows={arr(src?.per_device)} /></div>
        </div>
      </div>
    </SectionCard>
  );
}

function TopEvents({ rows }) {
  return (
    <SectionCard title="Top eventi (tecnico)" desc="Conteggio nel periodo, ultimo evento, trend vs periodo precedente di pari durata. Gli eventi sconosciuti sono mostrati comunque.">
      <MiniTable testid="top-events" cols={[
        { key: 'evento', label: 'Evento', render: (r) => <span className={r.noto ? '' : 'text-muted-foreground'}>{r.evento}{r.noto ? '' : ' (sconosciuto)'}</span> },
        { key: 'n', label: 'Conteggio', right: true, render: (r) => N(r.n) }, { key: 'ultimo', label: 'Ultimo', right: true, render: (r) => D(r.ultimo) },
        { key: 'trend_pct', label: 'Trend', right: true, render: (r) => (r.trend_pct === null || r.trend_pct === undefined ? (r.prev ? '—' : 'nuovo') : <span style={{ color: r.trend_pct >= 0 ? GOLD : WINE }}>{r.trend_pct >= 0 ? '+' : ''}{P(r.trend_pct)}</span>) },
      ]} rows={arr(rows).map((r) => ({ ...r, key: r.evento }))} />
    </SectionCard>
  );
}

function RawEvents({ filters }) {
  const [skip, setSkip] = useState(0);
  const [tipo, setTipo] = useState('');
  const { loading, data, error, retry } = useAsync(() => an2Events(filters, 50, skip, tipo), [JSON.stringify(filters), skip, tipo]);
  const items = arr(data?.items);
  return (
    <SectionCard title="Ultimi eventi (log tecnico)" desc="Per verificare che il tracking funzioni. Session id troncato, nessun IP / token / dato personale.">
      <div className="flex items-center gap-2 mb-2"><TextInput placeholder="filtra per evento (es. of_click)" value={tipo} onChange={(e) => { setSkip(0); setTipo(e.target.value.trim()); }} className="w-[260px]" data-testid="events-filter" /><span className="text-xs text-muted-foreground">{N(data?.total)} eventi</span></div>
      {loading ? <Skeleton h={160} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Log eventi non disponibile" /> : !items.length ? <Empty /> : (
        <MiniTable testid="raw-events" cols={[
          { key: 'timestamp', label: 'Quando', render: (r) => D(r.timestamp) }, { key: 'evento', label: 'Evento' }, { key: 'modella', label: 'Modella', render: (r) => r.modella || '—' },
          { key: 'mode', label: 'Mode', render: (r) => r.mode || '—' }, { key: 'source', label: 'Source', render: (r) => r.source || '—' }, { key: 'cta_source', label: 'CTA source', render: (r) => r.cta_source || '—' },
          { key: 'campagna', label: 'Campagna', render: (r) => r.campagna || '—' }, { key: 'device', label: 'Device', render: (r) => r.device || '—' }, { key: 'session', label: 'Sessione', render: (r) => r.session || '—' },
          { key: 'meta', label: 'Meta', render: (r) => (r.meta && Object.keys(r.meta).length ? JSON.stringify(r.meta) : '—') },
        ]} rows={items.map((r) => ({ ...r, key: r.id }))} />
      )}
      <div className="flex gap-2 mt-2"><Btn variant="ghost" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - 50))}>← Precedenti</Btn><Btn variant="ghost" disabled={!data || skip + 50 >= (data.total || 0)} onClick={() => setSkip(skip + 50)}>Successivi →</Btn></div>
    </SectionCard>
  );
}

function NotAvailable({ items }) {
  if (!arr(items).length) return null;
  return (
    <SectionCard title="Metriche non ancora disponibili" desc="Non inventate: richiedono un evento che il sito oggi non emette. Decidiamo insieme se aggiungerlo.">
      <MiniTable testid="not-available" cols={[{ key: 'metrica', label: 'Metrica' }, { key: 'evento', label: 'Evento necessario' }, { key: 'dove', label: 'Dove aggiungerlo' }]} rows={arr(items).map((r, i) => ({ ...r, key: i }))} />
    </SectionCard>
  );
}

function Compare({ filters, slugs, onClose }) {
  const { loading, data, error, retry } = useAsync(() => an2Compare(filters, slugs), [JSON.stringify(filters), slugs.join(',')]);
  const items = arr(data?.items);
  const rows = [['visite', 'Visite', N], ['visitatori_unici', 'Unici', N], ['secret', 'Secret', N], ['secret_rate', 'Secret %', P], ['cta_click', 'Click CTA', N], ['of_click', 'Click OF', N], ['ctr_of', 'CTR OF', P], ['social_click', 'Social', N], ['swipe_in', 'Swipe in', N], ['swipe_out', 'Swipe out', N], ['tempo_medio_secret_s', 'Tempo medio Secret', S]];
  return (
    <SectionCard title={`Confronto (${slugs.length} modelle)`} desc="Metriche oggettive affiancate. Nessun punteggio.">
      <Btn variant="ghost" onClick={onClose} className="mb-2" data-testid="compare-close">Chiudi confronto</Btn>
      {loading ? <Skeleton h={200} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Confronto non disponibile" /> : (
        <div className="overflow-x-auto"><table className="text-sm min-w-[520px]" data-testid="compare-table">
          <thead><tr className="text-[10px] caps-label text-muted-foreground"><th className="text-left py-2 px-2">Metrica</th>{items.map((m) => <th key={m.slug} className="text-right py-2 px-2">{m.modella}</th>)}</tr></thead>
          <tbody>{rows.map(([k, l, fmt]) => <tr key={k} className="border-t border-border/40"><td className="py-2 px-2">{l}</td>{items.map((m) => <td key={m.slug} className="py-2 px-2 text-right tabular-nums">{fmt(m[k])}</td>)}</tr>)}</tbody>
        </table></div>
      )}
    </SectionCard>
  );
}

// ------------------------------------------------------------------------------------------------ model detail
function ModelDetail({ slug, filters, onBack }) {
  const { loading, data, error, retry } = useAsync(() => an2Model(slug, filters), [slug, JSON.stringify(filters)]);
  if (loading) return <Skeleton h={140} n={4} />;
  if (error) return <ErrorPanel error={error} onRetry={retry} title={`Dettaglio ${slug} non disponibile`} />;
  const d = data || {}; const t = d.traffico || {}; const s = d.secret || {}; const o = d.onlyfans || {}; const sw = d.swipe || {};
  const social = Object.entries(d.social || {});
  const hasData = (t.visite || 0) + (s.attivazioni || 0) + (o.of_click || 0) + (sw.arrivi || 0) + social.length > 0;
  return (
    <div className="space-y-4" data-testid="model-detail">
      <div className="flex flex-wrap items-center gap-3">
        <Btn variant="ghost" onClick={onBack} data-testid="model-detail-back"><ArrowLeft className="h-4 w-4 mr-1" /> Tutte le modelle</Btn>
        <h2 className="font-serif text-2xl">Analytics → {d.modella || slug}</h2>
        {d.stato && d.stato !== 'pubblicata' && <span className="text-xs text-muted-foreground">({d.stato})</span>}
        <a href={an2ExportUrl('model', filters, slug)} target="_blank" rel="noreferrer" className="text-xs underline text-muted-foreground inline-flex items-center gap-1" data-testid="export-model"><Download className="h-3 w-3" /> CSV</a>
      </div>
      {!hasData ? <Empty text="Nessun evento per questa modella nel periodo selezionato." /> : (
        <>
          <WidgetBoundary name="detail-traffic" title="Traffico">
            <SectionCard title="Traffico" desc={`Giorno con più visite: ${t.giorno_top || '—'} · ora di punta (UTC): ${t.ora_top ? `${t.ora_top}:00` : '—'} · nuove visite / ritorni: non tracciato`}>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3"><Kpi label="Visite profilo" value={N(t.visite)} /><Kpi label="Visitatori unici" value={N(t.visitatori_unici)} /><Kpi label="Visite per visitatore" value={t.visitatori_unici ? (t.visite / t.visitatori_unici).toFixed(2) : '—'} /><Kpi label="Ultimo evento" value={D(d.ultimo_evento)} sub="qualsiasi evento di questa modella" /></div>
              {arr(t.per_giorno).length > 0 && (
                <div style={{ height: 160 }} data-testid="detail-by-day"><ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 200 }}><BarChart data={arr(t.per_giorno)}><XAxis dataKey="giorno" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} width={28} allowDecimals={false} /><Tooltip {...TT} /><Bar dataKey="n" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
              )}
              <div className="grid sm:grid-cols-3 gap-3 mt-3">
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Origine</div><MiniTable cols={[{ key: 'key', label: 'Source' }, { key: 'n', label: 'Visite', right: true, render: (r) => N(r.n) }]} rows={arr(t.per_source)} /></div>
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Dispositivo</div><MiniTable cols={[{ key: 'key', label: 'Device' }, { key: 'n', label: 'Visite', right: true, render: (r) => N(r.n) }]} rows={arr(t.per_device)} /></div>
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable cols={[{ key: 'key', label: 'Campagna' }, { key: 'n', label: 'Visite', right: true, render: (r) => N(r.n) }]} rows={arr(t.per_campagna)} /></div>
              </div>
            </SectionCard>
          </WidgetBoundary>
          <div className="grid lg:grid-cols-2 gap-4">
            <WidgetBoundary name="detail-secret" title="Lato Segreto">
              <SectionCard title="Lato Segreto">
                <div className="grid grid-cols-2 gap-2"><Kpi label="Attivazioni" value={N(s.attivazioni)} sub={`${N(s.sessioni)} sessioni`} /><Kpi label="Public → Secret" value={P(s.public_to_secret_pct)} sub="sessioni con attivazione / con visita" /><Kpi label="Tempo medio in Secret" value={S(s.tempo_medio_s)} /><Kpi label="Ritorni al Pubblico" value={N(s.ritorni_public)} sub="evento secret_return" /></div>
              </SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-of" title="OnlyFans">
              <SectionCard title="OnlyFans personale">
                <div className="grid grid-cols-2 gap-2 mb-3"><Kpi label="Click CTA" value={N(o.cta_click)} /><Kpi label="Click OF" value={N(o.of_click)} sub={`CTR ${P(o.ctr_of)}`} /><Kpi label="Da Public / da Secret" value={`${N(o.da_public)} / ${N(o.da_secret)}`} sub="la CTA personale vive nel Secret" /><Kpi label="Dopo swipe" value={N(o.dopo_swipe)} sub="dopo FilmStrip / Sorprendimi / marquee: non attribuito" /></div>
                <div className="text-[10px] caps-label text-muted-foreground mb-1">Provenienza (cta_source)</div>
                <MiniTable cols={[{ key: 'key', label: 'Provenienza' }, { key: 'n', label: 'Click', right: true, render: (r) => N(r.n) }]} rows={arr(o.per_provenienza)} />
                <div className="text-xs text-muted-foreground mt-2">Click marquee OF globale generati da questo profilo: <b className="text-foreground">{N(o.marquee_globale_da_questo_profilo)}</b></div>
              </SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-social" title="Social">
              <SectionCard title="Social">{social.length ? <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{social.map(([k, v]) => <Kpi key={k} label={k} value={N(v)} />)}</div> : <Empty text="Nessun click social nel periodo." />}</SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-swipe" title="Swipe">
              <SectionCard title="Swipe">
                <div className="grid grid-cols-2 gap-2 mb-3"><Kpi label="Arrivi via swipe" value={N(sw.arrivi)} sub={`${N(sw.arrivi_public)} Pubblico · ${N(sw.arrivi_secret)} Segreto`} /><Kpi label="Uscite via swipe" value={N(sw.uscite)} /><Kpi label="Click OF dopo swipe" value={N(sw.of_click_dopo_swipe)} /><Kpi label="Permanenza prima dello swipe" value="—" sub="non tracciato" /></div>
                <div className="grid sm:grid-cols-2 gap-3">
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Precedente → questa</div><MiniTable cols={[{ key: 'slug', label: 'Da' }, { key: 'n', label: 'N', right: true, render: (r) => N(r.n) }]} rows={arr(sw.da_quale_modella).map((r) => ({ ...r, key: r.slug }))} /></div>
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Questa → successiva</div><MiniTable cols={[{ key: 'slug', label: 'Verso' }, { key: 'n', label: 'N', right: true, render: (r) => N(r.n) }]} rows={arr(sw.verso_quale_modella).map((r) => ({ ...r, key: r.slug }))} /></div>
                </div>
              </SectionCard>
            </WidgetBoundary>
          </div>
          <SectionCard title="Media" desc="Nessun evento media è tracciato nel profilo (video visti, slot, completamenti): vedi metriche non disponibili."><Empty text="Tracking media non presente." /></SectionCard>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ page
const DEFAULT_F = { range_key: '30g', from: '', to: '', model: 'all', mode: 'all', source: 'all', campagna: 'all', fonte: 'all', device: 'all' };
const clean = (f) => Object.fromEntries(Object.entries(f).filter(([k, v]) => v && v !== 'all' && !(k === 'from' && f.range_key !== 'custom') && !(k === 'to' && f.range_key !== 'custom')));

export default function AdminAnalytics() {
  const [sp, setSp] = useSearchParams();
  const [f, setF] = useState(() => ({ ...DEFAULT_F, ...Object.fromEntries([...sp.entries()].filter(([k]) => k in DEFAULT_F)) }));
  const [detail, setDetail] = useState(sp.get('modella') || null);
  const [compare, setCompare] = useState([]);
  const filters = useMemo(() => clean(f), [f]);
  useEffect(() => { const q = { ...filters }; if (detail) q.modella = detail; setSp(q, { replace: true }); }, [filters, detail, setSp]);

  const opts = useAsync(() => an2Filters(filters), [filters.range_key, filters.from, filters.to]);
  const sum = useAsync(() => an2Summary(filters), [JSON.stringify(filters)]);
  const models = useAsync(() => an2Models(filters), [JSON.stringify(filters)]);

  const s = sum.data;
  const noData = s && (s.eventi_totali || 0) === 0;
  return (
    <div className="space-y-4" data-testid="admin-analytics">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div><h1 className="font-serif text-3xl">Analytics</h1><div className="text-sm text-muted-foreground">Centro di controllo: solo dati realmente tracciati, aggregati dal backend.</div></div>
        <div className="flex items-center gap-2"><Btn variant="ghost" onClick={() => { sum.retry(); models.retry(); }} data-testid="analytics-refresh"><RefreshCw className="h-4 w-4 mr-1" /> Aggiorna</Btn><a href={an2ExportUrl('summary', filters)} target="_blank" rel="noreferrer" className="text-xs underline text-muted-foreground inline-flex items-center gap-1" data-testid="export-summary"><Download className="h-3 w-3" /> CSV dashboard</a></div>
      </div>
      <WidgetBoundary name="filters" title="Filtri"><Filters f={f} setF={setF} options={opts.data} /></WidgetBoundary>
      {s?.period && <div className="text-xs text-muted-foreground" data-testid="analytics-period">Periodo: {D(s.period.from)} → {D(s.period.to)}{filters.model ? ` · modella: ${filters.model}` : ''}{filters.mode ? ` · ${filters.mode}` : ''}</div>}

      {detail ? (
        <WidgetBoundary name="model-detail" title="Dettaglio modella"><ModelDetail slug={detail} filters={{ ...filters, model: undefined }} onBack={() => setDetail(null)} /></WidgetBoundary>
      ) : (
        <>
          {sum.loading ? <Skeleton h={84} n={4} /> : sum.error ? <ErrorPanel error={sum.error} onRetry={sum.retry} /> : noData ? <Empty /> : (
            <>
              <WidgetBoundary name="scorecard" title="Scorecard"><Scorecard sc={s.scorecard || {}} /></WidgetBoundary>
              <WidgetBoundary name="funnel" title="Funnel"><SectionCard title="Funnel globale" desc="Sessioni per passo · conversione dal passo precedente · conversione dalla visita. Con il filtro modella diventa il funnel di quella creator.">{<Funnel steps={s.funnel} />}</SectionCard></WidgetBoundary>
            </>
          )}
          <WidgetBoundary name="timeseries" title="Andamento"><Timeseries filters={filters} /></WidgetBoundary>
          {compare.length >= 2 && <WidgetBoundary name="compare" title="Confronto"><Compare filters={filters} slugs={compare} onClose={() => setCompare([])} /></WidgetBoundary>}
          <WidgetBoundary name="models" title="Tabella modelle"><ModelsTable filters={filters} onOpen={(slug) => setDetail(slug)} onCompare={setCompare} /></WidgetBoundary>
          {!sum.loading && !sum.error && !noData && (
            <>
              <WidgetBoundary name="rankings" title="Classifiche"><Rankings models={models.data?.items} /></WidgetBoundary>
              <WidgetBoundary name="onlyfans" title="OnlyFans"><OnlyFans of={s.onlyfans} filters={filters} /></WidgetBoundary>
              <WidgetBoundary name="swipe-secret-home" title="Swipe / Secret / Home"><SwipeSecretHome sw={s.swipe} sec={s.secret} home={s.home} /></WidgetBoundary>
              <WidgetBoundary name="sources" title="Origine"><Sources src={s.sources} /></WidgetBoundary>
              <WidgetBoundary name="top-events" title="Top eventi"><TopEvents rows={s.top_events} /></WidgetBoundary>
            </>
          )}
          <WidgetBoundary name="raw-events" title="Log eventi"><RawEvents filters={filters} /></WidgetBoundary>
          {s && <WidgetBoundary name="not-available" title="Metriche mancanti"><NotAvailable items={s.not_available} /></WidgetBoundary>}
        </>
      )}
      {process.env.NODE_ENV !== 'production' && !api ? null : null}
    </div>
  );
}
