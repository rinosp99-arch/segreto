import { api } from '@/lib/api';

export const adminLogin = (email, password) => api.post('/admin/login', { email, password }).then((r) => r.data);
export const adminMe = () => api.get('/admin/me').then((r) => r.data);
export const changePassword = (password) => api.post('/admin/change-password', { password }).then((r) => r.data);

// models
export const admGetModels = (stato) => api.get('/admin/models', { params: stato ? { stato } : {} }).then((r) => r.data);
export const admGetModel = (id) => api.get(`/admin/models/${id}`).then((r) => r.data);
export const admCreateModel = (data) => api.post('/admin/models', data).then((r) => r.data);
export const admUpdateModel = (id, data) => api.put(`/admin/models/${id}`, data).then((r) => r.data);
export const admSetStatus = (id, stato) => api.patch(`/admin/models/${id}/stato`, { stato }).then((r) => r.data);
export const admDeleteModel = (id) => api.delete(`/admin/models/${id}`).then((r) => r.data);
export const admReorder = (order) => api.post('/admin/models/reorder', { order }).then((r) => r.data);
export const admCopyConfig = (id, source_id) => api.post(`/admin/models/${id}/copy-config`, { source_id }).then((r) => r.data);
export const admCopyConfigBulk = (source_id, target_ids, sections) => api.post('/admin/models/copy-config-bulk', { source_id, target_ids, sections }).then((r) => r.data);

// categories
export const admGetCategories = () => api.get('/admin/categories').then((r) => r.data);
export const admCreateCategory = (data) => api.post('/admin/categories', data).then((r) => r.data);
export const admUpdateCategory = (id, data) => api.put(`/admin/categories/${id}`, data).then((r) => r.data);
export const admDeleteCategory = (id) => api.delete(`/admin/categories/${id}`).then((r) => r.data);

// articles
export const admGetArticles = () => api.get('/admin/articles').then((r) => r.data);
export const admGetArticle = (id) => api.get(`/admin/articles/${id}`).then((r) => r.data);
export const admCreateArticle = (data) => api.post('/admin/articles', data).then((r) => r.data);
export const admUpdateArticle = (id, data) => api.put(`/admin/articles/${id}`, data).then((r) => r.data);
export const admDeleteArticle = (id) => api.delete(`/admin/articles/${id}`).then((r) => r.data);

// settings + audit
export const admGetSettings = () => api.get('/admin/settings').then((r) => r.data);
export const admUpdateSettings = (data) => api.put('/admin/settings', data).then((r) => r.data);
export const admAudit = () => api.get('/admin/audit').then((r) => r.data);

// analytics
export const anOverview = (range) => api.get('/admin/analytics/overview', { params: { range } }).then((r) => r.data);
export const anFunnel = (range, model_id) => api.get('/admin/analytics/funnel', { params: { range, model_id } }).then((r) => r.data);
export const anModels = (range) => api.get('/admin/analytics/models', { params: { range } }).then((r) => r.data);
export const anModelDetail = (id, range) => api.get(`/admin/analytics/model/${id}`, { params: { range } }).then((r) => r.data);
export const anTimeseries = (range) => api.get('/admin/analytics/timeseries', { params: { range } }).then((r) => r.data);
export const anArticles = (range) => api.get('/admin/analytics/articles', { params: { range } }).then((r) => r.data);
export const anCampaigns = (range) => api.get('/admin/analytics/campaigns', { params: { range } }).then((r) => r.data);
export const anPellicola = (range) => api.get('/admin/analytics/pellicola', { params: { range } }).then((r) => r.data);

