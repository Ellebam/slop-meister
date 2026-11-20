'use strict';
const fs = require('node:fs');
const LIMIT = 262144;
const DEADLINE = 55000;
const CLEAR_DELAY = 2000;
// How long a later step waits for its page after the previous step was submitted.
const STEP_WAIT = 15000;
const POLL = 250;
// A page can enable its submit button from a timer after input, and Chrome delays timers to about
// a second in a tab it does not draw.
const SUBMIT_WAIT = 5000;
// A page chooses its address, and the owner-only state that keeps it has a size limit.
const ADDRESS_LIMIT = 1024;
// Only the helper's own codes leave this process, because a driver error can quote what it was sent.
// A later page can keep the username field and need its value, as Apple's password page does, so a
// username is emptied when the whole fill ends. Code and password types never include email.
const kept = field => field.types.includes('email');
// Filled steps with their documents, so the hard deadline can empty them too. A step's own clear
// empties its other fields, so after it only the kept usernames remain here.
const retained = [];
// A stalled page can stall its clear, and the caller stops waiting at 60 seconds.
const CLEAR_WAIT = 3000;
const CODES = ['WRONG_DESTINATION', 'FRAME_UNAVAILABLE', 'FIELD_UNAVAILABLE', 'SUBMIT_UNAVAILABLE',
  'FIELD_CHANGED', 'FRAME_CHANGED', 'PAGE_OPERATION_FAILED'];

// This function runs in the inspected page. It never focuses or types into a control.
function pageStep(_document, step) {
  try {
    const roots = [document];
    for (let i = 0; i < roots.length; i++)
      for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot);
    const find = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
    const visible = e => e.checkVisibility({visibilityProperty: true, opacityProperty: true});
    if (step.mode === 'filled') return step.selectors.some(s => find(s).some(e => e.value)) ? 'FILLED' : 'EMPTY';
    // The handle reaches only the document that was filled, so a path it changed itself still gets cleared.
    if (step.mode === 'clear') {
      const {set} = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
      // Events let a framework drop its copy too, so a later render cannot restore the value.
      for (const field of step.fields)
        for (const node of find(field.selector)) {
          if (!node.value?.includes(field.value)) continue;
          set.call(node, '');
          node.dispatchEvent(new Event('input', {bubbles: true}));
          node.dispatchEvent(new Event('change', {bubbles: true}));
        }
      return 'CLEARED';
    }
    if (location.origin !== step.origin || location.pathname !== step.path) return 'WRONG_DESTINATION';
    const exposed = e => {
      const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
      let hit = document.elementFromPoint(x, y);
      while (hit?.shadowRoot) { const next = hit.shadowRoot.elementFromPoint(x, y); if (!next || next === hit) break; hit = next; }
      return !!hit && (hit === e || e.contains(hit) || hit.closest?.('label')?.control === e);
    };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    const nodes = step.fields.map(field => find(field.selector));
    // The effective state, because a disabled fieldset disables its controls without their own attribute.
    if (nodes.some((n, i) => n.length !== 1 || n[0].nodeName !== 'INPUT' || n[0].matches(':disabled') || n[0].readOnly || !visible(n[0]) || !exposed(n[0]) || !step.fields[i].types.includes(n[0].type))) return 'FIELD_UNAVAILABLE';
    // Two selectors for one box, as a mistyped code box list gives, would overwrite a share before the check.
    if (new Set(nodes.map(n => n[0])).size !== nodes.length) return 'FIELD_UNAVAILABLE';
    const buttons = find(step.submit);
    // A disabled button often ignores the pointer until the fields hold values, so only the click needs it reachable.
    if (buttons.length !== 1 || !visible(buttons[0]) || (!buttons[0].matches(':disabled') && !exposed(buttons[0]))) return 'SUBMIT_UNAVAILABLE';
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
    if (step.mode !== 'submit' || buttons[0].matches(':disabled') || !buttons[0].isConnected || !exposed(buttons[0])) return 'SUBMIT_UNAVAILABLE';
    buttons[0].click();
    return 'SUBMITTED';
  } catch { return 'PAGE_OPERATION_FAILED'; }
}

// A handle runs only in the document it came from, so a value never reaches a replacement page.
async function call(context, step) {
  const value = await context.evaluate(pageStep, step);
  if (typeof value !== 'string') throw new Error('PAGE_OPERATION_FAILED');
  return value;
}

const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));

const onDestination = (page, step) => {
  try {
    const url = new URL(page.url());
    return url.origin === step.origin && url.pathname === step.path;
  } catch { return false; }
};

// A named frame is the one direct child of the top page at exactly that origin and path.
function target(page, step) {
  if (!step.frame) return page;
  const matches = page.mainFrame().childFrames().filter(frame => onDestination(frame, step.frame));
  return matches.length === 1 ? matches[0] : null;
}

