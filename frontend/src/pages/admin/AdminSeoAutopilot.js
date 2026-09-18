import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Brain, Lock, Globe2, Clock, Search, Layers, Lightbulb, Wrench, FilePlus2, FileEdit, Merge, ShieldAlert, AlertTriangle,
  Play, Loader2, RefreshCw, ScrollText, Eye, Code2, Radar, ListOrdered, Sparkles,
} from 'lucide-react';
import {
  seoApStatus, seoApRun, seoApRuns, seoApLog, seoApOpportunities, seoApProposals, seoApCannibalization, seoApBacklog, seoApTech, seoApRender, seoApAdult, seoApClusters, seoApExecute,
} from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', info: 'hsl(200 50% 60%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };
const SEV = { CRITICAL: C.fail, HIGH: C.fail, MEDIUM: C.warn, LOW: C.info, INFO: C.muted, HOLD: C.muted };
const TABS = [
  { k: 'opportunita', l: 'Opportunità', icon: Lightbulb }, { k: 'backlog', l: 'Backlog', icon: ListOrdered }, { k: 'cluster', l: 'Cluster', icon: Layers },
  { k: 'proposte', l: 'Landing proposte', icon: FilePlus2 }, { k: 'cannibalizzazione', l: 'Cannibalizzazione', icon: Merge }, { k: 'tecnico', l: 'Audit tecnico', icon: Wrench },
  { k: 'rendering', l: 'Rendering', icon: Code2 }, { k: 'adult', l: 'Audit adult', icon: ShieldAlert }, { k: 'log', l: 'Log decisioni', icon: ScrollText },
];

function Pill({ label, color = C.muted, testid }) {
  return <span className="caps-label px-2.5 py-1 rounded-full text-[10px] whitespace-nowrap" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }} data-testid={testid}>{label}</span>;
}
function Kpi({ icon: Icon, label, value, sub, testid, color }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 caps-label text-muted-foreground mb-2"><Icon className="h-4 w-4" />{label}</div>
      <div className="text-3xl font-serif" style={color ? { color } : {}}>{value ?? '—'}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}
function fmt(ts) { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } }
function short(u) { if (!u) return '—'; try { const x = new URL(u); return x.pathname === '/' ? '/ (Home)' : x.pathname; } catch (e) { return u; } }
function Empty({ text }) { return <div className="text-sm text-muted-foreground py-6 text-center" data-testid="seo-ap-empty">{text}</div>; }
function Row({ children, testid }) { return <div className="flex flex-wrap items-start gap-2 py-2.5 border-b border-border/40 last:border-0 text-sm" data-testid={testid}>{children}</div>; }

