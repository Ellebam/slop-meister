'use strict';
const fs = require('node:fs');
const LIMIT = 262144;
const DEADLINE = 55000;
const CLEAR_DELAY = 2000;
// How long a later step waits for its page after the previous step was submitted.
const STEP_WAIT = 15000;
const POLL = 250;
// A page chooses its address, and the owner-only state that keeps it has a size limit.
const ADDRESS_LIMIT = 1024;

// This function runs in the inspected page. It never focuses or types into a control.
function pageStep(_document, step) {
  try {
    const roots = [document];
    for (let i = 0; i < roots.length; i++)
      for (const e of roots[i].querySelectorAll('*')) if (e.shadowRoot) roots.push(e.shadowRoot);
    const find = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
    const visible = e => e.checkVisibility({visibilityProperty: true, opacityProperty: true});
    if (step.mode === 'filled') return step.selectors.some(s => find(s).some(e => e.value)) ? 'FILLED' : 'EMPTY';
    if (location.origin !== step.origin || location.pathname !== step.path) return 'WRONG_DESTINATION';
    const exposed = e => {
      const r = e.getBoundingClientRect(), x = r.x + r.width / 2, y = r.y + r.height / 2;
      let hit = document.elementFromPoint(x, y);
      while (hit?.shadowRoot) { const next = hit.shadowRoot.elementFromPoint(x, y); if (!next || next === hit) break; hit = next; }
      return !!hit && (hit === e || e.contains(hit) || hit.closest?.('label')?.control === e);
    };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    if (step.mode === 'clear') {
      // Events let a framework drop its copy too, so a later render cannot restore the value.
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

// The page's own navigation replaces the read context, so a failed check means not yet ready.
async function ready(page, step, wait) {
  const metadata = {...step, mode: 'check', fields: step.fields.map(({value, ...field}) => field)};
  const deadline = Date.now() + wait;
  for (;;) {
    const document = await page.evaluateHandle(() => document).catch(() => null);
    const outcome = document ? await call(document, metadata).catch(() => 'PAGE_OPERATION_FAILED') : 'PAGE_OPERATION_FAILED';
    if (outcome === 'READY' || Date.now() >= deadline) return {outcome, document};
    await sleep(POLL);
  }
}

function refused(index, reason) {
  const entered = index > 0;
  return {result: 'BROWSER_BLOCKED', phase: 'preflight', step: index, reason,
    credential_input: entered, submission_attempted: entered};
}

async function submit(document, step) {
  try {
    const filled = await call(document, {...step, mode: 'fill'});
    if (filled !== 'FIELDS_VERIFIED') throw new Error(filled);
    const submitted = await call(document, {...step, mode: 'submit'});
    if (submitted !== 'SUBMITTED') throw new Error(submitted);
    await sleep(CLEAR_DELAY);
  } finally { await clear(document, step); }
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
  for (const [index, step] of request.steps.entries()) {
    const {outcome, document} = await ready(page, step, index ? STEP_WAIT : 0);
    if (outcome !== 'READY') {
      const known = ['WRONG_DESTINATION', 'FIELD_UNAVAILABLE', 'SUBMIT_UNAVAILABLE', 'PAGE_OPERATION_FAILED'];
      if (!known.includes(outcome)) throw new Error('PAGE_OPERATION_FAILED');
      return refused(index, outcome);
    }
    await submit(document, step);
  }
  return {result: 'BROWSER_LOGIN_SUBMITTED'};
}

// A credential the page still shows would reach the next snapshot, so it is removed on every path.
async function clear(document, step) {
  try { await call(document, {...step, mode: 'clear'}); }
  catch { /* A replaced document no longer holds the step's fields. */ }
}

async function main() {
  const timer = setTimeout(() => { console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_TIMEOUT: do not retry submission"}'); process.exit(1); }, DEADLINE);
  try {
    const raw = fs.readFileSync(0, 'utf8');
    if (raw.length > LIMIT) throw new Error('REQUEST_REFUSED');
    const request = JSON.parse(raw);
    const {chromium} = require(request.library);
    const browser = await chromium.connect(request.socket);
    const result = await operate(browser.contexts().flatMap(context => context.pages()), request);
    const output = JSON.stringify(result);
    if (output.length > LIMIT) throw new Error('RESPONSE_TOO_LARGE');
    console.log(output);
  } catch {
    console.log('{"result":"BROWSER_BLOCKED","reason":"BROWSER_OPERATION_FAILED: do not retry submission"}');
    process.exitCode = 1;
  } finally { clearTimeout(timer); }
  // Exiting ends this connection and leaves the session and the operator's browser open.
  process.exit();
}
if (require.main === module) main();
module.exports = {pageStep, operate};
