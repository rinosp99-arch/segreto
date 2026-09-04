import { useEffect, useState } from 'react';
import { anCampaigns } from '@/lib/adminApi';
import { SectionCard } from '@/pages/admin/ui';
import { Megaphone } from 'lucide-react';

const RANGES = [{ k: 'oggi', l: 'Oggi' }, { k: '7g', l: '7 giorni' }, { k: '30g', l: '30 giorni' }];

export default function AdminCampaigns() {
  const [range, setRange] = useState('30g');
  const [rows, setRows] = useState([]);

  useEffect(() => { anCampaigns(range).then((d) => setRows(d.items || [])).catch(() => setRows([])); }, [range]);

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h1 className="font-serif text-3xl">Campagne</h1>
        <div className="flex gap-1 bg-card border border-border/60 rounded-full p-1">
          {RANGES.map((r) => <button key={r.k} onClick={() => setRange(r.k)} className={`px-3 py-1.5 text-xs rounded-full ${range === r.k ? 'bg-primary/20 text-foreground' : 'text-muted-foreground'}`}>{r.l}</button>)}
        </div>
      </div>
      <p className="text-xs text-muted-foreground mb-5">Attribuzione delle sorgenti tramite link creator (es. /?ref=francesca-rossi&fonte=instagram&campagna=settembre).</p>

      <SectionCard>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="campaigns-table">
            <thead><tr className="text-left text-muted-foreground caps-label text-[10px]"><th className="py-2">Modella</th><th>Fonte</th><th>Campagna</th><th>Visite</th><th>Aperture profilo</th><th>Lato Segreto</th><th>Click OF</th><th>CTR OF</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-border/50">
                  <td className="py-2.5 font-serif text-base">{r.modella}</td>
                  <td className="capitalize">{r.fonte}</td>
                  <td className="text-muted-foreground">{r.campagna}</td>
                  <td>{r.visite}</td><td>{r.aperture_profilo}</td><td>{r.attivazioni}</td><td>{r.click_of}</td>
                  <td className="gold-text font-semibold">{r.ctr_of}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="py-10 text-center text-sm text-muted-foreground flex flex-col items-center gap-2">
              <Megaphone className="h-8 w-8" />
              Nessun dato campagna per questo periodo. Genera un link promozionale dalla scheda di una modella e condividilo.
            </div>
          )}
        </div>
      </SectionCard>
    </div>
  );
}
