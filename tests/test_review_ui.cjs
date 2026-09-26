const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('weekly review protects unsaved edits and submits all reflection fields', async () => {
  const root = path.join(__dirname, '..');
  const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
  const nodes = new Map([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], {
    value: '', textContent: '', innerHTML: '', hidden: false, disabled: false,
    scrollLeft: 0, scrollWidth: 100, listeners: {}, classList: {add() {}, remove() {}},
    addEventListener(type, handler) { this.listeners[type] = handler; },
    scrollIntoView() {},
  }]));
  nodes.get('reviewForm').elements = Object.fromEntries(['learning', 'blocker', 'follow_up', 'next_step'].map((name) => [name, {value: ''}]));
  const fields = nodes.get('reviewForm').elements;
  let allowDiscard = false;
  let saved = null;
  const context = vm.createContext({
    console, Date, Intl, URLSearchParams, clearTimeout() {}, setTimeout() { return 1; },
    confirm() { return allowDiscard; },
    window: {addEventListener() {}},
    document: {
      querySelector(selector) { const node = nodes.get(selector.slice(1)); assert.ok(node, `Unknown element ${selector}`); return node; },
      querySelectorAll() { return []; },
    },
    async fetch(url, options) {
      const parsed = new URL(url, 'http://localhost');
      let data;
      if (parsed.pathname === '/api/overview') {
        data = {first_used_on: '2026-09-14', stats: {total_records: 0, active_days: 0, total_minutes: 0}, activity: {}, milestones: [], categories: []};
      } else if (parsed.pathname === '/api/records') {
        data = [];
      } else if (parsed.pathname === '/api/review' && options.method === 'PUT') {
        saved = JSON.parse(options.body); data = {saved: true};
      } else if (parsed.pathname === '/api/review') {
        data = {week_start: parsed.searchParams.get('week_start'), week_end: '2026-09-26', categories: [], highlights: [], total_records: 0, active_days: 0, total_minutes: 0, learning: '', blocker: '', follow_up: '', next_step: '', previous_next_step: 'Finish two exercises'};
      } else { throw new Error(`Unexpected request ${url}`); }
      return {ok: true, status: 200, async json() { return data; }};
    },
  });
  vm.runInContext(fs.readFileSync(path.join(root, 'static/app.js'), 'utf8'), context);
  await new Promise(setImmediate);
  const state = vm.runInContext('state', context);
  const week = state.reviewWeek;
  assert.equal(nodes.get('reviewPreviousText').textContent, 'Finish two exercises');
  fields.blocker.value = 'Need to verify the boundary';
  fields.follow_up.value = 'Finished one exercise';
  nodes.get('reviewForm').listeners.input();
  assert.equal(state.reviewDirty, true);
  assert.match(nodes.get('reviewStatus').textContent, /未保存/);
  await vm.runInContext('refresh()', context);
  assert.equal(fields.blocker.value, 'Need to verify the boundary');
  await nodes.get('reviewPrev').listeners.click();
  assert.equal(state.reviewWeek, week);
  assert.equal(state.reviewDirty, true);
  await nodes.get('reviewForm').listeners.submit({preventDefault() {}});
  assert.equal(saved.blocker, 'Need to verify the boundary');
  assert.equal(saved.follow_up, 'Finished one exercise');
  assert.equal(state.reviewDirty, false);
  fields.learning.value = 'Another draft';
  nodes.get('reviewForm').listeners.input();
  allowDiscard = true;
  await nodes.get('reviewPrev').listeners.click();
  assert.notEqual(state.reviewWeek, week);
  assert.equal(state.reviewDirty, false);
  assert.equal(fields.learning.value, '');
});
