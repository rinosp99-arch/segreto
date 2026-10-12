import { useEffect, useMemo, useState } from 'react';
import { anSources, admGetModels } from '@/lib/adminApi';
import { SectionCard, Field, SelectInput, TextInput, Btn } from '@/pages/admin/ui';
import { Copy } from 'lucide-react';
import { toast } from 'sonner';

/* Where the visitors come from, for the selected period and compared with the period before (weekly review).
   Numbers come from the site's own visit counter (server/sources.js), not from an external service. */

const PERIOD = { oggi: 'ieri, stesse ore', '7g': '7 giorni precedenti', '30g': '30 giorni precedenti' };
const TAG_SOURCES = ['instagram', 'tiktok', 'telegram', 'facebook', 'onlyfans', 'x', 'whatsapp', 'altro'];

function Delta({ now, before }) {
  const d = now - before;
  if (!before && !now) return null;
  const color = d > 0 ? 'hsl(140 45% 60%)' : d < 0 ? 'hsl(0 60% 68%)' : 'hsl(var(--muted-foreground))';
  return <span className="text-[11px] ml-2" style={{ color }}>{d > 0 ? `+${d}` : d < 0 ? `−${Math.abs(d)}` : '='}</span>;
}

const cell = 'py-2 px-2 text-right tabular-nums';
const head = 'py-2 px-2 text-right caps-label text-muted-foreground font-normal';
const headLeft = 'py-2 px-2 text-left caps-label text-muted-foreground font-normal';

function SourcesTable({ data }) {
  const rows = data.sorgenti.filter((r) => r.visite);
  if (!rows.length) return <p className="text-sm text-muted-foreground">Ancora nessuna visita in questo periodo.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-testid="sources-table">
        <thead>
          <tr className="border-b border-border/60">
            <th className={headLeft}>Sorgente</th>
            <th className={head}>Visite</th>
            <th className={head}>Profili visti</th>
            <th className={head}>Click OnlyFans</th>
            <th className={head}>Click canale</th>
            <th className={head}>Con link marcato</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.chiave} className="border-b border-border/30">
              <td className="py-2 px-2">{r.nome}</td>
              <td className={cell}>{r.visite}<Delta now={r.visite} before={r.visite_prec} /></td>
              <td className={cell}>{r.profili}</td>
              <td className={cell}>{r.click_of}</td>
              <td className={cell}>{r.click_canale}</td>
              <td className={cell}>{r.marcate || '—'}</td>
            </tr>
          ))}
          <tr className="font-semibold">
            <td className="py-2 px-2">Totale</td>
            <td className={cell}>{data.totale.visite}<Delta now={data.totale.visite} before={data.precedente.visite} /></td>
            <td className={cell}>{data.totale.profili}</td>
            <td className={cell}>{data.totale.click_of}<Delta now={data.totale.click_of} before={data.precedente.click_of} /></td>
            <td className={cell}>{data.totale.click_canale}</td>
            <td className={cell} />
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function LinkBuilder() {
  const [models, setModels] = useState([]);
  const [page, setPage] = useState('/');
  const [source, setSource] = useState('instagram');
  const [custom, setCustom] = useState('');
  const [campaign, setCampaign] = useState('bio');
  useEffect(() => { admGetModels('pubblicata').then((d) => setModels(d.items || d || [])).catch(() => {}); }, []);

  const clean = (s) => s.trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '');
  const url = useMemo(() => {
    const fonte = clean(source === 'altro' ? custom : source);
    if (!fonte) return '';
    const q = new URLSearchParams({ fonte });
    if (clean(campaign)) q.set('campagna', clean(campaign));
    return `${window.location.origin}${page}?${q}`;
  }, [page, source, custom, campaign]);

  const copy = () => navigator.clipboard.writeText(url).then(() => toast.success('Link copiato')).catch(() => toast.error('Copia non riuscita: seleziona il link a mano'));

  return (
    <SectionCard title="Crea un link marcato" desc="Per bio, storie e messaggi: chi arriva da questo link viene contato sotto la sorgente scelta, anche quando l'app nasconde la provenienza.">
      <div className="grid sm:grid-cols-3 gap-x-4">
        <Field label="Pagina">
          <SelectInput value={page} onChange={(e) => setPage(e.target.value)}>
            <option value="/">Home</option>
            {models.map((m) => <option key={m.slug} value={`/modelle/${m.slug}`}>{m.nome_artistico || m.nome}</option>)}
          </SelectInput>
        </Field>
        <Field label="Sorgente">
          <SelectInput value={source} onChange={(e) => setSource(e.target.value)}>
            {TAG_SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
          </SelectInput>
          {source === 'altro' && <TextInput className="mt-2" placeholder="es. newsletter" value={custom} onChange={(e) => setCustom(e.target.value)} />}
        </Field>
        <Field label="Campagna" hint="Una parola per distinguere i link: bio, story, reel-12-10">
          <TextInput value={campaign} onChange={(e) => setCampaign(e.target.value)} />
        </Field>
      </div>
      <div className="flex flex-col sm:flex-row gap-2 sm:items-center">
        <code className="flex-1 rounded-lg bg-background border border-border px-3 py-2.5 text-xs break-all" data-testid="tagged-link">{url || 'Scegli una sorgente'}</code>
        <Btn variant="ghost" onClick={copy} disabled={!url}><Copy className="h-4 w-4" />Copia</Btn>
      </div>
    </SectionCard>
  );
}

