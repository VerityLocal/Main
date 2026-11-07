export function checkedSpan(text, start, end) {
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < 0 || start >= end || end > text.length) throw new Error("Invalid UTF-16 span");
  for (const boundary of [start, end]) {
    if (boundary > 0 && boundary < text.length) {
      const before = text.charCodeAt(boundary - 1), after = text.charCodeAt(boundary);
      if (before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff) throw new Error("Span splits a surrogate pair");
    }
  }
}

export function rangeForSegments(segments, start, end) {
  const ranges = [];
  for (const segment of segments) {
    if (!segment.node || !segment.node.isConnected || end <= segment.start || start >= segment.end) continue;
    const range = segment.node.ownerDocument.createRange();
    range.setStart(segment.node, Math.max(0, start - segment.start));
    range.setEnd(segment.node, Math.min(segment.node.data.length, end - segment.start));
    ranges.push(range);
  }
  return ranges;
}
