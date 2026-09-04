import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { admGetModels, admSetStatus, admDeleteModel, admReorder } from '@/lib/adminApi';
import { mediaUrl } from '@/lib/api';
import { Btn } from '@/pages/admin/ui';
import { Plus, ChevronUp, ChevronDown, Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

const STATO_STYLE = {
  pubblicata: { c: 'hsl(150 40% 55%)', b: 'hsl(150 40% 55% / 0.4)' },
  bozza: { c: 'hsl(38 70% 60%)', b: 'hsl(38 70% 60% / 0.4)' },
  disattivata: { c: 'hsl(0 55% 60%)', b: 'hsl(0 55% 60% / 0.4)' },
};

export default function AdminModels() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [demoTot, setDemoTot] = useState(0);

  const load = () => {
    setLoading(true);
    admGetModels().then((d) => { setItems(d.items || []); setDemoTot(d.demo_totale || 0); }).finally(() => setLoading(false));
  };
  useEffect(() => { load(); }, []);

  const toggleStatus = async (m) => {
    const next = m.stato === 'pubblicata' ? 'bozza' : 'pubblicata';
    try { await admSetStatus(m.id, next); toast.success(next === 'pubblicata' ? 'Pubblicata' : 'Messa in bozza'); load(); }
    catch (e) { toast.error(e?.response?.data?.detail || 'Errore'); }
  };
  const del = async (m) => { if (!window.confirm(`Eliminare ${m.nome_artistico}?`)) return; await admDeleteModel(m.id); toast.success('Eliminata'); load(); };
  const move = async (idx, dir) => {
    const arr = [...items]; const j = idx + dir; if (j < 0 || j >= arr.length) return;
    [arr[idx], arr[j]] = [arr[j], arr[idx]]; setItems(arr);
    await admReorder(arr.map((x) => x.id));
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">Modelle</h1>
        <Link to="/admin/modelle/nuova"><Btn data-testid="new-model-button"><Plus className="h-4 w-4" /> Nuova modella</Btn></Link>
      </div>

      {!loading && items.length > 0 && (
        <div className="flex items-center gap-3 mb-4 p-3 rounded-xl border border-border/60 bg-card" data-testid="demo-summary">
          <span className="caps-label text-muted-foreground">Stato contenuti</span>
          <span className="text-sm">
            <span className="gold-text font-semibold" data-testid="demo-count">{demoTot}</span> con contenuti <span style={{ color: 'hsl(38 75% 60%)' }}>DEMO</span>
            <span className="text-muted-foreground"> · </span>
            <span style={{ color: 'hsl(150 45% 58%)' }} className="font-semibold">{items.length - demoTot}</span> con contenuti REALI
          </span>
          <span className="ml-auto text-xs text-muted-foreground">su {items.length} totali</span>
        </div>
      )}
      {loading ? <div className="h-40 animate-pulse bg-muted/40 rounded-2xl" /> : (
        <div className="space-y-2" data-testid="admin-models-list">
          {items.map((m, i) => {
            const ss = STATO_STYLE[m.stato] || STATO_STYLE.bozza;
            return (
              <div key={m.id} className="flex items-center gap-3 rounded-xl border border-border/60 bg-card p-3" data-testid="admin-model-row">
                <div className="flex flex-col">
                  <button onClick={() => move(i, -1)} className="text-muted-foreground hover:text-foreground"><ChevronUp className="h-4 w-4" /></button>
                  <button onClick={() => move(i, 1)} className="text-muted-foreground hover:text-foreground"><ChevronDown className="h-4 w-4" /></button>
                </div>
                <img src={mediaUrl(m.foto_card)} alt="" className="h-14 w-14 rounded-lg object-cover" style={{ objectPosition: 'center 20%' }} />
                <div className="flex-1 min-w-0">
                  <div className="font-serif text-lg leading-none">{m.nome_artistico}</div>
                  <div className="text-xs text-muted-foreground truncate">/{m.slug} {m.badge ? `· ${m.badge}` : ''}</div>
                </div>
                {m.content_status && (
                  m.content_status.is_demo ? (
                    <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" title={`Demo: ${m.content_status.demo_fields.join(', ')}`} style={{ color: 'hsl(38 75% 60%)', border: '1px solid hsl(38 75% 60% / 0.4)' }} data-testid="content-badge-demo">DEMO</span>
                  ) : (
                    <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: 'hsl(150 45% 58%)', border: '1px solid hsl(150 45% 58% / 0.4)' }} data-testid="content-badge-real">REALE</span>
                  )
                )}
                <span className="caps-label px-2.5 py-1 rounded-full text-[10px]" style={{ color: ss.c, border: `1px solid ${ss.b}` }}>{m.stato}</span>
                <button onClick={() => toggleStatus(m)} className="text-xs px-3 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground">{m.stato === 'pubblicata' ? 'Bozza' : 'Pubblica'}</button>
                <Link to={`/admin/modelle/${m.id}`} className="h-9 w-9 flex items-center justify-center rounded-lg border border-border text-muted-foreground hover:text-foreground"><Pencil className="h-4 w-4" /></Link>
                <button onClick={() => del(m)} className="h-9 w-9 flex items-center justify-center rounded-lg border text-red-300" style={{ borderColor: 'hsl(0 55% 45% / 0.4)' }}><Trash2 className="h-4 w-4" /></button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
