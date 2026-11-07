chrome.storage.local.setAccessLevel({ accessLevel: "TRUSTED_CONTEXTS" }).catch(() => {});
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
chrome.runtime.onMessage.addListener((message, sender) => {
  if (sender.id !== chrome.runtime.id) return;
  if (message.type === "verity.document.changed" && sender.tab) {
    chrome.storage.local.set({ [`revision:${sender.tab.id}`]: { document_id: message.document_id, revision: message.revision } });
  }
});
