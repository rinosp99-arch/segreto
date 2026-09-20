import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Instagram, Play, Pause, SkipForward, Zap, RefreshCw, Loader2, PlugZap, Clock, Users, Repeat, CheckCircle2, AlertTriangle, ImageIcon, Video, Sparkles, ShieldCheck } from 'lucide-react';
import { igApStatus, igApLogs, igApTestConnection, igApStart, igApPause, igApPublishNow, igApSkip, igApSettings } from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', info: 'hsl(200 50% 60%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };
const STATUS_COLOR = { PUBLISHED: C.ok, MOCK_PREPARED: C.info, FAILED: C.fail, SKIPPED_NO_PUBLIC_MEDIA: C.warn, SKIPPED_NOT_INSTAGRAM_SAFE: C.warn, MANUAL_SKIP: C.muted, SKIP_DUPLICATE_SLOT: C.info };
const STATUS_LABEL = { MOCK_PREPARED: 'MOCK PREPARATO', PUBLISHED: 'PUBBLICATO', FAILED: 'ERRORE', SKIPPED_NO_PUBLIC_MEDIA: 'SALTATA: NO MEDIA PUBBLICI', SKIPPED_NOT_INSTAGRAM_SAFE: 'SALTATA: NON IG-SAFE', MANUAL_SKIP: 'SALTO MANUALE', SKIP_DUPLICATE_SLOT: 'SLOT DUPLICATO' };

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

