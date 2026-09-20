import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { LayoutDashboard, Users, Tags, Newspaper, BarChart3, Megaphone, Settings, LogOut, Menu, X, ExternalLink, Cpu, Brain, Send, Instagram, Twitter } from 'lucide-react';
import { adminMe } from '@/lib/adminApi';

const NAV = [
  { to: '/admin/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/admin/modelle', label: 'Modelle', icon: Users },
  { to: '/admin/categorie', label: 'Categorie', icon: Tags },
  { to: '/admin/articoli', label: 'Contenuti SEO', icon: Newspaper },
  { to: '/admin/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/admin/campagne', label: 'Campagne', icon: Megaphone },
  { to: '/admin/motore', label: 'Motore API', icon: Cpu },
  { to: '/admin/seo-autopilot', label: 'SEO Autopilot', icon: Brain },
  { to: '/admin/telegram-autopilot', label: 'Telegram Autopilot', icon: Send },
  { to: '/admin/instagram-autopilot', label: 'Instagram Autopilot', icon: Instagram },
  { to: '/admin/x-autopilot', label: 'X Autopilot', icon: Twitter },
  { to: '/admin/impostazioni', label: 'Impostazioni', icon: Settings },
];

export default function AdminLayout() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [open, setOpen] = useState(false);

  useEffect(() => {
    adminMe().then((d) => setEmail(d.email)).catch(() => { localStorage.removeItem('ls_admin_token'); navigate('/admin'); });
  }, [navigate]);

  const logout = () => { localStorage.removeItem('ls_admin_token'); navigate('/admin'); };

  const SidebarInner = () => (
    <div className="flex flex-col h-full">
      <div className="px-5 py-5"><div className="font-serif text-xl">LATO <span className="gold-text">SEGRETO</span></div><div className="caps-label text-muted-foreground mt-1">Amministrazione</div></div>
      <nav className="flex-1 px-3 space-y-1" data-testid="admin-nav">
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} onClick={() => setOpen(false)}
            className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors ${isActive ? 'bg-primary/15 text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'}`}>
            <n.icon className="h-[18px] w-[18px]" /> {n.label}
          </NavLink>
        ))}
      </nav>
      <div className="p-3 border-t border-border/60">
        <a href="/" target="_blank" rel="noreferrer" className="flex items-center gap-2 px-3 py-2 text-xs text-muted-foreground hover:text-foreground"><ExternalLink className="h-4 w-4" /> Vedi il sito</a>
        <div className="px-3 py-1 text-[11px] text-muted-foreground/70 truncate">{email}</div>
        <button onClick={logout} data-testid="admin-logout-button" className="w-full flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/40"><LogOut className="h-4 w-4" /> Esci</button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-background text-foreground flex">
      <aside className="hidden lg:block w-60 border-r border-border/60 sticky top-0 h-screen" data-testid="admin-sidebar"><SidebarInner /></aside>
      {open && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div className="absolute inset-0 bg-black/70" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-0 h-full w-64 bg-card border-r border-border/60"><SidebarInner /></div>
        </div>
      )}
      <div className="flex-1 min-w-0">
        <div className="lg:hidden flex items-center justify-between px-4 h-14 border-b border-border/60">
          <button onClick={() => setOpen(true)} className="h-9 w-9 flex items-center justify-center rounded-lg hover:bg-muted/40"><Menu className="h-5 w-5" /></button>
          <span className="font-serif">LATO SEGRETO</span>
          <span className="w-9" />
        </div>
        <main className="p-4 sm:p-6 max-w-6xl"><Outlet /></main>
      </div>
    </div>
  );
}
