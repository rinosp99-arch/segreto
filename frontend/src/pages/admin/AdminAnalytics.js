/* ADMIN → ANALYTICS — control center of everything the site really tracks (global + per creator).
   Robust by design: every widget is wrapped in its own error boundary (a broken chart never blanks the page),
   explicit LOADING / EMPTY / ERROR (+ Riprova) / PARTIAL states, no chart ever receives null data.
   Data: /api/admin/analytics/v2/* (backend aggregations, common event schema from lib/analytics.js). */
import { Component, useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { AlertTriangle, ArrowLeft, Download, RefreshCw, Search, ChevronUp, ChevronDown } from 'lucide-react';
import { SectionCard, Btn, SelectInput, TextInput } from '@/pages/admin/ui';
import { an2Summary, an2Models, an2Model, an2Timeseries, an2Compare, an2Events, an2Filters, an2ExportUrl, an2Visit } from '@/lib/adminApi';

// ------------------------------------------------------------------------------------------------ helpers
const N = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toLocaleString('it-IT'));
const P = (v) => (v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : `${Number(v).toLocaleString('it-IT', { maximumFractionDigits: 1 })}%`);
const S = (v) => (v === null || v === undefined ? '—' : `${Math.round(v)}s`);
const D = (iso) => { if (!iso) return '—'; const d = new Date(iso); return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); };
const arr = (x) => (Array.isArray(x) ? x : []);
const GOLD = 'hsl(42 45% 62%)';
const WINE = 'hsl(350 55% 45%)';
const RANGES = [['oggi', 'Oggi'], ['ieri', 'Ieri'], ['7g', '7 giorni'], ['30g', '30 giorni'], ['mese', 'Questo mese'], ['mese_scorso', 'Mese scorso'], ['custom', 'Personalizzato']];
const ENTRY_LABEL = { home_card: 'Card Home', filmstrip: 'FilmStrip', surprise: 'Sorprendimi', swipe: 'Swipe (gesto)', swipe_button: 'Swipe (pulsante)', related_models: 'Correlate', direct_profile: 'Diretto', campaign: 'Campagna', search: 'Ricerca', category: 'Categoria', landing: 'Landing' };
const EL = (k) => ENTRY_LABEL[k] || k || '—';

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
function MiniTable({ cols, rows, onRow, testid, emptyText, minW = 420 }) {
  if (!rows.length) return <Empty text={emptyText || 'Nessun dato.'} />;
  return (
    <div className="overflow-x-auto -mx-1">
      <table className="w-full text-sm" style={{ minWidth: minW }} data-testid={testid}>
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
const kn = (rows, k = 'key') => arr(rows).map((r) => ({ ...r, key: r[k] }));
const colN = (key, label) => ({ key, label, right: true, render: (r) => N(r[key]) });
const colP = (key, label) => ({ key, label, right: true, render: (r) => P(r[key]) });

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
      <SelectInput value={f.entry || 'all'} onChange={(e) => set('entry', e.target.value)} className="w-[150px]" data-testid="filter-entry">
        <option value="all">Ogni entry source</option>{arr(options?.entry_sources).map((s) => <option key={s} value={s}>{EL(s)}</option>)}
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
    ['Visite', N(sc.visite), `${N(sc.visitatori)} visitatori unici`, 'kpi-sessioni'], ['Home viste', N(sc.home_view), 'home_view'], ['Profili aperti', N(sc.profili_aperti), `${N(sc.visite_con_profilo)} visite · ${sc.profili_per_visita ?? '—'} profili/visita`, 'kpi-profili'],
    ['Visite engaged', N(sc.engaged_visite), 'video, scroll ≥50%, ≥10s o azione'], ['Lato Segreto', N(sc.secret_attivazioni), `${P(sc.secret_rate)} delle visite con profilo`, 'kpi-secret'],
    ['CTA viste → click', `${N(sc.cta_impressions)} → ${N(sc.cta_click)}`, `CTR CTA ${P(sc.ctr_cta)}`], ['Click OnlyFans personali', N(sc.of_click_personali), `CTR ${P(sc.ctr_of)} su profili · ${P(sc.ctr_of_su_impression)} su CTA viste`, 'kpi-of'],
    ['Marquee OF globale', `${N(sc.of_global_impressions)} → ${N(sc.of_click_globale)}`, `CTR ${P(sc.ctr_of_globale)} · impression → click`, 'kpi-of-global'],
    ['Click social', N(sc.social_click)], ['Swipe tra profili', N(sc.swipe), `${sc.swipe_per_visita ?? '—'} per visita con profilo`], ['Video start → completi', `${N(sc.video_start)} → ${N(sc.video_complete)}`, `completamento ${P(sc.video_completion_pct)}`],
    ['Engaged time medio', S(sc.engaged_medio_s), `in Secret ${S(sc.secret_engaged_medio_s)} · scroll medio ${P(sc.scroll_medio_pct)}`], ['Tempo in Secret (orologio)', S(sc.tempo_medio_secret_s), 'secret_time'],
    ['Sorprendimi / ricerche', `${N(sc.sorprendimi)} / ${N(sc.ricerche)}`, `${N(sc.filtri)} filtri · ${N(sc.categorie)} categorie`], ['Eventi', N(sc.eventi)],
  ];
  return <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2" data-testid="analytics-scorecard">{items.map(([l, v, s, t]) => <Kpi key={l} label={l} value={v} sub={s} testid={t} />)}</div>;
}

