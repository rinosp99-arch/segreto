import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Twitter, Play, Pause, SkipForward, Zap, RefreshCw, Loader2, PlugZap, Clock, Users, Repeat, CheckCircle2, AlertTriangle, Eye, EyeOff, Sparkles, ShieldCheck, Link2, Layers, KeyRound, Unplug, ExternalLink } from 'lucide-react';
import { xApStatus, xApLogs, xApTestConnection, xApStart, xApPause, xApPreview, xApPublishNow, xApSkip, xApSettings, xApConnection, xApAuthStart, xApAuthDisconnect } from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', info: 'hsl(200 50% 60%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };
const STATUS_COLOR = { PUBLISHED: C.ok, MOCK_PREPARED: C.info, FAILED: C.fail, PARTIAL_FAILED: C.warn, SKIPPED_NO_PUBLIC_MEDIA: C.warn, SKIPPED_NO_SECRET_MEDIA: C.warn, SKIPPED_NO_OF_LINK: C.warn, SKIPPED_NOT_X_SAFE: C.warn, MANUAL_SKIP: C.muted, SKIP_DUPLICATE_SLOT: C.info };
const STATUS_LABEL = { MOCK_PREPARED: 'MOCK PREPARATO', PUBLISHED: 'PUBBLICATO', FAILED: 'ERRORE', PARTIAL_FAILED: 'PARZIALE: RISPOSTA SECRET FALLITA', SKIPPED_NO_PUBLIC_MEDIA: 'SALTATA: NO PUBLIC', SKIPPED_NO_SECRET_MEDIA: 'SALTATA: NO SECRET', SKIPPED_NO_OF_LINK: 'SALTATA: NO LINK OF', SKIPPED_NOT_X_SAFE: 'SALTATA: NON X-SAFE', MANUAL_SKIP: 'SALTO MANUALE', SKIP_DUPLICATE_SLOT: 'SLOT DUPLICATO' };

