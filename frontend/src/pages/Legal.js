import { useEffect } from 'react';
import { setSeo } from '@/lib/seo';

// Operator of the site, as supplied by the owners on 13.11.2026. Same text in server/seo.js (LEGAL_BODY) for the HTML without JavaScript.
const OPERATOR = ['novag LLC', '30 N Gould St Ste N', 'Sheridan, WY 82801', 'Stati Uniti'];
const OPERATOR_EIN = '37-1299036';
const OPERATOR_EMAIL = 'novag.management69@gmail.com';

// operator: the address block is shown after paragraph number `after`
const CONTENT = {
  'note-legali': { t: 'Note legali', final: true, operator: { after: 1, ein: true }, b: [
    'Il sito LATO SEGRETO è gestito da:',
  ] },
  'privacy': { t: 'Informativa sulla Privacy', operator: { after: 2 }, b: [
    'La presente informativa descrive come vengono trattati i dati degli utenti di LATO SEGRETO.',
    'Titolare del trattamento dei dati è:',
    'Raccogliamo dati di navigazione anonimi e aggregati a fini statistici (visite, interazioni), tramite tecnologie first-party. Non raccogliamo dati sensibili.',
    'Gli utenti possono gestire le preferenze cookie in qualsiasi momento tramite il banner dedicato.',
  ] },
  'cookie': { t: 'Cookie Policy', b: [
    'Utilizziamo cookie tecnici necessari al funzionamento del sito e cookie di misurazione delle performance.',
    'I cookie non essenziali vengono attivati solo previo consenso. Puoi accettare o rifiutare dal banner.',
  ] },
  'termini': { t: 'Termini e Condizioni', b: [
    'L\'accesso a LATO SEGRETO è riservato esclusivamente a maggiorenni (18+).',
    'I contenuti hanno finalità promozionale. I link esterni conducono a piattaforme di terze parti (es. OnlyFans), soggette ai rispettivi termini.',
    'Tutte le creator presenti sono maggiorenni e hanno acconsentito alla promozione del proprio profilo.',
  ] },
  '18-plus': { t: 'Contenuti per Adulti (18+)', b: [
    'Questo sito contiene materiale destinato a un pubblico adulto e consenziente.',
    'Proseguendo dichiari di avere almeno 18 anni e che la visione di tali contenuti è legale nella tua giurisdizione.',
    'L\'architettura del sito è predisposta per integrare, se richiesto dalla normativa, sistemi di verifica dell\'età più avanzati.',
  ] },
};

export default function Legal({ kind }) {
  const c = CONTENT[kind] || CONTENT['privacy'];
  useEffect(() => {
    setSeo({ title: `${c.t} | LATO SEGRETO`, description: c.t });
    window.scrollTo(0, 0); // reached from the footer: otherwise the short page opens scrolled down, heading under the header
  }, [kind]);
  return (
    <div className="max-w-2xl mx-auto px-4 lg:px-6 py-12">
      <h1 className="text-4xl font-serif mb-6">{c.t}</h1>
      <div className="space-y-4 text-foreground/85 leading-relaxed">
        {c.b.slice(0, c.operator ? c.operator.after : c.b.length).map((p, i) => <p key={i}>{p}</p>)}
        {c.operator && (
          <>
            <address className="not-italic" data-testid="legal-operator">
              <strong>{OPERATOR[0]}</strong><br />
              {OPERATOR.slice(1).map((l) => <span key={l}>{l}<br /></span>)}
            </address>
            {c.operator.ein && <p>EIN (Tax ID): {OPERATOR_EIN}</p>}
            <p>Email: <a href={`mailto:${OPERATOR_EMAIL}`} className="underline underline-offset-4 hover:text-foreground">{OPERATOR_EMAIL}</a></p>
            {c.b.slice(c.operator.after).map((p, i) => <p key={`r${i}`}>{p}</p>)}
          </>
        )}
      </div>
      {!c.final && (
        <div className="mt-8 p-4 rounded-xl border border-border/60 text-xs text-muted-foreground">
          Testo segnaposto. Da sottoporre a revisione legale prima della pubblicazione ufficiale.
        </div>
      )}
    </div>
  );
}
