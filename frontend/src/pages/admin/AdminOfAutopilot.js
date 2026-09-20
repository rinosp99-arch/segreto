import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { Lock, RefreshCw, PlugZap, Loader2, ShieldCheck, Server, Link2, User, HeartPulse, Send, CalendarClock } from 'lucide-react';
import { ofApConnection, ofApTestConnection } from '@/lib/adminApi';
import { SectionCard, Btn } from '@/pages/admin/ui';

const C = { ok: 'hsl(150 45% 58%)', warn: 'hsl(38 75% 60%)', fail: 'hsl(0 60% 58%)', muted: 'hsl(var(--muted-foreground))', gold: 'hsl(var(--primary))' };

function Row({ icon: Icon, label, value, color = C.muted, testid }) {
  return (
    <div className="flex items-center justify-between gap-4 py-3 border-b border-border/40 last:border-0" data-testid={testid}>
      <span className="flex items-center gap-2 caps-label text-muted-foreground"><Icon className="h-4 w-4" /> {label}</span>
      <span className="caps-label px-2.5 py-1 rounded-full text-[10px] whitespace-nowrap" style={{ color, border: `1px solid ${color.replace(')', ' / 0.4)')}` }}>{value ?? '—'}</span>
    </div>
  );
}

export default function AdminOfAutopilot() {
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setS(await ofApConnection()); } catch (e) { toast.error('Impossibile leggere lo stato connessione OnlyFans'); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const test = async () => {
    setBusy(true);
    try { const r = await ofApTestConnection(); setS(r); toast.success(`Provider: ${r.CONNECTION_STATUS} · account ${r.ACCOUNT_USERNAME || '—'} · ${r.ACCOUNT_STATUS}`); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Test connessione fallito'); }
    finally { setBusy(false); }
  };

  const connected = s?.CONNECTION_STATUS === 'CONNECTED';
  const healthy = s?.ACCOUNT_STATUS === 'HEALTHY';

  return (
    <div data-testid="of-autopilot-page">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          <h1 className="font-serif text-3xl flex items-center gap-3"><Lock className="h-7 w-7" style={{ color: C.gold }} /> OnlyFans Autopilot</h1>
          <p className="text-sm text-muted-foreground mt-1">Fase connessione: verifica in sola lettura del collegamento all'account OnlyFans Lato Segreto tramite il provider. Nessuna pubblicazione, nessun upload, nessuno scheduler.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Btn variant="ghost" onClick={load} data-testid="of-refresh"><RefreshCw className="h-4 w-4" /> Aggiorna</Btn>
          <Btn onClick={test} disabled={busy} data-testid="of-test-connection">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />} Test connessione (sola lettura)</Btn>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <SectionCard title="Stato connessione" desc={s?.checked_at ? `Ultima verifica: ${new Date(s.checked_at).toLocaleString('it-IT')}` : 'Nessuna verifica ancora'}>
          <Row icon={Server} label="Provider" value={s?.PROVIDER || '—'} color={C.gold} testid="of-provider" />
          <Row icon={Link2} label="Connection" value={s?.CONNECTION_STATUS || '…'} color={connected ? C.ok : (s ? C.fail : C.muted)} testid="of-connection" />
          <Row icon={User} label="Account" value={s?.ACCOUNT_USERNAME || '—'} color={s?.ACCOUNT_USERNAME ? C.ok : C.muted} testid="of-account" />
          <Row icon={HeartPulse} label="Account health" value={s?.ACCOUNT_STATUS || '…'} color={healthy ? C.ok : (s?.ACCOUNT_STATUS === 'UNHEALTHY' ? C.fail : C.muted)} testid="of-health" />
          <Row icon={Send} label="Real posting" value={s?.REAL_POSTING || 'OFF'} color={s?.REAL_POSTING === 'ON' ? C.warn : C.muted} testid="of-real-posting" />
          <Row icon={CalendarClock} label="Auto scheduler" value={s?.AUTO_SCHEDULER || 'OFF'} color={s?.AUTO_SCHEDULER === 'ON' ? C.warn : C.muted} testid="of-auto-scheduler" />
          {s?.error && <div className="text-xs mt-3" style={{ color: C.fail }} data-testid="of-error">Errore: {s.error}</div>}
        </SectionCard>

        <SectionCard title="Sicurezza" desc="Tutte le chiamate avvengono dal backend verso il provider. Nessuna credenziale è mai inviata al browser.">
          <div className="text-sm text-muted-foreground space-y-2" data-testid="of-security-note">
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" style={{ color: C.ok }} /> Credenziali solo nell'ambiente backend, mascherate nei log.</div>
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" style={{ color: C.ok }} /> Piattaforma: {s?.PLATFORM || '—'} · ID account scoperto automaticamente{s?.OF_USER_ID_DISCOVERED ? ` (${s.of_user_id_masked})` : ''}.</div>
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" style={{ color: C.ok }} /> Scritture verso il provider in questa fase: {s?.OF_REAL_WRITE_CALLS ?? 0}.</div>
            <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4" style={{ color: C.ok }} /> Coda programmata leggibile: {s?.schedules_read === true ? `sì (${s.scheduled_count_sample ?? 0} in coda)` : (s?.schedules_read === false ? 'no' : '—')}.</div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
