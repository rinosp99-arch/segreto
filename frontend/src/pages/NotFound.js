import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { setSeo } from '@/lib/seo';

export default function NotFound() {
  useEffect(() => { setSeo({ title: 'Pagina non trovata | LATO SEGRETO', description: 'Pagina non trovata', noindex: true }); }, []);
  return (
    <div className="max-w-2xl mx-auto px-4 py-28 text-center">
      <div className="caps-label gold-text mb-3">404</div>
      <h1 className="font-serif text-4xl sm:text-5xl mb-3">Qui non c'è nessun Lato Segreto.</h1>
      <p className="text-muted-foreground mb-7">La pagina che cerchi non esiste o è stata rimossa.</p>
      <Link to="/" className="btn-gold inline-block rounded-xl px-7 py-3.5 text-sm" data-testid="not-found-home-button">Torna alle modelle</Link>
    </div>
  );
}
