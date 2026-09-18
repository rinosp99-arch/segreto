import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { Search, Shuffle, Menu, X } from 'lucide-react';
import { useTheme } from '@/lib/themeContext';
import { getSurprise, getCategories, track } from '@/lib/api';
import { setEntry } from '@/lib/analytics';
import { getSessionId } from '@/lib/session';
import SearchOverlay from '@/components/layout/SearchOverlay';
import { toast } from 'sonner';

export function Header() {
  const { homeMode, setHomeMode } = useTheme();
  // Switch attention cues (light/border/animation only): one stronger recall on the first view of the session, then a
  // discreet infinite micro-pulse + shimmer; a short flash on tap. Sizes/positions untouched.
  const [swIntro, setSwIntro] = useState(false);
  const [swTap, setSwTap] = useState(false);
  useEffect(() => {
    let seen = false;
    try { seen = sessionStorage.getItem('ls_switch_intro') === '1'; } catch { /* noop */ }
    if (seen) return undefined;
    const t = setTimeout(() => {
      setSwIntro(true);
      try { sessionStorage.setItem('ls_switch_intro', '1'); } catch { /* noop */ }
      setTimeout(() => setSwIntro(false), 1700);
    }, 1500);
    return () => clearTimeout(t);
  }, []);
  const flashTap = useCallback(() => { setSwTap(false); requestAnimationFrame(() => setSwTap(true)); setTimeout(() => setSwTap(false), 500); }, []);
  const swClass = `ls-switch ${homeMode === 'secret' ? 'ls-switch--secret' : 'ls-switch--public'} ${swIntro ? 'ls-switch--intro' : ''} ${swTap ? 'ls-switch--tap' : ''}`;
  const toggleHomeMode = (source = 'desktop') => {
    const next = homeMode === 'public' ? 'secret' : 'public';
    flashTap();
    setHomeMode(next);
    track({ tipo: next === 'secret' ? 'home_toggle_secret_on' : 'home_toggle_secret_off', session_id: getSessionId() });
    if (source === 'mobile') track({ tipo: next === 'secret' ? 'home_mobile_toggle_secret' : 'home_mobile_toggle_public', session_id: getSessionId() });
  };
  const navigate = useNavigate();
  const location = useLocation();
  const isHome = location.pathname === '/';
  const [scrolled, setScrolled] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [cats, setCats] = useState([]);
  const lastSurprise = useState({ slug: null })[0];

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => { getCategories().then((d) => setCats(d.items || [])).catch(() => {}); }, []);

  const surprise = async (source = 'desktop') => {
    track({ tipo: 'home_surprise_click', session_id: getSessionId(), meta: { source } });
    try {
      let m = await getSurprise();
      if (m && m.slug && m.slug === lastSurprise.slug) { try { m = await getSurprise(); } catch (e) { /* keep */ } }
      lastSurprise.slug = m.slug;
      track({ tipo: 'home_surprise_profile_open', model_slug: m.slug, session_id: getSessionId(), meta: { source } });
      setEntry('surprise', { source });
      navigate(`/modelle/${m.slug}`);
    } catch { toast.error('Nessuna modella disponibile'); }
  };

  return (
    <>
      <header className={`sticky top-0 z-40 transition-all duration-300 ${scrolled ? 'glass' : 'bg-transparent'}`}>
        <div className="max-w-6xl mx-auto px-4 lg:px-8">
          <div className={`flex items-center justify-between gap-3 transition-all ${scrolled ? 'h-14' : 'h-16'}`}>
            <Link to="/" className="flex items-center gap-2 min-w-0 mr-1">
              <span className="font-serif text-lg sm:text-xl md:text-2xl tracking-tight truncate">LATO <span className="gold-text">SEGRETO</span></span>
            </Link>

            <nav className="hidden md:flex items-center gap-1 text-sm">
              {cats.slice(0, 5).map((c) => (
                <Link key={c.slug} to={`/categorie/${c.slug}`} onClick={() => track({ tipo: 'home_category_click', meta: { categoria: c.slug, source: 'desktop' } })}
                  className="px-3 py-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors">
                  {c.nome}
                </Link>
              ))}
              <Link to="/articoli" className="px-3 py-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors">Rivista</Link>
            </nav>

            <div className="flex items-center gap-1 sm:gap-1.5 shrink-0">
              {isHome && (
                <>
                  {/* MOBILE compact pills (top-right) */}
                  <button onClick={() => toggleHomeMode('mobile')} data-testid="header-mode-switch-mobile"
                    className={`sm:hidden flex items-center gap-1 text-[10px] caps-label px-2 py-1.5 rounded-full border whitespace-nowrap ${swClass}`}
                    aria-label="Cambia lato Home">
                    <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'currentColor', boxShadow: '0 0 6px currentColor' }} />
                    {homeMode === 'secret' ? 'Pubblico' : 'Segreto'}
                  </button>
                  <button onClick={() => surprise('mobile')} data-testid="header-surprise-mobile"
                    className="sm:hidden flex items-center gap-1 text-[10px] caps-label px-2 py-1.5 rounded-full border border-border text-muted-foreground whitespace-nowrap"
                    aria-label="Sorprendimi">
                    <Shuffle className="h-3.5 w-3.5" /> Sorprendimi
                  </button>
                </>
              )}
              {isHome && (
                <button onClick={() => toggleHomeMode('desktop')}
                  data-testid="header-mode-switch"
                  className={`hidden sm:flex items-center gap-2 text-[11px] caps-label px-3 py-2 rounded-full border ${swClass}`}>
                  <span className="h-2 w-2 rounded-full" style={{ background: 'currentColor', boxShadow: '0 0 8px currentColor' }} />
                  {homeMode === 'secret' ? 'Lato Segreto' : 'Lato Pubblico'}
                </button>
              )}
              <button onClick={() => setSearchOpen(true)} data-testid="header-search-button"
                className="h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50 transition-colors shrink-0" aria-label="Cerca">
                <Search className="h-[18px] w-[18px]" />
              </button>
              <button onClick={() => surprise('desktop')} data-testid="header-surprise-button"
                className="hidden sm:flex items-center gap-1.5 btn-gold rounded-full px-4 py-2 text-xs">
                <Shuffle className="h-4 w-4" /> Sorprendimi
              </button>
              <button onClick={() => setMenuOpen(true)} className="md:hidden h-9 w-9 flex items-center justify-center rounded-full hover:bg-muted/50 shrink-0" aria-label="Menu">
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
              <Link key={c.slug} to={`/categorie/${c.slug}`} onClick={() => { setMenuOpen(false); track({ tipo: 'home_category_click', meta: { categoria: c.slug, source: 'mobile_menu' } }); }}
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
