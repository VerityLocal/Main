export function isGoogleDocs(url) {
  try { const parsed = new URL(url); return parsed.hostname === "docs.google.com" && parsed.pathname.startsWith("/document/"); }
  catch { return false; }
}
export const GOOGLE_DOCS_MESSAGE = "Google Docs canvas integration is disabled. Paste the document text for local analysis.";
