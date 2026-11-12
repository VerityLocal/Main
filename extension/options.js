import { safeBackend, tokenValid } from './common.js';
import { health } from './api.js';
const $ = id => document.getElementById(id);
$('extension-id').textContent = chrome.runtime.id;
const saved = await chrome.storage.local.get(['backend', 'token']);
$('backend').value = saved.backend || 'http://127.0.0.1:8000';
$('token').value = saved.token || '';
$('settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const backend = safeBackend($('backend').value); const token = $('token').value.trim();
    if (!tokenValid(token)) throw new Error('Use a URL-safe token with at least 32 characters.');
    await chrome.storage.local.setAccessLevel({ accessLevel: 'TRUSTED_CONTEXTS' });
    await chrome.storage.local.set({ backend, token });
    const result = await health();
    $('status').textContent = `Connected. Backend ${result.status}.`;
  } catch (error) { $('status').textContent = `Connection failed: ${error.message}`; }
});
$('forget').addEventListener('click', async () => {
  await chrome.storage.local.remove('token'); $('token').value = ''; $('status').textContent = 'Token removed.';
});
$('settings-form').dataset.ready = 'true';
