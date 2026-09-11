import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { Cpu, Search, ShieldCheck, ShieldAlert, ShieldOff, Loader2, Power, KeyRound, Bot, AlertTriangle, RotateCcw, Save } from 'lucide-react';
import { aiCapabilitiesAdmin, aiCapabilityToggle, v1KeyCapabilities } from '@/lib/adminApi';
import { SectionCard, Btn, TextInput, SelectInput } from '@/pages/admin/ui';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', muted: 'hsl(var(--muted-foreground))', ai: 'hsl(275 50% 62%)' };
const RISK = { SAFE: { label: 'SAFE', color: C.ok, Icon: ShieldCheck }, REVIEW_REQUIRED: { label: 'REVIEW', color: C.warn, Icon: ShieldAlert }, CRITICAL: { label: 'CRITICAL', color: C.fail, Icon: ShieldOff } };
const CAT_LABEL = { models: 'Modelle', media: 'Media', homepage: 'Home', filmstrip: 'FilmStrip', settings: 'Impostazioni', categories: 'Categorie', seo: 'SEO', landing: 'Landing', alerts: 'Alert', jobs: 'Job', backup: 'Backup', system: 'Sistema', rollback: 'Rollback', workflow: 'Workflow', admins: 'Admin' };

function Pill({ label, color, testid, title }) {
  return <span className="caps-label px-2 py-0.5 rounded-full text-[10px] whitespace-nowrap" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }} data-testid={testid} title={title}>{label}</span>;
}
function fmt(ts) { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } }
function Kpi({ label, value, sub, color, testid }) {
  return (
    <div className="rounded-xl border border-border/60 p-3" data-testid={testid}>
      <div className="caps-label text-muted-foreground text-[10px]">{label}</div>
      <div className="font-serif text-2xl" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function KeyPolicyRow({ k, onSave, busy }) {
  const [allow, setAllow] = useState((k.capability_allow || []).join(', '));
  const [deny, setDeny] = useState((k.capability_deny || []).join(', '));
  const dirty = allow !== (k.capability_allow || []).join(', ') || deny !== (k.capability_deny || []).join(', ');
  const parse = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
  return (
    <div className="rounded-xl border border-border/60 p-3 text-xs space-y-2" data-testid={`key-policy-${k.id}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <KeyRound className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="font-medium">{k.name}</span>
        <code className="text-muted-foreground">{k.prefix}…</code>
        <Pill label={k.role} color={k.role === 'AI_OPERATOR' ? C.ai : C.muted} />
        <Pill label={k.active ? 'attiva' : 'disattivata'} color={k.active ? C.ok : C.fail} />
        {!(k.capability_allow || []).length && !(k.capability_deny || []).length && <span className="text-muted-foreground">nessuna restrizione per capability (valgono solo gli scope)</span>}
      </div>
      <div className="grid sm:grid-cols-2 gap-2">
        <label className="block"><span className="caps-label text-[10px] text-muted-foreground">Allow (vuoto = tutte quelle permesse dagli scope) — es. models.*, seo.audit</span>
          <TextInput value={allow} onChange={(e) => setAllow(e.target.value)} placeholder="models.*, media.*" data-testid={`key-allow-${k.id}`} /></label>
        <label className="block"><span className="caps-label text-[10px] text-muted-foreground">Deny (prevale sempre) — es. models.publish</span>
          <TextInput value={deny} onChange={(e) => setDeny(e.target.value)} placeholder="models.publish, media.soft_delete" data-testid={`key-deny-${k.id}`} /></label>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-muted-foreground">Deny &gt; Allow &gt; Scope. L'allow-list restringe soltanto: non concede mai capability fuori dagli scope della chiave.</span>
        <Btn variant="ghost" disabled={!dirty || busy} onClick={() => onSave(k.id, allow.trim() ? parse(allow) : null, parse(deny))} data-testid={`key-policy-save-${k.id}`}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Salva policy</Btn>
      </div>
    </div>
  );
}

export function CapabilitiesPanel() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);
  const [q, setQ] = useState('');
  const [cat, setCat] = useState('');
  const [risk, setRisk] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(() => aiCapabilitiesAdmin().then((r) => { setD(r); setErr(null); }).catch(() => setErr('Impossibile caricare il registry delle capability')), []);
  useEffect(() => { load(); }, [load]);

  const items = useMemo(() => (d?.items || []).filter((c) =>
    (!cat || c.category === cat) && (!risk || c.risk === risk) &&
    (!q || (c.id + ' ' + c.description + ' ' + (c.natural_references || []).join(' ')).toLowerCase().includes(q.toLowerCase()))), [d, q, cat, risk]);

  // stable, sorted option list: the <select> keeps the same option nodes across reloads (no DOM detach on reset)
  const categoryOptions = useMemo(() => Object.entries(d?.by_category || {}).sort(([a], [b]) => a.localeCompare(b)), [d]);

  const toggle = async (c) => {
    if (c.status !== 'BOUND') return;
    if (!c.disabled && !window.confirm(`Disattivare la capability "${c.id}"? ChatGPT non potrà più eseguirla (né in anteprima) finché non la riattivi.`)) return;
    setBusy(c.id);
    try { await aiCapabilityToggle(c.id, !c.disabled); toast.success(c.disabled ? `${c.id} riattivata` : `${c.id} disattivata`); await load(); }
    catch (e) { toast.error(e?.response?.data?.detail?.message || 'Operazione fallita'); }
    finally { setBusy(''); }
  };
  const savePolicy = async (id, allow, deny) => {
    setBusy(`key-${id}`);
    try { await v1KeyCapabilities(id, allow, deny); toast.success('Policy chiave aggiornata'); await load(); }
    catch (e) { toast.error(e?.response?.data?.detail?.message || 'Pattern non validi'); }
    finally { setBusy(''); }
  };

  if (err) return <SectionCard title="Capacità ChatGPT"><div className="text-sm flex items-center gap-2" style={{ color: C.fail }} data-testid="capabilities-error"><AlertTriangle className="h-4 w-4" /> {err} <Btn variant="ghost" onClick={load}><RotateCcw className="h-4 w-4" /> Riprova</Btn></div></SectionCard>;
  if (!d) return <SectionCard title="Capacità ChatGPT"><div className="grid sm:grid-cols-4 gap-3" data-testid="capabilities-loading">{[0, 1, 2, 3].map((i) => <div key={i} className="h-20 rounded-xl border border-border/40 animate-pulse bg-muted/30" />)}</div></SectionCard>;

  const byRisk = d.by_risk || {};
  return (
    <div data-testid="capabilities-panel">
      <SectionCard title="Capacità ChatGPT · motore universale v2" desc={`Registry allowlisted verificato allo startup. Modalità attuale: ${d.mode}. Le capability UNBOUND o CRITICAL non sono mai eseguibili via API.`}>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
          <Kpi label="Totale" value={d.total} sub={`${Object.keys(d.by_category || {}).length} categorie`} testid="cap-kpi-total" />
          <Kpi label="Bound / Unbound" value={`${d.bound} / ${(d.unbound || []).length}`} color={(d.unbound || []).length ? C.fail : C.ok} sub={(d.unbound || []).length ? d.unbound.slice(0, 2).join(', ') : 'tutti i binding validi'} testid="cap-kpi-bound" />
          <Kpi label="Attive / Disattivate" value={`${d.enabled} / ${d.disabled}`} color={d.disabled ? C.warn : undefined} testid="cap-kpi-enabled" />
          <Kpi label="SAFE" value={byRisk.SAFE ?? 0} color={C.ok} testid="cap-kpi-safe" />
          <Kpi label="REVIEW" value={byRisk.REVIEW_REQUIRED ?? 0} color={C.warn} sub="anteprima + approvazione" testid="cap-kpi-review" />
          <Kpi label="CRITICAL" value={byRisk.CRITICAL ?? 0} color={C.fail} sub="mai via API" testid="cap-kpi-critical" />
          <Kpi label="Modalità" value={d.mode} color={d.mode === 'FULL' ? C.warn : C.ok} sub={d.mode === 'FULL' ? 'modifiche reali attive' : 'solo letture e anteprime'} testid="cap-kpi-mode" />
        </div>

        <div className="flex flex-wrap items-center gap-2 mb-3">
          <div className="relative flex-1 min-w-[200px]"><Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><TextInput value={q} onChange={(e) => setQ(e.target.value)} placeholder="Cerca capability (id, descrizione, frase naturale)…" className="pl-9" data-testid="cap-search" /></div>
          <SelectInput value={cat} onChange={(e) => setCat(e.target.value)} className="!w-auto text-xs py-2" data-testid="cap-filter-category">
            <option value="">Tutte le categorie</option>
            {categoryOptions.map(([k, n]) => <option key={k} value={k}>{CAT_LABEL[k] || k} ({n})</option>)}
          </SelectInput>
          <SelectInput value={risk} onChange={(e) => setRisk(e.target.value)} className="!w-auto text-xs py-2" data-testid="cap-filter-risk">
            <option value="">Tutti i rischi</option><option value="SAFE">SAFE</option><option value="REVIEW_REQUIRED">REVIEW</option><option value="CRITICAL">CRITICAL</option>
          </SelectInput>
          <span className="text-xs text-muted-foreground" data-testid="cap-count">{items.length} capability</span>
        </div>

        <div className="space-y-1.5 max-h-[520px] overflow-auto pr-1" data-testid="cap-list">
          {items.map((c) => {
            const R = RISK[c.risk] || RISK.SAFE;
            const off = c.disabled || c.status !== 'BOUND';
            return (
              <div key={c.id} className={`grid sm:grid-cols-[1fr_auto] gap-2 items-center rounded-xl border px-3 py-2 text-sm ${off ? 'border-border/40 opacity-70' : 'border-border/60'}`} data-testid={`cap-row-${c.id}`}>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <Cpu className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                    <code className="font-medium">{c.id}</code>
                    <span className="text-[10px] text-muted-foreground">v{c.capability_version}</span>
                    <Pill label={R.label} color={R.color} testid={`cap-risk-${c.id}`} />
                    <Pill label={CAT_LABEL[c.category] || c.category} color={C.muted} />
                    {c.read_only && <Pill label="lettura" color={C.muted} />}
                    {c.supports_dry_run && <Pill label="dry-run" color={C.ai} />}
                    {c.supports_rollback && <Pill label="rollback" color={C.ai} />}
                    {c.status !== 'BOUND' && <Pill label={c.status} color={C.fail} title={c.status_reason || ''} testid={`cap-status-${c.id}`} />}
                    {c.disabled && <Pill label="DISATTIVATA" color={C.warn} testid={`cap-disabled-${c.id}`} />}
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5 truncate" title={c.description}>{c.description}</div>
                  <div className="text-[10px] text-muted-foreground/70 mt-0.5">scope: {(c.required_scopes || []).join(', ')} · usi {c.usage?.count ?? 0} · errori {c.usage?.errors ?? 0}{c.status_reason && c.status !== 'BOUND' ? ` · ${c.status_reason}` : ''}</div>
                </div>
                <div className="flex items-center gap-2 justify-end">
                  {c.risk === 'CRITICAL' ? <span className="text-[11px]" style={{ color: C.fail }}>solo pannello admin</span>
                    : c.status !== 'BOUND' ? <span className="text-[11px]" style={{ color: C.fail }}>non eseguibile</span>
                      : <button onClick={() => toggle(c)} disabled={busy === c.id} className="inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors hover:border-primary/50" style={{ borderColor: (c.disabled ? C.fail : C.ok).replace(')', ' / 0.5)'), color: c.disabled ? C.fail : C.ok }} aria-pressed={!c.disabled} data-testid={`cap-toggle-${c.id}`}>
                        {busy === c.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Power className="h-3.5 w-3.5" />} {c.disabled ? 'Riattiva' : 'Attiva'}
                      </button>}
                </div>
              </div>
            );
          })}
          {!items.length && <div className="text-sm text-muted-foreground py-6 text-center" data-testid="cap-empty">Nessuna capability corrisponde ai filtri.</div>}
        </div>
      </SectionCard>

      <div className="grid lg:grid-cols-2 gap-5">
        <SectionCard title="Policy per chiave (allow / deny)" desc="Restrizioni per singola chiave API oltre agli scope. Deny prevale sempre; allow restringe soltanto.">
          <div className="space-y-2" data-testid="cap-key-policies">
            {(d.keys || []).map((k) => <KeyPolicyRow key={k.id} k={k} onSave={savePolicy} busy={busy === `key-${k.id}`} />)}
            {!(d.keys || []).length && <div className="text-sm text-muted-foreground">Nessuna chiave API attiva.</div>}
          </div>
        </SectionCard>

        <SectionCard title="Ultime esecuzioni via motore v2" desc="Azioni eseguite dal dispatcher (letture, anteprime e modifiche). Gli errori sono evidenziati.">
          {!!(d.recent_errors || []).length && (
            <div className="mb-3 rounded-xl border p-2.5 text-xs" style={{ borderColor: C.fail.replace(')', ' / 0.4)') }} data-testid="cap-recent-errors">
              <div className="flex items-center gap-2 mb-1" style={{ color: C.fail }}><AlertTriangle className="h-3.5 w-3.5" /> {d.recent_errors.length} errori recenti</div>
              {d.recent_errors.slice(0, 5).map((e) => <div key={e.id} className="truncate text-muted-foreground">{fmt(e.timestamp)} · <code>{e.action}</code> — {e.summary}</div>)}
            </div>
          )}
          <div className="space-y-1.5 max-h-[400px] overflow-auto pr-1" data-testid="cap-recent">
            {(d.recent || []).map((a) => (
              <div key={a.id} className="grid sm:grid-cols-[95px_1fr_auto] gap-2 text-xs border-b border-border/40 pb-1.5 last:border-0">
                <span className="text-muted-foreground">{fmt(a.timestamp)}</span>
                <span className="min-w-0"><span className="inline-flex items-center gap-1.5 flex-wrap"><Bot className="h-3 w-3 text-muted-foreground" /><code className="font-medium">{a.action}</code>{a.dry_run && <Pill label="dry-run" color={C.ai} />}<Pill label={a.ok ? 'ok' : 'errore'} color={a.ok ? C.ok : C.fail} />{a.target?.nome && <span className="text-muted-foreground">→ {a.target.nome}</span>}</span><div className="text-muted-foreground truncate">{a.summary}</div></span>
                <span className="text-right text-muted-foreground/70 whitespace-nowrap">{a.duration_ms != null ? `${a.duration_ms} ms` : ''}{a.rollback_ref ? ' · rollback' : ''}</span>
              </div>
            ))}
            {!(d.recent || []).length && <div className="text-sm text-muted-foreground">Nessuna esecuzione via motore v2 ancora.</div>}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
