'use strict';
const fs = require('node:fs');
const LIMIT = 262144;
const FRAME_LIMIT = 16 * 1024 * 1024;
const DEADLINE = 25000;
const CLEAR_DELAY = 2000;

// One private connection. Values are protocol arguments, never executable source.
async function connect(endpoint) {
  const url = new URL(endpoint);
  if (url.protocol !== 'ws:' || url.hostname !== '127.0.0.1' || url.username || url.password)
    throw new Error('ENDPOINT_REFUSED');
  const socket = new WebSocket(endpoint);
  const pending = new Map();
  let sequence = 0;
  const fail = () => {
    for (const request of pending.values()) request.reject(new Error('CONNECTION_FAILED'));
    pending.clear();
  };
  socket.addEventListener('close', fail);
  socket.addEventListener('error', fail);
  socket.addEventListener('message', event => {
    try {
      if (typeof event.data !== 'string' || Buffer.byteLength(event.data, 'utf8') > FRAME_LIMIT) return fail();
      const message = JSON.parse(event.data);
      const request = pending.get(message.id);
      if (!request) return;
      pending.delete(message.id);
      if (message.error) request.reject(new Error('OPERATION_FAILED'));
      else request.resolve(message.result);
    } catch { fail(); }
  });
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, {once: true});
    socket.addEventListener('error', () => reject(new Error('CONNECTION_FAILED')), {once: true});
  });
  return {
    send(method, params = {}) {
      return new Promise((resolve, reject) => {
        const id = ++sequence;
        pending.set(id, {resolve, reject});
        socket.send(JSON.stringify({id, method, params}));
      });
    },
    close() { socket.close(); }
  };
}

// This function runs in the inspected page. It never focuses or types into a control.
function pageStep(step) {
  try {
    const roots = [document];
    for (let i = 0; i < roots.length; i++)
      for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot);
    const find = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
    if (step.mode === 'filled') {
      if (find('iframe,frame').length) return 'UNINSPECTED_FRAME';
      return step.selectors.some(s => find(s).some(e => e.value)) ? 'FILLED' : 'EMPTY';
    }
    if (location.origin !== step.origin || location.pathname !== step.path) return 'WRONG_DESTINATION';
    const visible = e => e.checkVisibility({visibilityProperty: true, opacityProperty: true});
    const exposed = e => {
      const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
      let hit = document.elementFromPoint(x, y);
      while (hit?.shadowRoot) { const next = hit.shadowRoot.elementFromPoint(x, y); if (!next || next === hit) break; hit = next; }
      return !!hit && (hit === e || e.contains(hit));
    };
    if (step.mode === 'click' || step.mode === 'click-text') {
      const candidates = step.mode === 'click' ? find(step.selector) : find('button, a, [role=button]').filter(e => e.textContent.trim() === step.text);
      const found = candidates.filter(visible);
      if (found.length !== 1 || found[0].disabled || !exposed(found[0])) return 'CONTROL_UNAVAILABLE';
      found[0].click();
      return 'CLICKED';
    }
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    if (step.mode === 'clear') {
      for (const field of step.fields)
        for (const node of find(field.selector)) {
          if (!node.value?.includes(field.value)) continue;
          setter.call(node, '');
          node.dispatchEvent(new Event('input', {bubbles: true}));
          node.dispatchEvent(new Event('change', {bubbles: true}));
        }
      return 'CLEARED';
    }
    const nodes = step.fields.map(field => find(field.selector));
    if (nodes.some((n, i) => n.length !== 1 || n[0].nodeName !== 'INPUT' || n[0].disabled || n[0].readOnly || !visible(n[0]) || !exposed(n[0]) || !step.fields[i].types.includes(n[0].type))) return 'FIELD_UNAVAILABLE';
    const buttons = find(step.submit);
    if (buttons.length !== 1 || !visible(buttons[0]) || !exposed(buttons[0])) return 'SUBMIT_UNAVAILABLE';
    if (step.mode === 'check') return 'READY';
    if (step.mode === 'fill') {
      for (let i = 0; i < nodes.length; i++) {
        const node = nodes[i][0];
        setter.call(node, step.fields[i].value);
        node.dispatchEvent(new Event('input', {bubbles: true}));
        node.dispatchEvent(new Event('change', {bubbles: true}));
      }
    }
    if (nodes.some((n, i) => !n[0].isConnected || n[0].value !== step.fields[i].value)) return 'FIELD_CHANGED';
    if (step.mode === 'fill') return 'FIELDS_VERIFIED';
    if (step.mode !== 'submit' || buttons[0].disabled || !buttons[0].isConnected || !exposed(buttons[0])) return 'SUBMIT_UNAVAILABLE';
    buttons[0].click();
    return 'SUBMITTED';
  } catch { return 'PAGE_OPERATION_FAILED'; }
}

async function call(client, objectId, step) {
  const reply = await client.send('Runtime.callFunctionOn', {
    objectId, functionDeclaration: pageStep.toString(), arguments: [{value: step}], returnByValue: true
  });
  if (reply.exceptionDetails || typeof reply.result?.value !== 'string') throw new Error('PAGE_OPERATION_FAILED');
  return reply.result.value;
}

