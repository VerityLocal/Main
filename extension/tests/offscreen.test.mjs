import test from 'node:test';
import assert from 'node:assert/strict';
import { bytesToBase64, IMPORT_TTL, SESSION_TTL } from '../session.js';

const extension = 'a'.repeat(32);
const auth = { backend: 'http://127.0.0.1:8765', token: 't'.repeat(40) };
const source = (id, name = 'paper.pdf') => ({ id, name, url: `https://example.com/${name}`, target: { origin: 'https://example.com/*' } });
const result = { text: { status: 'scored', flagged_content_share: 0.54, analyzed_tokens: 100, threshold: 0.5 },
  code: { status: 'scored', flagged_content_share: 0.263, analyzed_tokens: 100, threshold: 0.5 },
  coverage: { pages_processed: 7, analyzed_characters: 1000, unscored_characters: 0, excluded_characters_by_reason: {}, unread_image_regions: 0 }, warnings: [] };
async function boot() {
  let listener; const original = globalThis.setInterval;
  globalThis.chrome = { runtime: { id: extension, getURL: path => `chrome-extension://${extension}/${path}`,
    onMessage: { addListener: value => { listener = value; } } } };
  globalThis.setInterval = () => 0;
  try { await import(`../offscreen.js?test=${crypto.randomUUID()}`); } finally { globalThis.setInterval = original; }
  return (message, sender = { id: extension, url: `chrome-extension://${extension}/background.js` }) => {
    let response; listener({ channel: 'offscreen', ...message }, sender, value => { response = value; }); return response;
  };
}
function mockFetch(counts) {
  return async (url, options) => {
    if (url.startsWith('https://')) { counts.capture++; assert.equal(options.headers, undefined); return new Response('%PDF-1.7\nfixture'); }
    assert.equal(options.headers.Authorization, `Bearer ${auth.token}`);
    if (options.method === 'POST') { counts.upload++; return Response.json({ job_id: 'b'.repeat(32) }); }
    return Response.json({ status: 'completed', stage: 'completed', progress: 1, result, expires_in_seconds: 900 });
  };
}
test('only the extension service worker may command the offscreen document', async () => {
  const send = await boot();
  assert.equal(send({ type: 'peek', source: source(1) }, { id: extension, url: `chrome-extension://${extension}/popup.html` }), undefined);
  assert.equal(send({ type: 'peek', source: source(1) }, { id: extension, url: 'https://example.com' }), undefined);
});
test('reopening uses the same capture/upload; details return retained bytes/results', async () => {
  const send = await boot(); const original = globalThis.fetch; const counts = { capture: 0, upload: 0 };
  globalThis.fetch = mockFetch(counts);
  try {
    const first = send({ type: 'start', source: source(1), auth }).record;
    assert.equal(send({ type: 'start', source: source(1), auth }).record.id, first.id);
    await new Promise(setImmediate);
    const complete = send({ type: 'peek', source: source(1) }).record;
    assert.equal(complete.state, 'completed'); assert.equal(complete.summary.text.flagged_content_share, 0.54);
    const detail = send({ type: 'review', id: first.id }); assert.deepEqual(detail.result, result);
    assert(detail.blobUrl.startsWith('blob:')); assert.deepEqual(counts, { capture: 1, upload: 1 });
    send({ type: 'clear', id: first.id }); assert(send({ type: 'review', id: first.id }).error.includes('expired'));
    assert.equal(send({ type: 'peek', source: source(1) }).record, null);
  } finally { globalThis.fetch = original; }
});
test('navigation and clearing invalidate in-flight work without restoring results', async () => {
  const send = await boot(); const original = globalThis.fetch; let resolveFetch;
  globalThis.fetch = () => new Promise(resolve => { resolveFetch = resolve; });
  try {
    const first = send({ type: 'start', source: source(1), auth }).record;
    send({ type: 'forgetTab', tabId: 1 }); resolveFetch(new Response('%PDF-1.7\nfixture')); await new Promise(setImmediate);
    assert.equal(send({ type: 'peek', source: source(1) }).record, null);
    assert(send({ type: 'review', id: first.id }).error);
  } finally { globalThis.fetch = original; }
});
test('manual binary import is ordered, bounded, and only submitted once', async () => {
  const send = await boot(); const original = globalThis.fetch; const counts = { capture: 0, upload: 0 };
  globalThis.fetch = mockFetch(counts);
  try {
    const bytes = new TextEncoder().encode('%PDF-1.7\nfixture');
    const record = send({ type: 'beginImport', source: source(1), name: 'selected.pdf', size: bytes.length }).record;
    assert(send({ type: 'importChunk', source: source(1), id: record.id, offset: 1, data: bytesToBase64(bytes) }).error);
    assert(send({ type: 'finishImport', source: source(1), id: record.id, auth }).error);
    send({ type: 'importChunk', source: source(1), id: record.id, offset: 0, data: bytesToBase64(bytes) });
    send({ type: 'finishImport', source: source(1), id: record.id, auth });
    assert(send({ type: 'finishImport', source: source(1), id: record.id, auth }).error);
    await new Promise(setImmediate); assert.deepEqual(counts, { capture: 0, upload: 1 });
    assert.equal(send({ type: 'peek', source: source(1) }).record.state, 'completed');
    send({ type: 'clear', id: record.id });
  } finally { globalThis.fetch = original; }
});
test('sessions expire; abandoned file imports expire sooner; only three PDFs are retained', async () => {
  const send = await boot(); const original = Date.now; let now = original(); Date.now = () => now;
  try {
    const record = send({ type: 'beginImport', source: source(1), name: 'selected.pdf', size: 10 }).record;
    now += IMPORT_TTL + 1; assert(send({ type: 'review', id: record.id }).error);
    for (let id = 1; id <= 4; id++) send({ type: 'beginImport', source: source(id), name: 'selected.pdf', size: 10 });
    assert.equal(send({ type: 'peek', source: source(1) }).record, null);
    assert(send({ type: 'peek', source: source(4) }).record);
    now += SESSION_TTL + 1;
    assert.equal(send({ type: 'peek', source: source(4) }).record, null);
  } finally { Date.now = original; }
});
test('total retained PDF bytes are capped even below the document-count limit', async () => {
  const send = await boot();
  const a = send({ type: 'beginImport', source: source(1), name: 'selected.pdf', size: 50 * 1024 * 1024 }).record;
  send({ type: 'beginImport', source: source(2), name: 'selected.pdf', size: 20 * 1024 * 1024 });
  assert(send({ type: 'review', id: a.id }).error);
  assert.equal(send({ type: 'peek', source: source(1) }).record, null);
});