export default function AdminSeoAutopilot() {
  const [s, setS] = useState(null);
  const [tab, setTab] = useState('opportunita');
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    try { setS(await seoApStatus()); setErr(''); } catch (e) { setErr('Impossibile caricare lo stato SEO Autopilot'); }
  }, []);
  const loadTab = useCallback(async (t) => {
    setData(null);
    try {
      const fn = {
        opportunita: () => seoApOpportunities({ status: 'OPEN', limit: 60 }), backlog: () => seoApBacklog(60), cluster: () => seoApClusters({ limit: 120 }),
        proposte: () => seoApProposals(), cannibalizzazione: seoApCannibalization, tecnico: seoApTech, rendering: seoApRender, adult: seoApAdult, log: () => seoApLog({ limit: 80 }),
      }[t];
      setData(await fn());
    } catch (e) { toast.error('Errore nel caricamento della sezione'); setData({ items: [] }); }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { loadTab(tab); }, [tab, loadTab]);
  useEffect(() => {
    if (!s?.running) return undefined;
    const t = setInterval(() => { load(); loadTab(tab); }, 8000);
    return () => clearInterval(t);
  }, [s?.running, load, loadTab, tab]);

  const run = async (kind) => {
    setBusy(kind);
    try {
      const r = await seoApRun(kind);
      toast[r.started ? 'success' : 'info'](r.started ? `Analisi "${kind}" avviata in background (READ_ONLY)` : 'Un\'analisi è già in corso');
      setTimeout(load, 1200);
    } catch (e) { toast.error(e?.response?.data?.detail || 'Avvio fallito'); } finally { setBusy(''); }
  };
  const proveGuard = async () => {
    try { await seoApExecute('test-guard'); toast.error('ATTENZIONE: il guard non ha bloccato'); }
    catch (e) { toast.success(`Guard attivo: ${e?.response?.status === 423 ? 'azione bloccata (423)' : 'bloccato'}`); loadTab('log'); setTab('log'); }
  };

  const t = s?.today || {};
  const gscOk = s?.GSC_STATUS === 'CONNECTED';
  const pm = s?.PUBLIC_MUTATIONS_last;

  return (
    <div data-testid="seo-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Brain className="h-7 w-7" style={{ color: C.gold }} /> SEO Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Motore di crescita organica: analizza, impara, propone. In READ_ONLY non modifica nulla del sito pubblico.</p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <Btn variant="ghost" onClick={() => { load(); loadTab(tab); }} data-testid="seo-ap-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn variant="ghost" onClick={() => run('tech_health')} disabled={!!busy || s?.running} data-testid="seo-ap-run-tech">{busy === 'tech_health' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Radar className="h-4 w-4" />} Audit tecnico</Btn>
          <Btn onClick={() => run('daily_analysis')} disabled={!!busy || s?.running} data-testid="seo-ap-run-daily">{busy === 'daily_analysis' || s?.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} {s?.running ? `In corso: ${s.running_kind}` : 'Analisi giornaliera'}</Btn>
        </div>
      </div>

      {err && <div className="rounded-xl border p-3 text-sm mb-4" style={{ borderColor: C.fail, color: C.fail }} data-testid="seo-ap-error">{err}</div>}

      <div className="flex flex-wrap gap-2 mb-5" data-testid="seo-ap-status-pills">
        <Pill label={`Stato: ${s?.mode?.mode || '…'}`} color={s?.mode?.mode === 'READ_ONLY' ? C.ok : s?.mode?.mode === 'OFF' ? C.muted : C.fail} testid="seo-ap-mode" />
        <Pill label={`FULL ${s?.mode?.full_locked ? 'bloccato' : 'sbloccato'}`} color={s?.mode?.full_locked ? C.ok : C.fail} testid="seo-ap-full-lock" />
        <Pill label={`Search Console: ${gscOk ? 'CONNECTED' : s?.GSC_STATUS || '…'}`} color={gscOk ? C.ok : C.warn} testid="seo-ap-gsc" />
        <Pill label={`Mutazioni pubbliche: ${pm === null || pm === undefined ? 'n/d' : pm}`} color={pm === 0 ? C.ok : pm > 0 ? C.fail : C.muted} testid="seo-ap-public-mutations" />
        <Pill label={`LLM ${s?.llm?.enabled ? `${s.llm.model} · ${s.llm.calls_today}/${s.llm.daily_budget} oggi` : 'off'} (solo suggerimenti)`} color={C.info} testid="seo-ap-llm" />
        <Pill label={`Browser ${s?.render_budget?.used_today ?? 0}/${s?.render_budget?.daily ?? 30} pagine oggi`} color={C.info} testid="seo-ap-render-budget" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <Kpi icon={Clock} label="Ultima analisi" value={fmt(s?.last_analysis_at)} sub={`ultimo run: ${fmt(s?.last_run_at)}`} testid="seo-ap-kpi-last" />
        <Kpi icon={Search} label="Query analizzate" value={t.queries_analysed} sub={`${t.keywords_total ?? 0} keyword totali · storico GSC ${s?.gsc_data?.days ?? 0} gg`} testid="seo-ap-kpi-queries" />
        <Kpi icon={Layers} label="Cluster" value={t.clusters} sub="intenti raggruppati (deterministico)" testid="seo-ap-kpi-clusters" />
        <Kpi icon={Lightbulb} label="Opportunità" value={t.open_opportunities} sub={`${t.new_opportunities ?? 0} nuove oggi`} testid="seo-ap-kpi-opps" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Kpi icon={Wrench} label="Problemi tecnici" value={t.tech_findings} sub={Object.entries(t.tech_problems || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || 'nessun audit'} testid="seo-ap-kpi-tech" />
        <Kpi icon={FilePlus2} label="Proposte CREATE" value={t.proposals_CREATE} sub={`${t.landing_drafts ?? 0} bozze landing interne`} testid="seo-ap-kpi-create" />
        <Kpi icon={FileEdit} label="Proposte UPDATE / MERGE" value={`${t.proposals_UPDATE ?? 0} / ${t.proposals_MERGE ?? 0}`} sub={`cannibalizzazioni aperte: ${t.cannibalization_open ?? 0}`} testid="seo-ap-kpi-update" />
        <Kpi icon={ShieldAlert} label="Bloccate dal quality gate" value={t.blocked_by_quality_gate} sub="REJECTED_BY_QUALITY_GATE" testid="seo-ap-kpi-gate" color={t.blocked_by_quality_gate ? C.warn : undefined} />
      </div>

      {!!(s?.errors?.length) && (
        <SectionCard title="Errori recenti del motore" desc="Ogni step fallisce in modo isolato: il run continua.">
          {s.errors.map((e, i) => <Row key={i} testid="seo-ap-engine-error"><span className="text-xs text-muted-foreground w-24">{fmt(e.timestamp)}</span><span className="font-mono text-xs">{e.target}</span><span className="text-muted-foreground">{e.reason}</span></Row>)}
        </SectionCard>
      )}

      <div className="flex flex-wrap gap-1.5 mb-4" data-testid="seo-ap-tabs">
        {TABS.map((x) => (
          <button key={x.k} onClick={() => setTab(x.k)} data-testid={`seo-ap-tab-${x.k}`}
            className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs transition-colors ${tab === x.k ? 'bg-primary/15 text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'}`}>
            <x.icon className="h-3.5 w-3.5" />{x.l}
          </button>
        ))}
      </div>

      <SectionCard>
        {!data ? <div className="flex items-center gap-2 text-sm text-muted-foreground py-6 justify-center"><Loader2 className="h-4 w-4 animate-spin" /> Caricamento…</div> : (
          <>
            {tab === 'opportunita' && (data.items?.length ? data.items.map((o) => (
              <Row key={o.fingerprint} testid="seo-ap-opportunity">
                <Pill label={o.score} color={SEV[o.score]} /><Pill label={o.suggested_action} color={C.gold} />
                <div className="flex-1 min-w-[240px]"><div className="font-medium">{o.target}</div><div className="text-xs text-muted-foreground mt-0.5">{o.reason}</div>
                  <div className="text-[11px] text-muted-foreground/70 mt-1 font-mono">{o.rule} · impression 28g: {o.metrics?.impressions_28 ?? 'UNKNOWN'} · pos: {o.metrics?.position_28 ?? 'UNKNOWN'} · CTR: {o.metrics?.ctr_28 ?? 'UNKNOWN'}</div></div>
              </Row>)) : <Empty text="Nessuna opportunità aperta. Con Search Console senza dati le metriche restano UNKNOWN: nessun numero viene inventato." />)}

            {tab === 'backlog' && (data.items?.length ? data.items.map((b) => (
              <Row key={b.fingerprint} testid="seo-ap-backlog-item">
                <span className="font-mono text-xs text-muted-foreground w-6">#{b.rank}</span><Pill label={b.score} color={SEV[b.score]} /><Pill label={b.action} color={C.gold} />
                <div className="flex-1 min-w-[240px]"><div className="font-medium break-all">{b.target}</div><div className="text-xs text-muted-foreground mt-0.5">{b.reason}</div></div>
              </Row>)) : <Empty text="Backlog vuoto." />)}

            {tab === 'cluster' && (data.items?.length ? data.items.map((c) => (
              <Row key={c.cluster_id} testid="seo-ap-cluster">
                <Pill label={c.intent} color={C.info} />
                <div className="flex-1 min-w-[240px]"><div className="font-medium">{c.primary_keyword} <span className="text-xs text-muted-foreground">({c.n_keywords} kw)</span></div>
                  <div className="text-xs text-muted-foreground mt-0.5">{(c.secondary_keywords || []).slice(0, 6).join(' · ')}</div>
                  <div className="text-[11px] text-muted-foreground/70 mt-1 font-mono">impression 28g: {c.metrics?.impressions_28 ?? 'UNKNOWN'} · pos: {c.metrics?.position_28 ?? 'UNKNOWN'} · trend: {c.trend?.status} · pagina: {short(c.current_page)} · cannibalizzazione: {c.cannibalization?.risk} · fonti: {(c.sources || []).join(',')}</div></div>
              </Row>)) : <Empty text="Nessun cluster: esegui l'analisi giornaliera." />)}

            {tab === 'proposte' && (
              <>
                <div className="text-xs text-muted-foreground mb-3 flex items-center gap-2"><Lock className="h-3.5 w-3.5" /> Proposte interne, non pubbliche, non eseguibili in READ_ONLY. <button onClick={proveGuard} className="underline hover:text-foreground" data-testid="seo-ap-prove-guard">Verifica guard FULL</button></div>
                {data.items?.length ? data.items.map((p) => (
                  <Row key={p.proposed_slug} testid="seo-ap-proposal">
                    <Pill label={p.status === 'SEO_DRAFT_PROPOSAL' ? 'BOZZA' : 'RIFIUTATA'} color={p.status === 'SEO_DRAFT_PROPOSAL' ? C.ok : C.warn} />{p.hold && <Pill label="HOLD: nessun dato GSC" />}
                    <div className="flex-1 min-w-[240px]"><div className="font-medium font-mono">/{p.proposed_slug} <span className="text-xs text-muted-foreground">{p.search_intent} · {p.creator_pertinenti?.length} creator reali · qualità {p.quality_score}</span></div>
                      <div className="text-xs mt-0.5">Title: {p.title_proposto} · H1: {p.h1_proposto}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">{p.motivo}</div>
                      <div className="text-[11px] mt-1 flex flex-wrap gap-1">{(p.quality_gate || []).map((g) => <span key={g.check} className="px-1.5 py-0.5 rounded font-mono" style={{ color: g.ok ? C.ok : C.fail, border: `1px solid ${(g.ok ? C.ok : C.fail).replace(')', ' / 0.35)')}` }} title={g.detail}>{g.check}</span>)}</div></div>
                  </Row>)) : <Empty text="Nessuna proposta di landing: il planner propone solo intenti distinti con creator reali." />}
              </>
            )}

            {tab === 'cannibalizzazione' && (data.items?.length ? data.items.map((c) => (
              <Row key={c.fingerprint} testid="seo-ap-cannibal">
                <Pill label={c.CANNIBALIZATION_RISK} color={SEV[c.CANNIBALIZATION_RISK]} /><Pill label={c.type} />
                <div className="flex-1 min-w-[240px]"><div className="text-xs">{c.reason}</div><div className="text-[11px] text-muted-foreground font-mono mt-0.5 break-all">{(c.urls || []).map(short).join('  ↔  ')}</div></div>
              </Row>)) : <Empty text="Nessuna cannibalizzazione rilevata." />)}

            {tab === 'tecnico' && (
              <>
                <div className="text-xs text-muted-foreground mb-3 font-mono" data-testid="seo-ap-tech-summary">{data.audit?.summary ? `${data.audit.summary.urls} URL · ${data.audit.summary.ok_200} ok · ${data.audit.summary.in_sitemap} in sitemap · ${data.audit.summary.broken_links} link rotti · ${fmt(data.audit.at)} · base ${data.audit.summary.base}` : 'nessun audit'}</div>
                {data.audit?.findings?.length ? data.audit.findings.map((f, i) => (
                  <Row key={i} testid="seo-ap-tech-finding"><Pill label={f.severity} color={SEV[f.severity]} /><div className="flex-1 min-w-[240px]"><div className="font-mono text-xs">{f.code}</div><div className="text-xs text-muted-foreground">{f.detail}</div>{f.url && <div className="text-[11px] text-muted-foreground/70 font-mono break-all">{f.url}</div>}</div></Row>
                )) : <Empty text="Nessuna rilevazione tecnica." />}
              </>
            )}

            {tab === 'rendering' && (
              <>
                <div className="text-xs text-muted-foreground mb-3 font-mono" data-testid="seo-ap-render-summary">{data.audit?.summary ? `${data.audit.summary.pages} pagine renderizzate · ${data.audit.summary.problems} con problemi · ispezioni Google: ${data.audit.summary.inspected} (${data.audit.summary.google_inspection || 'n/d'}) · budget ${data.audit.summary.used_today + (data.audit.summary.this_run || 0)}/${data.audit.summary.daily}` : 'nessun campione'}</div>
                {data.table?.length ? data.table.map((r) => (
                  <Row key={r.url} testid="seo-ap-render-row">
                    <Pill label={r.verdict} color={r.verdict === 'OK' ? C.ok : C.fail} />
                    <div className="flex-1 min-w-[240px]"><div className="font-mono text-xs break-all">{short(r.url)}</div>
                      <div className="grid md:grid-cols-3 gap-2 mt-1 text-[11px]">
                        <div><span className="caps-label text-muted-foreground">Initial HTML</span><div>title: {r.INITIAL_HTML.title || '—'}</div><div>h1: {r.INITIAL_HTML.h1 || '—'} · canonical: {r.INITIAL_HTML.canonical ? 'sì' : 'no'} · JSON-LD: {(r.INITIAL_HTML.jsonld || []).join(',') || '—'}</div></div>
                        <div><span className="caps-label text-muted-foreground">Rendered DOM</span><div>title: {r.RENDERED_DOM.title || '—'}</div><div>h1: {r.RENDERED_DOM.h1 || '—'} · canonical: {r.RENDERED_DOM.canonical ? 'sì' : 'no'} · JSON-LD: {(r.RENDERED_DOM.jsonld || []).join(',') || '—'} · {r.RENDERED_DOM.text_len} car. · {r.RENDERED_DOM.links} link</div></div>
                        <div><span className="caps-label text-muted-foreground">Google Inspection</span><div>{r.GOOGLE_INSPECTION.state}{r.GOOGLE_INSPECTION.coverage ? ` · ${r.GOOGLE_INSPECTION.coverage}` : ''}</div></div>
                      </div>
                      <div className="text-[11px] text-muted-foreground/70 font-mono mt-1">{(r.issues || []).join(' · ')}</div></div>
                  </Row>)) : <Empty text="Nessuna pagina renderizzata: esegui l'audit tecnico." />}
              </>
            )}

            {tab === 'adult' && (
              <>
                {(data.findings || []).map((f, i) => <Row key={i} testid="seo-ap-adult-finding"><Pill label={f.severity} color={SEV[f.severity]} /><div className="flex-1 min-w-[240px]"><div className="font-mono text-xs">{f.code}</div><div className="text-xs text-muted-foreground">{f.detail}</div></div></Row>)}
                {!!(data.recommendations?.length) && <div className="mt-4"><div className="caps-label text-muted-foreground mb-2">Raccomandazioni (nessuna applicata)</div>{data.recommendations.map((r, i) => <div key={i} className="text-xs text-muted-foreground flex gap-2 py-1"><Sparkles className="h-3.5 w-3.5 shrink-0" style={{ color: C.gold }} />{r}</div>)}</div>}
                {!data.findings?.length && <Empty text={data.note || 'Nessun audit adult eseguito.'} />}
              </>
            )}

            {tab === 'log' && (data.items?.length ? data.items.map((l) => (
              <Row key={l.id} testid="seo-ap-log-item">
                <span className="text-xs text-muted-foreground w-24 shrink-0">{fmt(l.timestamp)}</span><Pill label={l.kind} /><Pill label={l.result} color={l.result === 'ERROR' || l.result === 'FAIL' || l.result === 'BLOCKED' ? C.fail : l.result === 'PASS' ? C.ok : C.muted} />{l.source === 'LLM_SUGGESTION' && <Pill label="LLM_SUGGESTION" color={C.info} />}
                <div className="flex-1 min-w-[240px]"><div className="font-mono text-xs">{l.action} → {l.target}</div><div className="text-xs text-muted-foreground">{l.reason}</div></div>
              </Row>)) : <Empty text="Nessuna decisione registrata." />)}
          </>
        )}
      </SectionCard>

      <div className="text-[11px] text-muted-foreground flex items-center gap-2" data-testid="seo-ap-footer"><Eye className="h-3.5 w-3.5" /> Base analizzata: <span className="font-mono">{s?.crawl_base_url}</span> · Le impression Search Console sono del sito, non volumi di ricerca globali · <Globe2 className="h-3.5 w-3.5" /> proprietà GSC: <span className="font-mono">{s?.gsc?.property}</span></div>
    </div>
  );
}
