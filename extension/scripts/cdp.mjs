// Local testing utility. No dependency, no disabled browser security, no production bypass.
export async function connect(url) {
  const socket = new WebSocket(url); let next = 0;
  const pending = new Map(); const listeners = new Map();
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const entry = pending.get(message.id); if (!entry) return;
      pending.delete(message.id); clearTimeout(entry.timer);
      message.error ? entry.reject(new Error(message.error.message)) : entry.resolve(message.result);
    } else for (const listener of listeners.get(message.method) || []) listener(message.params);
  });
  socket.addEventListener('close', () => {
    for (const entry of pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('DevTools target closed.')); }
    pending.clear();
  });
  return {
    send(method, params = {}) {
      return new Promise((resolve, reject) => {
        if (socket.readyState !== WebSocket.OPEN) { reject(new Error('DevTools target closed.')); return; }
        const id = ++next;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timed out: ${method}`)); }, 240000);
        pending.set(id, { resolve, reject, timer }); socket.send(JSON.stringify({ id, method, params }));
      });
    },
    on(method, listener) { listeners.set(method, [...(listeners.get(method) || []), listener]); },
    close() { socket.close(); }
  };
}
export async function evaluate(client, expression) {
  const answer = await client.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (answer.exceptionDetails) throw new Error(answer.exceptionDetails.exception?.description || answer.exceptionDetails.text);
  return answer.result.value;
}
export function waitExpression(expression, timeout = 180000) {
  return `new Promise((resolve,reject)=>{const started=Date.now(); const tick=async()=>{try{const value=await (${expression});if(value)return resolve(value);if(Date.now()-started>${timeout})return reject(new Error('Condition timed out'));setTimeout(tick,100);}catch(e){reject(e)}};tick()})`;
}
