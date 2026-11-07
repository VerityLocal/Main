export async function consumeSSE(response, callback, signal) {
  if (!response.ok || !response.body) throw new Error(`Event connection failed (${response.status})`);
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = "", lines = [], frameSize = 0;
  const line = async value => {
    if (value !== "") {
      frameSize += value.length;
      if (frameSize > 1_000_000) throw new Error("Event frame is too large");
      lines.push(value); return;
    }
    const data = lines.filter(v => v.startsWith("data:")).map(v => v.slice(5).replace(/^ /, "")).join("\n");
    const name = lines.find(v => v.startsWith("event:"))?.slice(6).trim();
    lines = []; frameSize = 0;
    if (!data) return;
    const parsed = JSON.parse(data);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Invalid SSE envelope");
    await callback(name, parsed);
  };
  try {
    while (!signal?.aborted) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      while (buffer.length) {
        const match = /[\r\n]/.exec(buffer);
        if (!match || (!done && match[0] === "\r" && match.index === buffer.length - 1)) break;
        const length = buffer[match.index] === "\r" && buffer[match.index + 1] === "\n" ? 2 : 1;
        await line(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + length);
      }
      if (buffer.length + frameSize > 1_000_000) throw new Error("Event frame is too large");
      if (done) break; // Incomplete frames are discarded, never applied.
    }
  } finally { await reader.cancel().catch(() => {}); }
}

export function acceptEvent(state, event) {
  if (event.request_id !== state.request_id || event.document_id !== state.document_id ||
      event.document_revision !== state.document_revision || event.offset_unit !== "utf16_code_unit") {
    throw new Error("Mismatched document event rejected");
  }
  if (!Number.isInteger(event.sequence) || event.sequence < 1) throw new Error("Invalid event sequence");
  if (event.sequence <= (state.sequence || 0)) return false;
  if (event.sequence !== (state.sequence || 0) + 1) throw new Error("Missing event sequence; resynchronize");
  state.sequence = event.sequence;
  return true;
}