// Inside a frame the document's own destination is the frame's.
const inner = step => step.frame ? {...step, origin: step.frame.origin, path: step.frame.path} : step;

// The frame's document cannot see the top page, so the top page must show the frame at every control.
async function uncovered(page, frame, step) {
  const element = await frame.frameElement();
  const selectors = [...step.fields.map(field => field.selector), step.submit];
  const boxes = await Promise.all(selectors.map(async selector => (await frame.$(selector))?.boundingBox()));
  if (boxes.some(box => !box)) return 'FIELD_UNAVAILABLE';
  const points = boxes.map(box => ({x: box.x + box.width / 2, y: box.y + box.height / 2}));
  const hidden = await page.mainFrame().evaluate(([element, points]) =>
    element.checkVisibility({visibilityProperty: true, opacityProperty: true})
      ? points.findIndex(({x, y}) => {
        let hit = document.elementFromPoint(x, y);
        while (hit?.shadowRoot) { const next = hit.shadowRoot.elementFromPoint(x, y); if (!next || next === hit) break; hit = next; }
        return hit !== element;
      }) : 0, [element, points]);
  return hidden < 0 ? 'READY' : hidden < step.fields.length ? 'FIELD_UNAVAILABLE' : 'SUBMIT_UNAVAILABLE';
}

async function inspect(page, step, metadata) {
  if (step.frame && !onDestination(page, step)) return {outcome: 'WRONG_DESTINATION'};
  const context = target(page, step);
  if (!context) return {outcome: 'FRAME_UNAVAILABLE'};
  const document = await context.evaluateHandle(() => document);
  const outcome = await call(document, metadata);
  return {outcome: outcome === 'READY' && step.frame ? await uncovered(page, context, step) : outcome, document};
}

// The page's own navigation replaces the read context, so a failed check means not yet ready.
async function ready(page, step, wait) {
  const metadata = {...inner(step), mode: 'check', fields: step.fields.map(({value, ...field}) => field)};
  const deadline = Date.now() + wait;
  for (;;) {
    const {outcome, document} = await inspect(page, step, metadata).catch(() => ({outcome: 'PAGE_OPERATION_FAILED'}));
    if (outcome === 'READY' || Date.now() >= deadline) return {outcome, document};
    await sleep(POLL);
  }
}

function refused(index, reason) {
  const entered = index > 0;
  return {result: 'BROWSER_BLOCKED', phase: 'preflight', step: index, reason,
    credential_input: entered, submission_attempted: entered};
}

async function submit(page, document, step) {
  const own = inner(step);
  try {
    const filled = await call(document, {...own, mode: 'fill'});
    if (filled !== 'FIELDS_VERIFIED') throw new Error(filled);
    const deadline = Date.now() + SUBMIT_WAIT;
    for (;;) {
      // The top page could have moved or covered the frame while the fields were filled.
      if (step.frame) {
        const frame = onDestination(page, step) && target(page, step);
        if (!frame || await uncovered(page, frame, step) !== 'READY') throw new Error('FRAME_CHANGED');
      }
      // Every attempt repeats all checks, and nothing is clicked until they pass.
      const submitted = await call(document, {...own, mode: 'submit'});
      if (submitted === 'SUBMITTED') break;
      if (submitted !== 'SUBMIT_UNAVAILABLE' || Date.now() >= deadline) throw new Error(submitted);
      await sleep(POLL);
    }
    await sleep(CLEAR_DELAY);
  } finally { await clear(document, {...own, fields: own.fields.filter(field => !kept(field))}); }
}

async function operate(pages, request) {
  if (request.action === 'filled') {
    // Navigation is HTTPS only, so a blank tab is what the page tool opens after it lost the real one.
    const live = pages.filter(page => page.url() && page.url() !== 'about:blank');
    if (!live.length) return {result: 'PAGE_LOST'};
    const step = {mode: 'filled', selectors: request.selectors};
    // A snapshot includes embedded frames, and a frame in navigation has no read context for a moment.
    const check = async frame => call(await frame.evaluateHandle(() => document), step);
    const read = frame => check(frame).catch(() => sleep(POLL).then(() => check(frame)));
    const seen = await Promise.all(pages.flatMap(page => page.frames()).map(read));
    const {origin, pathname} = new URL(live[0].url());
    return {result: seen.includes('FILLED') ? 'FILLED' : 'EMPTY', pages: live.length, address: (origin + pathname).slice(0, ADDRESS_LIMIT)};
  }
  const page = pages.find(candidate => onDestination(candidate, request.steps[0]));
  if (!page) return refused(0, 'WRONG_DESTINATION');
  if (request.action === 'check') {
    const {outcome} = await ready(page, request.steps[0], 0);
    return outcome === 'READY' ? {result: 'BROWSER_FILL_READY'} : refused(0, outcome);
  }
  try {
    for (const [index, step] of request.steps.entries()) {
      const {outcome, document} = await ready(page, step, index ? STEP_WAIT : 0);
      if (outcome !== 'READY') {
        if (!CODES.includes(outcome)) throw new Error('PAGE_OPERATION_FAILED');
        return refused(index, outcome);
      }
      const held = [document, inner(step)];
      retained.push(held);
      try { await submit(page, document, step); }
      catch (error) {
        const code = CODES.includes(error?.message) ? error.message : 'PAGE_OPERATION_FAILED';
        return {result: 'BROWSER_BLOCKED', phase: 'input', step: index, reason: `${code}: do not retry submission`};
      } finally { held[1] = {...held[1], fields: held[1].fields.filter(kept)}; }
    }
    return {result: 'BROWSER_LOGIN_SUBMITTED'};
  } finally { for (const [document, step] of retained.splice(0)) await clear(document, step); }
}

