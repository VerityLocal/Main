import { safeBackend, tokenValid, FORMATS } from './common.js';

export async function configuration() {
  const { backend = 'http://127.0.0.1:8000', token } = await chrome.storage.local.get(['backend', 'token']);
  if (!tokenValid(token || '')) throw new Error('Set your local backend token in Settings first.');
  return { backend: safeBackend(backend), token };
}
async function request(path, options = {}, auth) {
  const { backend, token } = auth || await configuration();
  // Revalidate even when credentials arrive through trusted offscreen messaging.
  const base = safeBackend(backend);
  if (!tokenValid(token || '')) throw new Error('Invalid backend credentials. Check Settings.');
  const timeout = AbortSignal.timeout(options.method === 'POST' ? 45000 : 20000);
  const response = await fetch(base + path, {
    ...options, cache: 'no-store', credentials: 'omit', redirect: 'error',
    signal: options.signal ? AbortSignal.any([timeout, options.signal]) : timeout,
    headers: { ...options.headers, Authorization: `Bearer ${token}` }
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Backend returned HTTP ${response.status}.`);
  return data;
}
export function upload(bytes, format, threshold, auth, signal) {
  return request(`/analyze?format=${format}&threshold=${threshold}`, {
    method: 'POST', headers: { 'Content-Type': FORMATS[format] }, body: bytes, signal
  }, auth);
}
export function jobStatus(id, auth, signal) {
  if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('Invalid job identifier.');
  return request(`/analyze/${id}`, { signal }, auth);
}
export function health() { return request('/health'); }
