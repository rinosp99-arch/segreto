import { useRef, useState } from 'react';
import { mediaUrl } from '@/lib/api';
import { uploadMedia } from '@/lib/adminApi';
import { Btn, SelectInput } from '@/pages/admin/ui';
import { UploadCloud, Link2, Loader2, Trash2, X } from 'lucide-react';
import { toast } from 'sonner';

const SLOTS = [
  { v: 'ignora', l: '— Ignora —' },
  { v: 'foto_card', l: 'Foto card Home' },
  { v: 'foto_pub_1', l: 'Foto Pubblica 1' },
  { v: 'foto_pub_2', l: 'Foto Pubblica 2' },
  { v: 'foto_pub_3', l: 'Foto Pubblica 3' },
  { v: 'foto_sec_1', l: 'Foto Segreta 1' },
  { v: 'foto_sec_2', l: 'Foto Segreta 2' },
  { v: 'foto_sec_3', l: 'Foto Segreta 3' },
  { v: 'video_pub', l: 'Video Pubblico' },
  { v: 'video_sec', l: 'Video Segreto' },
  { v: 'pel_pub', l: 'Video Pellicola Pubblico' },
  { v: 'pel_sec', l: 'Video Pellicola Segreto' },
];

const guessTipo = (url) => (/\.(mp4|webm|mov)(\?|$)/i.test(url) ? 'video' : 'image');
const rid = () => Math.random().toString(36).slice(2, 9);
// smart default slot based on order of arrival
const AUTO_ORDER = ['foto_pub_1', 'foto_sec_1', 'foto_pub_2', 'foto_sec_2', 'foto_pub_3', 'foto_sec_3', 'video_pub', 'video_sec'];

export default function ImportRapido({ onApply, onClose }) {
  const [assets, setAssets] = useState([]);
  const [busy, setBusy] = useState(false);
  const [urls, setUrls] = useState('');
  const [drag, setDrag] = useState(false);
  const fileRef = useRef(null);

  const nextAutoSlot = (currentLen) => AUTO_ORDER[currentLen] || 'ignora';

  const addFiles = async (fileList) => {
    const files = Array.from(fileList || []);
    if (!files.length) return;
    setBusy(true);
    try {
      for (const f of files) {
        try {
          const res = await uploadMedia(f);
          setAssets((prev) => [...prev, { id: rid(), url: res.url, tipo: res.tipo || guessTipo(res.url), name: f.name, slot: nextAutoSlot(prev.length) }]);
        } catch (e) {
          toast.error(`Errore su ${f.name}`);
        }
      }
      toast.success('File caricati');
    } finally { setBusy(false); }
  };

  const addUrls = () => {
    const lines = urls.split('\n').map((l) => l.trim()).filter(Boolean);
    if (!lines.length) return;
    setAssets((prev) => {
      let out = [...prev];
      lines.forEach((u) => { out.push({ id: rid(), url: u, tipo: guessTipo(u), name: u.split('/').pop(), slot: nextAutoSlot(out.length) }); });
      return out;
    });
    setUrls('');
    toast.success(`${lines.length} link aggiunti`);
  };

  const setSlot = (id, slot) => setAssets((prev) => prev.map((a) => (a.id === id ? { ...a, slot } : a)));
  const removeAsset = (id) => setAssets((prev) => prev.filter((a) => a.id !== id));

  const apply = () => {
    const assigned = assets.filter((a) => a.slot && a.slot !== 'ignora');
    if (!assigned.length) { toast.error('Assegna almeno un file a una posizione'); return; }
    onApply(assigned);
    toast.success('Media assegnati al profilo. Ricordati di salvare.');
    onClose();
  };

  return (
    <div className="fixed inset-0 z-[80] flex items-center justify-center p-4" data-testid="import-rapido-modal">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-10 w-full max-w-3xl max-h-[88vh] overflow-auto rounded-2xl border border-border/60 bg-card p-6 card-elev-2">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-serif text-2xl">Import Rapido</h3>
          <button onClick={onClose} className="h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50"><X className="h-5 w-5" /></button>
        </div>

        {/* drag & drop */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
          className="rounded-xl border-2 border-dashed p-6 text-center cursor-pointer transition-colors mb-4"
          style={{ borderColor: drag ? 'hsl(var(--primary))' : 'hsl(var(--border))', background: drag ? 'hsl(var(--primary)/0.06)' : 'transparent' }}
          data-testid="import-dropzone"
        >
          {busy ? <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin" /> : <UploadCloud className="h-6 w-6 mx-auto mb-2 text-muted-foreground" />}
          <div className="text-sm">Trascina qui più file oppure clicca per selezionarli</div>
          <div className="text-[11px] text-muted-foreground mt-1">Immagini e video · caricamento multiplo</div>
          <input ref={fileRef} type="file" multiple accept="image/*,video/*" className="hidden" onChange={(e) => addFiles(e.target.files)} />
        </div>

        {/* url paste */}
        <div className="mb-4">
          <div className="caps-label text-muted-foreground mb-1.5 flex items-center gap-1.5"><Link2 className="h-3.5 w-3.5" /> Incolla più link (uno per riga)</div>
          <textarea value={urls} onChange={(e) => setUrls(e.target.value)} data-testid="import-urls"
            className="w-full rounded-lg bg-background border border-border px-3 py-2.5 text-sm outline-none focus:border-primary/60 min-h-[70px]"
            placeholder={'https://cdn.tuosito.com/foto1.jpg\nhttps://cdn.tuosito.com/video1.mp4'} />
          <Btn variant="ghost" onClick={addUrls} className="mt-2" data-testid="import-add-urls">Aggiungi link</Btn>
        </div>

        {/* assets list */}
        {assets.length > 0 && (
          <div className="space-y-2 mb-4" data-testid="import-assets">
            {assets.map((a) => (
              <div key={a.id} className="flex items-center gap-3 rounded-xl border border-border/60 p-2">
                <div className="h-14 w-14 rounded-lg overflow-hidden border border-border bg-muted/40 shrink-0 flex items-center justify-center">
                  {a.tipo === 'video'
                    ? <video src={mediaUrl(a.url)} className="h-full w-full object-cover" muted />
                    : <img src={mediaUrl(a.url)} alt="" className="h-full w-full object-cover" />}
                </div>
                <div className="flex-1 min-w-0"><div className="text-xs truncate">{a.name || a.url}</div><div className="text-[10px] text-muted-foreground uppercase">{a.tipo}</div></div>
                <SelectInput value={a.slot} onChange={(e) => setSlot(a.id, e.target.value)} className="w-52" data-testid="import-slot-select">
                  {SLOTS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
                </SelectInput>
                <button onClick={() => removeAsset(a.id)} className="text-red-300 h-9 w-9 flex items-center justify-center"><Trash2 className="h-4 w-4" /></button>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Btn variant="ghost" onClick={onClose}>Annulla</Btn>
          <Btn onClick={apply} disabled={assets.length === 0} data-testid="import-apply">Applica assegnazioni</Btn>
        </div>
      </div>
    </div>
  );
}
