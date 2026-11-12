// Session metadata/summary only. Document bytes and passage text stay in memory.
export const SESSION_TTL = 15 * 60 * 1000;
export const IMPORT_TTL = 60 * 1000;
export const MAX_DOCUMENTS = 3;
export const MAX_RETAINED_BYTES = 64 * 1024 * 1024;
export const CHUNK_BYTES = 192 * 1024;
export function analysisId(value) { return typeof value === 'string' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/.test(value); }
export function sourceKey(source) { return `${source.id}:${source.url}`; }
export function summaryOf(result) {
  if (!result) return null;
  const modality = value => ({ status: value.status, flagged_content_share: value.flagged_content_share,
    analyzed_tokens: value.analyzed_tokens, threshold: value.threshold });
  return { text: modality(result.text), code: modality(result.code), pages: result.coverage.pages_processed,
    analyzed: result.coverage.analyzed_characters, unscored: result.coverage.unscored_characters,
    excluded: Object.values(result.coverage.excluded_characters_by_reason).reduce((a,b) => a+b,0),
    unread: result.coverage.unread_image_regions, warnings: result.warnings.length };
}
export function bytesToBase64(bytes) {
  let text = '';
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}
export function base64ToBytes(value) {
  if (typeof value !== 'string' || value.length > Math.ceil(CHUNK_BYTES / 3) * 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) throw new Error('Invalid upload chunk.');
  return Uint8Array.from(atob(value), char => char.charCodeAt(0));
}
