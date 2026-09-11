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
