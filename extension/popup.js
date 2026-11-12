import { MAX_BYTES, percent } from './common.js';
import { CHUNK_BYTES, bytesToBase64 } from './session.js';
const $ = id => document.getElementById(id);
let source, record, stopped = false, importing = false, timer;
async function send(type, extra = {}) {
  const response = await chrome.runtime.sendMessage({ channel: 'coordinator', type, source, ...extra });
  if (!response) throw new Error('Extension background is unavailable. Reopen the popup.');
  if (response.error) throw new Error(response.error); return response;
}
function error(message) { $('status').textContent = message; $('progress').hidden = true; $('fallback').open = true; }
function render(next) {
  record = next; const completed = record?.state === 'completed';
  const active = !!record && !['failed', 'completed'].includes(record.state);
  $('filename').textContent = record?.name || source?.name || 'Choose a PDF';
  $('progress').hidden = !active; $('progress').value = record?.progress || 0;
  $('scores').hidden = !completed; $('coverage').hidden = !completed;
  $('details').hidden = !completed; $('details').disabled = !completed;
  $('clear').hidden = !record; $('retry').hidden = !record || active;
  $('retry').textContent = record?.hasBytes ? 'Re-analyze' : 'Try again';
  $('file').disabled = active;
  $('fallback').open = record?.state === 'failed';
  if (record) {
    $('permission').hidden = true; $('local-access').hidden = true;
    $('status').textContent = record.error || `${record.stage}${active && record.state === 'analyzing' ? ` (${Math.round(record.progress * 100)}%)` : ''}`;
  }
  if (completed) {
    for (const kind of ['text', 'code']) {
      const value = record.summary[kind]; $(`${kind}-score`).textContent = percent(value.flagged_content_share);
      $(`${kind}-status`).textContent = `${value.status.replaceAll('_', ' ')} · ${value.analyzed_tokens} analyzed tokens`;
    }
    const summary = record.summary;
    $('coverage').textContent = `${summary.pages} pages processed · ${summary.analyzed.toLocaleString()} characters analyzed.` +
      (summary.unscored || summary.excluded || summary.unread ? ' Some content was not scored; see details.' : '') +
      ' Temporary results expire within 15 minutes.';
  }
  clearTimeout(timer);
  if (active && !importing && !stopped) timer = setTimeout(poll, 700);
  else if (record && !importing && !stopped) timer = setTimeout(poll, Math.max(0, record.expiresAt - Date.now() + 10));
}
async function poll() {
  try {
    const answer = await send('peek');
    render(answer.record);
    if (!answer.record) error('This temporary analysis expired, was cleared, or its original tab changed. Reopen on the PDF or choose a file.');
  } catch (failure) {
    render(null);
    // A navigation can revoke activeTab while a capture is in flight. Refresh
    // the source for explicit file upload, but never silently start a new job.
    try { source = (await send('init')).source; } catch { /* Reopen to reconnect. */ }
    error(failure.message);
  }
}
async function start() {
  try { $('permission').disabled = true; const answer = await send('start'); render(answer.record); }
  catch (failure) { error(failure.message); } finally { $('permission').disabled = false; }
}
$('permission').addEventListener('click', async () => {
  try {
    // Request from a real click; never silently request broad website access.
    const granted = await chrome.permissions.request({ origins: [source.target.origin] });
    if (!granted) { error('Site permission declined. Choose the PDF file instead.'); return; }
    await start();
  } catch (failure) { error(failure.message); }
});
$('local-access').addEventListener('click', () => {
  chrome.tabs.create({ url: `chrome://extensions/?id=${chrome.runtime.id}` });
});
$('settings').addEventListener('click', () => chrome.runtime.openOptionsPage());
$('details').addEventListener('click', async () => {
  try { await send('details', { id: record.id }); window.close(); } catch (failure) { error(failure.message); }
});
$('manual-review').addEventListener('click', async () => {
  try { await send('manualReview'); window.close(); } catch (failure) { error(failure.message); }
});
$('clear').addEventListener('click', async () => {
  try {
    await send('clear', { id: record.id }); render(null);
    $('status').textContent = 'PDF and results cleared from the extension session. A submitted backend job may still finish.';
  } catch (failure) { error(failure.message); }
});
$('retry').addEventListener('click', async () => {
  try {
    if (record.hasBytes) render((await send('retry', { id: record.id })).record);
    else { await send('clear', { id: record.id }); await start(); }
  } catch (failure) { error(failure.message); }
});
$('file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  importing = true; clearTimeout(timer);
  try {
    if (file.size > MAX_BYTES) throw new Error('PDF exceeds 50 MiB.');
    record = (await send('beginImport', { name: file.name, size: file.size })).record; render(record);
    $('status').textContent = 'Reading selected PDF… Keep this popup open until the upload is submitted.';
    for (let offset = 0; offset < file.size; offset += CHUNK_BYTES) {
      const bytes = new Uint8Array(await file.slice(offset, offset + CHUNK_BYTES).arrayBuffer());
      await send('importChunk', { id: record.id, offset, data: bytesToBase64(bytes) });
    }
    const answer = await send('finishImport', { id: record.id }); importing = false; render(answer.record);
  } catch (failure) {
    if (record?.state === 'importing') { await send('clear', { id: record.id }).catch(() => {}); render(null); }
    error(failure.message);
  } finally { importing = false; $('file').disabled = !!record && !['failed', 'completed'].includes(record.state); }
});
window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); });
try {
  const initial = await send('init'); source = initial.source; render(initial.record);
  if (!initial.record) {
    if (!source.target) {
      error('Open a direct PDF tab, or choose a PDF file. Embedded, blob, and protected browser viewers may not be accessible.');
      // Chrome can hide even a local tab's URL until file access is enabled.
      // Explain the setting without attempting to bypass that restriction.
      if (!initial.fileAccess) { $('local-access').hidden = false; $('local-access').textContent = 'Local PDF? Enable file access'; }
    }
    else if (source.target.local && !initial.fileAccess) {
      $('local-access').hidden = false; error('Enable “Allow access to file URLs” in extension details, then reopen here. Or choose the PDF file.');
    } else if (!initial.permitted) {
      $('permission').hidden = false; error('Allow access to the PDF’s site to analyze this tab.');
    } else await start();
  }
} catch (failure) { error(failure.message); }
document.body.dataset.ready = 'true';
