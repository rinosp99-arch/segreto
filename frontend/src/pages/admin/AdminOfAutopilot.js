import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Lock, RefreshCw, PlugZap, Loader2, ShieldCheck, Play, Pause, Zap, SkipForward, Sparkles, Users, Repeat, Clock, CheckCircle2, Eye, EyeOff, Link2, AlertTriangle } from 'lucide-react';
import { ofApConnection, ofApTestConnection, ofApStatus, ofApPreview, ofApLogs, ofApStart, ofApPause, ofApPublishNow, ofApSkip, ofApSettings } from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', info: 'hsl(200 50% 60%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };
const STATUS_COLOR = { MOCK_CONFIRMED: C.info, MOCK_PREPARED: C.info, POST_CONFIRMED: C.ok, SCHEDULE_CONFIRMED: C.ok, POST_NOT_CONFIRMED: C.warn, SCHEDULE_NOT_CONFIRMED: C.warn, UPLOAD_FAILED: C.fail, FAILED: C.fail, SKIPPED_NO_PUBLIC: C.warn, SKIPPED_NO_SECRET: C.warn, SKIPPED_NO_OF_LINK: C.warn, MANUAL_SKIP: C.muted, SKIP_DUPLICATE_SLOT: C.info };
const STATUS_LABEL = { MOCK_CONFIRMED: 'MOCK CONFERMATO', MOCK_PREPARED: 'MOCK PREPARATO', POST_CONFIRMED: 'POST CONFERMATO', SCHEDULE_CONFIRMED: 'SCHEDULE CONFERMATO', POST_NOT_CONFIRMED: 'POST NON CONFERMATO', SCHEDULE_NOT_CONFIRMED: 'SCHEDULE NON CONFERMATO', UPLOAD_FAILED: 'UPLOAD FALLITO', FAILED: 'ERRORE', SKIPPED_NO_PUBLIC: 'SALTATA: NO PUBLIC', SKIPPED_NO_SECRET: 'SALTATA: NO SECRET', SKIPPED_NO_OF_LINK: 'SALTATA: NO LINK OF', MANUAL_SKIP: 'SALTO MANUALE', SKIP_DUPLICATE_SLOT: 'SLOT DUPLICATO', MOCK_DM_CONFIRMED: 'MOCK MASS DM CONFERMATO', MASS_DM_CONFIRMED: 'MASS DM CONFERMATO', MASS_DM_FAILED: 'MASS DM FALLITO', MASS_DM_NOT_CONFIRMED: 'MASS DM NON CONFERMATO', MASS_DM_REFRESH_FAILED: 'REFRESH FAN FALLITO', MASS_DM_TEST_STOPPED: 'TEST DM FERMATO' };
const RUN_LABEL = { OK: 'OK', PENDING: 'PENDING', RUNNING: 'RUNNING', SENDING: 'SENDING', FAILED: 'FAILED', UNVERIFIED: 'UNVERIFIED', DISABLED: 'OFF', MOCK_ONLY: 'MOCK ONLY', SKIPPED: 'SALTATO' };
const RUN_COLOR = { OK: C.ok, PENDING: C.muted, RUNNING: C.warn, SENDING: C.warn, FAILED: C.fail, UNVERIFIED: C.warn, DISABLED: C.muted, MOCK_ONLY: C.warn, SKIPPED: C.muted };

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
function MediaBox({ item, validation, side, testid }) {
  const Icon = side === 'PUBLIC' ? Eye : EyeOff;
  return (
    <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-xs flex-1 min-w-[220px]" data-testid={testid}>
      <div className="flex items-center gap-2 caps-label mb-2" style={{ color: side === 'PUBLIC' ? C.info : C.gold }}><Icon className="h-4 w-4" /> {side === 'PUBLIC' ? '1 · Lato Pubblico' : '2 · Lato Segreto'}</div>
      {item ? (<>
        <div className="font-medium">{item.type === 'video' ? 'VIDEO' : 'FOTO'} <span className="text-muted-foreground">· {item.id}</span></div>
        <div className="truncate text-muted-foreground mt-1" title={item.source_url}>{item.source_url}</div>
        {validation && <div className="mt-1" style={{ color: validation.ok ? C.ok : C.fail }}>{validation.ok ? `OK · HTTP ${validation.status_code} · ${validation.mime}${validation.size ? ` · ${Math.round(validation.size / 1024)} KB` : ''} · ${validation.source_type}` : `NON VALIDO · ${validation.reason}`}</div>}
      </>) : <div style={{ color: C.fail }}>nessun media valido</div>}
    </div>
  );
}
const fmtTime = (ts) => { if (!ts) return '—'; try { return new Date(ts).toLocaleString('it-IT', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); } catch (e) { return ts; } };
const hhmm = (iso, tz) => { try { return new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', timeZone: tz || 'Europe/Rome' }); } catch (e) { return iso; } };

export default function AdminOfAutopilot() {
  const [s, setS] = useState(null);
  const [logs, setLogs] = useState([]);
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState(null);
  const [preview, setPreview] = useState(null);

  const load = useCallback(async () => {
    try {
      const [st, lg] = await Promise.all([ofApStatus(), ofApLogs(40)]);
      setS(st); setLogs(lg.items || []);
      setForm((f) => f || { ...st.settings, schedule_times: st.settings.schedule_times.join(', ') });
    } catch (e) { toast.error('Impossibile caricare lo stato OnlyFans Autopilot'); }
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
    await act('settings', () => ofApSettings({ posts_per_day: Number(form.posts_per_day), schedule_times: times, timezone: form.timezone, use_ai_copy: form.use_ai_copy }), 'Impostazioni salvate');
    setForm(null);
  };

  const conn = s?.connection || {};
  const connected = s?.CONNECTION_STATUS === 'CONNECTED';
  const healthy = s?.ACCOUNT_STATUS === 'HEALTHY';
  const mock = !!s?.MOCK_MODE;
  const q = s?.queue || {};
  const sch = s?.schedule || {};
  const lp = s?.last_published;
  const le = s?.last_event;

  return (
    <div data-testid="of-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Lock className="h-7 w-7" style={{ color: C.gold }} /> OnlyFans Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Account centrale latosegreto: tutte le creator pubblicate a rotazione, 1 media Pubblico → 1 media Segreto presi dal sito, caption italiana e link OnlyFans reale della creator. Fase MOCK: nessuna scrittura reale.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={load} data-testid="of-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn variant="ghost" onClick={() => act('test', async () => { const r = await ofApTestConnection(); return r; }, (r) => `Provider: ${r.CONNECTION_STATUS} · ${r.ACCOUNT_USERNAME || '—'} · ${r.ACCOUNT_STATUS}`)} disabled={!!busy} data-testid="of-test-connection">{busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test connessione (sola lettura)</Btn>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-5" data-testid="of-status-pills">
        <Pill label={`Provider: ${s?.PROVIDER || '—'}`} color={C.gold} testid="of-provider" />
        <Pill label={`Connection: ${s?.CONNECTION_STATUS || '…'}`} color={connected ? C.ok : C.fail} testid="of-connection" />
        <Pill label={`Account: ${s?.ACCOUNT_USERNAME || '—'}`} color={s?.ACCOUNT_USERNAME ? C.ok : C.muted} testid="of-account" />
        <Pill label={`Health: ${s?.ACCOUNT_STATUS || '…'}`} color={healthy ? C.ok : C.fail} testid="of-health" />
        <Pill label={`Autopilot: ${s?.OF_AUTOPILOT_STATUS || '…'}`} color={s?.OF_AUTOPILOT_STATUS === 'ACTIVE' ? C.ok : (s?.OF_AUTOPILOT_STATUS === 'READY' ? C.info : C.warn)} testid="of-autopilot-status" />
        <Pill label={`MOCK_MODE: ${s ? (mock ? 'TRUE' : 'FALSE') : '…'}`} color={mock ? C.warn : C.muted} testid="of-mock" />
        <Pill label={`Real posting: ${s?.REAL_POSTING || 'OFF'}`} color={s?.REAL_POSTING === 'ON' ? C.warn : C.muted} testid="of-real-posting" />
        <Pill label={`Auto scheduler: ${s?.AUTO_SCHEDULER || 'OFF'}`} color={s?.AUTO_SCHEDULER === 'ON' ? C.warn : C.muted} testid="of-auto-scheduler" />
        <Pill label={`Write reali provider: ${s?.THE_ONLY_API_REAL_WRITE_CALLS ?? 0}`} color={(s?.THE_ONLY_API_REAL_WRITE_CALLS ?? 0) === 0 ? C.ok : C.fail} testid="of-write-calls" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Kpi icon={Users} label="Modelle" value={q.total ? `${q.position} / ${q.total}` : '—'} sub={q.current ? `${q.current.name} · ${q.current.n_public} public · ${q.current.n_secret} secret` : 'nessuna creator eleggibile'} testid="of-kpi-current" />
        <Kpi icon={Repeat} label="Ciclo" value={q.cycle_number ? `#${q.cycle_number}` : '—'} sub={`${q.done_in_cycle ?? 0} processate in questo ciclo`} testid="of-kpi-cycle" />
        <Kpi icon={Clock} label="Post oggi" value={`${sch.posts_today ?? 0} / ${sch.posts_per_day ?? 0}`} sub={`orari ${(s?.settings?.schedule_times || []).join(' · ')} (${sch.timezone || ''})`} testid="of-kpi-today" />
        <Kpi icon={CheckCircle2} label="Ultima" value={lp ? lp.model_name : (le?.model_name || '—')} sub={lp ? `${fmtTime(lp.at)} · ${STATUS_LABEL[lp.status] || lp.status}` : (le ? `${fmtTime(le.timestamp)} · ${STATUS_LABEL[le.status] || le.status}` : 'nessuna')} testid="of-kpi-last" />
      </div>

      <SectionCard title="Prossima" desc={s?.next?.model ? `${s.next.model} — ${s.next.slot ? hhmm(s.next.slot.at, sch.timezone) : '—'} (${s.next.slot?.slot_id || ''})` : 'nessuna'}>
        <div className="flex flex-wrap gap-2">
          {s?.enabled
            ? <Btn variant="ghost" onClick={() => act('pause', ofApPause, 'Autopilot in pausa')} disabled={!!busy} data-testid="of-pause"><Pause className="h-4 w-4" /> Pausa</Btn>
            : <Btn onClick={() => act('start', ofApStart, (r) => r.note || 'Autopilot attivo')} disabled={!!busy} data-testid="of-start"><Play className="h-4 w-4" /> Attiva</Btn>}
          <Btn variant="ghost" onClick={async () => { const r = await act('preview', ofApPreview, (r) => r.status === 'PREVIEW' ? `Anteprima pronta: ${r.model}` : `Esito: ${r.status}`); if (r && r.status === 'PREVIEW') setPreview(r); }} disabled={!!busy} data-testid="of-preview">{busy === 'preview' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />} Anteprima prossimo post</Btn>
          <Btn onClick={() => { if (window.confirm(mock ? 'MOCK_MODE: nessuna scrittura reale su OnlyFans. Simulare la pubblicazione immediata?' : 'Pubblicare ORA (immediato) sull\'account latosegreto?')) act('publish', ofApPublishNow, (r) => r.status === 'MOCK_CONFIRMED' ? `Mock confermato: ${r.model_name}` : (r.status === 'POST_CONFIRMED' ? `Pubblicata: ${r.model_name}` : `Esito: ${r.status}${r.error_code ? ` (${r.error_code})` : ''}`)); }} disabled={!!busy} data-testid="of-publish-now">{busy === 'publish' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} {mock ? 'Pubblica ora (MOCK)' : 'Pubblica ora'}</Btn>
          <Btn variant="ghost" onClick={() => act('skip', ofApSkip, (r) => `Saltata ${r.skipped}`)} disabled={!!busy} data-testid="of-skip"><SkipForward className="h-4 w-4" /> Salta modella</Btn>
        </div>
        <div className="flex flex-wrap items-center gap-2 mt-3 text-xs" data-testid="of-run-status">
          <span className="text-muted-foreground">Modella corrente{s?.current_run?.model_slug ? ` (${s.current_run.model_slug})` : q.current ? ` (${q.current.slug})` : ''}:</span>
          <Pill label={`FEED: ${RUN_LABEL[s?.current_run?.FEED_STATUS] || 'PENDING'}`} color={RUN_COLOR[s?.current_run?.FEED_STATUS] || C.muted} testid="of-feed-status" />
          <Pill label={`FAN REFRESH: ${RUN_LABEL[s?.current_run?.FAN_REFRESH_STATUS] || 'PENDING'}`} color={RUN_COLOR[s?.current_run?.FAN_REFRESH_STATUS] || C.muted} testid="of-fan-refresh-status" />
          <Pill label={`MASS MESSAGE: ${RUN_LABEL[s?.current_run?.MASS_DM_STATUS] || 'PENDING'}`} color={RUN_COLOR[s?.current_run?.MASS_DM_STATUS] || C.muted} testid="of-mass-dm-status" />
          {s?.current_run?.AUDIENCE != null && <span className="text-muted-foreground" data-testid="of-mass-dm-audience">Audience: {s.current_run.AUDIENCE}{s.current_run.cached_total != null ? ` (cache ${s.current_run.cached_total})` : ''}</span>}
          {s && !s.OF_MASS_DM_ENABLED && <span className="text-muted-foreground" data-testid="of-mass-dm-mode">mass message disattivato (OF_MASS_DM_ENABLED=false)</span>}
          {s?.OF_MASS_DM_ENABLED && s?.OF_MASS_DM_MOCK && <span className="text-muted-foreground" data-testid="of-mass-dm-mode">mass message in MOCK</span>}
        </div>
        {s?.last_error && <div className="text-xs mt-3 flex items-center gap-2" style={{ color: C.warn }} data-testid="of-last-error"><AlertTriangle className="h-4 w-4" /> Ultimo errore: {s.last_error}</div>}
        {mock && <div className="text-xs mt-3 flex items-center gap-2 text-muted-foreground" data-testid="of-mock-note"><ShieldCheck className="h-4 w-4" /> MOCK_MODE: upload, post e verifica sono simulati dal MockOFProvider. Il provider reale è usato solo in lettura (connessione/health). Cursori e coda avanzano solo dopo conferma.</div>}
        {preview && (
          <div className="mt-4 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm space-y-3" data-testid="of-preview-box">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium" data-testid="of-preview-model">{preview.model}</span><Pill label={preview.SAME_MODEL_MEDIA ? 'SAME_MODEL_MEDIA' : 'MEDIA NON COERENTI'} color={preview.SAME_MODEL_MEDIA ? C.ok : C.fail} testid="of-preview-same-model" /><span className="text-xs text-muted-foreground">{preview.position}/{preview.total} · ciclo #{preview.cycle_number} · caption {preview.caption_source} · slot {preview.slot?.slot_id || '—'} · provider {preview.provider} · {preview.account} ({preview.account_status}) · mock {String(preview.mock)}</span></div>
            <div className="flex flex-wrap gap-2"><MediaBox item={preview.public} validation={preview.public_validation} side="PUBLIC" testid="of-preview-public" /><MediaBox item={preview.secret} validation={preview.secret_validation} side="SECRET" testid="of-preview-secret" /></div>
            <pre className="whitespace-pre-wrap font-sans text-sm" data-testid="of-preview-caption">{preview.caption}</pre>
            <div className="text-xs flex items-center gap-2" data-testid="of-preview-of"><Link2 className="h-4 w-4" /> Link OF della modella: <span className="font-mono">{preview.of_url}</span></div>
          </div>
        )}
      </SectionCard>

      <div className="grid md:grid-cols-2 gap-4">
        <SectionCard title="Impostazioni" desc="Post al giorno, orari, timezone e caption AI (nessun controllo per abilitare scritture reali).">
          {form && (
            <div className="space-y-3 text-sm" data-testid="of-settings-form">
              <label className="block"><span className="caps-label text-muted-foreground">Post al giorno</span><Input type="number" min={1} max={12} value={form.posts_per_day} onChange={(e) => setForm({ ...form, posts_per_day: e.target.value })} data-testid="of-posts-per-day" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Orari (HH:MM, separati da virgola)</span><Input value={form.schedule_times} onChange={(e) => setForm({ ...form, schedule_times: e.target.value })} data-testid="of-schedule-times" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Timezone</span><Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="of-timezone" /></label>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Caption AI (fallback template)</span><Switch checked={!!form.use_ai_copy} onCheckedChange={(v) => setForm({ ...form, use_ai_copy: v })} data-testid="of-use-ai" /></div>
              <Btn onClick={saveSettings} disabled={busy === 'settings'} data-testid="of-save-settings">{busy === 'settings' ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Salva</Btn>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Rotazione" desc={`${q.total ?? 0} eleggibili · senza Public: ${(q.skipped_no_public || []).length} · senza Secret: ${(q.skipped_no_secret || []).length} · senza OF: ${(q.skipped_no_of_link || []).length} · escluse: ${(q.excluded || []).length}`}>
          <ol className="text-sm space-y-1 max-h-72 overflow-auto" data-testid="of-rotation">
            {(q.order || []).map((m, i) => (
              <li key={m.slug} className="flex items-center gap-2" data-testid="of-rotation-item">
                <span className="text-xs text-muted-foreground w-6">{i + 1}.</span><span className={m.done ? 'text-muted-foreground line-through' : ''}>{m.name}</span>
                {q.current?.slug === m.slug && <Pill label="prossima" color={C.gold} />}
              </li>
            ))}
          </ol>
          {!!(q.skipped_no_public || []).length && <div className="text-xs mt-2" style={{ color: C.warn }} data-testid="of-no-public">Senza media Public: {q.skipped_no_public.join(', ')}</div>}
          {!!(q.skipped_no_secret || []).length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="of-no-secret">Senza media Secret: {q.skipped_no_secret.join(', ')}</div>}
          {!!(q.skipped_no_of_link || []).length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="of-no-of">Senza link OnlyFans valido: {q.skipped_no_of_link.join(', ')}</div>}
        </SectionCard>
      </div>

      <SectionCard title="Log tecnico" desc="Quando, chi, quali media (sorgente sito), esito, provider post id.">
        {logs.length ? logs.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-2 py-2 border-b border-border/40 last:border-0 text-sm" data-testid="of-log-item">
            <span className="text-xs text-muted-foreground w-24">{fmtTime(l.timestamp)}</span>
            <Pill label={STATUS_LABEL[l.status] || l.status} color={STATUS_COLOR[l.status] || C.muted} />
            <span className="font-medium">{l.model_name || '—'}</span>
            <span className="text-xs text-muted-foreground">{l.action_type ? `${l.action_type}` : ''}{l.public_media_id ? ` · pub ${l.public_media_id}` : ''}{l.secret_media_id ? ` · sec ${l.secret_media_id}` : ''}{l.provider_post_id ? ` · post ${l.provider_post_id}` : ''}{l.cycle_number ? ` · ciclo #${l.cycle_number}` : ''}{l.error_code ? ` · ${l.error_code}` : ''}{l.slot_id ? ` · ${l.slot_id}` : ''}{l.mock ? ' · mock' : ''}</span>
          </div>
        )) : <div className="text-sm text-muted-foreground py-4 text-center" data-testid="of-log-empty">Nessuna pubblicazione ancora.</div>}
      </SectionCard>
      <div className="hidden" data-testid="of-security-note">{conn.PROVIDER}</div>
    </div>
  );
}