async function operate(client, request) {
  if (request.action === 'pages') {
    const {targetInfos} = await client.send('Target.getTargets');
    return {pages: targetInfos.filter(t => t.type === 'page').map(t => t.targetId),
      frames: targetInfos.some(t => t.type === 'iframe')};
  }
  if (request.action === 'create') {
    if (request.fresh) {
      const {targetInfos} = await client.send('Target.getTargets');
      if (targetInfos.some(target => target.type === 'page'))
        return {result: 'BROWSER_BLOCKED', reason: 'BROWSER_PROFILE_RESTORED_TABS'};
    }
    const target = await client.send('Target.createTarget', {url: 'about:blank', newWindow: true, background: true});
    const window = await client.send('Browser.getWindowForTarget', {targetId: target.targetId});
    await client.send('Browser.setWindowBounds', {windowId: window.windowId, bounds: {width: 1280, height: 900, windowState: 'normal'}});
    return target;
  }
  if (request.action === 'viewport') {
    // The window frame differs by machine, so it is measured and added to the page size.
    const read = async () => (await client.send('Runtime.evaluate', {
      expression: '[innerWidth, innerHeight, outerWidth - innerWidth, outerHeight - innerHeight]', returnByValue: true
    })).result.value;
    const [, , frameWidth, frameHeight] = await read();
    const {windowId} = await client.send('Browser.getWindowForTarget');
    await client.send('Browser.setWindowBounds', {windowId, bounds: {
      width: request.width + frameWidth, height: request.height + frameHeight, windowState: 'normal'}});
    const deadline = Date.now() + 2000;
    let size = await read();
    while ((size[0] < request.width || size[1] < request.height) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 100));
      size = await read();
    }
    return {result: 'BROWSER_VIEWPORT', width: size[0], height: size[1]};
  }
  if (request.action === 'close') {
    await client.send('Browser.close');
    return {result: 'BROWSER_CLOSED'};
  }
  if (request.action === 'open') {
    const previous = await client.send('Page.getFrameTree');
    const navigation = await client.send('Page.navigate', {url: request.url});
    if (navigation.errorText) throw new Error('NAVIGATION_FAILED');
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      try {
        const current = await client.send('Page.getFrameTree');
        const state = await client.send('Runtime.evaluate', {
          expression: 'location.protocol === "https:" && document.readyState !== "loading" && innerWidth > 0 && innerHeight > 0', returnByValue: true
        });
        const committed = !navigation.loaderId || current.frameTree.frame.loaderId !== previous.frameTree.frame.loaderId;
        if (committed && state.result?.value === true) return {result: 'BROWSER_OPENED'};
      } catch { /* A navigation can replace the read context. No input is repeated. */ }
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('NAVIGATION_TIMEOUT');
  }
  if (request.action === 'snapshot') {
    const tree = await client.send('Accessibility.getFullAXTree');
    return {snapshot: tree.nodes.filter(node => !node.ignored && node.name?.value && node.role?.value !== 'InlineTextBox')
      .map(node => `${node.role?.value}: ${node.name.value}`).join('\n')};
  }
  if (request.action === 'eval') {
    const response = await client.send('Runtime.evaluate', {
      expression: request.expression, returnByValue: true, awaitPromise: true
    });
    if (response.exceptionDetails) throw new Error('PAGE_OPERATION_FAILED');
    return {result: response.result?.value ?? null};
  }
  const context = await client.send('Runtime.evaluate', {expression: 'globalThis', returnByValue: false});
  const objectId = context.result?.objectId;
  if (!objectId) throw new Error('PAGE_CONTEXT_UNAVAILABLE');
  if (request.action === 'filled')
    return {result: await call(client, objectId, {mode: 'filled', selectors: request.selectors})};
  const step = request.step;
  if (request.action === 'click' || request.action === 'click-text') {
    const result = await call(client, objectId, {...step, mode: request.action});
    if (result !== 'CLICKED') throw new Error(result);
    return {result: 'BROWSER_CLICKED'};
  }
  const metadata = {...step, mode: 'check', fields: step.fields.map(({value, ...field}) => field)};
  const ready = await call(client, objectId, metadata);
  if (ready !== 'READY') {
    const known = ['WRONG_DESTINATION', 'FIELD_UNAVAILABLE', 'SUBMIT_UNAVAILABLE', 'PAGE_OPERATION_FAILED'];
    if (!known.includes(ready)) throw new Error('PAGE_OPERATION_FAILED');
    return {result: 'BROWSER_BLOCKED', phase: 'preflight', reason: ready,
      credential_input: false, submission_attempted: false};
  }
  try {
    const filled = await call(client, objectId, {...step, mode: 'fill'});
    if (filled !== 'FIELDS_VERIFIED') throw new Error(filled);
    const submitted = await call(client, objectId, {...step, mode: 'submit'});
    if (submitted !== 'SUBMITTED') throw new Error(submitted);
    await new Promise(resolve => setTimeout(resolve, CLEAR_DELAY));
  } finally { await clear(client, step); }
  return {result: 'BROWSER_LOGIN_SUBMITTED'};
}

// Navigation may replace the context. A later page command independently checks for retained values.
async function clear(client, step) {
  try {
    const context = await client.send('Runtime.evaluate', {expression: 'globalThis', returnByValue: false});
    if (context.result?.objectId) await call(client, context.result.objectId, {...step, mode: 'clear'});
  } catch { /* A replaced document no longer holds the step's controls. */ }
}

async function main() {
  const timer = setTimeout(() => { console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_TIMEOUT: do not retry submission"}'); process.exit(1); }, DEADLINE);
  let client;
  try {
    const raw = fs.readFileSync(0, 'utf8');
    if (raw.length > LIMIT) throw new Error('REQUEST_REFUSED');
    const request = JSON.parse(raw);
    client = await connect(request.endpoint);
    const result = await operate(client, request);
    const output = JSON.stringify(result);
    if (output.length > LIMIT) throw new Error('RESPONSE_TOO_LARGE');
    console.log(output);
  } catch {
    console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_OPERATION_FAILED: do not retry submission"}');
    process.exitCode = 1;
  } finally { client?.close(); clearTimeout(timer); }
}
if (require.main === module) main();
module.exports = {pageStep, operate};
