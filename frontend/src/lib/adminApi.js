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

// upload
export async function uploadMedia(file) {
  const fd = new FormData();
  fd.append('file', file);
  const r = await api.post('/admin/upload', fd, { headers: { 'Content-Type': 'multipart/form-data' } });
  return r.data; // {url, tipo}
}
