const HOST = "local.verity.helper";
const validToken = value => typeof value === "string" && /^[A-Za-z0-9_-]{32,128}$/.test(value);

export async function connectCompanion(api = globalThis.browser || globalThis.chrome) {
  if (!api?.runtime?.id) throw new Error("Load the extension in your browser first");
  const origin = api.runtime.getURL("").replace(/\/$/, "");
  let response;
  try {
    response = await api.runtime.sendNativeMessage(HOST, { type: "bootstrap", protocol: 1, origin });
  } catch {
    throw new Error("Install the Verity desktop companion once, then click Connect again. No terminal commands or pairing token are needed");
  }
  if (response?.protocol !== 1 || response.origin !== origin || !response.ready || !validToken(response.token)) {
    throw new Error(response?.code === "port_conflict" ? "Another local service is using the companion's port. Close it and click Connect again" : "The desktop companion could not start. Open the Verity installer to repair it");
  }
  await api.storage.local.set({ pairingToken: response.token });
  return response.token;
}
