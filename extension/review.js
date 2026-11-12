import { MAX_BYTES, fileFormat, pdfSignature, describeSources, sourceRanges } from './common.js';
import { upload, jobStatus } from './api.js';
import { evidenceList, renderPassages, renderSummary } from './evidence.js';
import { pdfTarget } from './capture.js';
import { analysisId } from './session.js';
const $ = id => document.getElementById(id);
let bytes, format, sourceText, result, pdf, pdfTask, page = 1, selected, generation = 0, renderTask, renderGeneration = 0;
let captureTarget;
let sharedId;
const query = new URL(location.href).searchParams;
async function coordinator(type, extra = {}) {
  const answer = await chrome.runtime.sendMessage({ channel: 'coordinator', type, ...extra });
  if (!answer) throw new Error('Extension background is unavailable.');
  if (answer.error) throw new Error(answer.error); return answer;
}
if (query.has('sourceTab')) {
  try { captureTarget = (await coordinator('reviewSource', { tabId: Number(query.get('sourceTab')) })).source; }
  catch (error) { $('status').textContent = error.message; }
}
function status(message) { $('status').textContent = message; }
function busy(value) { $('analyze').disabled = value || !bytes; $('capture').disabled = value || !captureTarget; $('file').disabled = value; }
async function clear() {
  const current = ++generation; result = null; bytes = null; sourceText = null; selected = null;
  let release;
  if (sharedId) {
    const previousId = sharedId; sharedId = null;
    release = coordinator('releaseReview', { id: previousId }).catch(() => {});
  }
  const previous = pdfTask; pdfTask = null; pdf = null; renderGeneration++;
  renderTask?.cancel();
  $('results').hidden = true; $('progress').hidden = true; $('pdf-canvas').hidden = true;
  $('pdf-canvas').dataset.renderedPage = ''; $('pdf-canvas').dataset.highlightedBoxes = '0';
  $('pdf-controls').hidden = true; $('source-view').hidden = true; $('file').value = '';
  $('passages').replaceChildren(); $('source-view').replaceChildren(); busy(false);
  status('Review cleared. No document or result is saved in browser storage.');
  await previous?.destroy();
  await release;
  return current;
}
async function loadFile(data, name) {
  const nextFormat = fileFormat(name);
  if (!nextFormat) throw new Error('Choose a .pdf, .py, .js, or .txt file.');
  if (data.byteLength > MAX_BYTES) throw new Error('File exceeds 50 MiB.');
  if (nextFormat === 'pdf' && !pdfSignature(data)) throw new Error('File does not contain PDF bytes.');
  // TextDecoder already removes the encoding BOM, exactly like utf-8-sig.
  const decoded = nextFormat !== 'pdf' ? new TextDecoder('utf-8', { fatal: true }).decode(data) : null;
  const current = await clear();
  if (current !== generation) return;
  bytes = data; format = nextFormat; sourceText = decoded;
  status(`Ready: ${name}. Content is kept in this review tab only.`); busy(false);
}
$('file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  const current = await clear();
  if (current !== generation) return;
  busy(true); status('Reading selected file…');
  try {
    if (file.size > MAX_BYTES) throw new Error('File exceeds 50 MiB.');
    const data = new Uint8Array(await file.arrayBuffer());
    if (current === generation) await loadFile(data, file.name);
  } catch (error) { if (current === generation) { status(error.message); busy(false); } }
});
$('clear').addEventListener('click', () => clear().catch(error => status(error.message)));
$('capture').addEventListener('click', async () => {
  try {
    const target = pdfTarget(captureTarget?.url);
    if (!target) throw new Error('Download this PDF and use file upload instead.');
    const granted = await chrome.permissions.request({ origins: [target.origin] });
    if (!granted) throw new Error('Site permission declined. Use file upload instead.');
    busy(true); status('Obtaining PDF bytes from the original tab…');
    const response = await coordinator('captureReviewPdf', { tabId: captureTarget.id });
    await loadFile(Uint8Array.from(response.bytes), response.name.endsWith('.pdf') ? response.name : 'document.pdf');
  } catch (error) { status(error.message); } finally { busy(false); }
});
$('analyze').addEventListener('click', async () => {
  const threshold = Number($('threshold').value);
  if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) { status('Threshold must be between 0 and 1.'); return; }
  const current = ++generation; busy(true); $('results').hidden = true; $('progress').hidden = false; $('progress').value = 0;
  try {
    const job = await upload(bytes, format, threshold);
    while (current === generation) {
      const snapshot = await jobStatus(job.job_id);
      if (current !== generation) break;
      $('progress').value = snapshot.progress;
      status(`${snapshot.status}: ${snapshot.stage.replaceAll('_', ' ')} (${Math.round(snapshot.progress * 100)}%)`);
      if (snapshot.status === 'failed') throw new Error(snapshot.error?.message || 'Analysis failed.');
      if (snapshot.status === 'completed') { result = snapshot.result; await showResult(current); break; }
      await new Promise(resolve => setTimeout(resolve, 700));
    }
  } catch (error) { if (current === generation) status(error.message); }
  finally { if (current === generation) busy(false); }
});
async function showResult(current) {
  const previous = pdfTask; pdfTask = null; pdf = null; renderGeneration++;
  renderTask?.cancel(); await previous?.destroy();
  if (current !== generation) return;
  $('results').hidden = false; $('coverage').replaceChildren();
  const coverage = result.coverage;
  for (const [label, value] of [['Pages processed', coverage.pages_processed], ['Analyzed characters', coverage.analyzed_characters], ['Unscored characters', coverage.unscored_characters], ['Excluded / uncertain characters', Object.values(coverage.excluded_characters_by_reason).reduce((a,b) => a+b,0)], ['Unread image regions', coverage.unread_image_regions], ['Duplicate image entries removed', coverage.duplicate_regions_removed]]) {
    const card = document.createElement('div'); card.className = 'card'; card.textContent = `${label}: ${value}`; $('coverage').append(card);
  }
  $('warnings').replaceChildren();
  for (const warning of [...result.warnings, result.disclaimer, coverage.note]) { const li = document.createElement('li'); li.textContent = warning; $('warnings').append(li); }
  renderSummary(result, $('modalities')); refreshPassages();
  status('Analysis complete. Review coverage and passages; scores are not proof of AI authorship.');
  // Model analysis is complete even if a background tab defers canvas painting.
  busy(false);
  if (format === 'pdf') {
    try {
      const pdfjs = await import('./vendor/pdf.mjs');
      if (current !== generation) return;
      pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdf.worker.mjs', import.meta.url).href;
      const task = pdfjs.getDocument({ data: bytes.slice(), isEvalSupported: false, useSystemFonts: false,
        cMapUrl: new URL('./vendor/cmaps/', import.meta.url).href, cMapPacked: true,
        standardFontDataUrl: new URL('./vendor/standard_fonts/', import.meta.url).href,
        wasmUrl: new URL('./vendor/wasm/', import.meta.url).href });
      pdfTask = task;
      const loaded = await task.promise;
      if (current !== generation) { await task.destroy(); return; }
      pdf = loaded;
      page = selected?.sources?.find(source => source.page != null)?.page || 1;
      $('pdf-controls').hidden = false; $('pdf-canvas').hidden = false; await renderPage();
    } catch (error) { if (current === generation) $('location').textContent = `PDF preview unavailable: ${error.message}. Run npm run build if assets are missing.`; }
  } else { $('source-view').hidden = false; highlightSource([]); }
}
function refreshPassages() { if (result) renderPassages(evidenceList(result, $('filter').value), $('passages'), item => {
  const current = generation;
  viewLocation(item).catch(error => { if (current === generation) status(error.message); });
}); }
$('filter').addEventListener('change', refreshPassages);
async function viewLocation(item) {
  selected = item; $('location').textContent = describeSources(item.sources);
  if (format === 'pdf') { const first = item.sources?.find(x => x.page != null); if (first && pdf) { page = first.page; await renderPage(); } }
  else highlightSource(item.sources || []);
}
function highlightSource(sources) {
  const root = $('source-view'); root.replaceChildren();
  const ranges = sourceRanges(sourceText, sources);
  let start = 0;
  for (const [left,right] of ranges) {
    if (left < start) continue;
    root.append(document.createTextNode(sourceText.slice(start,left)));
    const mark = document.createElement('mark'); mark.textContent = sourceText.slice(left,right); root.append(mark); start = right;
  }
  root.append(document.createTextNode(sourceText.slice(start))); root.querySelector('mark')?.scrollIntoView({ block:'nearest' });
}
async function renderPage() {
  if (!pdf) return;
  const current = ++renderGeneration, documentPdf = pdf, pageNumber = page, snapshot = result, evidence = selected;
  const previous = renderTask;
  previous?.cancel();
  if (previous) await previous.promise.catch(() => {});
  if (current !== renderGeneration || documentPdf !== pdf) return;
  const original = await documentPdf.getPage(pageNumber);
  if (current !== renderGeneration || documentPdf !== pdf) return;
  const viewport = original.getViewport({ scale: 1.2, rotation: 0 });
  const canvas = $('pdf-canvas'); canvas.dataset.renderedPage = ''; canvas.dataset.highlightedBoxes = '0';
  canvas.width = viewport.width; canvas.height = viewport.height;
  const context = canvas.getContext('2d'); const task = original.render({ canvasContext: context, viewport }); renderTask = task;
  try { await task.promise; } catch (error) { if (error.name === 'RenderingCancelledException') return; throw error; }
  if (current !== renderGeneration || documentPdf !== pdf) return;
  // Viewer and PyMuPDF extraction both use an unrotated crop-box. Adjust for
  // crop-box offsets before PDF.js's bottom-left coordinate transform.
  let highlightedBoxes = 0;
  for (const source of evidence?.sources || []) {
    if (source.page !== pageNumber || !source.bbox) continue;
    const record = snapshot.coverage.pages.find(x => x.number === pageNumber);
    if (!record) continue;
    const [x0,y0,x1,y1] = source.bbox;
    const rect = [...viewport.convertToViewportPoint(original.view[0]+x0, original.view[3]-y1),
                  ...viewport.convertToViewportPoint(original.view[0]+x1, original.view[3]-y0)];
    context.fillStyle = 'rgba(245, 174, 30, .28)'; context.strokeStyle = '#b57100';
    context.fillRect(Math.min(rect[0],rect[2]),Math.min(rect[1],rect[3]),Math.abs(rect[2]-rect[0]),Math.abs(rect[3]-rect[1]));
    context.strokeRect(Math.min(rect[0],rect[2]),Math.min(rect[1],rect[3]),Math.abs(rect[2]-rect[0]),Math.abs(rect[3]-rect[1]));
    highlightedBoxes++;
  }
  $('page-number').textContent = `${pageNumber} / ${documentPdf.numPages}`; $('previous').disabled = pageNumber <= 1; $('next').disabled = pageNumber >= documentPdf.numPages;
  canvas.dataset.renderedPage = String(pageNumber);
  canvas.dataset.highlightedBoxes = String(highlightedBoxes);
}
$('previous').addEventListener('click', () => { if (page > 1) { page--; renderPage().catch(error => status(error.message)); } });
$('next').addEventListener('click', () => { if (pdf && page < pdf.numPages) { page++; renderPage().catch(error => status(error.message)); } });
document.body.dataset.ready = 'true';
busy(false);
if (query.has('analysis')) {
  busy(true); status('Opening the existing PDF analysis…');
  try {
    const id = query.get('analysis');
    if (!analysisId(id)) throw new Error('Invalid analysis session.');
    const existing = await coordinator('reviewData', { id });
    const blobUrl = new URL(existing.blobUrl);
    if (blobUrl.protocol !== 'blob:' || !existing.blobUrl.startsWith(`blob:${chrome.runtime.getURL('')}`)) throw new Error('Invalid document handoff.');
    const response = await fetch(existing.blobUrl, { credentials: 'omit' });
    if (!response.ok) throw new Error('The temporary PDF expired. Analyze it again.');
    await loadFile(new Uint8Array(await response.arrayBuffer()), 'document.pdf');
    sharedId = id; result = existing.result;
    await showResult(generation);
  } catch (error) { status(error.message); }
  finally { busy(false); }
}