export default function AdminInstagramAutopilot() {
  const [s, setS] = useState(null);
  const [logs, setLogs] = useState([]);
  const [busy, setBusy] = useState('');
  const [form, setForm] = useState(null);
  const [preview, setPreview] = useState(null);

  const load = useCallback(async () => {
    try {
      const [st, lg] = await Promise.all([igApStatus(), igApLogs(40)]);
      setS(st); setLogs(lg.items || []);
      setForm((f) => f || { ...st.settings, schedule_times: st.settings.schedule_times.join(', ') });
    } catch (e) { toast.error('Impossibile caricare lo stato Instagram Autopilot'); }
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
    await act('settings', () => igApSettings({ posts_per_day: Number(form.posts_per_day), schedule_times: times, timezone: form.timezone, use_photo: form.use_photo, use_video: form.use_video, use_ai_copy: form.use_ai_copy }), 'Impostazioni salvate');
    setForm(null);
  };

  const conn = s?.connection || {};
  const connStatus = s?.CONNECTION_STATUS || conn.CONNECTION_STATUS || '…';
  const connected = connStatus === 'CONNECTED';
  const mock = !!s?.MOCK_MODE;
  const operational = !!s?.operational;
  const q = s?.queue || {};
  const sch = s?.schedule || {};
  const lp = s?.last_published;
  const notSafe = q.not_instagram_safe || {};
  const notSafeSlugs = Object.keys(notSafe);

  return (
    <div data-testid="instagram-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Instagram className="h-7 w-7" style={{ color: C.gold }} /> Instagram Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Coda circolare indipendente delle creator pubblicate: solo media del lato pubblico, caption in italiano, CTA "link in bio". Foto → post, video → Reel.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={load} data-testid="ig-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn variant="ghost" onClick={() => act('test', igApTestConnection, (r) => `Meta: ${r.CONNECTION_STATUS}${r.MOCK_MODE ? ' · MOCK_MODE' : ''}`)} disabled={!!busy} data-testid="ig-test-connection">{busy === 'test' ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test connessione</Btn>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mb-5" data-testid="ig-status-pills">
        <Pill label={s ? (s.enabled ? 'ATTIVO' : 'IN PAUSA') : '…'} color={s?.enabled ? C.ok : C.warn} testid="ig-state" />
        <Pill label={`Scheduler: ${s?.AUTO_SCHEDULER_ENABLED ? 'ABILITATO' : 'DISABILITATO (master switch)'}`} color={s?.AUTO_SCHEDULER_ENABLED ? C.ok : C.muted} testid="ig-scheduler" />
        <Pill label={`Meta: ${connStatus}`} color={connected ? C.ok : (mock ? C.warn : C.fail)} testid="ig-connection" />
        <Pill label={`MOCK_MODE: ${s ? (mock ? 'TRUE' : 'FALSE') : '…'}`} color={mock ? C.warn : C.muted} testid="ig-mock" />
        <Pill label={`Italy Audience: ${s?.ITALY_AUDIENCE_MODE ? 'ON' : 'OFF'}`} color={C.info} testid="ig-italy-mode" />
        <Pill label={`Chiamate Meta reali: ${s?.META_REAL_CALLS ?? 0}`} color={(s?.META_REAL_CALLS ?? 0) === 0 ? C.ok : C.fail} testid="ig-meta-calls" />
        <Pill label="Solo media pubblici" color={C.ok} testid="ig-public-only" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Kpi icon={Users} label="Creator corrente" value={q.total ? `${q.position} / ${q.total}` : '—'} sub={q.current ? `${q.current.name} · ${q.current.n_photos} foto · ${q.current.n_videos} video` : 'nessuna creator eleggibile'} testid="ig-kpi-current" />
        <Kpi icon={Repeat} label="Ciclo" value={q.cycle_number ? `#${q.cycle_number}` : '—'} sub={`${q.done_in_cycle ?? 0} processate in questo ciclo`} testid="ig-kpi-cycle" />
        <Kpi icon={Clock} label="Post oggi" value={`${sch.posts_today ?? 0} / ${sch.posts_per_day ?? 0}`} sub={`orari ${(s?.settings?.schedule_times || []).join(' · ')} (${sch.timezone || ''})`} testid="ig-kpi-today" />
        <Kpi icon={CheckCircle2} label="Ultima pubblicazione" value={lp ? lp.model_name : '—'} sub={lp ? `${fmtTime(lp.at)} · ${lp.post_type}${lp.ig_media_id ? ` · id ${lp.ig_media_id}` : ''}${mock ? ' · mock' : ''}` : 'nessuna'} testid="ig-kpi-last" />
      </div>

      <SectionCard title="Prossima pubblicazione" desc={s?.next?.model ? `${s.next.model} — ${s.next.slot ? hhmm(s.next.slot.at, sch.timezone) : '—'} (${s.next.slot?.slot_id || ''})` : 'nessuna'}>
        <div className="flex flex-wrap gap-2">
          {s?.enabled
            ? <Btn variant="ghost" onClick={() => act('pause', igApPause, 'Autopilot in pausa')} disabled={!!busy} data-testid="ig-pause"><Pause className="h-4 w-4" /> Pausa</Btn>
            : <Btn onClick={() => act('start', igApStart, (r) => r.note || 'Autopilot attivo')} disabled={!!busy || !operational} data-testid="ig-start"><Play className="h-4 w-4" /> Attiva</Btn>}
          <Btn onClick={() => { if (window.confirm(mock ? 'MOCK_MODE: nessun post reale su Instagram. Procedere?' : 'Pubblicare ORA la prossima creator su Instagram?')) act('publish', () => igApPublishNow(false), (r) => (r.status === 'PUBLISHED' || r.status === 'MOCK_PREPARED') ? `${r.status === 'MOCK_PREPARED' ? 'Mock preparato' : 'Pubblicata'}: ${r.model_name} (${r.post_type})` : `Esito: ${r.status}`); }} disabled={!!busy || !operational} data-testid="ig-publish-now">{busy === 'publish' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />} Pubblica ora</Btn>
          <Btn variant="ghost" onClick={async () => { const r = await act('dry', () => igApPublishNow(true), (r) => `Anteprima pronta: ${r.model}`); if (r) setPreview(r); }} disabled={!!busy} data-testid="ig-dry-run"><Sparkles className="h-4 w-4" /> Anteprima caption</Btn>
          <Btn variant="ghost" onClick={() => act('skip', igApSkip, (r) => `Saltata ${r.skipped}`)} disabled={!!busy} data-testid="ig-skip"><SkipForward className="h-4 w-4" /> Salta creator</Btn>
        </div>
        {!operational && <div className="text-xs mt-3 flex items-center gap-2" style={{ color: C.fail }} data-testid="ig-connection-error"><AlertTriangle className="h-4 w-4" /> {conn.error || 'Meta non connessa: attivazione bloccata.'}</div>}
        {mock && <div className="text-xs mt-3 flex items-center gap-2 text-muted-foreground" data-testid="ig-mock-note"><ShieldCheck className="h-4 w-4" /> MOCK_MODE attivo: il motore prepara il payload completo (media pubblico, caption, hashtag) senza alcuna chiamata a Meta. CONNECTION_STATUS resta NOT_CONNECTED finché non verranno collegate le credenziali.</div>}
        {preview && (
          <div className="mt-4 rounded-xl border border-border/60 bg-muted/20 p-3 text-sm" data-testid="ig-preview">
            <div className="flex flex-wrap items-center gap-2 mb-2"><Pill label={preview.post_type} color={C.info} /><span className="font-medium">{preview.model}</span><span className="text-xs text-muted-foreground">copy: {preview.copy_source} · ciclo #{preview.cycle_number}</span></div>
            <pre className="whitespace-pre-wrap font-sans text-sm" data-testid="ig-preview-caption">{preview.caption}</pre>
          </div>
        )}
      </SectionCard>

      <div className="grid md:grid-cols-2 gap-4">
        <SectionCard title="Impostazioni" desc="Orari e timezone configurabili (Italy Audience Mode: Europe/Rome).">
          {form && (
            <div className="space-y-3 text-sm" data-testid="ig-settings-form">
              <label className="block"><span className="caps-label text-muted-foreground">Post al giorno</span><Input type="number" min={1} max={12} value={form.posts_per_day} onChange={(e) => setForm({ ...form, posts_per_day: e.target.value })} data-testid="ig-posts-per-day" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Orari (HH:MM, separati da virgola)</span><Input value={form.schedule_times} onChange={(e) => setForm({ ...form, schedule_times: e.target.value })} data-testid="ig-schedule-times" /></label>
              <label className="block"><span className="caps-label text-muted-foreground">Timezone</span><Input value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} data-testid="ig-timezone" /></label>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><ImageIcon className="h-4 w-4" /> Usa foto (PHOTO_POST)</span><Switch checked={!!form.use_photo} onCheckedChange={(v) => setForm({ ...form, use_photo: v })} data-testid="ig-use-photo" /></div>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Video className="h-4 w-4" /> Usa video (REEL_POST)</span><Switch checked={!!form.use_video} onCheckedChange={(v) => setForm({ ...form, use_video: v })} data-testid="ig-use-video" /></div>
              <div className="flex items-center justify-between py-1"><span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Caption AI (fallback template)</span><Switch checked={!!form.use_ai_copy} onCheckedChange={(v) => setForm({ ...form, use_ai_copy: v })} data-testid="ig-use-ai" /></div>
              <Btn onClick={saveSettings} disabled={busy === 'settings'} data-testid="ig-save-settings">{busy === 'settings' ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Salva</Btn>
            </div>
          )}
        </SectionCard>

        <SectionCard title="Rotazione" desc={`${q.total ?? 0} eleggibili · senza media pubblici: ${(q.skipped_no_public_media || []).length} · con media non IG-safe: ${notSafeSlugs.length}`}>
          <ol className="text-sm space-y-1 max-h-72 overflow-auto" data-testid="ig-rotation">
            {(q.order || []).map((m, i) => (
              <li key={m.slug} className="flex items-center gap-2" data-testid="ig-rotation-item">
                <span className="text-xs text-muted-foreground w-6">{i + 1}.</span><span className={m.done ? 'text-muted-foreground line-through' : ''}>{m.name}</span>
                {q.current?.slug === m.slug && <Pill label="prossima" color={C.gold} />}
              </li>
            ))}
          </ol>
          {!!(q.skipped_no_public_media || []).length && <div className="text-xs mt-2" style={{ color: C.warn }} data-testid="ig-no-public-media">Senza media pubblici (saltate): {q.skipped_no_public_media.join(', ')}</div>}
          {!!notSafeSlugs.length && <div className="text-xs mt-1" style={{ color: C.warn }} data-testid="ig-not-safe">Media scartati (non IG-safe): {notSafeSlugs.map((k) => `${k} (${notSafe[k].length})`).join(', ')}</div>}
        </SectionCard>
      </div>

      <SectionCard title="Log tecnico" desc="Solo l'essenziale: quando, chi, quale media, tipo post, esito.">
        {logs.length ? logs.map((l) => (
          <div key={l.id} className="flex flex-wrap items-center gap-2 py-2 border-b border-border/40 last:border-0 text-sm" data-testid="ig-log-item">
            <span className="text-xs text-muted-foreground w-24">{fmtTime(l.timestamp)}</span>
            <Pill label={STATUS_LABEL[l.status] || l.status} color={STATUS_COLOR[l.status] || C.muted} />
            <span className="font-medium">{l.model_name || '—'}</span>
            <span className="text-xs text-muted-foreground">{l.post_type ? `${l.post_type}` : (l.media_type || '')}{l.ig_media_id ? ` · id ${l.ig_media_id}` : ''}{l.cycle_number ? ` · ciclo #${l.cycle_number}` : ''}{l.error_code ? ` · ${l.error_code}` : ''}{l.slot_id ? ` · ${l.slot_id}` : ''}{l.copy_source ? ` · ${l.copy_source}` : ''}{l.mock ? ' · mock' : ''}</span>
          </div>
        )) : <div className="text-sm text-muted-foreground py-4 text-center" data-testid="ig-log-empty">Nessuna pubblicazione ancora.</div>}
      </SectionCard>
    </div>
  );
}