/* PROFILE VIEW → ENGAGED → SECRET → CTA IMPRESSION → CTA CLICK → OF CLICK, closed per visit, with drop-off */
function Funnel({ steps, testid = 'analytics-funnel' }) {
  const rows = arr(steps);
  const max = Math.max(1, ...rows.map((s) => s.n || 0));
  if (!rows.length || !rows[0].n) return <Empty />;
  return (
    <div data-testid={testid}>
      <div className="space-y-2">
        {rows.map((s, i) => (
          <div key={s.key || s.step} className="grid grid-cols-[1fr_auto] sm:grid-cols-[170px_1fr_260px] items-center gap-2 text-sm">
            <div className="truncate">{s.step}</div>
            <div className="hidden sm:block h-6 rounded-md bg-muted/30 overflow-hidden"><div className="h-full rounded-md" style={{ width: `${Math.max(2, (100 * (s.n || 0)) / max)}%`, background: i < 2 ? GOLD : WINE, opacity: 0.85 }} /></div>
            <div className="text-right tabular-nums text-muted-foreground"><span className="text-foreground font-medium">{N(s.n)}</span>{s.n_raw !== undefined && s.n_raw !== s.n ? <span className="text-[10px]"> (grezzo {N(s.n_raw)})</span> : null}{i > 0 && <> · ↓ <span className="text-foreground">{P(s.prosegue_pct)}</span> · dal 1° <span className="text-foreground">{P(s.dal_primo_pct)}</span></>}</div>
          </div>
        ))}
      </div>
      <div className="mt-4">
        <div className="text-[10px] caps-label text-muted-foreground mb-1">Dove perdi gli utenti</div>
        <MiniTable minW={360} testid={`${testid}-dropoff`} cols={[{ key: 'step', label: 'Step' }, colN('n', 'Utenti (visite)'), colP('prosegue_pct', '% proseguono'), colP('abbandona_pct', '% abbandonano')]} rows={rows.map((s) => ({ ...s, key: s.key || s.step }))} />
      </div>
    </div>
  );
}

function EntrySources({ rows, testid = 'entry-sources' }) {
  return <MiniTable testid={testid} minW={520} cols={[{ key: 'entry_source', label: 'Entry source', render: (r) => r.label || EL(r.entry_source) }, colN('profili', 'Profili aperti'), colN('visite', 'Visite'), colN('secret', 'Secret'), colP('secret_rate', 'Secret %'), colN('of_click', 'Click OF'), colP('ctr_of', 'CTR OF')]} rows={kn(rows, 'entry_source')} emptyText="Nessun profilo aperto nel periodo." />;
}

function Paths({ p }) {
  const items = arr(p?.items);
  return (
    <SectionCard title="Percorsi più frequenti" desc={`Sequenze aggregate per visita (max 8 passi, ultime ${N(p?.visite_analizzate)} visite con visit_id). HOME · CARD · FILMSTRIP · SORPRENDIMI · RICERCA · {MODELLA} · SECRET · SWIPE · OF.`}>
      <MiniTable testid="analytics-paths" minW={520} cols={[{ key: 'percorso', label: 'Percorso', render: (r) => <span className="font-mono text-xs">{r.percorso}</span> }, colN('n', 'Visite'), colN('of', 'Con OF'), colP('quota_pct', 'Quota')]} rows={kn(items, 'percorso')} emptyText="Nessuna visita con visit_id nel periodo (tracking v2 attivo dal 18/09)." />
    </SectionCard>
  );
}

function DeviceCompare({ rows, testid = 'device-compare' }) {
  return <MiniTable testid={testid} minW={900} cols={[{ key: 'device', label: 'Device' }, colN('visite', 'Visite'), colN('profili', 'Profili'), colP('secret_rate', 'Secret %'), colN('cta_impressions', 'CTA viste'), colP('ctr_cta', 'CTR CTA'), colN('of_click', 'Click OF'), colP('ctr_of', 'CTR OF'), colN('of_global_click', 'OF globale'), colN('swipe', 'Swipe'), colN('video_start', 'Video start'), colP('video_completion_pct', 'Completamento'), { key: 'engaged_medio_s', label: 'Engaged', right: true, render: (r) => S(r.engaged_medio_s) }]} rows={kn(rows, 'device')} emptyText="Nessun dato device." />;
}

function Engagement({ eng, scroll }) {
  const e = eng || {}; const sc = scroll || {};
  const bars = ['scroll_25', 'scroll_50', 'scroll_75', 'scroll_100'].map((k) => ({ k: k.replace('scroll_', '') + '%', n: sc[k]?.n || 0, pct: sc[k]?.pct }));
  return (
    <SectionCard title="Engaged time e scroll" desc="Tempo REALE di attenzione: conta solo con pagina visibile e utente attivo negli ultimi 20s (un evento per profilo, niente heartbeat). Scroll: profondità massima per visita profilo.">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3" data-testid="analytics-engagement">
        <Kpi label="Profili misurati" value={N(e.profili_misurati)} /><Kpi label="Engaged medio" value={S(e.engaged_medio_s)} sub={`Pubblico ${S(e.public_medio_s)} · Secret ${S(e.secret_medio_s)}`} />
        <Kpi label="≥10s / ≥30s / ≥60s" value={`${P(e.oltre_10s?.pct)} / ${P(e.oltre_30s?.pct)} / ${P(e.oltre_60s?.pct)}`} sub="quota dei profili misurati" /><Kpi label="Scroll medio" value={P(e.scroll_medio_pct)} />
      </div>
      <div className="grid sm:grid-cols-[1fr_260px] gap-3 items-center">
        <MiniTable minW={300} cols={[{ key: 'k', label: 'Profondità' }, colN('n', 'Profili'), colP('pct', '% dei profili aperti')]} rows={bars.map((b) => ({ ...b, key: b.k }))} />
        <div style={{ height: 120 }}><ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 260, height: 120 }}><BarChart data={bars}><XAxis dataKey="k" tick={{ fontSize: 10 }} /><Tooltip {...TT} /><Bar dataKey="n" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div>
      </div>
    </SectionCard>
  );
}

function VideoTable({ rows, testid = 'video-slots' }) {
  return <MiniTable testid={testid} minW={720} cols={[{ key: 'slot', label: 'Slot', render: (r) => `#${r.slot ?? '—'}` }, { key: 'mode', label: 'Mode' }, colN('video_impression', 'Impression'), colN('video_start', 'Start'), colP('start_pct', 'Start %'), colN('video_25', '25%'), colN('video_50', '50%'), colN('video_75', '75%'), colN('video_complete', 'Completi'), colP('complete_pct', 'Compl. % (su start)'), colN('video_replay', 'Replay')]} rows={arr(rows).map((r) => ({ ...r, key: `${r.slot}-${r.mode}` }))} emptyText="Nessun evento video nel periodo." />;
}

