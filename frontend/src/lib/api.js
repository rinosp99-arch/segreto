import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API_BASE });

// attach admin token when present
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('ls_admin_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Resolve a media URL to something the browser can load.
// - absolute http(s): as-is
// - /api/uploads/...: served by backend -> prefix backend url
// - /media/...: served by frontend static -> as-is
export function mediaUrl(url) {
  if (!url) return '';
  if (url.startsWith('http://') || url.startsWith('https://')) return url;
  if (url.startsWith('/api/')) return `${BACKEND_URL}${url}`;
  return url;
}

// ---- public endpoints ----
export const getModels = (params) => api.get('/models', { params }).then((r) => r.data);
export const getModel = (slug) => api.get(`/models/${slug}`).then((r) => r.data);
export const getModelSecret = (slug) => api.get(`/models/${slug}/segreto`).then((r) => r.data);
export const getRelated = (slug) => api.get(`/models/${slug}/correlate`).then((r) => r.data);
export const getSurprise = () => api.get('/surprise').then((r) => r.data);
export const getCategories = () => api.get('/categories').then((r) => r.data);
export const getCategory = (slug) => api.get(`/categories/${slug}`).then((r) => r.data);
export const getArticles = () => api.get('/articles').then((r) => r.data);
export const getArticle = (slug) => api.get(`/articles/${slug}`).then((r) => r.data);
export const getPublicSettings = () => api.get('/settings').then((r) => r.data);
export const getPellicola = () => api.get('/pellicola').then((r) => r.data);

// ---- tracking ----
export function track(evt) {
  try {
    let attr = null;
    try { attr = JSON.parse(sessionStorage.getItem('ls_attr') || 'null'); } catch (e) { attr = null; }
    const payload = attr ? { ref: attr.ref, fonte: attr.fonte, campagna: attr.campagna, ...evt } : evt;
    const body = JSON.stringify(payload);
    if (evt._beacon && navigator.sendBeacon) {
      navigator.sendBeacon(`${API_BASE}/track`, new Blob([body], { type: 'application/json' }));
      return;
    }
    api.post('/track', payload).catch(() => {});
  } catch (e) { /* noop */ }
}
