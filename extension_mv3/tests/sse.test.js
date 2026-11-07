import test from "node:test";
import assert from "node:assert/strict";
import { consumeSSE, acceptEvent } from "../src/messaging/sse.js";

function response(chunks) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({ start(controller) {
    for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
    controller.close();
  } }));
}
test("SSE handles CRLF across byte boundaries and Unicode", async () => {
  const frame = 'event: analysis.started\r\ndata: {"text":"😀 café"}\r\n\r\n';
  const bytes = new TextEncoder().encode(frame);
  const received = [];
  await consumeSSE(response([...bytes].map(byte => new Uint8Array([byte]))), (name, event) => received.push([name, event]));
  assert.deepEqual(received, [["analysis.started", { text: "😀 café" }]]);
});
test("comments ignored and incomplete final frame never applied", async () => {
  const received = [];
  await consumeSSE(response([': heartbeat\n\ndata: {"a":1}\n\n', 'data: {"a":2}\n']), (_, e) => received.push(e));
  assert.deepEqual(received, [{ a: 1 }]);
});
test("multi-line data, CR-only separators, invalid and oversized input", async () => {
  const received = [];
  await consumeSSE(response(['event: x\rdata: {\rdata: "a": 1}\r\r']), (name, e) => received.push([name, e]));
  assert.deepEqual(received, [["x", { a: 1 }]]);
  await assert.rejects(consumeSSE(response(['data: []\n\n']), () => {}), /envelope/);
  await assert.rejects(consumeSSE(response(['data: invalid\n\n']), () => {}), SyntaxError);
  await assert.rejects(consumeSSE(response(['x'.repeat(1_000_001)]), () => {}), /too large/);
});
test("reject stale/mismatched/gapped events; ignore replay duplicates", () => {
  const state = { request_id: "r", document_id: "d", document_revision: 2, sequence: 0 };
  const event = { request_id: "r", document_id: "d", document_revision: 2, sequence: 1, offset_unit: "utf16_code_unit" };
  assert.equal(acceptEvent(state, event), true);
  assert.equal(acceptEvent(state, event), false);
  assert.throws(() => acceptEvent(state, { ...event, document_revision: 1 }), /Mismatched/);
  assert.throws(() => acceptEvent(state, { ...event, request_id: "other" }), /Mismatched/);
  assert.throws(() => acceptEvent(state, { ...event, sequence: 3 }), /Missing/);
  assert.throws(() => acceptEvent(state, { ...event, sequence: 1.5 }), /Invalid/);
});
