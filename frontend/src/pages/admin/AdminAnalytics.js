import { useEffect, useState } from 'react';
import { anOverview, anFunnel, anModels, anTimeseries } from '@/lib/adminApi';
import { SectionCard } from '@/pages/admin/ui';
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

const RANGES = [{ k: 'oggi', l: 'Oggi' }, { k: '7g', l: '7 giorni' }, { k: '30g', l: '30 giorni' }];

export default function AdminAnalytics() {
  const [range, setRange] = useState('30g');
  const [ov, setOv] = useState(null);
  const [funnel, setFunnel] = useState(null);
  const [rows, setRows] = useState([]);
  const [ts, setTs] = useState([]);

  useEffect(() => {
    anOverview(range).then(setOv).catch(() => {});
    anFunnel(range).then((d) => setFunnel(d.steps || [])).catch(() => {});
    anModels(range).then((d) => setRows(d.items || [])).catch(() => {});
    anTimeseries(range).then((d) => setTs(d.items || [])).catch(() => {});
  }, [range]);

  const axis = { stroke: 'hsl(var(--muted-foreground))', fontSize: 11 };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="font-serif text-3xl">Analytics</h1>
        <div className="flex gap-1 bg-card border border-border/60 rounded-full p-1">
          {RANGES.map((r) => <button key={r.k} onClick={() => setRange(r.k)} className={`px-3 py-1.5 text-xs rounded-full ${range === r.k ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`}>{r.l}</button>)}
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
        {[['Visite', ov?.visite], ['Attivazioni', ov?.attivazioni], ['Click OF', ov?.click_of], ['CTR medio', (ov?.ctr_medio ?? 0) + '%']].map(([l, v], i) => (
          <div key={i} className="rounded-2xl border border-border/60 bg-card p-4" data-testid="analytics-kpi-card"><div className="caps-label text-muted-foreground mb-1">{l}</div><div className="text-3xl font-serif">{v ?? '—'}</div></div>
        ))}
      </div>

      <div className="grid lg:grid-cols-2 gap-5 mb-5">
        <SectionCard title="Andamento">
          <div style={{ height: 220 }} data-testid="analytics-chart">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={ts}>
                <defs><linearGradient id="g1" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="hsl(var(--chart-1))" stopOpacity={0.5} /><stop offset="100%" stopColor="hsl(var(--chart-1))" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="giorno" tick={axis} tickFormatter={(d) => d?.slice(5)} />
                <YAxis tick={axis} allowDecimals={false} />
                <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 10, fontSize: 12 }} />
                <Area type="monotone" dataKey="visite" stroke="hsl(var(--chart-1))" fill="url(#g1)" />
                <Area type="monotone" dataKey="attivazioni" stroke="hsl(var(--chart-2))" fillOpacity={0} />
                <Area type="monotone" dataKey="click_of" stroke="hsl(var(--accent))" fillOpacity={0} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>
        <SectionCard title="Funnel">
          <div style={{ height: 220 }} data-testid="analytics-funnel-chart">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnel} layout="vertical" margin={{ left: 20 }}>
                <XAxis type="number" tick={axis} allowDecimals={false} />
                <YAxis type="category" dataKey="nome" tick={axis} width={90} />
                <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 10, fontSize: 12 }} />
                <Bar dataKey="valore" fill="hsl(var(--chart-1))" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Classifica modelle">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-muted-foreground caps-label text-[10px]"><th className="py-2">Modella</th><th>Visite</th><th>Segreto %</th><th>Msg</th><th>Click OF</th><th>CTR</th><th>T. medio</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border/50">
                  <td className="py-2.5 font-serif text-base">{r.nome_artistico}</td>
                  <td>{r.visite}</td><td>{r.perc_attivazione}%</td><td>{r.messaggi_aperti}</td><td>{r.click_of}</td>
                  <td className="gold-text font-semibold">{r.ctr_of}%</td><td className="text-muted-foreground">{r.tempo_medio_segreto}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}
