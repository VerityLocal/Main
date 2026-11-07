const api = globalThis.browser || globalThis.chrome;
api.storage.local.setAccessLevel?.({ accessLevel: "TRUSTED_CONTEXTS" }).catch(() => {});
api.sidePanel?.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
// Tab changes invalidate only that tab's scan. Never persist document text.
api.tabs.onUpdated.addListener((tabId, change) => {
  if (change.status === "loading" || change.url) api.runtime.sendMessage({ type: "verity.invalidated", tabId }).catch(() => {});
});
