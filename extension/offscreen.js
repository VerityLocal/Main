import { upload, jobStatus } from './api.js';
import { fetchPdf } from './capture.js';
import { MAX_BYTES, pdfSignature } from './common.js';
import { SESSION_TTL, IMPORT_TTL, MAX_DOCUMENTS, MAX_RETAINED_BYTES, CHUNK_BYTES, sourceKey, summaryOf, base64ToBytes } from './session.js';

const records = new Map();
function live(record) { return records.get(record.id) === record && Date.now() < record.expiresAt; }
function dispose(record) {
  record.controller.abort(); if (record.blobUrl) URL.revokeObjectURL(record.blobUrl);
  record.bytes = record.result = record.chunks = null; records.delete(record.id);
}
function prune() { for (const record of records.values()) if (Date.now() >= record.expiresAt) dispose(record); }
setInterval(() => {
  prune();
  if (!records.size) chrome.runtime.sendMessage({ channel: 'coordinator', type: 'offscreenIdle' }).catch(() => {});
}, 10000);
function find(source) { prune(); return [...records.values()].find(record => record.key === sourceKey(source)); }
function requireRecord(id, source) {
  prune(); const record = records.get(id);
  if (!record || (source && record.key !== sourceKey(source))) throw new Error('This temporary analysis expired or was cleared. Analyze the PDF again.');
  return record;
}
function publicRecord(record) {
  return record ? { id: record.id, name: record.name, state: record.state, progress: record.progress,
    stage: record.stage, error: record.error, expiresAt: record.expiresAt, jobId: record.jobId,
    hasBytes: !!record.bytes, summary: summaryOf(record.result) } : null;
}
function reserve(record, size) {
  if (size > MAX_BYTES) throw new Error('PDF exceeds 50 MiB.');
  record.reserved = size;
  while ([...records.values()].reduce((sum, item) => sum + item.reserved, 0) > MAX_RETAINED_BYTES) {
    const victim = [...records.values()].find(item => item !== record);
    if (!victim) throw new Error('Temporary PDF memory limit exceeded.'); dispose(victim);
  }
}
function create(source, name, size = 0) {
  prune(); const previous = find(source); if (previous) dispose(previous);
  while (records.size >= MAX_DOCUMENTS) dispose(records.values().next().value);
  const record = { id: crypto.randomUUID(), key: sourceKey(source), tabId: source.id, name,
    expiresAt: Date.now() + SESSION_TTL, reserved: 0, state: 'capturing', stage: 'Obtaining PDF', progress: 0,
    controller: new AbortController(), bytes: null, result: null, blobUrl: null };
  records.set(record.id, record); reserve(record, size); return record;
}
function retain(record, bytes) {
  if (!live(record)) return;
  if (!pdfSignature(bytes)) throw new Error('The selected file does not contain PDF bytes.');
  reserve(record, bytes.length); record.bytes = bytes;
  record.blobUrl = URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }));
}
function fail(record, error) {
  if (!live(record)) return;
  record.state = 'failed'; record.stage = 'Analysis unavailable';
  record.error = error.name === 'AbortError' ? 'Analysis session was interrupted. Try again.' : error.message;
}
async function run(record, auth) {
  try {
    record.state = 'uploading'; record.stage = 'Submitting to local backend';
    const job = await upload(record.bytes, 'pdf', 0.5, auth, record.controller.signal);
    if (!live(record)) return;
    record.jobId = job.job_id; record.state = 'analyzing';
    while (live(record)) {
      const snapshot = await jobStatus(record.jobId, auth, record.controller.signal);
      if (!live(record)) return;
      record.progress = snapshot.progress; record.stage = snapshot.stage.replaceAll('_', ' ');
      if (snapshot.status === 'failed') throw new Error(snapshot.error?.message || 'Analysis failed.');
      if (snapshot.status === 'completed') {
        record.result = snapshot.result; record.state = 'completed'; record.stage = 'Analysis complete'; record.progress = 1;
        record.expiresAt = Date.now() + Math.min(SESSION_TTL, (snapshot.expires_in_seconds ?? SESSION_TTL / 1000) * 1000);
        return;
      }
      await new Promise(resolve => setTimeout(resolve, 700));
    }
  } catch (error) { fail(record, error); }
}
async function capture(record, source, auth) {
  try {
    const bytes = await fetchPdf(source.url, record.controller.signal);
    if (!live(record)) return; retain(record, bytes); await run(record, auth);
  } catch (error) { fail(record, error); }
}
function handle(message) {
  const { type, source, id } = message;
  if (type === 'empty') { prune(); return { empty: !records.size }; }
  if (type === 'peek') return { record: publicRecord(find(source)) };
  if (type === 'start') {
    const existing = find(source); if (existing) return { record: publicRecord(existing) };
    const record = create(source, source.name); void capture(record, source, message.auth);
    return { record: publicRecord(record) };
  }
  if (type === 'forgetTab') {
    for (const record of records.values()) if (record.tabId === message.tabId) dispose(record);
    return {};
  }
  if (type === 'beginImport') {
    if (typeof message.name !== 'string' || !/\.pdf$/i.test(message.name) || !Number.isInteger(message.size) || message.size < 5 || message.size > MAX_BYTES) throw new Error('Choose a valid PDF of up to 50 MiB.');
    const record = create(source, message.name, message.size);
    record.state = 'importing'; record.stage = 'Reading selected PDF'; record.expiresAt = Date.now() + IMPORT_TTL;
    record.chunks = []; record.received = 0; return { record: publicRecord(record) };
  }
  const record = requireRecord(id, source);
  if (type === 'clear') { dispose(record); return {}; }
  if (type === 'importChunk') {
    if (record.state !== 'importing' || message.offset !== record.received) throw new Error('PDF upload is out of order. Select the file again.');
    const chunk = base64ToBytes(message.data);
    if (!chunk.length || chunk.length > CHUNK_BYTES || record.received + chunk.length > record.reserved) throw new Error('Invalid PDF upload length.');
    record.chunks.push(chunk); record.received += chunk.length;
    return {};
  }
  if (type === 'finishImport') {
    if (record.state !== 'importing' || record.received !== record.reserved) throw new Error('PDF upload is incomplete. Select the file again.');
    const bytes = new Uint8Array(record.received); let offset = 0;
    for (const chunk of record.chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    record.chunks = null; record.expiresAt = Date.now() + SESSION_TTL;
    retain(record, bytes); void run(record, message.auth); return { record: publicRecord(record) };
  }
  if (type === 'retry') {
    if (!['completed', 'failed'].includes(record.state) || !record.bytes) throw new Error('Select the PDF again to retry.');
    record.controller.abort(); record.controller = new AbortController(); record.error = null; record.result = null;
    record.jobId = null; record.progress = 0; record.expiresAt = Date.now() + SESSION_TTL;
    void run(record, message.auth); return { record: publicRecord(record) };
  }
  if (type === 'review' || type === 'validateReview') {
    if (record.state !== 'completed' || !record.blobUrl) throw new Error('Detailed results are not ready.');
    return type === 'review' ? { blobUrl: record.blobUrl, name: record.name, result: record.result } : {};
  }
  throw new Error('Unsupported analysis operation.');
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.channel !== 'offscreen' || sender.id !== chrome.runtime.id || sender.url !== chrome.runtime.getURL('background.js')) return false;
  try { respond(handle(message)); } catch (error) { respond({ error: error.message }); }
  return false;
});
