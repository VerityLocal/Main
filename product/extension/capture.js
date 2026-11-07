export const MAX_BYTES = 16 * 1024 * 1024;
const api = () => globalThis.browser || globalThis.chrome;

export function pdfURL(value, base) {
  try {
    const url = new URL(value, base);
    if (/viewer\.html$/i.test(url.pathname)) {
      const target = url.searchParams.get("file");
      if (target && /\.pdf(?:[?#]|$)/i.test(target)) return pdfURL(target, url.href);
    }
    if (!["http:", "https:", "file:", "blob:"].includes(url.protocol)) {
      // Built-in viewers can put the original document in a query parameter.
      for (const name of ["file", "src", "url"]) {
        const target = url.searchParams.get(name);
        if (target && /\.pdf(?:[?#]|$)/i.test(target)) return pdfURL(target);
      }
      return null;
    }
    return /\.pdf$/i.test(url.pathname) ? url.href : null;
  } catch { return null; }
}

// Runs in the current page's MAIN world. Its output is data, never trusted HTML/code.
export async function probePage(mode = "probe") {
  const viewer = globalThis.PDFViewerApplication;
  if (viewer?.pdfDocument) {
    if (mode === "bytes") {
      const data = await viewer.pdfDocument.getData();
      if (data.byteLength > 16 * 1024 * 1024) return { error: "The active PDF exceeds 16 MB" };
      let binary = "";
      for (let i = 0; i < data.length; i += 32768) binary += String.fromCharCode(...data.subarray(i, i + 32768));
      return { data: btoa(binary), pages: viewer.pdfDocument.numPages };
    }
    return { viewer: true, url: viewer.url || location.href, pages: viewer.pdfDocument.numPages };
  }
  const candidates = [];
  if (document.contentType === "application/pdf") candidates.push({ url: location.href, label: "Active PDF" });
  for (const element of document.querySelectorAll('embed,iframe,object')) {
    if (!element.getClientRects().length) continue;
    const raw = element.getAttribute("original-url") || element.getAttribute("src") || element.getAttribute("data");
    if (!raw) continue;
    try {
      const url = new URL(raw, location.href);
      if (element.type === "application/pdf" || /\.pdf$/i.test(url.pathname) || (/viewer\.html$/i.test(url.pathname) && url.searchParams.has("file"))) {
        candidates.push({ url: url.href, label: element.title || "Embedded PDF" });
      }
    } catch {}
  }
  return { candidates, title: document.title };
}

export async function detect(tab) {
  const direct = pdfURL(tab.url);
  if (direct) return [{ kind: "pdf", url: direct, label: tab.title || "Active PDF", tabId: tab.id }];
  if (!/^https?:|^file:/i.test(tab.url || "")) throw new Error("Open a PDF or website in a regular browser tab");
  let frames;
  try {
    frames = await api().scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, world: "MAIN", func: probePage });
  } catch {
    // Native viewer pages may reject injection; direct URLs above still work.
    frames = await api().scripting.executeScript({ target: { tabId: tab.id }, world: "MAIN", func: probePage });
  }
  const found = [];
  for (const { frameId, result } of frames) {
    if (result?.viewer) found.push({ kind: "pdf", viewer: true, frameId, url: result.url, label: "Active PDF", tabId: tab.id });
    for (const candidate of result?.candidates || []) {
      const url = pdfURL(candidate.url, tab.url) || candidate.url;
      found.push({ kind: "pdf", url, label: candidate.label, tabId: tab.id });
    }
  }
  // Do not substitute the surrounding website if an embedded PDF cannot be fetched.
  const unique = [...new Map(found.map(value => [value.url, value])).values()];
  return unique.length ? unique : [{ kind: "website", url: tab.url, tabId: tab.id, label: tab.title || "Current website" }];
}

export function permissionPattern(value) {
  const url = new URL(value);
  if (url.protocol === "file:") return "file:///*";
  if (!["http:", "https:"].includes(url.protocol)) return null;
  return `${url.protocol}//${url.hostname}/*`;
}

export async function allowPDF(source) {
  if (source.viewer) return true;
  const pattern = permissionPattern(source.url);
  if (!pattern) throw new Error("This PDF cannot be accessed directly. Open it in its own tab");
  const permissions = { origins: [pattern] };
  if (await api().permissions.contains(permissions)) return true;
  if (!await api().permissions.request(permissions)) throw new Error("PDF access was not granted. No content was read");
  return true;
}

async function boundedBytes(response) {
  if (!response.ok) throw new Error("The active PDF could not be read. Open its original URL in a tab");
  const length = Number(response.headers.get("content-length"));
  if (length > MAX_BYTES) throw new Error("The active PDF exceeds 16 MB");
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > MAX_BYTES) throw new Error("The active PDF exceeds 16 MB");
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(() => {}); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  if (!new TextDecoder().decode(bytes.slice(0, 1024)).trimStart().startsWith("%PDF-")) throw new Error("The active resource is not a readable PDF");
  let binary = "";
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(binary);
}

export async function capture(source, helper, signal) {
  if (source.kind === "website") {
    const values = await api().scripting.executeScript({ target: { tabId: source.tabId }, files: ["content.js"] });
    const result = values[0]?.result;
    if (result?.error || !result?.text?.trim()) throw new Error(result?.error || "No readable website text was found");
    return result;
  }
  let data;
  if (source.viewer) {
    const values = await api().scripting.executeScript({ target: { tabId: source.tabId, frameIds: [source.frameId] }, world: "MAIN", func: probePage, args: ["bytes"] });
    const result = values[0]?.result;
    if (!result?.data || result.error) throw new Error(result?.error || "The PDF viewer is not ready. Try again after it loads");
    if (result.pages > 200) throw new Error("The active PDF exceeds 200 pages");
    data = result.data;
  } else {
    // Already-authorized active-document acquisition, not an AI analysis web call.
    data = await boundedBytes(await fetch(source.url, { signal, credentials: "include", cache: "default", redirect: "error" }));
  }
  return helper("/extract", { data }, signal);
}
