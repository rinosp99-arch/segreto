import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { anOverview, anFunnel } from '@/lib/adminApi';
import { SectionCard } from '@/pages/admin/ui';
import { Eye, Flame, MousePointerClick, TrendingUp } from 'lucide-react';

const RANGES = [{ k: 'oggi', l: 'Oggi' }, { k: '7g', l: '7 giorni' }, { k: '30g', l: '30 giorni' }];

function Kpi({ icon: Icon, label, value, suffix }) {
  return (
    <div className="rounded-2xl border border-border/60 bg-card p-4" data-testid="analytics-kpi-card">
      <div className="flex items-center gap-2 caps-label text-muted-foreground mb-2"><Icon className="h-4 w-4" />{label}</div>
      <div className="text-3xl font-serif">{value}{suffix}</div>
    </div>
  );
}

export default function Dashboard() {
  const [range, setRange] = useState('7g');
  const [ov, setOv] = useState(null);
  const [funnel, setFunnel] = useState(null);

  useEffect(() => {
    anOverview(range).then(setOv).catch(() => {});
    anFunnel(range).then(setFunnel).catch(() => {});
  }, [range]);

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">Dashboard</h1>
        <div className="flex gap-1 bg-card border border-border/60 rounded-full p-1">
          {RANGES.map((r) => (
            <button key={r.k} onClick={() => setRange(r.k)} className={`px-3 py-1.5 text-xs rounded-full transition-colors ${range === r.k ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`}>{r.l}</button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        <Kpi icon={Eye} label="Visite" value={ov?.visite ?? '—'} />
        <Kpi icon={Flame} label="Lati Segreti" value={ov?.attivazioni ?? '—'} />
        <Kpi icon={MousePointerClick} label="Click OnlyFans" value={ov?.click_of ?? '—'} />
        <Kpi icon={TrendingUp} label="CTR medio" value={ov?.ctr_medio ?? '—'} suffix="%" />
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        <SectionCard title="Funnel di conversione">
          <div className="space-y-3">
            {funnel?.steps?.map((s, i) => (
              <div key={i}>
                <div className="flex justify-between text-sm mb-1"><span>{s.nome}</span><span className="text-muted-foreground">{s.valore} · {s.percentuale}%</span></div>
                <div className="h-2.5 rounded-full bg-muted overflow-hidden"><div className="h-full rounded-full" style={{ width: `${s.percentuale}%`, background: 'hsl(var(--primary))' }} /></div>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title="In evidenza">
          {ov?.modella_top_visite ? (
            <div className="space-y-4">
              <Link to={`/admin/modelle`} className="flex items-center gap-3">
                <div className="text-xs caps-label text-muted-foreground w-24">Più visitata</div>
                <div className="font-serif text-lg">{ov.modella_top_visite.nome_artistico}</div>
                <div className="ml-auto text-sm text-muted-foreground">{ov.modella_top_visite.visite} visite</div>
              </Link>
              {ov.modella_top_ctr && (
                <div className="flex items-center gap-3">
                  <div className="text-xs caps-label text-muted-foreground w-24">Miglior CTR</div>
                  <div className="font-serif text-lg">{ov.modella_top_ctr.nome_artistico}</div>
                  <div className="ml-auto text-sm text-muted-foreground">{ov.modella_top_ctr.ctr_of}%</div>
                </div>
              )}
            </div>
          ) : <p className="text-sm text-muted-foreground">Ancora nessun dato per questo periodo.</p>}
          <div className="mt-5 flex gap-2">
            <Link to="/admin/modelle/nuova" className="btn-gold rounded-lg px-4 py-2 text-sm">Nuova modella</Link>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