// upload
export async function uploadMedia(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await api.post('/admin/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  return r.data; // {url, tipo}
}

// ---- SUPER API v1 (Motore) ----
export const v1Dashboard = (range) => api.get('/v1/dashboard/overview', { params: { range } }).then((r) => r.data);
export const v1HealthRun = () => api.post('/v1/health/run').then((r) => r.data);
export const v1SeoAudit = () => api.post('/v1/seo/audit', { scope: 'all' }).then((r) => r.data);
export const v1SeoFixAll = (dry_run = false) => api.post('/v1/seo/fix-all', { scope: 'all', dry_run }).then((r) => r.data);
export const v1SeoIssues = (params) => api.get('/v1/seo/issues', { params }).then((r) => r.data);
export const v1SeoFix = (issue_id, apply_review = false) => api.post('/v1/seo/fix', { issue_id, apply_review }).then((r) => r.data);
export const v1SeoIgnore = (issue_id) => api.post(`/v1/seo/issues/${issue_id}/ignore`).then((r) => r.data);
export const v1Rollback = (version_id, reason) => api.post(`/v1/versions/${version_id}/rollback`, { reason }).then((r) => r.data);
export const v1JobRun = (name) => api.post(`/v1/jobs/${name}/run`).then((r) => r.data);
export const v1AlertAck = (id) => api.post(`/v1/alerts/${id}/ack`).then((r) => r.data);
export const v1AlertResolve = (id) => api.post(`/v1/alerts/${id}/resolve`).then((r) => r.data);
export const v1Keys = () => api.get('/v1/auth/keys').then((r) => r.data);
export const v1CreateKey = (data) => api.post('/v1/auth/keys', data).then((r) => r.data);
export const v1RevokeKey = (id) => api.delete(`/v1/auth/keys/${id}`).then((r) => r.data);
export const v1Config = () => api.get('/v1/config').then((r) => r.data);
export const v1SetFlag = (name, value) => api.put(`/v1/config/flags/${name}`, { value }).then((r) => r.data);
export const v1Backup = () => api.post('/v1/backup', {}).then((r) => r.data);

// ---- Phase 10: ChatGPT control layer ----
export const aiControl = () => api.get('/v1/ai/control').then((r) => r.data);
export const aiControlPatch = (data) => api.patch('/v1/ai/control', data).then((r) => r.data);
export const aiTestConnection = () => api.post('/v1/ai/test-connection').then((r) => r.data);
export const v1KeyRotate = (id) => api.post(`/v1/auth/keys/${id}/rotate`).then((r) => r.data);
export const v1KeyDisable = (id) => api.post(`/v1/auth/keys/${id}/disable`).then((r) => r.data);
export const v1KeyEnable = (id) => api.post(`/v1/auth/keys/${id}/enable`).then((r) => r.data);

// ---- Phase 12A: universal engine v2 (capability governance) ----
export const aiCapabilitiesAdmin = () => api.get('/v2/ai/admin/capabilities').then((r) => r.data);
export const aiCapabilityToggle = (capability_id, disabled) => api.post('/v2/ai/admin/capabilities/toggle', { capability_id, disabled }).then((r) => r.data);
export const v1KeyCapabilities = (id, capability_allow, capability_deny) => api.patch(`/v1/auth/keys/${id}/capabilities`, { capability_allow, capability_deny }).then((r) => r.data);

// analytics v2 (control center) — backend aggregations, filters as query params
const v2 = (path, params) => api.get(`/admin/analytics/v2/${path}`, { params }).then((r) => r.data);
export const an2Summary = (filters) => v2('summary', filters);
export const an2Models = (filters) => v2('models', filters);
export const an2Model = (slug, filters) => v2(`model/${encodeURIComponent(slug)}`, filters);
export const an2Timeseries = (filters, granularity) => v2('timeseries', { ...filters, granularity });
export const an2Compare = (filters, slugs) => v2('compare', { ...filters, slugs: slugs.join(',') });
export const an2Events = (filters, limit = 50, skip = 0, tipo) => v2('events', { ...filters, limit, skip, tipo: tipo || undefined });
export const an2Filters = (filters) => v2('filters', filters);
export const an2Visit = (visitId) => v2(`visit/${encodeURIComponent(visitId)}`, {});
export const an2ExportUrl = (kind, filters, slug) => {
  const q = new URLSearchParams({ kind, ...Object.fromEntries(Object.entries({ ...filters, slug }).filter(([, v]) => v !== undefined && v !== null && v !== '')) });
  return `${process.env.REACT_APP_BACKEND_URL}/api/admin/analytics/v2/export.csv?${q.toString()}`;
};

// ---------------- SEO AUTOPILOT (fase 14, READ_ONLY) ----------------
const seoAp = (path, params) => api.get(`/admin/seo-autopilot/${path}`, { params }).then((r) => r.data);
export const seoApStatus = () => seoAp('status');
export const seoApRun = (kind, params) => api.post(`/admin/seo-autopilot/run/${kind}`, null, { params }).then((r) => r.data);
export const seoApRuns = (limit = 10) => seoAp('runs', { limit });
export const seoApLog = (params) => seoAp('log', params);
export const seoApOpportunities = (params) => seoAp('opportunities', params);
export const seoApClusters = (params) => seoAp('clusters', params);
export const seoApPageMap = () => seoAp('page-map');
export const seoApProposals = (params) => seoAp('proposals', params);
export const seoApCannibalization = () => seoAp('cannibalization');
export const seoApBacklog = (limit = 50) => seoAp('backlog', { limit });
export const seoApTech = () => seoAp('tech');
export const seoApRender = () => seoAp('render');
export const seoApAdult = () => seoAp('adult');
export const seoApExecute = (slug) => api.post(`/admin/seo-autopilot/execute/${slug}`).then((r) => r.data);

// ---------------- TELEGRAM AUTOPILOT ----------------
const tgAp = (path, params) => api.get(`/admin/telegram-autopilot/${path}`, { params }).then((r) => r.data);
export const tgApStatus = () => tgAp('status');
export const tgApLogs = (limit = 40) => tgAp('logs', { limit });
export const tgApTestConnection = (real = false) => api.post('/admin/telegram-autopilot/test-connection', null, { params: { real } }).then((r) => r.data);
export const tgApStart = () => api.post('/admin/telegram-autopilot/start').then((r) => r.data);
export const tgApPause = () => api.post('/admin/telegram-autopilot/pause').then((r) => r.data);
export const tgApPublishNow = (dryRun = false) => api.post('/admin/telegram-autopilot/publish-now', null, { params: { dry_run: dryRun } }).then((r) => r.data);
export const tgApSkip = () => api.post('/admin/telegram-autopilot/skip').then((r) => r.data);
export const tgApSettings = (body) => api.patch('/admin/telegram-autopilot/settings', body).then((r) => r.data);

// ---------------- INSTAGRAM AUTOPILOT (independent queue, MOCK / NOT_CONNECTED) ----------------
const igAp = (path, params) => api.get(`/admin/instagram-autopilot/${path}`, { params }).then((r) => r.data);
export const igApStatus = () => igAp('status');
export const igApLogs = (limit = 40) => igAp('logs', { limit });
export const igApTestConnection = () => api.post('/admin/instagram-autopilot/test-connection').then((r) => r.data);
export const igApStart = () => api.post('/admin/instagram-autopilot/start').then((r) => r.data);
export const igApPause = () => api.post('/admin/instagram-autopilot/pause').then((r) => r.data);
export const igApPublishNow = (dryRun = false) => api.post('/admin/instagram-autopilot/publish-now', null, { params: { dry_run: dryRun } }).then((r) => r.data);
export const igApSkip = () => api.post('/admin/instagram-autopilot/skip').then((r) => r.data);
export const igApSettings = (body) => api.patch('/admin/instagram-autopilot/settings', body).then((r) => r.data);

// ---------------- X AUTOPILOT (independent queue, MOCK / NOT_CONNECTED) ----------------
const xAp = (path, params) => api.get(`/admin/x-autopilot/${path}`, { params }).then((r) => r.data);
export const xApStatus = () => xAp('status');
export const xApLogs = (limit = 40) => xAp('logs', { limit });
export const xApTestConnection = () => api.post('/admin/x-autopilot/test-connection').then((r) => r.data);
export const xApStart = () => api.post('/admin/x-autopilot/start').then((r) => r.data);
export const xApPause = () => api.post('/admin/x-autopilot/pause').then((r) => r.data);
export const xApPreview = () => api.post('/admin/x-autopilot/preview').then((r) => r.data);
export const xApPublishNow = () => api.post('/admin/x-autopilot/publish-now').then((r) => r.data);
export const xApSkip = () => api.post('/admin/x-autopilot/skip').then((r) => r.data);
export const xApSettings = (body) => api.patch('/admin/x-autopilot/settings', body).then((r) => r.data);
export const xApConnection = (live = false) => xAp('connection', { live });
export const xApAuthStatus = () => xAp('auth/status');
export const xApAuthStart = () => api.post('/admin/x-autopilot/auth/start').then((r) => r.data);
export const xApAuthDisconnect = () => api.post('/admin/x-autopilot/auth/disconnect').then((r) => r.data);

// ---------------- ONLYFANS AUTOPILOT (provider connection, READ-ONLY phase) ----------------
export const ofApConnection = () => api.get('/admin/of-autopilot/connection').then((r) => r.data);
export const ofApTestConnection = () => api.post('/admin/of-autopilot/test-connection').then((r) => r.data);
export const ofApStatus = () => api.get('/admin/of-autopilot/status').then((r) => r.data);
export const ofApPreview = () => api.get('/admin/of-autopilot/preview').then((r) => r.data);
export const ofApLogs = (limit = 40) => api.get('/admin/of-autopilot/logs', { params: { limit } }).then((r) => r.data);
export const ofApStart = () => api.post('/admin/of-autopilot/start').then((r) => r.data);
export const ofApPause = () => api.post('/admin/of-autopilot/pause').then((r) => r.data);
export const ofApPublishNow = () => api.post('/admin/of-autopilot/publish-now').then((r) => r.data);
export const ofApSkip = () => api.post('/admin/of-autopilot/skip').then((r) => r.data);
export const ofApSettings = (body) => api.patch('/admin/of-autopilot/settings', body).then((r) => r.data);
