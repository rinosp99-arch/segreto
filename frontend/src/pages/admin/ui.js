import { useState } from 'react';
import { mediaUrl } from '@/lib/api';
import { uploadMedia } from '@/lib/adminApi';
import { Upload, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

export function SectionCard({ title, desc, children, className = '' }) {
  return (
    <div className={`rounded-2xl border border-border/60 bg-card p-5 mb-5 ${className}`}>
      {title && <div className="mb-4"><h3 className="font-serif text-xl">{title}</h3>{desc && <p className="text-xs text-muted-foreground mt-1">{desc}</p>}</div>}
      {children}
    </div>
  );
}

export function Field({ label, children, hint }) {
  return (
    <label className="block mb-4">
      <span className="caps-label text-muted-foreground block mb-1.5">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-muted-foreground/70 block mt-1">{hint}</span>}
    </label>
  );
}

const inputCls = 'w-full rounded-lg bg-background border border-border px-3 py-2.5 text-sm outline-none focus:border-primary/60 transition-colors';

export function TextInput(props) { return <input {...props} className={`${inputCls} ${props.className || ''}`} />; }
export function TextArea(props) { return <textarea {...props} className={`${inputCls} min-h-[90px] ${props.className || ''}`} />; }
export function SelectInput({ children, ...props }) { return <select {...props} className={`${inputCls} ${props.className || ''}`}>{children}</select>; }

export function Toggle({ checked, onChange, label }) {
  return (
    <button type="button" onClick={() => onChange(!checked)} className="flex items-center gap-3">
      <span className="relative h-6 w-11 rounded-full transition-colors" style={{ background: checked ? 'hsl(var(--primary))' : 'hsl(var(--muted))' }}>
        <span className="absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all" style={{ left: checked ? '22px' : '2px' }} />
      </span>
      {label && <span className="text-sm">{label}</span>}
    </button>
  );
}

export function Btn({ variant = 'primary', className = '', children, ...props }) {
  const base = 'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition-all disabled:opacity-50';
  const styles = {
    primary: 'btn-gold',
    ghost: 'border border-border text-muted-foreground hover:text-foreground',
    danger: 'border text-red-300 hover:bg-red-500/10',
  };
  return <button {...props} className={`${base} ${styles[variant]} ${className}`} style={variant === 'danger' ? { borderColor: 'hsl(0 55% 45% / 0.5)' } : {}}>{children}</button>;
}

export function UploadField({ label, value, onChange, accept = 'image/*,video/*', hint, statusKey, overrides, onOverride }) {
  const [busy, setBusy] = useState(false);
  const handleFile = async (e) => {
    const file = e.target.files?.[0]; if (!file) return;
    setBusy(true);
    try { const res = await uploadMedia(file); onChange(res.url); toast.success('File caricato'); }
    catch (err) { toast.error(err?.response?.data?.detail || 'Errore caricamento'); }
    finally { setBusy(false); }
  };
  const ov = statusKey && overrides ? (overrides[statusKey] || 'auto') : null;
  return (
    <Field label={label} hint={hint}>
      <div className="flex gap-2 items-start">
        <div className="h-20 w-20 rounded-lg overflow-hidden border border-border bg-muted/40 shrink-0 flex items-center justify-center">
          {value ? (
            (value.includes('.mp4') || value.includes('.webm'))
              ? <video src={mediaUrl(value)} className="h-full w-full object-cover" muted />
              : <img src={mediaUrl(value)} alt="" className="h-full w-full object-cover" />
          ) : <span className="text-[10px] text-muted-foreground">vuoto</span>}
        </div>
        <div className="flex-1">
          <TextInput value={value || ''} onChange={(e) => onChange(e.target.value)} placeholder="URL o carica un file" />
          <div className="mt-2 flex items-center gap-2 flex-wrap">
            <label className="inline-flex items-center gap-2 text-xs px-3 py-1.5 rounded-lg border border-border cursor-pointer hover:border-primary/60 transition-colors">
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />} Carica
              <input type="file" accept={accept} onChange={handleFile} className="hidden" disabled={busy} />
            </label>
            {statusKey && onOverride && (
              <span className="inline-flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground caps-label">Tipo</span>
                <select value={ov} onChange={(e) => onOverride(statusKey, e.target.value)} data-testid={`override-${statusKey}`}
                  className="rounded-lg bg-background border border-border px-2 py-1 text-[11px] outline-none focus:border-primary/60">
                  <option value="auto">Automatico</option>
                  <option value="demo">Demo</option>
                  <option value="reale">Reale</option>
                </select>
              </span>
            )}
          </div>
        </div>
      </div>
    </Field>
  );
}