function Pill({ label, color = C.muted, testid }) {
  return <span className="caps-label px-2.5 py-1 rounded-full text-[10px] whitespace-nowrap" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }} data-testid={testid}>{label}</span>;
}
function Kpi({ icon: Icon, label, value, sub, testid }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4" data-testid={testid}>
      <div className="flex items-center gap-2 caps-label text-muted-foreground mb-2"><Icon className="h-4 w-4" />{label}</div>
      <div className="text-2xl font-serif">{value ?? '—'}</div>
      {sub && <div className="text-[11px] text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}
const fmtTime = (ts) => { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } };
const hhmm = (iso, tz) => { try { return new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', timeZone: tz || 'Europe/Rome' }); } catch (e) { return iso; } };

function MediaBox({ item, side, testid }) {
  const Icon = side === 'PUBLIC' ? Eye : EyeOff;
  return (
    <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-xs flex-1 min-w-[200px]" data-testid={testid}>
      <div className="flex items-center gap-2 caps-label mb-2" style={{ color: side === 'PUBLIC' ? C.info : C.gold }}><Icon className="h-4 w-4" /> {side === 'PUBLIC' ? '1 · Lato Pubblico' : '2 · Lato Segreto'}</div>
      {item ? (<>
        <div className="font-medium">{item.type === 'video' ? 'VIDEO' : 'FOTO'} <span className="text-muted-foreground">· {item.id}</span></div>
        <div className="truncate text-muted-foreground mt-1" title={item.url}>{item.url}</div>
      </>) : <div className="text-muted-foreground">—</div>}
    </div>
  );
}

export default function AdminXAutopilot() {
  const [s, setS] = useState(null);
  const [logs, setLogs] = useState([]);
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState(null);
  const [preview, setPreview] = useState(null);
  const [xconn, setXconn] = useState(null);
  const [authUrl, setAuthUrl] = useState(null);
  const [manualStep, setManualStep] = useState(null);

  const loadConn = useCallback(async (live) => {
    setBusy(live ? 'xconn' : '');
    try { const r = await xApConnection(live); setXconn(r); if (live) toast.success(`Account X: ${r.X_ACCOUNT_CONNECTED ? '@' + r.X_USERNAME : 'non collegato'}`); }
    catch (e) { if (live) toast.error('Verifica connessione X fallita'); }
    finally { setBusy(''); }
  }, []);
  useEffect(() => { loadConn(false); }, [loadConn]);
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const a = p.get('x_auth');
    if (a === 'ok') toast.success(`Account X collegato${p.get('user') ? ': @' + p.get('user') : ''}`);
    else if (a === 'denied') toast.warning('Autorizzazione X annullata');
    else if (a === 'error') toast.error(`Autorizzazione X fallita: ${p.get('code') || ''}`);
    if (a) { window.history.replaceState({}, '', window.location.pathname); loadConn(true); }
  }, [loadConn]);
  const startAuth = async () => {
    setBusy('auth'); setManualStep(null);
    try { const r = await xApAuthStart(); setAuthUrl(r.authorize_url); window.open(r.authorize_url, '_blank', 'noopener'); toast.success('Apri il link X e autorizza l\'account'); }
    catch (e) { const d = e?.response?.data?.detail; setManualStep(d?.MISSING_MANUAL_STEP || d?.detail || 'Avvio autorizzazione fallito'); toast.error(d?.error || 'Avvio autorizzazione fallito'); }
    finally { setBusy(''); }
  };

  const load = useCallback(async () => {
    try {
      const [st, lg] = await Promise.all([xApStatus(), xApLogs(40)]);
      setS(st); setLogs(lg.items || []);
      setForm((f) => f || { ...st.settings, schedule_times: st.settings.schedule_times.join(', ') });
    } catch (e) { toast.error('Impossibile caricare lo stato X Autopilot'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const act = async (key, fn, okMsg) => {
    setBusy(key);
    try { const r = await fn(); toast.success(typeof okMsg === 'function' ? okMsg(r) : okMsg); await load(); return r; }
    catch (e) { toast.error(e?.response?.data?.detail || 'Operazione fallita'); }
    finally { setBusy(''); }
  };
  const saveSettings = async () => {
    const times = form.schedule_times.split(',').map((t) => t.trim()).filter(Boolean);
    await act('settings', () => xApSettings({ posts_per_day: Number(form.posts_per_day), schedule_times: times, timezone: form.timezone, use_ai_copy: form.use_ai_copy, italy_audience_mode: form.italy_audience_mode }), 'Impostazioni salvate');
    setForm(null);
  };

  const conn = s?.connection || {};
  const connStatus = s?.CONNECTION_STATUS || '…';
  const connected = connStatus === 'CONNECTED';
  const mock = !!s?.MOCK_MODE;
  const operational = !!s?.operational;
  const q = s?.queue || {};
  const sch = s?.schedule || {};
  const lp = s?.last_published;
  const le = s?.last_event;
  const notSafe = q.not_x_safe || {};
  const notSafeSlugs = Object.keys(notSafe);

  return (
    <div data-testid="x-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Twitter className="h-7 w-7" style={{ color: C.gold }} /> X Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Un solo account X Lato Segreto, tutte le creator pubblicate a rotazione: 1 media Pubblico → 1 media Segreto, copy italiano, link OnlyFans reale della creator. Foto+foto in un post, con video in thread.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={load} data-testid="x-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn variant="ghost" onClick={() => act('test', xApTestConnection, (r) => `X: ${r.CONNECTION_STATUS}${r.MOCK_MODE ? ' · MOCK_MODE' : ''}`)} disabled={!!busy} data-testid="x-test-connection">{busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test connessione</Btn>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-5" data-testid="x-status-pills">
        <Pill label={s ? (s.enabled ? 'ATTIVO' : 'IN PAUSA') : '…'} color={s?.enabled ? C.ok : C.warn} testid="x-state" />
        <Pill label={`Scheduler: ${s?.AUTO_SCHEDULER_ENABLED ? 'ABILITATO' : 'DISABILITATO (master switch)'}`} color={s?.AUTO_SCHEDULER_ENABLED ? C.ok : C.muted} testid="x-scheduler" />
        <Pill label={`Connessione: ${connStatus}`} color={connected ? C.ok : (mock ? C.warn : C.fail)} testid="x-connection" />
        <Pill label={`MOCK_MODE: ${s ? (mock ? 'TRUE' : 'FALSE') : '…'}`} color={mock ? C.warn : C.muted} testid="x-mock" />
        <Pill label={`Italy Audience: ${s?.ITALY_AUDIENCE_MODE ? 'ON' : 'OFF'}`} color={C.info} testid="x-italy-mode" />
        <Pill label={`Chiamate X reali: ${s?.X_REAL_CALLS ?? 0}`} color={(s?.X_REAL_CALLS ?? 0) === 0 ? C.ok : C.fail} testid="x-real-calls" />
        <Pill label="Pubblico → Segreto" color={C.gold} testid="x-order-rule" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Kpi icon={Users} label="Modella" value={q.total ? `${q.position} / ${q.total}` : '—'} sub={q.current ? `${q.current.name} · ${q.current.n_public} public · ${q.current.n_secret} secret` : 'nessuna creator eleggibile'} testid="x-kpi-current" />
        <Kpi icon={Repeat} label="Ciclo" value={q.cycle_number ? `#${q.cycle_number}` : '—'} sub={`${q.done_in_cycle ?? 0} processate in questo ciclo`} testid="x-kpi-cycle" />
        <Kpi icon={Clock} label="Post oggi" value={`${sch.posts_today ?? 0} / ${sch.posts_per_day ?? 0}`} sub={`orari ${(s?.settings?.schedule_times || []).join(' · ')} (${sch.timezone || ''})`} testid="x-kpi-today" />
        <Kpi icon={CheckCircle2} label="Ultima" value={lp ? lp.model_name : (le?.model_name || '—')} sub={lp ? `${fmtTime(lp.at)} · ${lp.format}${mock ? ' · mock' : ''} · OK` : (le ? `${fmtTime(le.timestamp)} · ${STATUS_LABEL[le.status] || le.status}` : 'nessuna')} testid="x-kpi-last" />
      </div>

      <SectionCard title="Account X reale" desc="Collegamento OAuth 1.0a (backend-only): le chiavi restano nei Secrets, i token utente sono cifrati nel database. Nessun post viene creato in questa fase.">
        <div className="flex flex-wrap gap-2 mb-3" data-testid="x-conn-pills">
          <Pill label={`APP AUTH: ${xconn ? (xconn.X_APP_AUTH_READY === null ? 'NON VERIFICATA' : xconn.X_APP_AUTH_READY ? 'OK' : 'KO') : '…'}`} color={xconn?.X_APP_AUTH_READY ? C.ok : (xconn?.X_APP_AUTH_READY === false ? C.fail : C.muted)} testid="x-app-auth" />
          <Pill label={`USER AUTH: ${xconn ? (xconn.X_USER_AUTH_PRESENT ? (xconn.X_USER_AUTH_READY ? 'OK' : 'TOKEN SALVATO') : 'ASSENTE') : '…'}`} color={xconn?.X_USER_AUTH_READY ? C.ok : (xconn?.X_USER_AUTH_PRESENT ? C.warn : C.muted)} testid="x-user-auth" />
          <Pill label={`ACCOUNT: ${xconn?.X_USERNAME ? '@' + xconn.X_USERNAME : '—'}`} color={xconn?.X_ACCOUNT_CONNECTED ? C.ok : C.muted} testid="x-account" />
          <Pill label={`SCRITTURA: ${xconn ? (xconn.X_WRITE_CAPABILITY_READY === null ? 'N/D' : xconn.X_WRITE_CAPABILITY_READY ? 'READ-WRITE' : 'SOLO LETTURA') : '…'}`} color={xconn?.X_WRITE_CAPABILITY_READY ? C.ok : (xconn?.X_WRITE_CAPABILITY_READY === false ? C.fail : C.muted)} testid="x-write-cap" />
          <Pill label={`Post reali creati: ${xconn?.REAL_X_POSTS_CREATED ?? s?.REAL_X_POSTS_CREATED ?? 0}`} color={C.ok} testid="x-real-posts" />
          <Pill label={`Gate scrittura: ${xconn?.X_REAL_POSTING_ENABLED ? 'APERTO' : 'CHIUSO'}`} color={xconn?.X_REAL_POSTING_ENABLED ? C.warn : C.ok} testid="x-write-gate" />
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn onClick={startAuth} disabled={!!busy} data-testid="x-auth-start">{busy === 'auth' ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />} {xconn?.X_USER_AUTH_PRESENT ? 'Ri-autorizza account X' : 'Collega account X'}</Btn>
          <Btn variant="ghost" onClick={() => loadConn(true)} disabled={!!busy} data-testid="x-conn-check">{busy === 'xconn' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Verifica account (read-only)</Btn>
          {xconn?.X_USER_AUTH_PRESENT && <Btn variant="ghost" onClick={() => { if (window.confirm('Scollegare l\'account X (solo token locale)?')) act('disc', xApAuthDisconnect, 'Account X scollegato').then(() => loadConn(false)); }} disabled={!!busy} data-testid="x-auth-disconnect"><Unplug className="h-4 w-4" /> Scollega</Btn>}
        </div>
        {authUrl && <div className="text-xs mt-3 flex items-center gap-2 break-all" data-testid="x-auth-url"><ExternalLink className="h-4 w-4 shrink-0" /> <a href={authUrl} target="_blank" rel="noopener noreferrer" className="underline" style={{ color: C.gold }}>{authUrl}</a></div>}
        {manualStep && <div className="text-xs mt-3 flex items-start gap-2" style={{ color: C.warn }} data-testid="x-manual-step"><AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> <span>{manualStep}</span></div>}
        {xconn && xconn.MISSING_MANUAL_STEP && xconn.MISSING_MANUAL_STEP !== 'NONE' && !manualStep && <div className="text-xs mt-3 flex items-start gap-2 text-muted-foreground" data-testid="x-missing-step"><AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" /> <span>{xconn.MISSING_MANUAL_STEP}</span></div>}
      </SectionCard>

      <SectionCard title="Prossima" desc={s?.next?.model ? `${s.next.model} — ${s.next.slot ? hhmm(s.next.slot.at, sch.timezone) : '—'} (${s.next.slot?.slot_id || ''})` : 'nessuna'}>
        <div className="flex flex-wrap gap-2">
          {s?.enabled
            ? <Btn variant="ghost" onClick={() => act('pause', xApPause, 'Autopilot in pausa')} disabled={!!busy} data-testid="x-pause"><Pause className="h-4 w-4" /> Pausa</Btn>
            : <Btn onClick={() => act('start', xApStart, (r) => r.note || 'Autopilot attivo')} disabled={!!busy || !operational} data-testid="x-start"><Play className="h-4 w-4" /> Attiva</Btn>}
          <Btn onClick={() => { if (window.confirm(mock ? 'MOCK_MODE: nessun post reale su X. Procedere?' : 'Pubblicare ORA la prossima creator su X?')) act('publish', xApPublishNow, (r) => (r.status === 'PUBLISHED' || r.status === 'MOCK_PREPARED') ? `${r.status === 'MOCK_PREPARED' ? 'Mock preparato' : 'Pubblicata'}: ${r.model_name} (${r.format})` : `Esito: ${r.status}`); }} disabled={!!busy || !operational} data-testid="x-publish-now">{busy === 'publish' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Pubblica ora</Btn>
          <Btn variant="ghost" onClick={async () => { const r = await act('preview', xApPreview, (r) => r.status === 'PREVIEW' ? `Anteprima pronta: ${r.model}` : `Esito: ${r.status}`); if (r && r.status === 'PREVIEW') setPreview(r); }} disabled={!!busy} data-testid="x-preview"><Sparkles className="h-4 w-4" /> Anteprima prossimo post</Btn>
          <Btn variant="ghost" onClick={() => act('skip', xApSkip, (r) => `Saltata ${r.skipped}`)} disabled={!!busy} data-testid="x-skip"><SkipForward className="h-4 w-4" /> Salta modella</Btn>
        </div>
        {!operational && <div className="text-xs mt-3 flex items-center gap-2" style={{ color: C.fail }} data-testid="x-connection-error"><AlertTriangle className="h-4 w-4" /> {conn.error || 'X non connessa: attivazione bloccata.'}</div>}
        {mock && <div className="text-xs mt-3 flex items-center gap-2 text-muted-foreground" data-testid="x-mock-note"><ShieldCheck className="h-4 w-4" /> MOCK_MODE attivo: il motore prepara il payload completo (coppia Pubblico→Segreto, copy, link OF) senza alcuna chiamata a X. CONNECTION_STATUS resta NOT_CONNECTED finché non verranno collegate le credenziali X.</div>}
        {preview && (
          <div className="mt-4 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm space-y-3" data-testid="x-preview-box">
            <div className="flex flex-wrap items-center gap-2"><Pill label={preview.format || '—'} color={C.info} testid="x-preview-format" /><span className="font-medium" data-testid="x-preview-model">{preview.model}</span><span className="text-xs text-muted-foreground">copy: {preview.copy_source} · ciclo #{preview.cycle_number} · {preview.x_length}/280 · slot {preview.slot?.slot_id || '—'}</span></div>
            <div className="flex flex-wrap gap-2"><MediaBox item={preview.public} side="PUBLIC" testid="x-preview-public" /><MediaBox item={preview.secret} side="SECRET" testid="x-preview-secret" /></div>
            <pre className="whitespace-pre-wrap font-sans text-sm" data-testid="x-preview-text">{preview.text}</pre>
            {preview.format === 'THREAD' && <div className="text-xs text-muted-foreground flex items-center gap-2" data-testid="x-preview-reply"><Layers className="h-4 w-4" /> Risposta nel thread (media Segreto): «{preview.reply_text}»</div>}
            <div className="text-xs flex items-center gap-2" data-testid="x-preview-of"><Link2 className="h-4 w-4" /> Link OF: <span className="font-mono">{preview.of_url}</span></div>
          </div>
        )}
      </SectionCard>

      <div className="grid md:grid-cols-2 gap-4">
        <SectionCard title="Impostazioni" desc="Orari, timezone e modalità configurabili (Italy Audience Mode: Europe/Rome).">
          {form && (
            <div className="space-y-3 text-sm" data-testid="x-settings-form">
              <label className="block"><span className="caps-label text-muted-foreground">Post al giorno</span><Input type="number" min={1} max={12} value={form.posts_per_day} onChange={(e) => setForm({ ...form, posts_per_day: e.target.value })} data-testid="x-posts-per-day" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Orari (HH:MM, separati da virgola)</span><Input value={form.schedule_times} onChange={(e) => setForm({ ...form, schedule_times: e.target.value })} data-testid="x-schedule-times" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Timezone</span><Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="x-timezone" /></label>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Copy AI (fallback template)</span><Switch checked={!!form.use_ai_copy} onCheckedChange={(v) => setForm({ ...form, use_ai_copy: v })} data-testid="x-use-ai" /></div>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Italy Audience Mode</span><Switch checked={!!form.italy_audience_mode} onCheckedChange={(v) => setForm({ ...form, italy_audience_mode: v })} data-testid="x-italy-switch" /></div>
              <Btn onClick={saveSettings} disabled={busy === 'settings'} data-testid="x-save-settings">{busy === 'settings' ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Salva</Btn>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Rotazione" desc={`${q.total ?? 0} eleggibili · senza Public: ${(q.skipped_no_public_media || []).length} · senza Secret: ${(q.skipped_no_secret_media || []).length} · senza OF: ${(q.skipped_no_of_link || []).length} · media non X-safe: ${notSafeSlugs.length}`}>
          <ol className="text-sm space-y-1 max-h-72 overflow-auto" data-testid="x-rotation">
            {(q.order || []).map((m, i) => (
              <li key={m.slug} className="flex items-center gap-2" data-testid="x-rotation-item">
                <span className="text-xs text-muted-foreground w-6">{i + 1}.</span><span className={m.done ? 'text-muted-foreground line-through' : ''}>{m.name}</span>
                {q.current?.slug === m.slug && <Pill label="prossima" color={C.gold} />}
              </li>
            ))}
          </ol>
          {!!(q.skipped_no_public_media || []).length && <div className="text-xs mt-2" style={{ color: C.warn }} data-testid="x-no-public">Senza media Public: {q.skipped_no_public_media.join(', ')}</div>}
          {!!(q.skipped_no_secret_media || []).length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="x-no-secret">Senza media Secret: {q.skipped_no_secret_media.join(', ')}</div>}
          {!!(q.skipped_no_of_link || []).length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="x-no-of">Senza link OnlyFans valido: {q.skipped_no_of_link.join(', ')}</div>}
          {!!notSafeSlugs.length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="x-not-safe">Media scartati (non X-safe): {notSafeSlugs.map((k) => `${k} (${notSafe[k].length})`).join(', ')}</div>}
        </SectionCard>
      </div>

      <SectionCard title="Log tecnico" desc="Solo l'essenziale: quando, chi, quali media, formato, esito.">
        {logs.length ? logs.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-2 py-2 border-b border-border/40 last:border-0 text-sm" data-testid="x-log-item">
            <span className="text-xs text-muted-foreground w-24">{fmtTime(l.timestamp)}</span>
            <Pill label={STATUS_LABEL[l.status] || l.status} color={STATUS_COLOR[l.status] || C.muted} />
            <span className="font-medium">{l.model_name || '—'}</span>
            <span className="text-xs text-muted-foreground">{l.format ? `${l.format}` : ''}{l.public_media_id ? ` · pub ${l.public_media_id}` : ''}{l.secret_media_id ? ` · sec ${l.secret_media_id}` : ''}{l.x_post_id ? ` · id ${l.x_post_id}` : ''}{l.cycle_number ? ` · ciclo #${l.cycle_number}` : ''}{l.error_code ? ` · ${l.error_code}` : ''}{l.slot_id ? ` · ${l.slot_id}` : ''}{l.copy_source ? ` · ${l.copy_source}` : ''}{l.mock ? ' · mock' : ''}</span>
          </div>
        )) : <div className="text-sm text-muted-foreground py-4 text-center" data-testid="x-log-empty">Nessuna pubblicazione ancora.</div>}
      </SectionCard>
    </div>
  );
}
