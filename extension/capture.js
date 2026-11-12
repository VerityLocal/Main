import { pdfSignature } from './common.js';

export const CAPTURE_BYTES = 8 * 1024 * 1024;
export function pdfTarget(value) {
  try {
    const url = new URL(value);
    if (url.username || url.password) return null;
    if (!['http:', 'https:', 'file:'].includes(url.protocol)) return null;
    if (url.protocol === 'file:' && (url.hostname || !/\.pdf$/i.test(url.pathname))) return null;
    url.hash = '';
    return { url: url.href, origin: url.protocol === 'file:' ? 'file:///*' : `${url.origin}/*`, local: url.protocol === 'file:' };
  } catch { return null; }
}
export function pdfName(value) {
  try { return decodeURIComponent(new URL(value).pathname.split('/').pop() || 'document.pdf'); }
  catch { return 'document.pdf'; }
}
export async function fetchPdf(value, signal) {
  const target = pdfTarget(value);
  if (!target) throw new Error('This browser viewer cannot be captured. Choose the PDF file instead.');
  const timeout = AbortSignal.timeout(30000);
  // Site cookies may be needed for university PDFs. Never attach backend headers.
  const response = await fetch(target.url, { credentials: target.local ? 'omit' : 'include', cache: 'no-store',
    redirect: 'error', signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (!response.ok) throw new Error(`PDF download returned HTTP ${response.status}. Choose the PDF file instead.`);
  if (Number(response.headers.get('Content-Length')) > CAPTURE_BYTES) {
    await response.body?.cancel(); throw new Error('Tab capture is limited to 8 MiB. Choose the PDF file instead (up to 50 MiB).');
  }
  if (!response.body) throw new Error('No PDF bytes were returned. Choose the PDF file instead.');
  const reader = response.body.getReader(); const chunks = []; let length = 0;
  try {
    while (true) {
      const { done, value: chunk } = await reader.read(); if (done) break;
      length += chunk.length;
      if (length > CAPTURE_BYTES) throw new Error('Tab capture is limited to 8 MiB. Choose the PDF file instead (up to 50 MiB).');
      chunks.push(chunk);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const bytes = new Uint8Array(length); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  if (!pdfSignature(bytes)) throw new Error('The tab returned a viewer/login page, not a PDF. Choose the PDF file instead.');
  return bytes;
}
