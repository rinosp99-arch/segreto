import { useEffect, useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Search, Shuffle, Menu, X } from 'lucide-react';
import { useTheme } from '@/lib/themeContext';
import { getSurprise, getCategories } from '@/lib/api';
import SearchOverlay from '@/components/layout/SearchOverlay';
import { toast } from 'sonner';

export function Header() {
  const { homeMode, setHomeMode } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === '/';
  const [scrolled, setScrolled] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [cats, setCats] = useState([]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => { getCategories().then((d) => setCats(d.items || [])).catch(() => {}); }, []);

  const surprise = async () => {
    try { const m = await getSurprise(); navigate(`/modelle/${m.slug}`); }
    catch { toast.error('Nessuna modella disponibile'); }
  };

  return (
    <>
      <header className={`sticky top-0 z-40 transition-all duration-300 ${scrolled ? 'glass' : 'bg-transparent'}`}>
        <div className="max-w-6xl mx-auto px-4 lg:px-8">
          <div className={`flex items-center justify-between gap-3 transition-all ${scrolled ? 'h-14' : 'h-16'}`}>
            <Link to="/" className="flex items-center gap-2 shrink-0">
              <span className="font-serif text-xl md:text-2xl tracking-tight">LATO <span className="gold-text">SEGRETO</span></span>
            </Link>

            <nav className="hidden md:flex items-center gap-1 text-sm">
              {cats.slice(0, 5).map((c) => (
                <Link key={c.slug} to={`/categorie/${c.slug}`}
                  className="px-3 py-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors">
                  {c.nome}
                </Link>
              ))}
              <Link to="/articoli" className="px-3 py-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors">Rivista</Link>
            </nav>

            <div className="flex items-center gap-1.5">
              {isHome && (
                <button onClick={() => setHomeMode(homeMode === 'public' ? 'secret' : 'public')}
                  data-testid="header-mode-switch"
                  className="hidden sm:flex items-center gap-2 text-[11px] caps-label px-3 py-2 rounded-full border transition-colors"
                  style={{ borderColor: homeMode === 'secret' ? 'hsl(var(--primary) / 0.5)' : 'hsl(var(--border))', color: homeMode === 'secret' ? 'hsl(var(--primary))' : 'hsl(var(--muted-foreground))' }}>
                  <span className={`h-2 w-2 rounded-full ${homeMode === 'secret' ? '' : 'opacity-40'}`} style={{ background: homeMode === 'secret' ? 'hsl(var(--primary))' : 'currentColor' }} />
                  {homeMode === 'secret' ? 'Lato Segreto' : 'Lato Pubblico'}
                </button>
              )}
              <button onClick={() => setSearchOpen(true)} data-testid="header-search-button"
                className="h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50 transition-colors" aria-label="Cerca">
                <Search className="h-[18px] w-[18px]" />
              </button>
              <button onClick={surprise} data-testid="header-surprise-button"
                className="hidden sm:flex items-center gap-1.5 btn-gold rounded-full px-4 py-2 text-xs">
                <Shuffle className="h-4 w-4" /> Sorprendimi
              </button>
              <button onClick={() => setMenuOpen(true)} className="md:hidden h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50" aria-label="Menu">
                <Menu className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {menuOpen && (
        <div className="fixed inset-0 z-[70] md:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={() => setMenuOpen(false)} />
          <div className="absolute right-0 top-0 h-full w-72 glass p-5 flex flex-col gap-1">
            <div className="flex justify-between items-center mb-4">
              <span className="font-serif text-lg">Menu</span>
              <button onClick={() => setMenuOpen(false)} className="h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50"><X className="h-5 w-5" /></button>
            </div>
            <button onClick={() => { setMenuOpen(false); surprise(); }} className="btn-gold rounded-xl py-3 text-sm mb-3 flex items-center justify-center gap-2"><Shuffle className="h-4 w-4" />Sorprendimi</button>
            {cats.map((c) => (
              <Link key={c.slug} to={`/categorie/${c.slug}`} onClick={() => setMenuOpen(false)}
                className="px-3 py-2.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40">{c.nome}</Link>
            ))}
            <Link to="/articoli" onClick={() => setMenuOpen(false)} className="px-3 py-2.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40">Rivista</Link>
          </div>
        </div>
      )}

      <SearchOverlay open={searchOpen} onClose={() => setSearchOpen(false)} />
    </>
  );
}
