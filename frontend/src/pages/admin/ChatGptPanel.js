import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Bot, Copy, PlugZap, Loader2, RotateCcw, Pause, Play, Ban, ShieldAlert, Activity, ClipboardCheck } from 'lucide-react';
import { aiControl, aiControlPatch, aiTestConnection, v1KeyRotate, v1KeyDisable, v1KeyEnable, v1RevokeKey, v1CreateKey } from '@/lib/adminApi';
import { SectionCard, Btn, TextInput } from '@/pages/admin/ui';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', muted: 'hsl(var(--muted-foreground))', ai: 'hsl(275 50% 62%)' };

function Pill({ label, color, testid }) {
  return <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }} data-testid={testid}>{label}</span>;
}
function Toggle({ on, onChange, label, testid, danger }) {
  return (
    <button onClick={() => onChange(!on)} className="flex items-center justify-between w-full rounded-xl border border-border/60 bg-card px-4 py-3 text-sm hover:border-primary/50 transition-colors" data-testid={testid} aria-pressed={on}>
      <span>{label}</span>
      <span className="caps-label text-[10px] px-2.5 py-1 rounded-full" style={{ color: on ? (danger ? C.warn : C.ok) : C.fail, border: `1px solid ${(on ? (danger ? C.warn : C.ok) : C.fail).replace(')', ' / 0.4)')}` }}>{on ? 'ON' : 'OFF'}</span>
    </button>
  );
}
function fmt(ts) { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } }

