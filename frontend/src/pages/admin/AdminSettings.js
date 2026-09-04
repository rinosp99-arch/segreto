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

      <SectionCard title="Integrazione SEO (Soro)" desc="Endpoint webhook per contenuti esterni. La chiave API è configurata lato server (backend/.env) e non viene mostrata qui.">
        <div className="p-3 rounded-lg border border-border/60 text-xs font-mono mb-3">POST /api/integrations/seo/articles</div>
        <div className="flex items-center justify-between p-3 rounded-lg border border-border/60">
          <div><div className="text-sm">Pubblicazione automatica</div><div className="text-xs text-muted-foreground">Se disattivata, i contenuti esterni arrivano come bozza (consigliato).</div></div>
          <Toggle checked={!!s.auto_publish_articles} onChange={(v) => set('auto_publish_articles', v)} />
        </div>
        <div className="mt-3"><Btn onClick={save} variant="ghost">Salva integrazione</Btn></div>
      </SectionCard>

      <SectionCard title="Sicurezza">
        <Field label="Nuova password" hint="Minimo 8 caratteri"><TextInput type="password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
        <Btn onClick={savePw} disabled={pw.length < 8}>Aggiorna password</Btn>
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
