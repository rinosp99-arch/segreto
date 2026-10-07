import { useCallback, useEffect, useState } from 'react';
import { aiGetControl, aiSetControl, aiGetKeys, aiCreateKey, aiToggleKey, aiDeleteKey, aiGetActions } from '@/lib/adminApi';
import { SectionCard, Field, TextInput, SelectInput, Toggle, Btn } from '@/pages/admin/ui';
import { toast } from 'sonner';

const when = (iso) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—');
const copy = (text, label) => navigator.clipboard.writeText(text).then(() => toast.success(`${label} copiato`), () => toast.error('Copia non riuscita: seleziona e copia a mano'));

// Settings section for the AI interface a custom GPT uses (/api/v2/ai): switches, keys, last actions.
export default function AiControl() {
  const [ctl, setCtl] = useState(null);
  const [keys, setKeys] = useState([]);
  const [actions, setActions] = useState([]);
  const [name, setName] = useState('');
  const [preset, setPreset] = useState('read_only');
  const [fresh, setFresh] = useState(null); // the new key, shown once

  const load = useCallback(() => {
    aiGetControl().then(setCtl).catch(() => {});
    aiGetKeys().then((d) => setKeys(d.items || [])).catch(() => {});
    aiGetActions(20).then((d) => setActions(d.items || [])).catch(() => {});
  }, []);
  useEffect(load, [load]);

  const fail = (e) => toast.error(e?.response?.data?.detail || 'Errore');
  const flag = (patch, msg) => aiSetControl(patch).then((d) => { setCtl(d); toast.success(msg); }).catch(fail);
  const create = () => aiCreateKey(name.trim(), preset).then((k) => { setFresh(k); setName(''); load(); }).catch(fail);
  const toggle = (k) => aiToggleKey(k.id, !k.disabled).then(load).catch(fail);
  const remove = (k) => { if (window.confirm(`Eliminare definitivamente la chiave «${k.name}»? Il GPT che la usa smette subito di funzionare.`)) aiDeleteKey(k.id).then(load).catch(fail); };

  if (!ctl) return null;
  const full = ctl.mode === 'FULL';

  return (
    <SectionCard title="Interfaccia AI (Custom GPT)" desc="Permette a un GPT personalizzato di leggere e gestire il sito con una chiave dedicata. Ogni modifica è registrata e annullabile.">
      <div className="flex flex-wrap items-center gap-6 mb-2">
        <Toggle checked={ctl.ai_api_enabled} onChange={(v) => flag({ ai_api_enabled: v }, v ? 'Interfaccia AI attiva' : 'Interfaccia AI spenta')} label="Interfaccia attiva" />
        <Toggle checked={full} onChange={(v) => flag({ ai_write_enabled: v }, v ? 'Modalità FULL' : 'Modalità READ_ONLY')} label="Modifiche consentite (FULL)" />
      </div>
      <p className="text-xs text-muted-foreground mb-4" data-testid="ai-mode">
        {!ctl.ai_api_enabled ? 'Spenta: tutte le chiavi sono bloccate subito (interruttore di emergenza).'
          : full ? 'FULL: il GPT può applicare modifiche. Le azioni delicate chiedono comunque conferma.'
            : 'READ_ONLY: il GPT può solo leggere e mostrare anteprime, non cambia nulla.'}
      </p>

      <Field label="Schema da importare nel GPT" hint="GPT → Configura → Azioni → Importa da URL. Autenticazione: API Key, tipo Bearer.">
        <div className="flex gap-2">
          <TextInput readOnly value={ctl.schema_url} onFocus={(e) => e.target.select()} className="font-mono text-xs" />
          <Btn variant="ghost" onClick={() => copy(ctl.schema_url, 'URL')}>Copia</Btn>
        </div>
      </Field>

      <div className="grid sm:grid-cols-[1fr_auto_auto] gap-x-3 items-end">
        <Field label="Nuova chiave"><TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="es. GPT AI CONTROL" maxLength={80} /></Field>
        <Field label="Permessi"><SelectInput value={preset} onChange={(e) => setPreset(e.target.value)}><option value="read_only">Solo lettura</option><option value="full">Completi</option></SelectInput></Field>
        <div className="mb-4"><Btn onClick={create} disabled={!name.trim()} data-testid="ai-create-key">Crea chiave</Btn></div>
      </div>
      {fresh && (
        <div className="p-3 rounded-lg border mb-4" style={{ borderColor: 'hsl(38 75% 60% / 0.5)' }} data-testid="ai-new-key">
          <div className="text-sm mb-2">Chiave «{fresh.name}» creata. <strong>Copiala adesso: non verrà più mostrata.</strong></div>
          <div className="flex gap-2">
            <TextInput readOnly value={fresh.key} onFocus={(e) => e.target.select()} className="font-mono text-xs" />
            <Btn variant="ghost" onClick={() => copy(fresh.key, 'Chiave')}>Copia</Btn>
            <Btn variant="ghost" onClick={() => setFresh(null)}>Fatto</Btn>
          </div>
        </div>
      )}

      <div className="space-y-2 mb-5">
        {keys.map((k) => (
          <div key={k.id} className="flex flex-wrap items-center gap-3 p-3 rounded-lg border border-border/60 text-sm">
            <div className="flex-1 min-w-[10rem]">
              <div className={k.disabled ? 'line-through text-muted-foreground' : ''}>{k.name}</div>
              <div className="text-xs text-muted-foreground font-mono">{k.prefix}… · {k.preset === 'full' ? 'completi' : 'solo lettura'} · ultimo uso {when(k.last_used_at)}</div>
            </div>
            <Btn variant="ghost" onClick={() => toggle(k)}>{k.disabled ? 'Riattiva' : 'Disattiva'}</Btn>
            <Btn variant="danger" onClick={() => remove(k)}>Elimina</Btn>
          </div>
        ))}
        {keys.length === 0 && <p className="text-sm text-muted-foreground">Nessuna chiave. Senza chiave nessun GPT può accedere.</p>}
      </div>

      <div className="caps-label text-muted-foreground mb-1.5">Ultime 20 azioni del GPT</div>
      <div className="space-y-1.5 max-h-64 overflow-auto">
        {actions.map((a) => (
          <div key={a.id} className="flex items-center gap-3 text-xs text-muted-foreground" title={a.summary || ''}>
            <span className="font-mono">{when(a.ts)}</span>
            <span style={{ color: a.ok ? 'hsl(150 45% 58%)' : 'hsl(0 60% 65%)' }}>{a.ok ? 'ok' : a.code || 'errore'}</span>
            <span className="text-foreground">{a.action}</span>
            <span>{a.kind === 'dry_run' ? 'anteprima' : 'esecuzione'}</span>
            <span className="truncate">{a.target || ''} · {a.key_name || ''}</span>
          </div>
        ))}
        {actions.length === 0 && <p className="text-sm text-muted-foreground">Ancora nessuna azione.</p>}
      </div>
    </SectionCard>
  );
}