export default function Sources({ range }) {
  const [data, setData] = useState(null);
  useEffect(() => { setData(null); anSources(range).then(setData).catch(() => setData(false)); }, [range]);
  const max = data ? Math.max(1, ...data.giorni.map((g) => g.visite)) : 1;

  return (
    <div className="mt-5">
      <SectionCard title="Provenienza dei visitatori" desc={`Visite per sorgente. La differenza accanto al numero è rispetto a: ${PERIOD[range] || PERIOD['7g']}.`}>
        {data === null && <div className="h-32 rounded-xl animate-pulse bg-muted/50" />}
        {data === false && <p className="text-sm text-muted-foreground">Dati non disponibili al momento.</p>}
        {data && (
          <>
            <SourcesTable data={data} />
            <p className="text-[11px] text-muted-foreground/80 mt-3 leading-relaxed">
              «Diretto / origine non rilevata» comprende chi digita l'indirizzo e chi arriva da app che nascondono la provenienza
              (spesso Instagram, WhatsApp, Telegram). Per contare con certezza usa un link marcato. «Click canale» = click sul canale
              OnlyFans generale del brand.
            </p>
          </>
        )}
      </SectionCard>

      {data && (
        <div className="grid lg:grid-cols-2 gap-5">
          <SectionCard title="Visite per giorno">
            {data.giorni.length === 0 ? <p className="text-sm text-muted-foreground">Ancora nessun dato.</p> : (
              <div className="space-y-2">
                {data.giorni.map((g) => (
                  <div key={g.giorno} className="flex items-center gap-3 text-sm">
                    <span className="w-24 text-muted-foreground">{new Date(`${g.giorno}T12:00:00`).toLocaleDateString('it-IT', { weekday: 'short', day: '2-digit', month: '2-digit' })}</span>
                    <div className="flex-1 h-2.5 rounded-full bg-muted overflow-hidden"><div className="h-full rounded-full" style={{ width: `${(g.visite / max) * 100}%`, background: 'hsl(var(--primary))' }} /></div>
                    <span className="w-10 text-right tabular-nums">{g.visite}</span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title="Profili più visti">
            {data.top_profili.length === 0 ? <p className="text-sm text-muted-foreground">Ancora nessun dato.</p> : (
              <table className="w-full text-sm">
                <thead><tr className="border-b border-border/60"><th className={headLeft}>Profilo</th><th className={head}>Visite</th><th className={head}>Click OnlyFans</th></tr></thead>
                <tbody>
                  {data.top_profili.map((p) => (
                    <tr key={p.slug} className="border-b border-border/30"><td className="py-2 px-2">{p.nome}</td><td className={cell}>{p.visite}</td><td className={cell}>{p.click_of}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
          </SectionCard>
        </div>
      )}

      {data && data.campagne.length > 0 && (
        <SectionCard title="Link marcati">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-border/60"><th className={headLeft}>Sorgente</th><th className={headLeft}>Campagna</th><th className={head}>Visite</th><th className={head}>Profili visti</th><th className={head}>Click OnlyFans</th></tr></thead>
            <tbody>
              {data.campagne.map((c) => (
                <tr key={`${c.fonte}|${c.campagna}`} className="border-b border-border/30"><td className="py-2 px-2">{c.fonte}</td><td className="py-2 px-2">{c.campagna}</td><td className={cell}>{c.visite}</td><td className={cell}>{c.profili}</td><td className={cell}>{c.click_of}</td></tr>
              ))}
            </tbody>
          </table>
        </SectionCard>
      )}

      <LinkBuilder />
    </div>
  );
}
