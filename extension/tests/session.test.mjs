import test from 'node:test';
import assert from 'node:assert/strict';
import { analysisId, sourceKey, summaryOf, bytesToBase64, base64ToBytes, CHUNK_BYTES } from '../session.js';
import { percent } from '../common.js';

test('per-tab/document keys and opaque review identifiers', () => {
  const a = { id: 1, url: 'https://example.com/a.pdf' };
  assert.notEqual(sourceKey(a), sourceKey({ ...a, id: 2 }));
  assert.notEqual(sourceKey(a), sourceKey({ ...a, url: 'https://example.com/b.pdf' }));
  assert(analysisId(crypto.randomUUID())); assert(!analysisId('../../etc/passwd')); assert(!analysisId(null));
});
test('popup summary has honest separate signals and no passage text', () => {
  const text = { status: 'scored', flagged_content_share: 0.54, analyzed_tokens: 100, threshold: 0.5, chunk_scores: [{ text: 'PRIVATE STUDENT TEXT' }] };
  const code = { ...text, status: 'no_analyzable_content', flagged_content_share: null, analyzed_tokens: 0 };
  const summary = summaryOf({ text, code, coverage: { pages_processed: 7, analyzed_characters: 1000,
    unscored_characters: 200, excluded_characters_by_reason: { references: 10, tables: 20 }, unread_image_regions: 1 }, warnings: ['PRIVATE NOTE'] });
  assert.equal(percent(summary.text.flagged_content_share), '54.0%'); assert.equal(percent(summary.code.flagged_content_share), 'Not scored');
  assert.equal(summary.excluded, 30); assert.equal(summary.warnings, 1);
  assert(!JSON.stringify(summary).includes('PRIVATE'));
});
test('bounded Chrome JSON upload chunks round-trip exact binary bytes', () => {
  const bytes = Uint8Array.from({ length: CHUNK_BYTES }, (_, i) => i % 256);
  assert.deepEqual(base64ToBytes(bytesToBase64(bytes)), bytes);
  assert.throws(() => base64ToBytes('!bad!')); assert.throws(() => base64ToBytes('a'.repeat(CHUNK_BYTES * 2)));
});
