import { describeSources, percent } from './common.js';
export function evidenceList(result, filter) {
  if (filter === 'excluded') return result.exclusions.map(item => ({ ...item, modality: 'excluded' }));
  return ['text', 'code'].flatMap(kind => {
    const summary = result[kind];
    const items = filter === 'analyzed' ? summary.chunk_scores : filter === 'unscored' ? summary.unscored_passages : summary.flagged_passages;
    return (items || []).map(item => ({ ...item, modality: kind }));
  });
}
export function renderSummary(result, root, doc = document) {
  root.replaceChildren();
  for (const kind of ['text', 'code']) {
    const value = result[kind]; const card = doc.createElement('article'); card.className = 'card';
    const heading = doc.createElement('h3'); heading.textContent = kind === 'text' ? 'Theory / prose' : 'Code';
    const badge = doc.createElement('span'); badge.className = 'badge'; badge.textContent = 'Unvalidated for university submissions';
    const metric = doc.createElement('p'); metric.className = 'metric'; metric.textContent = percent(value.flagged_content_share);
    const label = doc.createElement('p'); label.textContent = 'Share of analyzed content flagged';
    const info = doc.createElement('p'); info.className = 'muted';
    info.textContent = `${value.status.replaceAll('_',' ')} · ${value.analyzed_tokens} analyzed tokens · threshold ${value.threshold}. Not percentage actually AI-written.`;
    card.append(heading, badge, metric, label, info); root.append(card);
  }
}
export function renderPassages(items, root, onView, doc = document) {
  root.replaceChildren();
  if (!items.length) { const p = doc.createElement('p'); p.textContent = 'No passages in this category. This does not establish human authorship.'; root.append(p); }
  for (const item of items) {
    const detail = doc.createElement('details'); detail.className = 'passage';
    const summary = doc.createElement('summary');
    summary.textContent = `${item.modality} · ${describeSources(item.sources)} · ${item.reason || `raw score ${item.probability?.toFixed(3)}`}`;
    const pre = doc.createElement('pre'); pre.textContent = item.text || '(No readable passage text)';
    const provenance = doc.createElement('p'); provenance.className = 'muted';
    provenance.textContent = `Section: ${item.section || 'Unknown'} · Extraction: ${[...new Set((item.sources || []).map(x => x.method))].join(', ')}. PDF highlights cover extracted line boxes, not exact glyphs.`;
    const button = doc.createElement('button'); button.className = 'secondary'; button.textContent = 'View location'; button.addEventListener('click', () => onView(item));
    detail.append(summary, pre, provenance, button); root.append(detail);
  }
}
