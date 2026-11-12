import test from 'node:test';
import assert from 'node:assert/strict';

const id = 'a'.repeat(32);
const sender = path => ({ id, url: `chrome-extension://${id}/${path}` });
async function boot({ allowed = true, localAccess = false } = {}) {
  let listener, hidden = false, tab = { id: 7, url: 'https://example.com/paper.pdf', title: 'PDF' };
  const calls = [];
  globalThis.chrome = {
    storage: { local: { setAccessLevel: async () => {}, get: async () => ({ backend: 'http://127.0.0.1:8765', token: 't'.repeat(40) }) }, session: { setAccessLevel: async () => {} } },
    runtime: { id, getURL: path => `chrome-extension://${id}/${path.replace(/^\//, '')}`,
      getContexts: async () => hidden ? [{}] : [],
      onMessage: { addListener: value => { listener = value; } },
      sendMessage: async message => { calls.push(message); return message.type === 'empty' ? { empty: true } : { record: null }; } },
    offscreen: { createDocument: async options => { hidden = true; calls.push({ type: 'create', options }); }, closeDocument: async () => { hidden = false; calls.push({ type: 'close' }); } },
    tabs: { query: async () => [tab], get: async tabId => { assert.equal(tabId, tab.id); return tab; },
      create: async options => { calls.push({ type: 'tab', options }); return { id: 9 }; },
      onRemoved: { addListener: () => {} }, onUpdated: { addListener: () => {} } },
    extension: { isAllowedFileSchemeAccess: async () => localAccess }, permissions: { contains: async () => allowed }
  };
  await import(`../background.js?test=${crypto.randomUUID()}`);
  return {
    calls, changeTab: value => { tab = { ...tab, ...value }; },
    send: (message, from = sender('popup.html')) => new Promise(resolve => {
      const async = listener({ channel: 'coordinator', ...message }, from, resolve); if (!async) resolve(undefined);
    })
  };
}
test('site pages, content scripts, and unrelated extension pages cannot start analysis', async () => {
  const app = await boot();
  for (const from of [{ id, url: 'https://example.com' }, { id: 'b'.repeat(32), url: sender('popup.html').url }, sender('options.html')]) {
    assert.equal(await app.send({ type: 'start' }, from), undefined);
  }
  assert.equal(app.calls.length, 0);
});
test('permission refusal fails closed without downloading or uploading', async () => {
  const app = await boot({ allowed: false });
  const initial = await app.send({ type: 'init' }); assert.equal(initial.permitted, false);
  const response = await app.send({ type: 'start', source: initial.source });
  assert.match(response.error, /Allow access/); assert(!app.calls.some(x => x.type === 'start'));
});
test('a popup cannot reuse a capture target after its tab navigates', async () => {
  const app = await boot(); const initial = await app.send({ type: 'init' });
  app.changeTab({ url: 'https://example.com/other.pdf' });
  assert.match((await app.send({ type: 'start', source: initial.source })).error, /original tab changed/);
  assert(!app.calls.some(x => x.type === 'start'));
});
test('only trusted background-to-offscreen messages carry backend credentials', async () => {
  const app = await boot(); const initial = await app.send({ type: 'init' });
  assert(!JSON.stringify(initial).includes('t'.repeat(40)));
  await app.send({ type: 'start', source: initial.source });
  const command = app.calls.find(x => x.type === 'start');
  assert.equal(command.channel, 'offscreen'); assert.equal(command.auth.backend, 'http://127.0.0.1:8765');
  assert.equal(command.auth.token, 't'.repeat(40));
});
test('local-file capture requires Chrome file-access setting as well as permission', async () => {
  const app = await boot({ allowed: true, localAccess: false });
  app.changeTab({ url: 'file:///Users/student/paper.pdf' });
  const initial = await app.send({ type: 'init' }); assert(initial.source.target.local); assert.equal(initial.permitted, false);
  assert((await app.send({ type: 'start', source: initial.source })).error);
});
test('details are only delivered to their matching opaque review URL', async () => {
  const app = await boot(); const analysis = crypto.randomUUID();
  assert.match((await app.send({ type: 'reviewData', id: analysis }, sender('review.html?analysis=wrong'))).error, /Invalid review/);
  assert(!app.calls.some(x => x.type === 'review'));
  await app.send({ type: 'reviewData', id: analysis }, sender(`review.html?analysis=${analysis}`));
  assert(app.calls.some(x => x.type === 'review' && x.id === analysis));
});
test('idle offscreen cleanup is serialized and rejects forged idle messages', async () => {
  const app = await boot(); await app.send({ type: 'init' });
  assert.equal(await app.send({ type: 'offscreenIdle' }, { id, url: 'https://example.com' }), undefined);
  await app.send({ type: 'offscreenIdle' }, sender('offscreen.html'));
  assert(app.calls.some(x => x.type === 'close'));
});
