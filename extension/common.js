export const MAX_BYTES = 50 * 1024 * 1024;
export const FORMATS = { pdf: 'application/pdf', python: 'text/x-python', javascript: 'text/javascript', text: 'text/plain' };
export function fileFormat(name) {
  return ({ pdf: 'pdf', py: 'python', js: 'javascript', txt: 'text' })[name.split('.').pop().toLowerCase()] || null;
}
export function safeBackend(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Backend must be http://127.0.0.1:PORT with no path or credentials.');
  }
  return url.origin;
}
export function tokenValid(token) { return /^[A-Za-z0-9_-]{32,}$/.test(token); }
export function pdfSignature(bytes) { return new TextDecoder().decode(bytes.subarray(0, 5)) === '%PDF-'; }
export function percent(value) { return value == null ? 'Not scored' : `${(value * 100).toFixed(1)}%`; }
export function describeSources(sources = []) {
  const pages = [...new Set(sources.filter(x => x.page != null).map(x => x.page))];
  const lines = sources.filter(x => x.line != null).map(x => x.line);
  return pages.length ? `Pages ${pages.join(', ')}` : lines.length ? `Lines ${Math.min(...lines)}–${Math.max(...lines)}` : 'Location unavailable';
}
export function sourceRanges(text, sources) {
  // Backend offsets count Unicode code points; JavaScript slices UTF-16 units.
  const boundaries = new Set(sources.flatMap(x => [x.source_start, x.source_end]));
  const offsets = new Map(); let point = 0, unit = 0;
  for (const char of text) {
    if (boundaries.has(point)) offsets.set(point, unit);
    point++; unit += char.length;
  }
  if (boundaries.has(point)) offsets.set(point, unit);
  return sources.filter(x => Number.isInteger(x.source_start) && Number.isInteger(x.source_end)
      && x.source_start >= 0 && x.source_end >= x.source_start && x.source_end <= point)
    .map(x => [offsets.get(x.source_start), offsets.get(x.source_end)])
    .sort((a,b) => a[0]-b[0]);
}
