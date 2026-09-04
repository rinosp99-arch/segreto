import { Link } from 'react-router-dom';

export function Footer() {
  return (
    <footer className="mt-20 border-t border-border/60">
      <div className="max-w-6xl mx-auto px-4 lg:px-8 py-10">
        <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6">
          <div>
            <div className="font-serif text-xl mb-2">LATO <span className="gold-text">SEGRETO</span></div>
            <p className="text-xs text-muted-foreground max-w-sm leading-relaxed">
              Il lato che non hai ancora visto. Uno spazio premium riservato a un pubblico adulto.
              Tutte le creator sono maggiorenni.
            </p>
          </div>
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
            <Link to="/18-plus" className="text-muted-foreground hover:text-foreground transition-colors">18+</Link>
            <Link to="/privacy" className="text-muted-foreground hover:text-foreground transition-colors">Privacy</Link>
            <Link to="/cookie" className="text-muted-foreground hover:text-foreground transition-colors">Cookie</Link>
            <Link to="/termini" className="text-muted-foreground hover:text-foreground transition-colors">Termini</Link>
            <Link to="/articoli" className="text-muted-foreground hover:text-foreground transition-colors">Rivista</Link>
          </div>
        </div>
        <div className="hairline mt-8 pt-6 flex flex-col sm:flex-row justify-between gap-2 text-[11px] text-muted-foreground/70">
          <span>© {new Date().getFullYear()} LATO SEGRETO. Tutti i diritti riservati.</span>
          <span>I link esterni conducono a profili di terze parti (OnlyFans). Contenuti per adulti.</span>
        </div>
      </div>
    </footer>
  );
}
