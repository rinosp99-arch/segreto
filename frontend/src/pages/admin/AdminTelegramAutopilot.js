import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Send, Play, Pause, SkipForward, Zap, RefreshCw, Loader2, PlugZap, Clock, Users, Repeat, CheckCircle2, AlertTriangle, ImageIcon, Video, Sparkles } from 'lucide-react';
import { tgApStatus, tgApLogs, tgApTestConnection, tgApStart, tgApPause, tgApPublishNow, tgApSkip, tgApSettings } from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', info: 'hsl(200 50% 60%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };
const STATUS_COLOR = { PUBLISHED: C.ok, FAILED: C.fail, SKIPPED_NO_MEDIA: C.warn, SKIPPED_NO_OF_LINK: C.warn, MANUAL_SKIP: C.muted, SKIP_DUPLICATE_SLOT: C.info };

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

export default function AdminTelegramAutopilot() {
  const [s, setS] = useState(null);
  const [logs, setLogs] = useState([]);
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState(null);

  const load = useCallback(async () => {
    try {
      const [st, lg] = await Promise.all([tgApStatus(), tgApLogs(40)]);
      setS(st); setLogs(lg.items || []);
      setForm((f) => f || { ...st.settings, schedule_times: st.settings.schedule_times.join(', ') });
    } catch (e) { toast.error('Impossibile caricare lo stato Telegram Autopilot'); }
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
    await act('settings', () => tgApSettings({ posts_per_day: Number(form.posts_per_day), schedule_times: times, timezone: form.timezone, use_photo: form.use_photo, use_video: form.use_video, use_ai_copy: form.use_ai_copy }), 'Impostazioni salvate');
    setForm(null);
  };

  const tg = s?.telegram || {};
  const connected = tg.TELEGRAM_CONNECTION_STATUS === 'CONNECTED';
  const q = s?.queue || {};
  const sch = s?.schedule || {};
  const lp = s?.last_published;

  return (
    <div data-testid="telegram-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Send className="h-7 w-7" style={{ color: C.gold }} /> Telegram Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Rotazione circolare automatica di tutte le modelle pubblicate sul canale, con foto/video, copy personalizzato e link OnlyFans diretto.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={load} data-testid="tg-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn variant="ghost" onClick={() => act('test', () => tgApTestConnection(true), (r) => `Telegram: ${r.TELEGRAM_CONNECTION_STATUS}`)} disabled={!!busy} data-testid="tg-test-connection">{busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test connessione</Btn>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-5" data-testid="tg-status-pills">
        <Pill label={s ? (s.enabled ? 'ATTIVO' : 'IN PAUSA') : '…'} color={s?.enabled ? C.ok : C.warn} testid="tg-state" />
        <Pill label={`Scheduler: ${s?.AUTO_SCHEDULER_ENABLED ? 'ABILITATO' : 'DISABILITATO (master switch)'}`} color={s?.AUTO_SCHEDULER_ENABLED ? C.ok : C.muted} testid="tg-scheduler" />
        <Pill label={`Telegram: ${connected ? 'CONNECTED' : tg.TELEGRAM_CONNECTION_STATUS || '…'}`} color={connected ? C.ok : C.fail} testid="tg-connection" />
        <Pill label={`Canale: ${s?.channel || '—'}`} color={C.info} testid="tg-channel" />
        {s?.mock && <Pill label="MODALITÀ MOCK: nessun post reale" color={C.warn} testid="tg-mock" />}
        {tg.bot?.username && <Pill label={`Bot: @${tg.bot.username}${tg.bot_is_admin ? ' · admin' : ''}`} testid="tg-bot" />}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Kpi icon={Users} label="Modella corrente" value={q.total ? `${q.position} / ${q.total}` : '—'} sub={q.current ? `${q.current.name} · ${q.current.n_photos} foto · ${q.current.n_videos} video` : 'nessuna modella eleggibile'} testid="tg-kpi-current" />
        <Kpi icon={Repeat} label="Ciclo" value={q.cycle_number ? `#${q.cycle_number}` : '—'} sub={`${q.done_in_cycle ?? 0} pubblicate in questo ciclo`} testid="tg-kpi-cycle" />
        <Kpi icon={Clock} label="Post oggi" value={`${sch.posts_today ?? 0} / ${sch.posts_per_day ?? 0}`} sub={`orari ${(s?.settings?.schedule_times || []).join(' · ')} (${sch.timezone || ''})`} testid="tg-kpi-today" />
        <Kpi icon={CheckCircle2} label="Ultima pubblicazione" value={lp ? lp.model_name : '—'} sub={lp ? `${fmtTime(lp.at)} · ${lp.media_type} · OK (msg ${lp.message_id})` : 'nessuna'} testid="tg-kpi-last" />
      </div>

      <SectionCard title="Prossima pubblicazione" desc={s?.next?.model ? `${s.next.model} — ${s.next.slot ? hhmm(s.next.slot.at, sch.timezone) : '—'} (${s.next.slot?.slot_id || ''})` : 'nessuna'}>
        <div className="flex flex-wrap gap-2">
          {s?.enabled
            ? <Btn variant="ghost" onClick={() => act('pause', tgApPause, 'Autopilot in pausa')} disabled={!!busy} data-testid="tg-pause"><Pause className="h-4 w-4" /> Pausa</Btn>
            : <Btn onClick={() => act('start', tgApStart, (r) => r.note || 'Autopilot attivo')} disabled={!!busy || !connected} data-testid="tg-start"><Play className="h-4 w-4" /> Attiva</Btn>}
          <Btn onClick={() => { if (window.confirm(s?.mock ? 'Modalità mock: nessun post reale. Procedere?' : 'Pubblicare ORA la prossima modella sul canale reale?')) act('publish', () => tgApPublishNow(false), (r) => r.status === 'PUBLISHED' ? `Pubblicata ${r.model_name} (msg ${r.message_id})` : `Esito: ${r.status}`); }} disabled={!!busy || !connected} data-testid="tg-publish-now">{busy === 'publish' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Pubblica ora</Btn>
          <Btn variant="ghost" onClick={() => act('dry', () => tgApPublishNow(true), (r) => `Anteprima pronta: ${r.model}`)} disabled={!!busy} data-testid="tg-dry-run"><Sparkles className="h-4 w-4" /> Anteprima copy</Btn>
          <Btn variant="ghost" onClick={() => act('skip', tgApSkip, (r) => `Saltata ${r.skipped}`)} disabled={!!busy} data-testid="tg-skip"><SkipForward className="h-4 w-4" /> Salta modella</Btn>
        </div>
        {!connected && <div className="text-xs mt-3 flex items-center gap-2" style={{ color: C.fail }} data-testid="tg-connection-error"><AlertTriangle className="h-4 w-4" /> {tg.error || 'Telegram non connesso: attivazione bloccata.'}</div>}
      </SectionCard>

      <div className="grid md:grid-cols-2 gap-4">
        <SectionCard title="Impostazioni" desc="Orari e timezone non sono fissi nel codice.">
          {form && (
            <div className="space-y-3 text-sm" data-testid="tg-settings-form">
              <label className="block"><span className="caps-label text-muted-foreground">Post al giorno</span><Input type="number" min={1} max={12} value={form.posts_per_day} onChange={(e) => setForm({ ...form, posts_per_day: e.target.value })} data-testid="tg-posts-per-day" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Orari (HH:MM, separati da virgola)</span><Input value={form.schedule_times} onChange={(e) => setForm({ ...form, schedule_times: e.target.value })} data-testid="tg-schedule-times" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Timezone</span><Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="tg-timezone" /></label>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><ImageIcon className="h-4 w-4" /> Usa foto</span><Switch checked={!!form.use_photo} onCheckedChange={(v) => setForm({ ...form, use_photo: v })} data-testid="tg-use-photo" /></div>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Video className="h-4 w-4" /> Usa video</span><Switch checked={!!form.use_video} onCheckedChange={(v) => setForm({ ...form, use_video: v })} data-testid="tg-use-video" /></div>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Genera testo AI (fallback template)</span><Switch checked={!!form.use_ai_copy} onCheckedChange={(v) => setForm({ ...form, use_ai_copy: v })} data-testid="tg-use-ai" /></div>
              <Btn onClick={saveSettings} disabled={busy === 'settings'} data-testid="tg-save-settings">{busy === 'settings' ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Salva</Btn>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Rotazione" desc={`${q.total ?? 0} eleggibili · senza OF: ${(q.skipped_no_of || []).length} · senza media: ${(q.skipped_no_media || []).length}`}>
          <ol className="text-sm space-y-1 max-h-72 overflow-auto" data-testid="tg-rotation">
            {(q.order || []).map((m, i) => (
              <li key={m.slug} className="flex items-center gap-2" data-testid="tg-rotation-item">
                <span className="text-xs text-muted-foreground w-6">{i + 1}.</span><span className={m.done ? 'text-muted-foreground line-through' : ''}>{m.name}</span>
                {q.current?.slug === m.slug && <Pill label="prossima" color={C.gold} />}
              </li>
            ))}
          </ol>
          {!!(q.skipped_no_of || []).length && <div className="text-xs mt-2" style={{ color: C.warn }}>Senza link OnlyFans (saltate): {q.skipped_no_of.join(', ')}</div>}
          {!!(q.skipped_no_media || []).length && <div className="text-xs mt-1" style={{ color: C.warn }}>Senza media pubblici (saltate): {q.skipped_no_media.join(', ')}</div>}
        </SectionCard>
      </div>

      <SectionCard title="Log tecnico" desc="Solo l'essenziale: quando, chi, quale media, esito.">
        {logs.length ? logs.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-2 py-2 border-b border-border/40 last:border-0 text-sm" data-testid="tg-log-item">
            <span className="text-xs text-muted-foreground w-24">{fmtTime(l.timestamp)}</span>
            <Pill label={l.status} color={STATUS_COLOR[l.status] || C.muted} />
            <span className="font-medium">{l.model_name || '—'}</span>
            <span className="text-xs text-muted-foreground">{l.media_type ? `${l.media_type}` : ''}{l.message_id ? ` · msg ${l.message_id}` : ''}{l.cycle_number ? ` · ciclo #${l.cycle_number}` : ''}{l.error_code ? ` · ${l.error_code}` : ''}{l.slot_id ? ` · ${l.slot_id}` : ''}{l.mock ? ' · mock' : ''}</span>
          </div>
        )) : <div className="text-sm text-muted-foreground py-4 text-center" data-testid="tg-log-empty">Nessuna pubblicazione ancora.</div>}
      </SectionCard>
    </div>
  );
}