export function ChatGptPanel() {
  const [c, setC] = useState(null);
  const [busy, setBusy] = useState('');
  const [test, setTest] = useState(null);
  const [created, setCreated] = useState(null);
  const [keyName, setKeyName] = useState('ChatGPT Production');
  const [withPublish, setWithPublish] = useState(false);

  const load = useCallback(() => aiControl().then(setC).catch(() => toast.error('Impossibile caricare il controllo ChatGPT')), []);
  useEffect(() => { load(); }, [load]);

  const patch = async (data) => {
    setBusy('patch');
    try { setC(await aiControlPatch(data)); toast.success('Impostazione aggiornata'); }
    catch (e) { toast.error('Aggiornamento fallito'); }
    finally { setBusy(''); }
  };
  const runTest = async () => {
    setBusy('test'); setTest(null);
    try { const r = await aiTestConnection(); setTest(r); (r.status === 'green' ? toast.success : r.status === 'yellow' ? toast.warning : toast.error)(r.summary); load(); }
    catch (e) { toast.error('Test fallito'); }
    finally { setBusy(''); }
  };
  const keyAction = async (label, fn) => {
    setBusy(label);
    try { const r = await fn(); if (r?.api_key) setCreated(r); toast.success('Operazione eseguita'); load(); }
    catch (e) { toast.error(e?.response?.data?.detail?.message || e?.response?.data?.detail || 'Operazione fallita'); }
    finally { setBusy(''); }
  };
  const createKey = () => keyAction('create', () => v1CreateKey({ name: keyName.trim() || 'ChatGPT Production', role: 'AI_OPERATOR', source: 'chatgpt', scopes: withPublish ? [...(c?.setup?.recommended_scopes || []), 'landing:publish'] : undefined }));

  const setup = c?.setup || {};
  const configText = () => [
    '# LATO SEGRETO — configurazione ChatGPT (senza chiave: inseriscila solo nel campo Authentication di ChatGPT)',
    `Base URL: ${setup.base_url}`,
    `OpenAPI (import in GPT Actions): ${setup.openapi_url}`,
    `Capabilities: ${setup.capabilities_url}`,
    `Docs: ${setup.docs_url}`,
    `Autenticazione: API Key · header "${setup.auth_header}" (alternativa: "${setup.auth_alternative}")`,
    `Ruolo chiave: ${setup.recommended_role}`,
    `Scopes consigliati: ${(setup.recommended_scopes || []).join(', ')}`,
    `Scopes opzionali (da concedere esplicitamente): ${(setup.optional_scopes || []).join(', ')}`,
    'Header consigliati: Idempotency-Key (POST), X-Request-ID (correlazione)',
    'Risposte: {ok, summary, data, warnings, next_steps, request_id, changes, approval_required}',
    'Errori: {ok:false, code, summary} · codici: ' + (setup.error_codes || []).join(', '),
    'Esempi: POST /api/v1/ai/models/find {"model":"Alessia"} · POST /api/v1/ai/models/Alessia/seo/apply-safe-fixes · POST /api/v1/ai/analytics/query {"metric":"onlyfans_ctr","group_by":"model","country":"IT","period":"7d"}',
    'Sicurezza: solo SAFE eseguite direttamente; REVIEW_REQUIRED → token di approvazione (single-use, 30 min); CRITICAL mai; dry_run=true disponibile; publish passa sempre dal validator; rollback sempre disponibile.',
  ].join('\n');
  const copy = (t, msg) => { navigator.clipboard?.writeText(t); toast.success(msg || 'Copiato'); };

  const m = c?.metrics || {};
  const statusColor = { connected: C.ok, never_used: C.warn, no_key: C.warn, disabled: C.fail }[c?.status] || C.muted;
  const statusLabel = { connected: 'Connected', never_used: 'Never used', no_key: 'Nessuna chiave', disabled: 'Disabilitata' }[c?.status] || '—';

  return (
    <div className="grid lg:grid-cols-2 gap-5" data-testid="chatgpt-panel">
      <SectionCard title="ChatGPT API · controllo" desc="Kill switch immediato e modalità. Le API admin tradizionali restano sempre attive.">
        <div className="space-y-2">
          <Toggle on={!!c?.flags?.ai_api_enabled} onChange={(v) => patch({ ai_api_enabled: v })} label="ChatGPT API (kill switch)" testid="ai-kill-switch" />
          <Toggle on={!!c?.flags?.ai_write_enabled} onChange={(v) => patch({ ai_write_enabled: v })} label={`Modalità: ${c?.flags?.ai_write_enabled ? 'FULL (lettura + modifiche)' : 'READ_ONLY (solo lettura, audit, anteprime)'}`} testid="ai-mode-toggle" danger />
          <Toggle on={!!c?.flags?.ai_batch_enabled} onChange={(v) => patch({ ai_batch_enabled: v })} label="Operazioni batch" testid="ai-batch-toggle" />
          <Toggle on={!!c?.flags?.ai_approval_flow_enabled} onChange={(v) => patch({ ai_approval_flow_enabled: v })} label="Flusso approvazioni (REVIEW_REQUIRED)" testid="ai-approval-toggle" />
          <div className="flex items-center justify-between rounded-xl border border-border/60 bg-card px-4 py-3 text-sm">
            <span>Rate limit AI (richieste/min, min 10)</span>
            <div className="flex items-center gap-2">
              <input type="number" min={10} defaultValue={c?.rate_limit_per_min || 120} key={c?.rate_limit_per_min} onBlur={(e) => Number(e.target.value) !== c?.rate_limit_per_min && patch({ rate_limit_per_min: Number(e.target.value) })} className="w-20 bg-input border border-border rounded-lg px-2 py-1 text-sm" data-testid="ai-rate-limit" />
            </div>
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 mt-4 text-sm">
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">Richieste/min</div><div className="font-serif text-xl">{m.last_minute?.requests ?? 0}</div></div>
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">Richieste/ora</div><div className="font-serif text-xl">{m.last_hour?.requests ?? 0}</div></div>
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">Errori/ora · 429</div><div className="font-serif text-xl">{m.last_hour?.errors ?? 0} · {m.last_hour?.rate_limited ?? 0}</div></div>
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">Success rate</div><div className="font-serif text-xl">{m.last_hour?.success_rate ?? '—'}{m.last_hour?.success_rate != null ? '%' : ''}</div></div>
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">p50 / p95</div><div className="font-serif text-xl">{m.last_hour?.p50_ms ?? 0} / {m.last_hour?.p95_ms ?? 0} ms</div></div>
          <div className="rounded-xl border border-border/60 p-3"><div className="caps-label text-muted-foreground text-[10px]">Mutazioni · rollback</div><div className="font-serif text-xl">{m.counters?.mutations ?? 0} · {m.counters?.rollbacks ?? 0}</div></div>
        </div>
        <div className="text-[11px] text-muted-foreground mt-2">Approvazioni richieste {m.counters?.approvals_requested ?? 0} · confermate {m.counters?.approvals_confirmed ?? 0} · azioni critiche bloccate {m.counters?.critical_blocked ?? 0} · ultima richiesta {fmt(m.last_request_at)}</div>
        {!!(m.top_capabilities || []).length && <div className="text-[11px] text-muted-foreground mt-1">Top: {m.top_capabilities.slice(0, 5).map(([k, n]) => `${k} (${n})`).join(' · ')}</div>}
      </SectionCard>

      <SectionCard title="Collega ChatGPT" desc="Dati da inserire in ChatGPT (GPT Actions). La chiave API non viene mai inclusa nella configurazione copiata.">
        <div className="flex items-center gap-2 mb-3"><Pill label={statusLabel} color={statusColor} testid="chatgpt-status" /><span className="text-xs text-muted-foreground">ultima richiesta {fmt(c?.last_request?.timestamp)} · ultimo errore {c?.last_error ? `${fmt(c.last_error.timestamp)} (${c.last_error.action})` : 'nessuno'}</span></div>
        <div className="space-y-1.5 text-xs" data-testid="chatgpt-setup">
          {[['Base URL', setup.base_url], ['OpenAPI URL', setup.openapi_url], ['Capabilities URL', setup.capabilities_url], ['Authentication', `API Key · ${setup.auth_header}`], ['Ruolo consigliato', setup.recommended_role]].map(([k, v]) => (
            <div key={k} className="flex items-center justify-between gap-2 rounded-lg border border-border/50 px-3 py-2"><span className="text-muted-foreground shrink-0">{k}</span><code className="truncate">{v}</code><button onClick={() => copy(v)} className="h-7 w-7 rounded-md border border-border flex items-center justify-center shrink-0" title="Copia"><Copy className="h-3.5 w-3.5" /></button></div>
          ))}
        </div>
        <div className="flex flex-wrap gap-2 mt-3">
          <Btn onClick={() => copy(configText(), 'Configurazione copiata (senza chiave)')} data-testid="chatgpt-copy-config"><ClipboardCheck className="h-4 w-4" /> Copia configurazione ChatGPT</Btn>
          <Btn variant="ghost" onClick={runTest} disabled={busy === 'test'} data-testid="chatgpt-test-connection">{busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test ChatGPT API</Btn>
        </div>
        {test && (
          <div className="mt-3 rounded-xl border p-3 text-sm" style={{ borderColor: (test.status === 'green' ? C.ok : test.status === 'yellow' ? C.warn : C.fail).replace(')', ' / 0.5)') }} data-testid="chatgpt-test-result">
            <div className="flex items-center gap-2 mb-2"><Pill label={test.status === 'green' ? 'TUTTO OK' : test.status === 'yellow' ? 'WARNING' : 'ERRORI'} color={test.status === 'green' ? C.ok : test.status === 'yellow' ? C.warn : C.fail} /><span className="text-xs text-muted-foreground">{test.summary}</span></div>
            <div className="grid sm:grid-cols-2 gap-1">
              {test.results.map((r) => <div key={r.check} className="flex items-start gap-2 text-xs"><span style={{ color: r.ok ? C.ok : r.level === 'error' ? C.fail : C.warn }}>●</span><span><b>{r.check}</b> — {r.detail}</span></div>)}
            </div>
          </div>
        )}
        <div className="mt-4 border-t border-border/50 pt-3">
          <div className="caps-label text-muted-foreground text-[10px] mb-2">Chiave dedicata ChatGPT (ruolo AI_OPERATOR)</div>
          <div className="flex flex-wrap gap-2 items-center">
            <TextInput value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="ChatGPT Production" className="max-w-[220px]" data-testid="chatgpt-key-name" />
            <label className="flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={withPublish} onChange={(e) => setWithPublish(e.target.checked)} data-testid="chatgpt-key-publish-scope" /> concedi landing:publish</label>
            <Btn onClick={createKey} disabled={busy === 'create'} data-testid="chatgpt-create-key">{busy === 'create' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />} Crea chiave ChatGPT</Btn>
          </div>
          {created && (
            <div className="rounded-xl border border-primary/40 bg-primary/10 p-3 mt-3 text-sm" data-testid="chatgpt-key-created">
              <div className="flex items-center justify-between gap-2 mb-1"><div className="caps-label text-muted-foreground">Chiave {created.name} — visibile SOLO ora, non sarà più recuperabile</div><button onClick={() => setCreated(null)} className="text-[11px] text-muted-foreground hover:text-foreground underline" data-testid="chatgpt-key-dismiss">Ho copiato, nascondi</button></div>
              <div className="flex items-center gap-2"><code className="text-xs break-all flex-1" data-testid="chatgpt-key-value">{created.api_key}</code><button onClick={() => copy(created.api_key, 'Chiave copiata')} className="h-8 w-8 rounded-lg border border-border flex items-center justify-center" data-testid="chatgpt-key-copy"><Copy className="h-4 w-4" /></button></div>
              <div className="text-[11px] text-muted-foreground mt-1">Nel database è salvato solo l'hash SHA-256 e il prefisso <code>{created.prefix}</code>. Se la perdi, usa "Ruota" per generarne una nuova.</div>
            </div>
          )}
          <div className="space-y-2 mt-3" data-testid="chatgpt-keys">
            {(c?.keys || []).map((k) => (
              <div key={k.id} className="flex items-center justify-between gap-3 text-xs border-b border-border/40 pb-2 last:border-0">
                <div className="min-w-0"><div className="font-medium truncate">{k.name} <span className="text-muted-foreground">{k.prefix}…</span> <Pill label={k.role} color={k.role === 'AI_OPERATOR' ? C.ai : C.muted} /></div>
                  <div className="text-[11px] text-muted-foreground">{k.request_count || k.uses || 0} richieste · {k.error_count || 0} errori · ultimo uso {fmt(k.last_used_at)} · IP {k.last_ip || '—'} · {k.active ? 'attiva' : 'disattivata'}</div></div>
                <div className="flex gap-1 shrink-0">
                  <button onClick={() => keyAction(`rot-${k.id}`, () => v1KeyRotate(k.id))} className="h-7 w-7 rounded-md border border-border flex items-center justify-center" title="Ruota" data-testid="key-rotate"><RotateCcw className="h-3.5 w-3.5" /></button>
                  {k.active ? <button onClick={() => keyAction(`dis-${k.id}`, () => v1KeyDisable(k.id))} className="h-7 w-7 rounded-md border border-border flex items-center justify-center" title="Disattiva" data-testid="key-disable"><Pause className="h-3.5 w-3.5" /></button>
                    : <button onClick={() => keyAction(`en-${k.id}`, () => v1KeyEnable(k.id))} className="h-7 w-7 rounded-md border border-border flex items-center justify-center" title="Riattiva" data-testid="key-enable"><Play className="h-3.5 w-3.5" /></button>}
                  <button onClick={() => { if (window.confirm(`Revocare definitivamente la chiave "${k.name}"? ChatGPT smetterà di funzionare subito.`)) keyAction(`rev-${k.id}`, () => v1RevokeKey(k.id)); }} className="h-7 w-7 rounded-md border flex items-center justify-center text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.5)' }} title="Revoca" data-testid="key-revoke"><Ban className="h-3.5 w-3.5" /></button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Attività ChatGPT" desc="Ogni operazione: attore, chiave, request_id, target, risultato, modifiche, rollback disponibile." className="lg:col-span-2">
        {!!(c?.pending_approvals || []).length && <div className="mb-3 text-xs flex items-center gap-2"><ShieldAlert className="h-4 w-4" style={{ color: C.warn }} /> {c.pending_approvals.length} approvazioni in attesa: {c.pending_approvals.slice(0, 3).map((p) => `${p.type} → ${p.target?.nome || p.target?.slug}`).join(' · ')}</div>}
        <div className="space-y-2 max-h-[460px] overflow-auto pr-1" data-testid="chatgpt-activity">
          {(c?.activity || []).map((a) => (
            <div key={a.id} className="grid sm:grid-cols-[110px_1fr_auto] gap-2 text-sm border-b border-border/40 pb-2 last:border-0">
              <div className="text-[11px] text-muted-foreground">{fmt(a.timestamp)}<br />{a.duration_ms != null ? `${a.duration_ms} ms` : ''}</div>
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap"><Bot className="h-3.5 w-3.5 text-muted-foreground" /><span className="font-medium">{a.action}</span>{a.target?.nome && <span className="text-xs text-muted-foreground">→ {a.target.nome}</span>}<Pill label={a.ok ? 'ok' : 'errore'} color={a.ok ? C.ok : C.fail} /><Pill label={a.source} color={a.source === 'chatgpt' ? C.ai : C.muted} /></div>
                <div className="text-xs text-muted-foreground mt-0.5">{a.summary}</div>
                {!!(a.changes || []).length && <div className="text-[11px] text-muted-foreground/80 truncate">Modifiche: {a.changes.slice(0, 4).map((ch) => ch.field).join(', ')}</div>}
                <div className="text-[10px] text-muted-foreground/60">{a.actor} · req {String(a.request_id || '').slice(0, 8)}</div>
              </div>
              <div className="text-right text-[11px]">{a.rollback_ref ? <span className="inline-flex items-center gap-1 text-muted-foreground"><RotateCcw className="h-3 w-3" /> rollback disponibile</span> : <span className="text-muted-foreground/50">—</span>}</div>
            </div>
          ))}
          {!(c?.activity || []).length && <div className="text-sm text-muted-foreground flex items-center gap-2"><Activity className="h-4 w-4" /> Nessuna attività ChatGPT ancora.</div>}
        </div>
      </SectionCard>
    </div>
  );
}
