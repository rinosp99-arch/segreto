import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Activity, ShieldCheck, Globe2, MousePointerClick, TrendingUp, AlertTriangle, Wrench, Bot, Cog, KeyRound,
  Play, RotateCcw, Check, Loader2, RefreshCw, ExternalLink, Database, Copy, Cpu,
} from 'lucide-react';
import {
  v1Dashboard, v1HealthRun, v1SeoAudit, v1SeoFixAll, v1SeoIssues, v1SeoFix, v1SeoIgnore, v1Rollback, v1JobRun, v1AlertAck, v1AlertResolve,
  v1Keys, v1CreateKey, v1RevokeKey, v1Backup,
} from '@/lib/adminApi';
import { SectionCard, Btn, TextInput, SelectInput, Field } from '@/pages/admin/ui';
import { ChatGptPanel } from '@/pages/admin/ChatGptPanel';
import { CapabilitiesPanel } from '@/pages/admin/CapabilitiesPanel';

const RANGES = [{ k: 'oggi', l: 'Oggi' }, { k: '7g', l: '7 giorni' }, { k: '30g', l: '30 giorni' }];
const STATUS_COLOR = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', unknown: 'hsl(var(--muted-foreground))', critical: 'hsl(0 60% 58%)', warning: 'hsl(38 75% 60%)', info: 'hsl(200 50% 60%)' };
const SEV = { SAFE_AUTO_FIX: { l: 'SAFE', c: 'hsl(150 45% 58%)' }, REVIEW_REQUIRED: { l: 'REVIEW', c: 'hsl(38 75% 60%)' }, CRITICAL: { l: 'CRITICAL', c: 'hsl(0 60% 58%)' } };
const ROLES = ['AI_OPERATOR', 'SEO_MANAGER', 'CONTENT_MANAGER', 'ANALYST', 'READ_ONLY', 'ADMIN', 'SUPER_ADMIN'];

function Pill({ label, color, testid }) {
  return <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }} data-testid={testid}>{label}</span>;
}

function Kpi({ icon: Icon, label, value, suffix = '', sub, testid }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 caps-label text-muted-foreground mb-2"><Icon className="h-4 w-4" />{label}</div>
      <div className="text-3xl font-serif">{value ?? '—'}{suffix}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}

function fmt(ts) { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } }

