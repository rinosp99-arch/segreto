import { useEffect, useState } from 'react';
import { admGetSettings, admUpdateSettings, changePassword, admAudit } from '@/lib/adminApi';
import { SectionCard, Field, TextInput, TextArea, SelectInput, Toggle, Btn } from '@/pages/admin/ui';
import { toast } from 'sonner';

export default function AdminSettings() {
  const [s, setS] = useState(null);
  const [pw, setPw] = useState('');
  const [audit, setAudit] = useState([]);

  useEffect(() => { admGetSettings().then(setS); admAudit().then((d) => setAudit(d.items || [])); }, []);
  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));
  const setPelli = (k, v) => setS((p) => ({ ...p, home_pellicola: { ...(p.home_pellicola || {}), [k]: v } }));

  const save = async () => { try { await admUpdateSettings(s); toast.success('Impostazioni salvate'); } catch { toast.error('Errore'); } };
  const savePw = async () => { try { await changePassword(pw); toast.success('Password aggiornata'); setPw(''); } catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); } };

  if (!s) return <div className="h-64 animate-pulse bg-muted/40 rounded-2xl" />;

  return (
    <div className="max-w-2xl">
      <h1 className="font-serif text-3xl mb-5">Impostazioni</h1>
      <SectionCard title="Sito">
        <Field label="Nome brand"><TextInput value={s.brand_name || ''} onChange={(e) => set('brand_name', e.target.value)} /></Field>
        <Field label="Descrizione sito"><TextArea value={s.site_description || ''} onChange={(e) => set('site_description', e.target.value)} /></Field>
        <Field label="Contatti footer"><TextInput value={s.footer_contatti || ''} onChange={(e) => set('footer_contatti', e.target.value)} /></Field>
        <Field label="Switch home predefinito"><SelectInput value={s.global_switch_default || 'public'} onChange={(e) => set('global_switch_default', e.target.value)}><option value="public">Lato Pubblico</option><option value="secret">Lato Segreto (teaser)</option></SelectInput></Field>
        <Btn onClick={save} data-testid="save-settings-button">Salva</Btn>
      </SectionCard>

      <SectionCard title="HOME → PELLICOLA «IN MOVIMENTO»" desc="Controlla la fascia cinematografica in Home. I video attivi contemporaneamente sono limitati per le performance.">
        {(() => { const p = s.home_pellicola || {}; return (
          <>
            <div className="flex flex-wrap items-center gap-6 mb-3">
              <Toggle checked={p.attiva !== false} onChange={(v) => setPelli('attiva', v)} label="Attiva pellicola" />
              <Toggle checked={!!p.pausa_su_touch} onChange={(v) => setPelli('pausa_su_touch', v)} label="Pausa su touch/hover" />
              <Toggle checked={!!p.nomi_sempre_visibili} onChange={(v) => setPelli('nomi_sempre_visibili', v)} label="Nomi sempre visibili" />
              <Toggle checked={!!p.seconda_fila} onChange={(v) => setPelli('seconda_fila', v)} label="Seconda fila (in senso opposto)" />
            </div>
            <div className="grid sm:grid-cols-2 gap-x-4">
              <Field label="Titolo"><TextInput value={p.titolo || ''} onChange={(e) => setPelli('titolo', e.target.value)} placeholder="IN MOVIMENTO" /></Field>
              <Field label="Sottotitolo"><TextInput value={p.sottotitolo || ''} onChange={(e) => setPelli('sottotitolo', e.target.value)} placeholder="Una foto non racconta tutto." /></Field>
            </div>
            <div className="grid sm:grid-cols-3 gap-x-4">
              <Field label="Velocità (sec per video)" hint="3 = veloce · 12 = lenta">
                <TextInput type="number" min="3" max="14" value={p.velocita ?? 6} onChange={(e) => setPelli('velocita', Math.max(3, Math.min(14, parseInt(e.target.value || '6', 10))))} data-testid="pellicola-velocita" />
              </Field>
              <Field label="Max video attivi" hint="Consigliato 6–10">
                <TextInput type="number" min="4" max="12" value={p.max_video_attivi ?? 8} onChange={(e) => setPelli('max_video_attivi', Math.max(4, Math.min(12, parseInt(e.target.value || '8', 10))))} data-testid="pellicola-maxvideo" />
              </Field>
              <Field label="Inserisci dopo N card" hint="Tra 8 e 12">
                <TextInput type="number" min="4" max="20" value={p.inserisci_dopo_n ?? 10} onChange={(e) => setPelli('inserisci_dopo_n', Math.max(4, Math.min(20, parseInt(e.target.value || '10', 10))))} />
              </Field>
            </div>
            <Btn onClick={save} data-testid="save-pellicola-button">Salva pellicola</Btn>
          </>
        ); })()}
      </SectionCard>

      <SectionCard title="Integrazione SEO (Soro)" desc="Endpoint webhook per contenuti esterni. La chiave API è configurata lato server (backend/.env) e non viene mostrata qui.">
        <div className="p-3 rounded-lg border border-border/60 text-xs font-mono mb-3">POST /api/integrations/seo/articles</div>
        <div className="flex items-center justify-between p-3 rounded-lg border border-border/60">
          <div><div className="text-sm">Pubblicazione automatica</div><div className="text-xs text-muted-foreground">Se disattivata, i contenuti esterni arrivano come bozza (consigliato).</div></div>
          <Toggle checked={!!s.auto_publish_articles} onChange={(v) => set('auto_publish_articles', v)} />
        </div>
        <div className="mt-3"><Btn onClick={save} variant="ghost">Salva integrazione</Btn></div>
      </SectionCard>

      <SectionCard title="Sicurezza">
        <Field label="Nuova password" hint="Minimo 10 caratteri"><TextInput type="password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        <Btn onClick={savePw} disabled={pw.length < 10}>Aggiorna password</Btn>
      </SectionCard>

      <SectionCard title="Registro attività">
        <div className="space-y-1.5 max-h-64 overflow-auto">
          {audit.map((a) => (
            <div key={a.id} className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="font-mono">{(a.timestamp || '').slice(0, 16).replace('T', ' ')}</span>
              <span className="text-foreground">{a.action}</span><span>{a.entity}</span><span className="truncate">{a.actor}</span>
            </div>
          ))}
          {audit.length === 0 && <p className="text-sm text-muted-foreground">Nessuna attività registrata.</p>}
        </div>
      </SectionCard>
    </div>
  );
}
