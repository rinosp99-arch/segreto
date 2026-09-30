import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { setNotFoundSeo } from '@/lib/seo';
import { api } from '@/lib/api';

export default function NotFound() {
  const location = useLocation();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);

  useEffect(() => { setNotFoundSeo(); }, []);

  // Safe redirects managed by the SEO engine (e.g. slug changes): resolve before showing the 404
  useEffect(() => {
    let alive = true;
    api.get('/redirects/resolve', { params: { path: location.pathname } })
      .then((r) => { if (alive && r.data?.redirect) navigate(r.data.redirect, { replace: true }); else if (alive) setChecking(false); })
      .catch(() => { if (alive) setChecking(false); });
    return () => { alive = false; };
  }, [location.pathname, navigate]);

  if (checking) return <div className="max-w-2xl mx-auto px-4 py-28" aria-busy="true" />;

  return (
    <div className="max-w-2xl mx-auto px-4 py-28 text-center">
      <div className="caps-label gold-text mb-3">404</div>
      <h1 className="font-serif text-4xl sm:text-5xl mb-3">Qui non c'è nessun Lato Segreto.</h1>
      <p className="text-muted-foreground mb-7">La pagina che cerchi non esiste o è stata rimossa.</p>
      <Link to="/" className="btn-gold inline-block rounded-xl px-7 py-3.5 text-sm" data-testid="not-found-home-button">Torna alle modelle</Link>
    </div>
  );
}