function CtaTable({ rows, testid = 'cta-types' }) {
  return <MiniTable testid={testid} minW={560} cols={[{ key: 'cta_type', label: 'CTA' }, colN('impressions', 'Viste'), colN('click', 'Click'), colP('ctr', 'CTR'), colN('dismiss', 'Chiuse'), colN('of_click', 'Click OF'), { key: 'secondi_medi_al_click', label: 'Secondi al click', right: true, render: (r) => S(r.secondi_medi_al_click) }]} rows={kn(rows, 'cta_type')} emptyText="Nessuna CTA nel periodo." />;
}

function Timeseries({ filters }) {
  const [gran, setGran] = useState('day');
  const [metric, setMetric] = useState('visite');
  const { loading, data, error, retry } = useAsync(() => an2Timeseries(filters, gran), [JSON.stringify(filters), gran]);
  const items = arr(data?.items);
  const metrics = [['visite', 'Visite'], ['home', 'Home'], ['profili', 'Profili aperti'], ['secret', 'Secret'], ['cta_imp', 'CTA viste'], ['of_click', 'Click OF'], ['marquee', 'OF globale'], ['swipe', 'Swipe'], ['video_start', 'Video start'], ['social', 'Social']];
  return (
    <SectionCard title="Andamento" desc="Quando arrivano le visite, quando si attiva il Lato Segreto, quando si clicca OF. Ora / giorno / settimana / mese (fuso Europa/Roma).">
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

const MODEL_COLS = [
  ['modella', 'Modella'], ['visite', 'Views', 1], ['visite_uniche', 'Visite', 1], ['visitatori_unici', 'Visitatori', 1], ['quota_traffico', '% traffico', 1, P], ['engaged', 'Engaged', 1], ['engaged_rate', 'Engaged %', 1, P],
  ['secret', 'Secret', 1], ['secret_rate', 'Secret %', 1, P], ['cta_impressions', 'CTA viste', 1], ['cta_click', 'CTA click', 1], ['ctr_cta', 'CTR CTA', 1, P], ['of_click', 'Click OF', 1], ['ctr_of', 'CTR OF', 1, P],
  ['social_click', 'Social', 1], ['swipe_in', 'Swipe in', 1], ['swipe_out', 'Swipe out', 1], ['video_start', 'Video start', 1], ['video_completion_pct', 'Video compl.', 1, P], ['scroll_50_pct', 'Scroll ≥50%', 1, P],
  ['engaged_medio_s', 'Engaged medio', 1, S], ['secret_engaged_medio_s', 'Engaged Secret', 1, S], ['marquee_click', 'OF globale', 1],
  ['via_home', 'Da card', 1], ['via_filmstrip', 'Da FilmStrip', 1], ['via_surprise', 'Da Sorprendimi', 1], ['via_swipe', 'Da swipe', 1], ['via_search', 'Da ricerca', 1], ['via_category', 'Da categoria', 1], ['via_related', 'Da correlate', 1], ['via_direct', 'Diretto', 1], ['via_campaign', 'Campagna', 1],
  ['ultimo_evento', 'Ultimo evento', 1, D],
];

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
  const th = (k, l, right) => (
    <th key={k} className={`py-2 px-2 whitespace-nowrap cursor-pointer select-none ${right ? 'text-right' : 'text-left'}`} onClick={() => setSort((s) => ({ key: k, dir: s.key === k && s.dir === 'desc' ? 'asc' : 'desc' }))} data-testid={`sort-${k}`}>
      {l} {sort.key === k ? (sort.dir === 'desc' ? <ChevronDown className="inline h-3 w-3" /> : <ChevronUp className="inline h-3 w-3" />) : null}
    </th>
  );
  const toggle = (slug) => setSel((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : s.length >= 5 ? s : [...s, slug]));
  return (
    <SectionCard title="Tutte le modelle" desc="Una riga per modella pubblicata. Ogni colonna è ordinabile (clicca l'intestazione), ricercabile, esportabile. Clicca il nome per il dettaglio; spunta 2–5 modelle per confrontarle.">
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="relative"><Search className="h-4 w-4 absolute left-2 top-2.5 text-muted-foreground" /><TextInput placeholder="Cerca modella" value={q} onChange={(e) => setQ(e.target.value)} className="pl-8 w-[220px]" data-testid="models-search" /></div>
        <Btn variant="ghost" onClick={() => onCompare(sel)} disabled={sel.length < 2} data-testid="models-compare-btn">Confronta ({sel.length})</Btn>
        <a href={an2ExportUrl('models', filters)} className="text-xs underline text-muted-foreground inline-flex items-center gap-1" target="_blank" rel="noreferrer" data-testid="export-models"><Download className="h-3 w-3" /> CSV</a>
      </div>
      {loading ? <Skeleton h={200} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Tabella modelle non disponibile" /> : !items.length ? <Empty text={q ? 'Nessuna modella corrisponde alla ricerca.' : 'Nessuna modella pubblicata.'} /> : (
        <div className="overflow-x-auto -mx-2">
          <table className="text-sm min-w-[2400px]" data-testid="models-table">
            <thead><tr className="text-[10px] caps-label text-muted-foreground"><th className="px-2" />{MODEL_COLS.map(([k, l, r]) => th(k, l, r))}</tr></thead>
            <tbody>
              {items.map((r) => (
                <tr key={r.slug} className="border-t border-border/40 hover:bg-muted/20" data-testid={`model-row-${r.slug}`}>
                  <td className="px-2"><input type="checkbox" checked={sel.includes(r.slug)} onChange={() => toggle(r.slug)} aria-label={`Confronta ${r.modella}`} data-testid={`compare-${r.slug}`} /></td>
                  {MODEL_COLS.map(([k, , right, fmt]) => (
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
  const blocks = [top('visite', N, 'Più visualizzate'), top('secret_rate', P, 'Secret % più alta'), top('of_click', N, 'Più click OF'), top('ctr_of', P, 'CTR OF più alto'), top('engaged_medio_s', S, 'Engaged time più alto'), top('video_completion_pct', P, 'Video più completati'), top('swipe_in', N, 'Più raggiunte via swipe'), top('swipe_out', N, 'Più lasciate via swipe')];
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

function OnlyFans({ of, cta, filters }) {
  const p = of?.personali || {}; const g = of?.globale || {};
  return (
    <SectionCard title="OnlyFans" desc="A) link personali delle creator (ogni CTA del profilo porta a OF: impression CTA = impression OF) · B) pagina globale LATO SEGRETO (marquee) — separati.">
      <div className="grid lg:grid-cols-2 gap-4">
        <div>
          <div className="flex items-center justify-between mb-2"><div className="font-medium">A · OnlyFans personali</div><a href={an2ExportUrl('of_clicks', filters)} target="_blank" rel="noreferrer" className="text-xs underline text-muted-foreground" data-testid="export-of">CSV click OF</a></div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <Kpi label="Impression CTA" value={N(p.impressions)} /><Kpi label="Click OF" value={N(p.totale)} sub={`${N(p.visite)} visite`} /><Kpi label="CTR su impression" value={P(p.ctr)} /><Kpi label="Profili medi prima del click" value={p.profili_medi_prima_del_click ?? '—'} />
          </div>
          <div className="text-[10px] caps-label text-muted-foreground mb-1">CTA per tipo</div>
          <CtaTable rows={cta?.per_tipo} />
          <div className="grid sm:grid-cols-2 gap-3 mt-3">
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Per modella</div><MiniTable minW={200} testid="of-personal-by-model" cols={[{ key: 'key', label: 'Modella' }, colN('n', 'Click')]} rows={arr(p.per_modella)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Da quale percorso (entry source)</div><MiniTable minW={200} cols={[{ key: 'key', label: 'Entry', render: (r) => EL(r.key) }, colN('n', 'Click')]} rows={arr(p.per_entry_source)} /></div>
          </div>
          <div className="text-xs text-muted-foreground mt-2">Click OF dopo swipe: <b className="text-foreground">{N(p.dopo_swipe)}</b> · dopo gesto <b className="text-foreground">{N(p.dopo_gesture)}</b> · dopo pulsante ‹ › <b className="text-foreground">{N(p.dopo_pulsante)}</b></div>
        </div>
        <div>
          <div className="font-medium mb-2">B · OnlyFans globale</div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
            <Kpi label="Impression marquee" value={N(g.impressions)} sub={`Home ${N(g.impressions_home)} · Profili ${N(g.impressions_profili)}`} /><Kpi label="Click" value={N(g.totale)} sub={`Home ${N(g.home)} · Profili ${N(g.profili)}`} /><Kpi label="CTR" value={P(g.ctr)} sub={`Home ${P(g.ctr_home)} · Profili ${P(g.ctr_profili)}`} /><Kpi label="Pubblico / Segreto" value={arr(g.per_modalita).map((m) => `${m.key}: ${m.n}`).join(' · ') || '—'} />
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Da quale modella</div><MiniTable minW={200} testid="of-global-by-model" cols={[{ key: 'key', label: 'Modella' }, colN('n', 'Click')]} rows={arr(g.per_modella)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Entry source del profilo</div><MiniTable minW={200} cols={[{ key: 'key', label: 'Entry', render: (r) => EL(r.key) }, colN('n', 'Click')]} rows={arr(g.per_entry_source)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable minW={200} cols={[{ key: 'key', label: 'Campagna' }, colN('n', 'Click')]} rows={arr(g.per_campagna)} /></div>
            <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Fonte</div><MiniTable minW={200} cols={[{ key: 'key', label: 'Fonte' }, colN('n', 'Click')]} rows={arr(g.per_fonte)} /></div>
          </div>
          {arr(g.per_ora).length > 0 && (
            <div className="mt-3" style={{ height: 120 }} data-testid="of-global-by-hour">
              <div className="text-[10px] caps-label text-muted-foreground mb-1">Click per ora (UTC)</div>
              <ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 120 }}><BarChart data={arr(g.per_ora)}><XAxis dataKey="ora" tick={{ fontSize: 10 }} /><Tooltip {...TT} /><Bar dataKey="n" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer>
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
      <SectionCard title="Swipe tra profili" desc="Gesto: profile_swipe_next/previous · Pulsanti ‹ › e tastiera: profile_nav_next_click/prev_click.">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Kpi label="Swipe totali" value={N(sw?.totali)} sub={`${N(sw?.visite)} visite · media ${sw?.media_swipe_per_visita ?? '—'}`} /><Kpi label="Gesto / pulsante" value={`${N(d.gesture)} / ${N(d.button)}`} />
          <Kpi label="→ Prossima / ← Precedente" value={`${N(d.next)} / ${N(d.previous)}`} /><Kpi label="Profili medi prima di OF" value={sw?.profili_medi_prima_di_of ?? '—'} sub={`OF dopo gesto ${N(sw?.of_dopo_gesture)} · pulsante ${N(sw?.of_dopo_pulsante)}`} />
        </div>
        <div className="text-[10px] caps-label text-muted-foreground mb-1">Modelle più raggiunte tramite swipe</div>
        <MiniTable minW={200} testid="swipe-reached" cols={[{ key: 'slug', label: 'Modella' }, colN('n', 'Arrivi')]} rows={arr(sw?.modelle_raggiunte).map((r) => ({ ...r, key: r.slug }))} />
      </SectionCard>
      <SectionCard title="Lato Segreto" desc="Attivazioni, quota visite, tempo (orologio e engaged), CTA/OF avvenuti in Secret.">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Kpi label="Attivazioni" value={N(sec?.attivazioni)} sub={`${N(sec?.visite)} visite`} /><Kpi label="% visite che attivano" value={P(sec?.rate_visitatori)} sub={`${P(sec?.rate_profili)} di chi apre un profilo`} />
          <Kpi label="Tempo in Secret" value={S(sec?.tempo_medio_s)} sub={`engaged ${S(sec?.engaged_medio_s)} · ${N(sec?.ritorni_public)} ritorni`} /><Kpi label="CTA / OF in Secret" value={`${N(sec?.cta_click)} / ${N(sec?.of_click)}`} />
        </div>
        <div className="text-[10px] caps-label text-muted-foreground mb-1">Per modella</div>
        <MiniTable minW={200} testid="secret-by-model" cols={[{ key: 'key', label: 'Modella' }, colN('n', 'Attivazioni')]} rows={arr(sec?.per_modella)} />
      </SectionCard>
      <SectionCard title="Home" desc="Cosa vede e cosa clicca l'utente in Home, e quale elemento lo porta dentro una modella.">
        <div className="grid grid-cols-2 gap-2 mb-3">
          <Kpi label="Home viste" value={N(home?.home_view)} sub={`${N(home?.toggle_totali)} switch · ${N(home?.toggle_secret_on)} verso Segreto`} /><Kpi label="Card viste → cliccate" value={`${N(home?.card_impressions)} → ${N(home?.card_click)}`} sub={`CTR card ${P(home?.card_ctr)}`} />
          <Kpi label="FilmStrip" value={`${N(home?.filmstrip_impression)} / ${N(home?.filmstrip_video_view)} / ${N(home?.filmstrip_click_profilo)}`} sub="impression / video / click profilo" /><Kpi label="Sorprendimi" value={N(home?.sorprendimi_click)} sub={`${N(home?.sorprendimi_profili_aperti)} profili aperti`} />
          <Kpi label="Marquee OF Home" value={`${N(home?.marquee_home_impression)} → ${N(home?.marquee_home_click)}`} sub={`CTR ${P(home?.marquee_home_ctr)}`} /><Kpi label="Ricerche / filtri / categorie" value={`${N(home?.ricerche)} / ${N(home?.filtri)} / ${N(home?.categorie)}`} sub={`${N(home?.landing_da_campagna)} landing campagna`} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Card più cliccate</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Modella' }, colN('n', 'Click')]} rows={arr(home?.card_top)} /></div>
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Filtri usati</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Filtro' }, colN('n', 'Usi')]} rows={arr(home?.filtri_usati)} /></div>
        </div>
      </SectionCard>
    </div>
  );
}

function Sources({ src }) {
  return (
    <SectionCard title="Origine del traffico e campagne" desc="source = dominio del referrer esterno (direct / instagram / tiktok / google / …), dispositivo, fonte / campagna / ref dei link tracciati.">
      <div className="grid lg:grid-cols-2 gap-4">
        <MiniTable testid="sources-detail" cols={[{ key: 'source', label: 'Origine' }, colN('visite', 'Visite'), colN('profili', 'Profili'), colN('secret', 'Secret'), colN('of_click', 'OF'), colP('ctr_of', 'CTR')]} rows={kn(src?.dettaglio, 'source')} />
        <div className="grid sm:grid-cols-3 gap-3">
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Campagna' }, colN('n', 'Eventi')]} rows={arr(src?.per_campagna)} /></div>
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Fonte</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Fonte' }, colN('n', 'Eventi')]} rows={arr(src?.per_fonte)} /></div>
          <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Dispositivo</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Device' }, colN('n', 'Eventi')]} rows={arr(src?.per_device)} /></div>
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
        colN('n', 'Conteggio'), { key: 'ultimo', label: 'Ultimo', right: true, render: (r) => D(r.ultimo) },
        { key: 'trend_pct', label: 'Trend', right: true, render: (r) => (r.trend_pct === null || r.trend_pct === undefined ? (r.prev ? '—' : 'nuovo') : <span style={{ color: r.trend_pct >= 0 ? GOLD : WINE }}>{r.trend_pct >= 0 ? '+' : ''}{P(r.trend_pct)}</span>) },
      ]} rows={kn(rows, 'evento')} />
    </SectionCard>
  );
}

function VisitJourney({ visitId, onClose }) {
  const { loading, data, error, retry } = useAsync(() => an2Visit(visitId), [visitId]);
  return (
    <div className="rounded-xl border border-border/60 p-3 mb-3 bg-card/40" data-testid="visit-journey">
      <div className="flex items-center justify-between mb-2"><div className="text-sm">Visita <span className="font-mono text-xs">{visitId.slice(0, 8)}…</span> · {N(data?.n)} eventi</div><Btn variant="ghost" onClick={onClose} data-testid="visit-journey-close">Chiudi</Btn></div>
      {loading ? <Skeleton h={60} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Visita non disponibile" /> : (
        <>
          <div className="font-mono text-xs text-primary mb-2 break-words">{data?.percorso || '—'}</div>
          <MiniTable minW={700} cols={[{ key: 'seq', label: '#' }, { key: 'timestamp', label: 'Quando', render: (r) => D(r.timestamp) }, { key: 'evento', label: 'Evento' }, { key: 'modella', label: 'Modella', render: (r) => r.modella || '—' }, { key: 'mode', label: 'Mode', render: (r) => r.mode || '—' }, { key: 'entry_source', label: 'Entry', render: (r) => EL(r.entry_source) }, { key: 'valore', label: 'Valore', right: true, render: (r) => (r.valore ?? '—') }, { key: 'meta', label: 'Dettagli', render: (r) => [r.cta_type, r.slot ? `slot ${r.slot}` : null, r.input, r.to_model ? `→ ${r.to_model}` : null, r.platform].filter(Boolean).join(' · ') || (r.meta && Object.keys(r.meta).length ? JSON.stringify(r.meta) : '—') }]} rows={arr(data?.items).map((r) => ({ ...r, key: r.id }))} />
        </>
      )}
    </div>
  );
}

function RawEvents({ filters }) {
  const [skip, setSkip] = useState(0);
  const [tipo, setTipo] = useState('');
  const [visit, setVisit] = useState(null);
  const { loading, data, error, retry } = useAsync(() => an2Events(filters, 50, skip, tipo), [JSON.stringify(filters), skip, tipo]);
  const items = arr(data?.items);
  return (
    <SectionCard title="Ultimi eventi (log tecnico)" desc="Per verificare che il tracking funzioni. Id troncati, nessun IP / token / dato personale. Clicca una visita per ricostruire il percorso completo.">
      <div className="flex items-center gap-2 mb-2"><TextInput placeholder="filtra per evento (es. of_click)" value={tipo} onChange={(e) => { setSkip(0); setTipo(e.target.value.trim()); }} className="w-[260px]" data-testid="events-filter" /><span className="text-xs text-muted-foreground">{N(data?.total)} eventi</span></div>
      {visit && <VisitJourney visitId={visit} onClose={() => setVisit(null)} />}
      {loading ? <Skeleton h={160} /> : error ? <ErrorPanel error={error} onRetry={retry} title="Log eventi non disponibile" /> : !items.length ? <Empty /> : (
        <MiniTable testid="raw-events" minW={1100} cols={[
          { key: 'timestamp', label: 'Quando', render: (r) => D(r.timestamp) }, { key: 'evento', label: 'Evento' }, { key: 'modella', label: 'Modella', render: (r) => r.modella || '—' },
          { key: 'mode', label: 'Mode', render: (r) => r.mode || '—' }, { key: 'entry_source', label: 'Entry', render: (r) => (r.entry_source ? EL(r.entry_source) : '—') }, { key: 'path', label: 'Path', render: (r) => r.path || '—' },
          { key: 'source', label: 'Source', render: (r) => r.source || '—' }, { key: 'device', label: 'Device', render: (r) => r.device || '—' }, { key: 'campagna', label: 'Campagna', render: (r) => r.campagna || '—' },
          { key: 'visit', label: 'Visita', render: (r) => (r.visit_id ? <button type="button" className="underline text-primary font-mono text-xs" onClick={() => setVisit(r.visit_id)} data-testid={`open-visit-${r.id}`}>{r.visit}</button> : <span className="text-muted-foreground">legacy</span>) },
          { key: 'dettagli', label: 'Dettagli', render: (r) => [r.cta_type, r.cta_source, r.slot ? `slot ${r.slot}` : null, r.input, r.to_model ? `→ ${r.to_model}` : null, r.platform, r.valore !== null && r.valore !== undefined ? `v=${r.valore}` : null].filter(Boolean).join(' · ') || (r.meta && Object.keys(r.meta).length ? JSON.stringify(r.meta) : '—') },
        ]} rows={items.map((r) => ({ ...r, key: r.id }))} />
      )}
      <div className="flex gap-2 mt-2"><Btn variant="ghost" disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - 50))}>← Precedenti</Btn><Btn variant="ghost" disabled={!data || skip + 50 >= (data.total || 0)} onClick={() => setSkip(skip + 50)}>Successivi →</Btn></div>
    </SectionCard>
  );
}

function NotAvailable({ items }) {
  if (!arr(items).length) return null;
  return (
    <SectionCard title="Limiti del tracking (dichiarati)" desc="Nessuna metrica è ricostruita artificialmente: qui ciò che non è misurato e perché.">
      <MiniTable testid="not-available" cols={[{ key: 'metrica', label: 'Metrica' }, { key: 'evento', label: 'Nota' }, { key: 'dove', label: 'Dove' }]} rows={arr(items).map((r, i) => ({ ...r, key: i }))} />
    </SectionCard>
  );
}

function Compare({ filters, slugs, onClose }) {
  const { loading, data, error, retry } = useAsync(() => an2Compare(filters, slugs), [JSON.stringify(filters), slugs.join(',')]);
  const items = arr(data?.items);
  const rows = [['visite', 'Views', N], ['visite_uniche', 'Visite', N], ['visitatori_unici', 'Visitatori', N], ['engaged_rate', 'Engaged %', P], ['secret', 'Secret', N], ['secret_rate', 'Secret %', P], ['cta_impressions', 'CTA viste', N], ['cta_click', 'CTA click', N], ['ctr_cta', 'CTR CTA', P], ['of_click', 'Click OF', N], ['ctr_of', 'CTR OF', P], ['social_click', 'Social', N], ['swipe_in', 'Swipe in', N], ['swipe_out', 'Swipe out', N], ['video_start', 'Video start', N], ['video_completion_pct', 'Video compl.', P], ['scroll_50_pct', 'Scroll ≥50%', P], ['engaged_medio_s', 'Engaged medio', S], ['secret_engaged_medio_s', 'Engaged Secret', S], ['marquee_click', 'OF globale', N]];
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
  const d = data || {}; const t = d.traffico || {}; const s = d.secret || {}; const o = d.onlyfans || {}; const sw = d.swipe || {}; const eng = d.engaged || {}; const sc = d.scroll || {}; const media = d.media || {};
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
          <WidgetBoundary name="detail-kpi" title="Riepilogo">
            <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-2" data-testid="detail-kpi">
              <Kpi label="Views" value={N(t.visite)} sub={`${N(t.visite_uniche)} visite · ${N(t.visitatori_unici)} visitatori`} /><Kpi label="Secret activation" value={P(s.public_to_secret_pct)} sub={`${N(s.attivazioni)} attivazioni · ${S(s.secondi_medi_prima_attivazione)} prima di premere`} />
              <Kpi label="CTA viste → click" value={`${N(o.impressions)} → ${N(o.cta_click)}`} sub={`CTR CTA ${P(d.cta?.ctr)}`} /><Kpi label="Click OF" value={N(o.of_click)} sub={`CTR ${P(o.ctr_of)} su views · ${P(o.ctr_of_su_impression)} su CTA viste`} />
              <Kpi label="Engaged time" value={S(eng.engaged_medio_s)} sub={`Secret ${S(eng.secret_medio_s)} · scroll ${P(eng.scroll_medio_pct)}`} /><Kpi label="Swipe in / out" value={`${N(sw.arrivi)} / ${N(sw.uscite)}`} sub={`OF globale da qui: ${N(o.marquee_globale_da_questo_profilo)}`} />
            </div>
          </WidgetBoundary>
          <WidgetBoundary name="detail-funnel" title="Funnel">
            <SectionCard title="Funnel" desc="PROFILE VIEW → ENGAGED → SECRET → CTA IMPRESSION → CTA CLICK → ONLYFANS CLICK. Chiuso per visita: ogni passo richiede i precedenti. Sotto: dove perdi gli utenti.">
              <Funnel steps={d.funnel} testid="detail-funnel" />
            </SectionCard>
          </WidgetBoundary>
          <div className="grid lg:grid-cols-2 gap-4">
            <WidgetBoundary name="detail-entry" title="Entry source"><SectionCard title="Come arrivano a questa modella" desc="entry_source della visita al profilo e cosa converte da ogni ingresso."><EntrySources rows={d.entry_sources} testid="detail-entry-sources" /></SectionCard></WidgetBoundary>
            <WidgetBoundary name="detail-device" title="Device"><SectionCard title="Mobile vs desktop vs tablet" desc="Le stesse metriche per dispositivo."><DeviceCompare rows={d.device_compare} testid="detail-device-compare" /></SectionCard></WidgetBoundary>
          </div>
          <WidgetBoundary name="detail-traffic" title="Traffico">
            <SectionCard title="Traffico e andamento" desc={`Giorno con più views: ${t.giorno_top || '—'} · ora di punta (UTC): ${t.ora_top ? `${t.ora_top}:00` : '—'} · ultimo evento: ${D(d.ultimo_evento)}`}>
              <div className="grid sm:grid-cols-2 gap-3">
                {arr(t.per_giorno).length > 0 && <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Views per giorno</div><div style={{ height: 160 }} data-testid="detail-by-day"><ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 160 }}><BarChart data={arr(t.per_giorno)}><XAxis dataKey="giorno" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} width={28} allowDecimals={false} /><Tooltip {...TT} /><Bar dataKey="n" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div></div>}
                {arr(t.per_ora).length > 0 && <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Views per ora (UTC) · click OF per ora</div><div style={{ height: 160 }}><ResponsiveContainer width="100%" height="100%" initialDimension={{ width: 320, height: 160 }}><BarChart data={arr(t.per_ora).map((h) => ({ ...h, of: (arr(t.of_per_ora).find((x) => x.ora === h.ora) || {}).n || 0 }))}><XAxis dataKey="ora" tick={{ fontSize: 10 }} /><YAxis tick={{ fontSize: 10 }} width={28} allowDecimals={false} /><Tooltip {...TT} /><Bar dataKey="n" name="views" fill={GOLD} radius={[4, 4, 0, 0]} isAnimationActive={false} /><Bar dataKey="of" name="OF" fill={WINE} radius={[4, 4, 0, 0]} isAnimationActive={false} /></BarChart></ResponsiveContainer></div></div>}
              </div>
              <div className="grid sm:grid-cols-4 gap-3 mt-3">
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Origine</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Source' }, colN('n', 'Views')]} rows={arr(t.per_source)} /></div>
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Dispositivo</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Device' }, colN('n', 'Views')]} rows={arr(t.per_device)} /></div>
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Campagna</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Campagna' }, colN('n', 'Views')]} rows={arr(t.per_campagna)} /></div>
                <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Fonte</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Fonte' }, colN('n', 'Views')]} rows={arr(t.per_fonte)} /></div>
              </div>
            </SectionCard>
          </WidgetBoundary>
          <WidgetBoundary name="detail-media" title="Video">
            <SectionCard title="Video per slot" desc="Impression (tile ≥50% visibile) → start → 25/50/75% → completo, per slot e modalità. Ogni milestone al massimo una volta per visita.">
              {media.disponibile ? <VideoTable rows={media.per_slot} testid="detail-video" /> : <Empty text="Nessun evento video per questa modella nel periodo (tracking video attivo dal 18/09)." />}
            </SectionCard>
          </WidgetBoundary>
          <WidgetBoundary name="detail-engagement" title="Engagement"><Engagement eng={eng} scroll={sc} /></WidgetBoundary>
          <div className="grid lg:grid-cols-2 gap-4">
            <WidgetBoundary name="detail-secret" title="Lato Segreto">
              <SectionCard title="Lato Segreto">
                <div className="grid grid-cols-2 gap-2"><Kpi label="Attivazioni" value={N(s.attivazioni)} sub={`${N(s.visite)} visite`} /><Kpi label="Public → Secret" value={P(s.public_to_secret_pct)} sub="visite con attivazione / visite con view" /><Kpi label="Tempo in Secret" value={S(s.tempo_medio_s)} sub={`engaged ${S(s.engaged_medio_s)}`} /><Kpi label="Ritorni al Pubblico" value={N(s.ritorni_public)} sub="secret_return" /></div>
              </SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-of" title="OnlyFans">
              <SectionCard title="OnlyFans personale">
                <div className="grid grid-cols-2 gap-2 mb-3"><Kpi label="CTA viste / click" value={`${N(o.impressions)} / ${N(o.cta_click)}`} /><Kpi label="Click OF" value={N(o.of_click)} sub={`CTR ${P(o.ctr_of)}`} /><Kpi label="Da Public / da Secret" value={`${N(o.da_public)} / ${N(o.da_secret)}`} /><Kpi label="Dopo swipe" value={N(o.dopo_swipe)} sub={`gesto ${N(o.dopo_gesture)} · pulsante ${N(o.dopo_pulsante)}`} /></div>
                <div className="text-[10px] caps-label text-muted-foreground mb-1">CTA per tipo</div>
                <CtaTable rows={d.cta?.per_tipo} testid="detail-cta" />
                <div className="grid sm:grid-cols-2 gap-3 mt-3">
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Entry source del click</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Entry', render: (r) => EL(r.key) }, colN('n', 'Click')]} rows={arr(o.per_entry_source)} /></div>
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Device del click</div><MiniTable minW={160} cols={[{ key: 'key', label: 'Device' }, colN('n', 'Click')]} rows={arr(o.per_device)} /></div>
                </div>
                <div className="text-xs text-muted-foreground mt-2">Marquee OF globale in questo profilo: <b className="text-foreground">{N(o.marquee_globale_impressions)}</b> impression → <b className="text-foreground">{N(o.marquee_globale_da_questo_profilo)}</b> click (CTR {P(o.marquee_ctr)})</div>
              </SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-social" title="Social">
              <SectionCard title="Social">{social.length ? <><div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{social.map(([k, v]) => <Kpi key={k} label={k} value={N(v)} />)}</div>{arr(d.social_per_mode).length > 0 && <div className="text-xs text-muted-foreground mt-2">Per modalità: {arr(d.social_per_mode).map((m) => `${m.key}: ${m.n}`).join(' · ')}</div>}</> : <Empty text="Nessun click social nel periodo." />}</SectionCard>
            </WidgetBoundary>
            <WidgetBoundary name="detail-swipe" title="Swipe">
              <SectionCard title="Swipe">
                <div className="grid grid-cols-2 gap-2 mb-3"><Kpi label="Arrivi via swipe" value={N(sw.arrivi)} sub={`gesto ${N(sw.arrivi_gesture)} · pulsante ${N(sw.arrivi_pulsante)}`} /><Kpi label="Uscite via swipe" value={N(sw.uscite)} sub={`gesto ${N(sw.uscite_gesture)} · pulsante ${N(sw.uscite_pulsante)}`} /><Kpi label="Click OF dopo swipe" value={N(sw.of_click_dopo_swipe)} /><Kpi label="Secondi prima di uscire" value={S(sw.secondi_medi_prima_di_uscire)} /></div>
                <div className="grid sm:grid-cols-2 gap-3">
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Precedente → questa</div><MiniTable minW={160} cols={[{ key: 'slug', label: 'Da' }, colN('n', 'N')]} rows={kn(sw.da_quale_modella, 'slug')} /></div>
                  <div><div className="text-[10px] caps-label text-muted-foreground mb-1">Questa → successiva</div><MiniTable minW={160} cols={[{ key: 'slug', label: 'Verso' }, colN('n', 'N')]} rows={kn(sw.verso_quale_modella, 'slug')} /></div>
                </div>
              </SectionCard>
            </WidgetBoundary>
          </div>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------------------------------------ page
const DEFAULT_F = { range_key: '30g', from: '', to: '', model: 'all', mode: 'all', entry: 'all', source: 'all', campagna: 'all', fonte: 'all', device: 'all' };
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
        <div><h1 className="font-serif text-3xl">Analytics</h1><div className="text-sm text-muted-foreground">Centro di controllo: solo dati realmente tracciati, aggregati dal backend. Visita = 30 min di inattività / nuova scheda.</div></div>
        <div className="flex items-center gap-2"><Btn variant="ghost" onClick={() => { sum.retry(); models.retry(); }} data-testid="analytics-refresh"><RefreshCw className="h-4 w-4 mr-1" /> Aggiorna</Btn><a href={an2ExportUrl('summary', filters)} target="_blank" rel="noreferrer" className="text-xs underline text-muted-foreground inline-flex items-center gap-1" data-testid="export-summary"><Download className="h-3 w-3" /> CSV dashboard</a></div>
      </div>
      <WidgetBoundary name="filters" title="Filtri"><Filters f={f} setF={setF} options={opts.data} /></WidgetBoundary>
      {s?.period && <div className="text-xs text-muted-foreground" data-testid="analytics-period">Periodo: {D(s.period.from)} → {D(s.period.to)}{filters.model ? ` · modella: ${filters.model}` : ''}{filters.mode ? ` · ${filters.mode}` : ''}{filters.entry ? ` · entry: ${EL(filters.entry)}` : ''}</div>}

      {detail ? (
        <WidgetBoundary name="model-detail" title="Dettaglio modella"><ModelDetail slug={detail} filters={{ ...filters, model: undefined }} onBack={() => setDetail(null)} /></WidgetBoundary>
      ) : (
        <>
          {sum.loading ? <Skeleton h={84} n={4} /> : sum.error ? <ErrorPanel error={sum.error} onRetry={sum.retry} /> : noData ? <Empty /> : (
            <>
              <WidgetBoundary name="scorecard" title="Scorecard"><Scorecard sc={s.scorecard || {}} /></WidgetBoundary>
              <WidgetBoundary name="funnel" title="Funnel"><SectionCard title="Funnel globale" desc="PROFILE VIEW → ENGAGED → SECRET → CTA IMPRESSION → CTA CLICK → ONLYFANS CLICK, per visita (chiuso: ogni passo richiede i precedenti). Con il filtro modella diventa il funnel di quella creator."><Funnel steps={s.funnel} /></SectionCard></WidgetBoundary>
              <div className="grid lg:grid-cols-2 gap-4">
                <WidgetBoundary name="entry" title="Entry source"><SectionCard title="Come arrivano alle modelle (entry source)" desc="Da dove parte la visita a un profilo e quanto converte ogni ingresso."><EntrySources rows={s.entry_sources} /></SectionCard></WidgetBoundary>
                <WidgetBoundary name="device" title="Device"><SectionCard title="Mobile vs desktop vs tablet" desc="Le stesse metriche affiancate per dispositivo."><DeviceCompare rows={s.device_compare} /></SectionCard></WidgetBoundary>
              </div>
              <WidgetBoundary name="paths" title="Percorsi"><Paths p={s.percorsi} /></WidgetBoundary>
            </>
          )}
          <WidgetBoundary name="timeseries" title="Andamento"><Timeseries filters={filters} /></WidgetBoundary>
          {compare.length >= 2 && <WidgetBoundary name="compare" title="Confronto"><Compare filters={filters} slugs={compare} onClose={() => setCompare([])} /></WidgetBoundary>}
          <WidgetBoundary name="models" title="Tabella modelle"><ModelsTable filters={filters} onOpen={(slug) => setDetail(slug)} onCompare={setCompare} /></WidgetBoundary>
          {!sum.loading && !sum.error && !noData && (
            <>
              <WidgetBoundary name="rankings" title="Classifiche"><Rankings models={models.data?.items} /></WidgetBoundary>
              <WidgetBoundary name="onlyfans" title="OnlyFans"><OnlyFans of={s.onlyfans} cta={s.cta} filters={filters} /></WidgetBoundary>
              <WidgetBoundary name="video" title="Video"><SectionCard title="Video (tutte le modelle)" desc="Per slot e modalità: impression → start → milestone → completo. Es. “il video Secret #2 viene avviato dal 62% e completato dal 31%”."><VideoTable rows={s.video?.per_slot} /></SectionCard></WidgetBoundary>
              <WidgetBoundary name="engagement" title="Engagement"><Engagement eng={s.engaged} scroll={s.scroll} /></WidgetBoundary>
              <WidgetBoundary name="swipe-secret-home" title="Swipe / Secret / Home"><SwipeSecretHome sw={s.swipe} sec={s.secret} home={s.home} /></WidgetBoundary>
              <WidgetBoundary name="sources" title="Origine"><Sources src={s.sources} /></WidgetBoundary>
              <WidgetBoundary name="top-events" title="Top eventi"><TopEvents rows={s.top_events} /></WidgetBoundary>
            </>
          )}
          <WidgetBoundary name="raw-events" title="Log eventi"><RawEvents filters={filters} /></WidgetBoundary>
          {s && <WidgetBoundary name="not-available" title="Limiti"><NotAvailable items={s.not_available} /></WidgetBoundary>}
        </>
      )}
    </div>
  );
}
