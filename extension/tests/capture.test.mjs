import test from 'node:test';
import assert from 'node:assert/strict';
import { fetchPdf, pdfTarget, pdfName, CAPTURE_BYTES } from '../capture.js';

test('capture only accepts direct, credential-free web/local PDF URLs', () => {
  assert.equal(pdfTarget('https://example.com/paper.pdf#page=3').url, 'https://example.com/paper.pdf');
  assert.equal(pdfTarget('https://example.com/download?id=123').origin, 'https://example.com/*');
  assert.equal(pdfTarget('file:///Users/student/Paper.PDF').local, true);
  for (const url of ['javascript:alert(1)', 'chrome://settings', 'blob:https://example.com/id',
    'https://user:secret@example.com/paper.pdf', 'file://server/paper.pdf', 'file:///etc/passwd']) assert.equal(pdfTarget(url), null);
  assert.equal(pdfName('https://example.com/%E0%A4.pdf'), 'document.pdf');
});
test('PDF capture never attaches backend authorization and rejects redirects', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(options.redirect, 'error'); assert.equal(options.credentials, 'include');
    assert.equal(options.headers, undefined); assert.equal(url, 'https://example.com/paper.pdf');
    return new Response('%PDF-1.7\nfixture');
  };
  try { assert.equal(new TextDecoder().decode(await fetchPdf('https://example.com/paper.pdf')), '%PDF-1.7\nfixture'); }
  finally { globalThis.fetch = original; }
});
test('login/viewer bodies never become a detector input', async () => {
  const original = globalThis.fetch; globalThis.fetch = async () => new Response('<html>Sign in</html>');
  try { await assert.rejects(fetchPdf('https://example.com/download'), /viewer\/login/); }
  finally { globalThis.fetch = original; }
});
test('capture enforces both declared and streamed byte limits', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('', { headers: { 'Content-Length': String(CAPTURE_BYTES + 1) } });
    await assert.rejects(fetchPdf('https://example.com/paper.pdf'), /8 MiB/);
    globalThis.fetch = async () => new Response(new ReadableStream({ start(controller) {
      controller.enqueue(new Uint8Array(CAPTURE_BYTES)); controller.enqueue(new Uint8Array(1)); controller.close();
    } }));
    await assert.rejects(fetchPdf('https://example.com/paper.pdf'), /8 MiB/);
  } finally { globalThis.fetch = original; }
});
