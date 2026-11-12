import { configuration } from './api.js';
import { fetchPdf, pdfTarget, pdfName } from './capture.js';
import { analysisId } from './session.js';

chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
chrome.storage.session.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
let bridge = Promise.resolve();
function serialized(action) {
  const result = bridge.then(action); bridge = result.catch(() => {}); return result;
}
function offscreen(message) { return serialized(() => dispatch(message)); }
async function dispatch(message) {
  const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'], documentUrls: [chrome.runtime.getURL('offscreen.html')] });
  if (!contexts.length) await chrome.offscreen.createDocument({ url: 'offscreen.html', reasons: ['BLOBS'],
    justification: 'Retain bounded, temporary PDF Blob URLs for optional evidence review and finish uploads after the popup closes.' });
  const answer = await chrome.runtime.sendMessage({ ...message, channel: 'offscreen' });
  if (!answer) throw new Error('Analysis session was interrupted. Reopen the extension and try again.');
  if (answer.error) throw new Error(answer.error);
  return answer;
}
async function sourceTab(id) {
  const tab = Number.isInteger(id) ? await chrome.tabs.get(id) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  if (!tab?.id) throw new Error('No active document tab was found.');
  const target = pdfTarget(tab.url);
  return { id: tab.id, url: target?.url || tab.url || '', name: target ? pdfName(target.url) : 'Choose a PDF',
    target, title: tab.title || '' };
}
async function verifySource(source) {
  if (!source || !Number.isInteger(source.id)) throw new Error('No original PDF tab was selected.');
  const current = await sourceTab(source.id);
  if (current.url !== source.url) throw new Error('The original tab changed. Reopen the extension on the PDF.');
  return current;
}
async function permission(source) {
  if (!source.target) return false;
  if (source.target.local && !(await chrome.extension.isAllowedFileSchemeAccess())) return false;
  return chrome.permissions.contains({ origins: [source.target.origin] });
}
function trustedPage(sender) {
  if (sender.id !== chrome.runtime.id || !sender.url) return '';
  const url = new URL(sender.url);
  if (url.protocol !== 'chrome-extension:' || url.hostname !== chrome.runtime.id) return '';
  return ['/popup.html', '/review.html'].includes(url.pathname) ? url.pathname : '';
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message?.channel !== 'coordinator') return false;
  if (message.type === 'offscreenIdle' && sender.id === chrome.runtime.id && sender.url === chrome.runtime.getURL('offscreen.html')) {
    serialized(async () => {
      const contexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
      if (contexts.length && (await dispatch({ type: 'empty' })).empty) await chrome.offscreen.closeDocument();
      return {};
    }).then(respond).catch(error => respond({ error: error.message }));
    return true;
  }
  const page = trustedPage(sender); if (!page) return false;
  (async () => {
    const type = message.type;
    if (page === '/review.html') {
      if (type === 'reviewData') {
        if (!analysisId(message.id) || new URL(sender.url).searchParams.get('analysis') !== message.id) throw new Error('Invalid review session.');
        return offscreen({ type: 'review', id: message.id });
      }
      if (type === 'releaseReview') {
        if (new URL(sender.url).searchParams.get('analysis') !== message.id) throw new Error('Invalid review session.');
        return offscreen({ type: 'clear', id: message.id });
      }
      if (type === 'reviewSource' || type === 'captureReviewPdf') {
        if (Number(new URL(sender.url).searchParams.get('sourceTab')) !== message.tabId) throw new Error('Open the review from the popup to select its original tab.');
        const source = await sourceTab(message.tabId);
        if (type === 'reviewSource') return { source };
        if (!(await permission(source))) throw new Error('Site permission was not granted. Choose the PDF file instead.');
        const bytes = await fetchPdf(source.url);
        return { bytes: Array.from(bytes), name: source.name };
      }
      throw new Error('Unsupported review request.');
    }
    if (type === 'init') {
      const source = await sourceTab();
      const { record } = await offscreen({ type: 'peek', source });
      return { source, record, permitted: await permission(source), fileAccess: await chrome.extension.isAllowedFileSchemeAccess() };
    }
    const source = await verifySource(message.source);
    if (type === 'start') {
      if (!(await permission(source))) throw new Error('Allow access to this PDF site, or choose the PDF file instead.');
      return offscreen({ type: 'start', source, auth: await configuration() });
    }
    if (type === 'beginImport') {
      await configuration();
      return offscreen({ type, source, name: message.name, size: message.size });
    }
    if (['importChunk', 'finishImport', 'retry', 'peek', 'clear'].includes(type)) {
      if (type !== 'peek' && !analysisId(message.id)) throw new Error('Invalid analysis session.');
      return offscreen({ type, source, id: message.id, data: message.data, offset: message.offset,
        ...(['finishImport', 'retry'].includes(type) ? { auth: await configuration() } : {}) });
    }
    if (type === 'details') {
      if (!analysisId(message.id)) throw new Error('Invalid analysis session.');
      await offscreen({ type: 'validateReview', source, id: message.id });
      const tab = await chrome.tabs.create({ url: chrome.runtime.getURL(`review.html?analysis=${message.id}`) });
      return { tabId: tab.id };
    }
    if (type === 'manualReview') {
      await chrome.tabs.create({ url: chrome.runtime.getURL(`review.html?sourceTab=${source.id}`) }); return {};
    }
    throw new Error('Unsupported popup request.');
  })().then(respond).catch(error => respond({ error: error.message }));
  return true;
});
async function forgetTab(tabId) {
  // Do not create a hidden document just because an unrelated tab navigates.
  if ((await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] })).length) {
    await offscreen({ type: 'forgetTab', tabId });
  }
}
chrome.tabs.onRemoved.addListener(id => { forgetTab(id).catch(() => {}); });
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.status === 'loading') forgetTab(id).catch(() => {});
});