export default function AdminMotore() {
  const [range, setRange] = useState('7g');
  const [d, setD] = useState(null);
  const [issues, setIssues] = useState([]);
  const [busy, setBusy] = useState('');
  const [keys, setKeys] = useState([]);
  const [newKey, setNewKey] = useState({ name: '', role: 'AI_OPERATOR' });
  const [created, setCreated] = useState(null);

  const load = useCallback(async () => {
    try {
      const [dash, iss] = await Promise.all([v1Dashboard(range), v1SeoIssues({ status: 'open', limit: 60 })]);
      setD(dash); setIssues(iss.items || []);
    } catch (e) { toast.error('Impossibile caricare il Motore API'); }
  }, [range]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { v1Keys().then((r) => setKeys(r.items || [])).catch(() => {}); }, []);

  const run = async (key, fn, okMsg) => {
    setBusy(key);
    try { const r = await fn(); toast.success(typeof okMsg === 'function' ? okMsg(r) : okMsg); await load(); return r; }
    catch (e) { toast.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || 'Operazione fallita'); }
    finally { setBusy(''); }
  };

  const createKey = async () => {
    if (!newKey.name.trim()) return toast.error('Dai un nome alla chiave');
    setBusy('key');
    try { const r = await v1CreateKey({ name: newKey.name.trim(), role: newKey.role }); setCreated(r); setNewKey({ name: '', role: 'AI_OPERATOR' }); v1Keys().then((x) => setKeys(x.items || [])); toast.success('API key creata: copiala ora, non sarà più visibile'); }
    catch (e) { toast.error(e?.response?.data?.detail?.message || 'Errore creazione chiave'); }
    finally { setBusy(''); }
  };

  const api = d?.api_status || {};
  const traffic = d?.traffic?.steps || [];
  const it = d?.italian_traffic;
  const docsUrl = `${process.env.REACT_APP_BACKEND_URL}/api/docs`;

  return (
    <div data-testid="admin-motore-page">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl">Motore API</h1>
          <p className="text-xs text-muted-foreground mt-1">SUPER API v1 · gestione, SEO Autopilot, self-healing, Italy Engine, AI control.</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex gap-1 bg-card border border-border/60 rounded-full p-1">
            {RANGES.map((r) => <button key={r.k} onClick={() => setRange(r.k)} className={`px-3 py-1.5 text-xs rounded-full transition-colors ${range === r.k ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`} data-testid={`motore-range-${r.k}`}>{r.l}</button>)}
          </div>
          <Btn variant="ghost" onClick={load} data-testid="motore-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <a href={docsUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm border border-border text-muted-foreground hover:text-foreground" data-testid="motore-docs-link"><ExternalLink className="h-4 w-4" /> OpenAPI</a>
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        <Kpi icon={Activity} label="API status" value={api.api === 'online' ? 'Online' : 'Offline'} sub={`DB ${api.database ? 'ok' : 'KO'} · health ${api.health || 'n/d'} · ${api.events_24h ?? 0} eventi 24h`} testid="kpi-api-status" />
        <Kpi icon={ShieldCheck} label="SEO health" value={d?.seo_health?.score} suffix="/100" sub={`SAFE ${d?.seo_issues?.SAFE_AUTO_FIX ?? 0} · REVIEW ${d?.seo_issues?.REVIEW_REQUIRED ?? 0} · CRITICAL ${d?.seo_issues?.CRITICAL ?? 0}`} testid="kpi-seo-health" />
        <Kpi icon={TrendingUp} label="Traffico" value={traffic[1]?.value} sub={`${traffic[0]?.value ?? 0} sessioni · ${traffic[2]?.value ?? 0} Lati Segreti`} testid="kpi-traffic" />
        <Kpi icon={Globe2} label="Traffico italiano" value={it?.share} suffix="%" sub={`${it?.steps?.[1]?.value ?? 0} profili visti dall'Italia`} testid="kpi-italian-traffic" />
        <Kpi icon={MousePointerClick} label="Click OnlyFans" value={d?.onlyfans_clicks} sub={`CTA viste ${traffic[3]?.value ?? 0}`} testid="kpi-of-clicks" />
        <Kpi icon={TrendingUp} label="Conversion rate" value={d?.conversion_rate} suffix="%" sub="click OnlyFans / profili visti" testid="kpi-conversion" />
        <Kpi icon={Wrench} label="Auto fix (7g)" value={d?.auto_fixes?.count_7d} sub="fix SEO sicuri, tutti reversibili" testid="kpi-autofixes" />
        <Kpi icon={AlertTriangle} label="Alert aperti" value={d?.alerts?.length} sub={Object.entries(d?.models_by_status || {}).map(([k, v]) => `${k} ${v}`).join(' · ')} testid="kpi-alerts" />
      </div>

      {/* Actions */}
      <SectionCard title="Azioni rapide" desc="Ogni azione è tracciata (audit + versioni). I fix SEO applicano solo le issue SAFE.">
        <div className="flex flex-wrap gap-2">
          <Btn onClick={() => run('health', v1HealthRun, (r) => `Health check: ${r.overall}`)} disabled={!!busy} data-testid="motore-run-health">{busy === 'health' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Activity className="h-4 w-4" />} Esegui health check</Btn>
          <Btn variant="ghost" onClick={() => run('audit', v1SeoAudit, (r) => `Audit SEO: ${r.total} issue, score ${r.health_score}`)} disabled={!!busy} data-testid="motore-run-audit">{busy === 'audit' ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />} Audit SEO</Btn>
          <Btn variant="ghost" onClick={() => run('fixall', () => v1SeoFixAll(false), (r) => `Applicati ${r.applied} fix sicuri`)} disabled={!!busy} data-testid="motore-fix-all">{busy === 'fixall' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />} Applica fix SEO sicuri</Btn>
          <Btn variant="ghost" onClick={() => run('backup', v1Backup, (r) => `Backup creato (${Math.round(r.size / 1024)} KB)`)} disabled={!!busy} data-testid="motore-backup">{busy === 'backup' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />} Backup ora</Btn>
        </div>
      </SectionCard>

      {/* Phase 10 - ChatGPT control layer */}
      <div className="mb-5" data-testid="chatgpt-section">
        <div className="flex items-center gap-2 mb-3"><Bot className="h-5 w-5 text-muted-foreground" /><h2 className="font-serif text-2xl">ChatGPT Control Layer</h2></div>
        <ChatGptPanel />
      </div>

      {/* Phase 12A - universal engine v2: capability governance */}
      <div className="mb-5" data-testid="capabilities-section">
        <div className="flex items-center gap-2 mb-3"><Cpu className="h-5 w-5 text-muted-foreground" /><h2 className="font-serif text-2xl">Capacità ChatGPT</h2></div>
        <CapabilitiesPanel />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Health checks */}
        <SectionCard title="Self-healing · controlli" desc={api.health_at ? `Ultimo controllo ${fmt(api.health_at)}` : 'Nessun controllo eseguito'}>
          <div className="space-y-2" data-testid="motore-health-checks">
            {(api.checks || []).map((c) => (
              <div key={c.name} className="flex items-start justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="font-medium">{c.name}</div><div className="text-xs text-muted-foreground truncate">{c.detail}</div></div>
                <Pill label={c.status} color={STATUS_COLOR[c.status] || STATUS_COLOR.unknown} />
              </div>
            ))}
            {!(api.checks || []).length && <div className="text-sm text-muted-foreground">Esegui un health check per vedere i risultati.</div>}
          </div>
        </SectionCard>

        {/* Top models */}
        <SectionCard title="Top modelle" desc="Ordinate per click OnlyFans nel periodo">
          <div className="space-y-2" data-testid="motore-top-models">
            {(d?.top_models || []).slice(0, 6).map((m) => (
              <div key={m.id} className="flex items-center gap-3 text-sm">
                <div className="h-9 w-9 rounded-lg overflow-hidden bg-muted/40 shrink-0">{m.foto_card && <img src={m.foto_card} alt="" className="h-full w-full object-cover" />}</div>
                <div className="flex-1 min-w-0"><div className="truncate">{m.nome_artistico}</div><div className="text-[11px] text-muted-foreground">{m.visits} visite · IT {m.italian_share}% · attivazione {m.activation_rate}%</div></div>
                <div className="text-right"><div className="font-serif text-lg">{m.onlyfans_clicks}</div><div className="text-[10px] text-muted-foreground">{m.conversion_rate}% conv.</div></div>
              </div>
            ))}
            {!(d?.top_models || []).length && <div className="text-sm text-muted-foreground">Nessun dato nel periodo.</div>}
          </div>
        </SectionCard>

        {/* SEO issues */}
        <SectionCard title="SEO issues" desc="SAFE = correggibili in automatico · REVIEW = conferma umana · CRITICAL = mai automatico">
          <div className="space-y-2 max-h-[420px] overflow-auto pr-1" data-testid="motore-seo-issues">
            {issues.map((i) => (
              <div key={i.id} className="flex items-start justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0">
                  <div className="flex items-center gap-2"><Pill label={SEV[i.severity]?.l || i.severity} color={SEV[i.severity]?.c || STATUS_COLOR.unknown} /><span className="text-xs text-muted-foreground">{i.entity_type} · {i.entity_label}</span></div>
                  <div className="mt-1">{i.message}</div>
                  {i.suggested_value != null && <div className="text-[11px] text-muted-foreground truncate">Suggerito: {typeof i.suggested_value === 'string' ? i.suggested_value : JSON.stringify(i.suggested_value)}</div>}
                </div>
                <div className="flex gap-1 shrink-0">
                  {i.severity !== 'CRITICAL' && (i.fix || i.suggested_value != null) && (
                    <button onClick={() => run(`fix-${i.id}`, () => v1SeoFix(i.id, i.severity === 'REVIEW_REQUIRED'), 'Fix applicato')} className="h-8 w-8 rounded-lg border border-border flex items-center justify-center hover:border-primary/60" title="Applica" data-testid={`seo-fix-${i.code}`}><Check className="h-4 w-4" /></button>
                  )}
                  <button onClick={() => run(`ign-${i.id}`, () => v1SeoIgnore(i.id), 'Issue ignorata')} className="h-8 px-2 rounded-lg border border-border text-[11px] text-muted-foreground hover:text-foreground" data-testid={`seo-ignore-${i.code}`}>Ignora</button>
                </div>
              </div>
            ))}
            {!issues.length && <div className="text-sm text-muted-foreground">Nessuna issue aperta. Esegui un audit per aggiornare.</div>}
          </div>
        </SectionCard>

        {/* Alerts */}
        <SectionCard title="Alert" desc="Problemi importanti che richiedono revisione">
          <div className="space-y-2" data-testid="motore-alerts">
            {(d?.alerts || []).map((a) => (
              <div key={a.id} className="flex items-start justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="flex items-center gap-2"><Pill label={a.severity} color={STATUS_COLOR[a.severity] || STATUS_COLOR.unknown} /><span className="font-medium truncate">{a.titolo}</span></div><div className="text-xs text-muted-foreground mt-1">{a.messaggio}</div><div className="text-[10px] text-muted-foreground/70">{fmt(a.created_at)} · {a.stato}</div></div>
                <div className="flex gap-1 shrink-0">
                  {a.stato === 'open' && <button onClick={() => run(`ack-${a.id}`, () => v1AlertAck(a.id), 'Alert preso in carico')} className="h-8 px-2 rounded-lg border border-border text-[11px]" data-testid="alert-ack">Presa visione</button>}
                  <button onClick={() => run(`res-${a.id}`, () => v1AlertResolve(a.id), 'Alert risolto')} className="h-8 px-2 rounded-lg border border-border text-[11px]" data-testid="alert-resolve">Risolto</button>
                </div>
              </div>
            ))}
            {!(d?.alerts || []).length && <div className="text-sm text-muted-foreground">Nessun alert aperto.</div>}
          </div>
        </SectionCard>

        {/* Rollback */}
        <SectionCard title="Versioni & rollback" desc="Ogni modifica importante salva before/after. Il rollback crea una nuova versione (mai distruttivo).">
          <div className="space-y-2 max-h-[380px] overflow-auto pr-1" data-testid="motore-versions">
            {(d?.rollback?.recent_versions || []).map((v) => (
              <div key={v.id} className="flex items-start justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="flex items-center gap-2 flex-wrap"><Pill label={v.source} color={v.source === 'ai' ? 'hsl(275 50% 62%)' : v.source === 'autofix' ? 'hsl(150 45% 58%)' : v.source === 'rollback' ? 'hsl(38 75% 60%)' : 'hsl(var(--muted-foreground))'} /><span className="text-xs">{v.entity} · {v.operation}</span></div><div className="text-xs text-muted-foreground truncate mt-1">{v.reason} — {(v.changed_fields || []).slice(0, 5).join(', ')}</div><div className="text-[10px] text-muted-foreground/70">{fmt(v.timestamp)} · {v.actor}</div></div>
                {!v.rolled_back && <button onClick={() => run(`rb-${v.id}`, () => v1Rollback(v.id, 'Rollback da pannello'), 'Rollback eseguito')} className="h-8 px-2 rounded-lg border border-border text-[11px] inline-flex items-center gap-1 hover:border-primary/60" data-testid="version-rollback"><RotateCcw className="h-3.5 w-3.5" /> Rollback</button>}
                {v.rolled_back && <span className="text-[10px] text-muted-foreground">annullata</span>}
              </div>
            ))}
          </div>
        </SectionCard>

        {/* AI actions */}
        <SectionCard title="Azioni AI" desc="Operazioni eseguite tramite gli endpoint /api/v1/ai">
          <div className="space-y-2 max-h-[380px] overflow-auto pr-1" data-testid="motore-ai-actions">
            {(d?.ai_actions || []).map((a) => (
              <div key={a.id} className="text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="flex items-center gap-2"><Bot className="h-4 w-4 text-muted-foreground" /><span className="font-medium">{a.action}</span><Pill label={a.ok ? 'ok' : 'errore'} color={a.ok ? STATUS_COLOR.ok : STATUS_COLOR.fail} /></div>
                <div className="text-xs text-muted-foreground mt-1">{a.summary}</div>
                <div className="text-[10px] text-muted-foreground/70">{fmt(a.timestamp)} · {a.actor}</div>
              </div>
            ))}
            {!(d?.ai_actions || []).length && <div className="text-sm text-muted-foreground">Nessuna azione AI ancora. Crea una API key AI_OPERATOR qui sotto e collega ChatGPT.</div>}
          </div>
        </SectionCard>

        {/* Jobs */}
        <SectionCard title="Background jobs" desc="Scheduler interno. Puoi lanciare un job manualmente.">
          <div className="space-y-2" data-testid="motore-jobs">
            {(d?.background_jobs || []).map((j) => (
              <div key={j.name} className="flex items-center justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="font-medium">{j.name}</div><div className="text-[11px] text-muted-foreground truncate">{j.description} · ogni {Math.round(j.interval_s / 60)} min · ultimo {fmt(j.last_run)}</div></div>
                <div className="flex items-center gap-2 shrink-0">
                  <Pill label={j.last_status || 'mai'} color={j.last_status === 'ok' ? STATUS_COLOR.ok : j.last_status === 'error' ? STATUS_COLOR.fail : STATUS_COLOR.unknown} />
                  <button onClick={() => run(`job-${j.name}`, () => v1JobRun(j.name), (r) => `${j.name}: ${r.status}`)} disabled={!!busy} className="h-8 w-8 rounded-lg border border-border flex items-center justify-center hover:border-primary/60" title="Esegui" data-testid={`job-run-${j.name}`}>{busy === `job-${j.name}` ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}</button>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>

        {/* API keys */}
        <SectionCard title="API keys (ChatGPT / integrazioni)" desc="Header X-API-Key. Il ruolo AI_OPERATOR può gestire modelle, media, SEO e leggere analytics; non può toccare chiavi, utenti o backup.">
          <div className="grid sm:grid-cols-[1fr_170px_auto] gap-2 items-end mb-3">
            <Field label="Nome"><TextInput value={newKey.name} onChange={(e) => setNewKey({ ...newKey, name: e.target.value })} placeholder="es. chatgpt-operatore" data-testid="apikey-name" /></Field>
            <Field label="Ruolo"><SelectInput value={newKey.role} onChange={(e) => setNewKey({ ...newKey, role: e.target.value })} data-testid="apikey-role">{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</SelectInput></Field>
            <Btn onClick={createKey} disabled={busy === 'key'} className="mb-4" data-testid="apikey-create">{busy === 'key' ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} Crea</Btn>
          </div>
          {created && (
            <div className="rounded-xl border border-primary/40 bg-primary/10 p-3 mb-3 text-sm" data-testid="apikey-created">
              <div className="caps-label text-muted-foreground mb-1">Chiave creata — copiala ora</div>
              <div className="flex items-center gap-2"><code className="text-xs break-all flex-1">{created.api_key}</code><button onClick={() => { navigator.clipboard?.writeText(created.api_key); toast.success('Copiata'); }} className="h-8 w-8 rounded-lg border border-border flex items-center justify-center" data-testid="apikey-copy"><Copy className="h-4 w-4" /></button></div>
            </div>
          )}
          <div className="space-y-2" data-testid="apikey-list">
            {keys.map((k) => (
              <div key={k.id} className="flex items-center justify-between gap-3 text-sm border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="font-medium truncate">{k.name} <span className="text-[11px] text-muted-foreground">{k.prefix}…</span></div><div className="text-[11px] text-muted-foreground">{k.role} · {k.uses || 0} usi · ultimo {fmt(k.last_used_at)}</div></div>
                {k.active ? <button onClick={() => run(`rk-${k.id}`, async () => { await v1RevokeKey(k.id); v1Keys().then((x) => setKeys(x.items || [])); }, 'Chiave revocata')} className="h-8 px-2 rounded-lg border text-[11px] text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.5)' }} data-testid="apikey-revoke">Revoca</button> : <span className="text-[10px] text-muted-foreground">revocata</span>}
              </div>
            ))}
            {!keys.length && <div className="text-sm text-muted-foreground">Nessuna chiave. Creane una per collegare ChatGPT.</div>}
          </div>
          <div className="mt-3 text-[11px] text-muted-foreground flex items-center gap-2"><Cog className="h-3.5 w-3.5" /> Catalogo azioni AI: <code>GET /api/v1/ai/capabilities</code> · Documentazione: <code>/api/docs</code></div>
        </SectionCard>
      </div>
    </div>
  );
}