// A credential the page still shows would reach the next snapshot, so it is removed on every path.
async function clear(document, step) {
  if (!step.fields.length) return;
  try { await call(document, {...step, mode: 'clear'}); }
  catch { /* A replaced document no longer holds the step's fields. */ }
}

// Chrome's own ID of a page and of the page that opened it, the same in every connection.
async function identity(page) {
  const session = await page.context().newCDPSession(page);
  try { return (await session.send('Target.getTargetInfo')).targetInfo; }
  finally { await session.detach().catch(() => {}); }
}

// Other sessions share this Chrome. Their pages are never read or filled, only this session's tab
// and the popups whose opener chain leads to it.
async function owned(pages, own) {
  const infos = await Promise.all(pages.map(page => identity(page).catch(() => null)));
  const opener = new Map(infos.filter(Boolean).map(info => [info.targetId, info.openerId]));
  const mine = id => {
    for (const seen = new Set(); id && !seen.has(id); id = opener.get(id)) {
      if (id === own) return true;
      seen.add(id);
    }
    return false;
  };
  return infos.map(info => typeof own === 'string' && !!info && mine(info.targetId)
    ? (info.targetId === own ? 'main' : 'popup') : null);
}

// Indexes are the page tool's tab numbers, which follow the same page order.
async function route(pages, request) {
  const index = request.index;
  if (request.action === 'own') {
    if (!Number.isInteger(index) || !pages[index]) throw new Error('PAGE_OPERATION_FAILED');
    return {target: (await identity(pages[index])).targetId};
  }
  const roles = await owned(pages, request.own);
  if (request.action === 'close') {
    // One popup by index, or at close the whole session, popups first.
    const chosen = index === undefined ? roles.map((role, i) => role && i).filter(i => i !== null)
      : [index];
    if (index !== undefined && roles[index] !== 'popup') throw new Error('PAGE_OPERATION_FAILED');
    chosen.sort((a, b) => (roles[a] === 'main') - (roles[b] === 'main'));
    for (const i of chosen) await pages[i].close();
    return {result: 'CLOSED'};
  }
  const main = roles.indexOf('main');
  if (main < 0) return ['check', 'fill'].includes(request.action) ? refused(0, 'PAGE_LOST') : {result: 'PAGE_LOST'};
  if (request.current !== null && request.current !== undefined && !roles[request.current])
    return {result: 'FOREIGN'};
  const own = [pages[main], ...pages.filter((_, i) => roles[i] === 'popup')];
  const result = await operate(own, request);
  if (request.action !== 'filled' || result.result === 'PAGE_LOST') return result;
  return {...result, main, owned: roles.map((role, i) => role && i).filter(i => i !== null)};
}

async function main() {
  const timer = setTimeout(async () => {
    console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_TIMEOUT: do not retry submission"}');
    await Promise.race([Promise.all(retained.map(([document, step]) => clear(document, step))), sleep(CLEAR_WAIT)]);
    process.exit(1);
  }, DEADLINE);
  try {
    const raw = fs.readFileSync(0, 'utf8');
    if (raw.length > LIMIT) throw new Error('REQUEST_REFUSED');
    const request = JSON.parse(raw);
    const {chromium} = require(request.library);
    const browser = await chromium.connect(request.socket);
    const result = await route(browser.contexts().flatMap(context => context.pages()), request);
    const output = JSON.stringify(result);
    if (output.length > LIMIT) throw new Error('RESPONSE_TOO_LARGE');
    console.log(output);
  } catch {
    console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_OPERATION_FAILED: do not retry submission"}');
    process.exitCode = 1;
  } finally { clearTimeout(timer); }
  // Exiting ends this connection and leaves the page tool session and the profile's Chrome open.
  process.exit();
}
if (require.main === module) main();
module.exports = {pageStep, operate, route};
