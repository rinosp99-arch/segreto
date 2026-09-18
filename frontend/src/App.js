import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Outlet, Navigate } from 'react-router-dom';
import { Toaster } from '@/components/ui/sonner';
import '@/index.css';
import { ThemeCtx } from '@/lib/themeContext';

import AgeGate from '@/components/AgeGate';
import CookieBanner from '@/components/CookieBanner';
import { Header } from '@/components/layout/Header';
import { Footer } from '@/components/layout/Footer';
import { getSessionId } from '@/lib/session';
import { captureAttribution } from '@/lib/attribution';
import { track } from '@/lib/api';
import { startCampaignVisit, getVisit } from '@/lib/analytics';

import Home from '@/pages/Home';
import ProfileSwipe from '@/pages/ProfileSwipe';
import CategoryPage from '@/pages/CategoryPage';
import LandingPage from '@/pages/LandingPage';
import ArticlesList from '@/pages/ArticlesList';
import ArticlePage from '@/pages/ArticlePage';
import Legal from '@/pages/Legal';
import NotFound from '@/pages/NotFound';
import AdminLogin from '@/pages/admin/AdminLogin';
import AdminLayout from '@/pages/admin/AdminLayout';
import Dashboard from '@/pages/admin/Dashboard';
import AdminModels from '@/pages/admin/AdminModels';
import ModelEditor from '@/pages/admin/ModelEditor';
import AdminCategories from '@/pages/admin/AdminCategories';
import AdminArticles from '@/pages/admin/AdminArticles';
import ArticleEditor from '@/pages/admin/ArticleEditor';
import AdminAnalytics from '@/pages/admin/AdminAnalytics';
import AdminCampaigns from '@/pages/admin/AdminCampaigns';
import AdminMotore from '@/pages/admin/AdminMotore';
import AdminSeoAutopilot from '@/pages/admin/AdminSeoAutopilot';
import AdminSettings from '@/pages/admin/AdminSettings';

function PublicLayout() {
  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground transition-theme grain">
      <Header />
      <main className="flex-1"><Outlet /></main>
      <Footer />
    </div>
  );
}

function RequireAdmin({ children }) {
  const token = localStorage.getItem('ls_admin_token');
  if (!token) return <Navigate to="/admin" replace />;
  return children;
}

export default function App() {
  const [homeMode, setHomeMode] = useState('public');

  useEffect(() => {
    getSessionId();
    getVisit();                                   // visit_id: new tab or 30 min of inactivity -> new visit
    const attr = captureAttribution();
    const fresh = new URLSearchParams(window.location.search).get('ref');
    if (fresh && attr && attr.ref) {
      startCampaignVisit(attr.ref);               // a campaign landing never mixes with the previous journey
      track({ tipo: 'landing', model_slug: attr.ref, session_id: getSessionId(), entry_source: 'campaign' });
    }
  }, []);

  return (
    <ThemeCtx.Provider value={{ homeMode, setHomeMode }}>
      <BrowserRouter>
        <AgeGate />
        <CookieBanner />
        <Toaster position="top-center" theme="dark" richColors />
        <Routes>
          <Route element={<PublicLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/modelle/:slug" element={<ProfileSwipe />} />
            <Route path="/categorie/:slug" element={<CategoryPage />} />
            <Route path="/l/:slug" element={<LandingPage />} />
            <Route path="/articoli" element={<ArticlesList />} />
            <Route path="/articoli/:slug" element={<ArticlePage />} />
            <Route path="/privacy" element={<Legal kind="privacy" />} />
            <Route path="/cookie" element={<Legal kind="cookie" />} />
            <Route path="/termini" element={<Legal kind="termini" />} />
            <Route path="/18-plus" element={<Legal kind="18-plus" />} />
            <Route path="*" element={<NotFound />} />
          </Route>

          <Route path="/admin" element={<AdminLogin />} />
          <Route path="/admin" element={<RequireAdmin><AdminLayout /></RequireAdmin>}>
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="modelle" element={<AdminModels />} />
            <Route path="modelle/nuova" element={<ModelEditor />} />
            <Route path="modelle/:id" element={<ModelEditor />} />
            <Route path="categorie" element={<AdminCategories />} />
            <Route path="articoli" element={<AdminArticles />} />
            <Route path="articoli/nuovo" element={<ArticleEditor />} />
            <Route path="articoli/:id" element={<ArticleEditor />} />
            <Route path="analytics" element={<AdminAnalytics />} />
            <Route path="campagne" element={<AdminCampaigns />} />
            <Route path="motore" element={<AdminMotore />} />
            <Route path="seo-autopilot" element={<AdminSeoAutopilot />} />
            <Route path="impostazioni" element={<AdminSettings />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ThemeCtx.Provider>
  );
}
