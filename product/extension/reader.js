export function safeURL(value) {
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch { return null; }
}
export const percent = score => Number.isFinite(score) ? `${Math.round(score * 100)}%` : "Unavailable";

export function validateResult(result, text) {
  if (result.schema_version !== 1 || result.text !== text || !Array.isArray(result.segments) || result.segments.length > 1500) throw new Error("The scan does not match this document");
  let end = 0;
  for (const row of result.segments) {
    if (!Number.isInteger(row.start) || !Number.isInteger(row.end) || row.start < end || row.end <= row.start || row.end > text.length || text.slice(row.start, row.end) !== row.text) throw new Error("The scan contains invalid text ranges");
    for (const key of ["ai", "plagiarism"]) {
      const value = row[key];
      if (!value || (value.score !== null && (!Number.isFinite(value.score) || value.score < 0 || value.score > 1))) throw new Error("The scan contains invalid scores");
    }
    end = row.end;
  }
  return result;
}

export function renderReader(container, text, rows, onSelect) {
  const doc = container.ownerDocument;
  container.replaceChildren();
  let end = 0;
  for (const row of rows) {
    container.append(doc.createTextNode(text.slice(end, row.start)));
    const element = doc.createElement("span");
    element.textContent = text.slice(row.start, row.end);
    const copy = row.plagiarism.score >= 0.72;
    const ai = row.ai.score >= 0.65;
    element.className = `segment${copy ? " copied" : ""}${ai ? " artificial" : ""}`;
    element.tabIndex = 0;
    element.setAttribute("role", "button");
    const source = safeURL(row.plagiarism.match?.url);
    element.title = `Source similarity: ${percent(row.plagiarism.score)}\nAI estimate: ${percent(row.ai.score)}\nAI classification confidence: ${percent(row.ai.confidence)}${source ? "\nSource: " + source : ""}`;
    element.setAttribute("aria-label", element.title + " — " + row.text);
    element.addEventListener("click", () => onSelect(row));
    element.addEventListener("focus", () => onSelect(row));
    element.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(row); } });
    container.append(element);
    end = row.end;
  }
  container.append(doc.createTextNode(text.slice(end)));
}

export function exportReport(result, identity, format) {
  const report = { product: "Verity", scanned_at: new Date().toISOString(), document: identity, ...result };
  if (format === "json") return { content: JSON.stringify(report, null, 2), type: "application/json", extension: "json" };
  const lines = ["Verity review", identity.title || "Active document", "", ...result.notes, "", `AI-written estimate (scored text): ${result.overall.ai.percent == null ? "Unavailable" : Math.round(result.overall.ai.percent) + "%"}`, `Source similarity (checked text): ${result.overall.plagiarism.percent == null ? "Unavailable" : Math.round(result.overall.plagiarism.percent) + "%"}`, `AI coverage: ${percent(result.overall.ai.coverage)}; source search coverage: ${percent(result.overall.plagiarism.search_coverage)}`, ""];
  for (const row of result.segments) lines.push(row.text, `AI: ${percent(row.ai.score)} (${row.ai.status}), confidence ${percent(row.ai.confidence)}; source similarity: ${percent(row.plagiarism.score)} (${row.plagiarism.status})`, safeURL(row.plagiarism.match?.url) || "", "");
  return { content: lines.join("\n"), type: "text/plain", extension: "txt" };
}
