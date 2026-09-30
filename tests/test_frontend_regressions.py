"""Frontend-only regression checks against the canonical live inline planner script."""

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def run_node(script):
    if not shutil.which("node"):
        pytest.skip("Node.js is required for frontend JavaScript checks")
    result = subprocess.run(
        ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout


# Each test loads the actual HTML, not a copy of its JavaScript.
BOOTSTRAP = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('frontend/index.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const source = scripts.at(-1);
function functionBody(name) {
  const declaration = `async function ${name}(`;
  const plain = `function ${name}(`;
  const start = source.indexOf(declaration) !== -1 ? source.indexOf(declaration) : source.indexOf(plain);
  assert(start !== -1, `Missing function ${name}`);
  const end = source.indexOf('\n}', start);
  assert(end !== -1, `Unclosed function ${name}`);
  return source.slice(start, end + 2);
}
"""


def test_scripts_parse_and_live_wiring():
    run_node(BOOTSTRAP + r"""
scripts.forEach((script, i) => new vm.Script(script, { filename: `index-${i}.js` }));
new vm.Script(fs.readFileSync('frontend/app.js', 'utf8'), { filename: 'app.js' });
const landing = fs.readFileSync('frontend/landing.html', 'utf8');
[...landing.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .forEach((match, i) => new vm.Script(match[1], { filename: `landing-${i}.js` }));
assert(html.includes('id="ai-start-date"') && html.includes('id="ai-start-time"'));
assert(!html.includes('id="ai-start-display"'));
assert(source.includes("window.API_BASE_URL + '/api/google/oauth/login'"));
assert(source.includes('window.LOGIN_URL'));
assert(html.includes('id="memory-panel" hidden'));
assert(html.includes('id="memory-form"'));
assert(!html.includes('<script src="app.js"'));
assert(source.includes('result.warning') && source.includes('result.success'));
""")


def test_auth_host_and_relative_routes():
    run_node(BOOTSTRAP + r"""
const landing = fs.readFileSync('frontend/landing.html', 'utf8');
const landingConfig = [...landing.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
for (const [hostname, port, origin, api, login, planner] of [
  ['localhost', '8000', 'http://localhost:8000', 'http://localhost:8000', '/home', '/'],
  ['127.0.0.1', '5500', 'http://127.0.0.1:5500', 'http://127.0.0.1:8000', 'landing.html', 'index.html'],
  ['schedule.netlify.app', '', 'https://schedule.netlify.app', 'https://predestination.onrender.com', 'landing.html', 'index.html'],
  ['predestination.onrender.com', '', 'https://predestination.onrender.com', 'https://predestination.onrender.com', '/home', '/'],
]) {
  const location = { hostname, port, origin, protocol: origin.split(':')[0] + ':' };
  const indexCtx = { window: { location } };
  const landingCtx = { window: { location } };
  vm.runInNewContext(scripts[0], indexCtx);
  vm.runInNewContext(landingConfig, landingCtx);
  assert.equal(indexCtx.window.API_BASE_URL, api);
  assert.equal(landingCtx.window.API_BASE_URL, api);
  assert.equal(indexCtx.window.LOGIN_URL, login);
  assert.equal(landingCtx.window.PLANNER_URL, planner);
}
""")


def test_default_plan_start_is_next_half_hour_and_editable():
    run_node(BOOTSTRAP + r"""
const fixed = new Date(2026, 8, 30, 10, 15).getTime();
const inputs = { 'ai-start-date': { value: '' }, 'ai-start-time': { value: '' } };
const ctx = {
  Date: class extends Date { static now() { return fixed; } },
  document: { getElementById: id => inputs[id] },
  dateStr: date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`,
  dateTimeLocalStr: date => `${ctx.dateStr(date)}T${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`,
  pad: n => String(n).padStart(2, '0'),
};
vm.createContext(ctx);
vm.runInContext(functionBody('defaultAiStart') + '\n' + functionBody('getAiStartAfter'), ctx);
ctx.defaultAiStart();
assert.equal(inputs['ai-start-date'].value, '2026-09-30');
assert.equal(inputs['ai-start-time'].value, '10:30');
inputs['ai-start-time'].value = '11:00';
assert.equal(ctx.getAiStartAfter(), '2026-09-30T11:00');
""")


def test_chat_is_not_blocked_by_old_start_and_never_double_sends():
    run_node(BOOTSTRAP + r"""
let sent = [];
let resolveRequest;
const node = () => ({ textContent: '', innerText: '', children: [], appendChild(child) { this.children.push(child); }, remove() { this.removed = true; } });
const input = { value: 'hello', disabled: false };
const btn = { disabled: false, textContent: 'Send' };
const chat = node();
const ctx = {
  aiPrompt: input, aiSendBtn: btn, aiMessages: chat, aiRequestInFlight: false, sessionHistoryLoading: false,
  getAiStartAfter: () => '2000-01-01T08:00', dateTimeLocalStr: () => '2026-09-30T09:00',
  slackSlider: { value: '0.1' }, currentSessionId: null,
  document: { createElement: node },
  window: { API_BASE_URL: '', LOGIN_URL: '/home' },
  fetch: (url, options) => { sent.push({ url, options }); return new Promise(resolve => { resolveRequest = resolve; }); },
  readApiError: async () => 'Server rejected the request',
};
vm.createContext(ctx);
vm.runInContext(functionBody('sendAiMessage'), ctx);
(async () => {
  const first = ctx.sendAiMessage();
  await ctx.sendAiMessage();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, '/api/agent/chat');
  assert.equal(JSON.parse(sent[0].options.body).start_after, null);
  assert.equal(btn.disabled, true);
  resolveRequest({ ok: false, status: 400 });
  await first;
  assert.equal(btn.disabled, false);
  assert.equal(input.disabled, false);
  assert.match(chat.children.at(-1).textContent, /Server rejected the request/);
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_history_loads_messages_and_ignores_old_response():
    run_node(BOOTSTRAP + r"""
let replies = [];
const nodes = [];
const chat = { children: [], replaceChildren(...items) { this.children = items; }, appendChild(el) { this.children.push(el); }, scrollHeight: 5, scrollTop: 0 };
const ctx = {
  aiRequestInFlight: false, sessionHistoryLoading: false, aiSendBtn: { disabled: false },
  currentSessionId: null, sessionViewId: 0, aiMessages: chat,
  updateSessionLabel: () => {}, closeSessionsDrawer: () => {}, loadSessions: () => {},
  document: { querySelectorAll: () => [], createElement: () => {
    const el = { className: '', textContent: '' }; nodes.push(el); return el;
  } },
  window: { API_BASE_URL: '', LOGIN_URL: '/home' },
  fetch: url => { assert.match(url, /\/api\/agent\/sessions\/.*\/messages/); return new Promise(resolve => replies.push(resolve)); },
  readApiError: async () => 'Forbidden',
};
vm.createContext(ctx);
vm.runInContext(functionBody('resumeSession'), ctx);
(async () => {
  const old = ctx.resumeSession('old', 'Old');
  const recent = ctx.resumeSession('new', 'New');
  replies[1]({ ok: true, status: 200, json: async () => [
    { role: 'user', content: '<my prompt>' }, { role: 'assistant', content: 'Reply' }
  ] });
  await recent;
  assert.equal(chat.children[0].className, 'user-msg');
  assert.equal(chat.children[0].textContent, '<my prompt>');
  assert.equal(chat.children[1].textContent, 'Reply');
  replies[0]({ ok: true, status: 200 });
  await old;
  assert.equal(chat.children.length, 2);
  assert.equal(ctx.currentSessionId, 'new');
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_slots_ignore_out_of_order_responses():
    run_node(BOOTSTRAP + r"""
let replies = [];
const rendered = [];
const ctx = {
  slotsRequestId: 0, freeSearchId: 0, freeResults: null, currentDate: 'A', allSlots: [],
  dateStr: value => value, renderBlocks: () => rendered.push(ctx.allSlots[0]),
  renderSidebar: () => {}, navigateToStep: () => {}, detectCurrentStep: () => 'busy',
  executePendingHighlight: () => {}, showToast: () => { throw Error('Unexpected toast'); },
  window: { API_BASE_URL: '', LOGIN_URL: '/home' },
  fetch: url => new Promise(resolve => replies.push({ url, resolve })),
};
vm.createContext(ctx);
vm.runInContext(functionBody('fetchSlots'), ctx);
(async () => {
  const old = ctx.fetchSlots();
  ctx.currentDate = 'B';
  const recent = ctx.fetchSlots();
  replies[1].resolve({ ok: true, status: 200, json: async () => ['B'] });
  await recent;
  replies[0].resolve({ ok: true, status: 200, json: async () => ['A'] });
  await old;
  assert.equal(ctx.allSlots[0], 'B');
  assert.deepEqual(rendered, ['B']);
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_preset_cancel_and_recurring_delete_abort_without_requests():
    run_node(BOOTSTRAP + r"""
let apply;
const start = source.indexOf("presetApplyBtn.addEventListener('click', async ()=>{");
const end = source.indexOf('\n});', start);
assert(start !== -1 && end !== -1);
const ctx = {
  presetApplyBtn: { addEventListener: (event, callback) => { apply = callback; } },
  presetSelect: { value: 'student' }, presets: [{ id: 'student', name: 'Student' }],
  allSlots: [{ id: 7, repeatDays: [0, 1] }],
  window: { confirm: () => false },
  fetch: () => { throw Error('Cancel must not call fetch'); },
  showToast: () => { throw Error('Unexpected toast'); },
};
vm.createContext(ctx);
vm.runInContext(source.slice(start, end + 4) + '\n' + functionBody('deleteSlot'), ctx);
(async () => {
  await apply();
  assert.equal(await ctx.deleteSlot(7), false);
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_memory_controls_are_inside_collapsible_panel():
    live = (FRONTEND / "index.html").read_text(encoding="utf-8")
    opening = live.index('<div id="memory-panel" hidden>')
    closing = live.index("</div>", opening)
    panel = live[opening:closing]
    assert 'id="memory-list"' in panel
    assert 'id="memory-form"' in panel
    assert 'id="memory-status"' in panel


def test_memory_panel_opens_and_form_submits_without_alpine():
    run_node(BOOTSTRAP + r"""
const first = source.indexOf("memoryToggle.addEventListener('click', () => {");
const last = source.indexOf("\nfunction buildGrid()", first);
assert(first !== -1 && last !== -1);
const handlers = {};
const toggle = { setAttribute(name, value) { this[name] = value; },
  addEventListener(name, callback) { handlers[name] = callback; } };
const form = { addEventListener(name, callback) { handlers.submit = callback; } };
const panel = { hidden: true };
let loaded = 0, added = 0, prevented = 0;
const ctx = {
  memoryToggle: toggle, memoryPanel: panel, memoryLoadId: 0,
  loadMemoryPreferences: () => { loaded++; },
  addMemoryPreference: () => { added++; },
  document: { getElementById: id => { assert.equal(id, 'memory-form'); return form; } }
};
vm.createContext(ctx);
vm.runInContext(source.slice(first, last), ctx);
handlers.click();
assert.equal(panel.hidden, false);
assert.equal(toggle['aria-expanded'], 'true');
assert.equal(loaded, 1);
handlers.submit({ preventDefault: () => { prevented++; } });
assert.equal(prevented, 1);
assert.equal(added, 1);
handlers.click();
assert.equal(panel.hidden, true);
assert.equal(toggle['aria-expanded'], 'false');
assert.equal(ctx.memoryLoadId, 1);
""")


def test_memory_renders_preferences_as_text_not_html():
    run_node(BOOTSTRAP + r"""
const makeNode = tag => ({ tag, children: [], className: '', textContent: '',
  append(...children) { this.children.push(...children); },
  appendChild(child) { this.children.push(child); },
  replaceChildren(...children) { this.children = children; },
  addEventListener(event, callback) { this.handler = callback; },
  setAttribute(name, value) { this[name] = value; },
  set innerHTML(value) { throw Error('Untrusted HTML insertion: ' + value); },
});
const list = makeNode('ul');
const removed = [];
const ctx = { memoryList: list, document: { createElement: makeNode }, removeMemoryPreference: id => removed.push(id) };
vm.createContext(ctx);
vm.runInContext(functionBody('renderMemoryPreferences'), ctx);
const unsafe = '<img src=x onerror=alert(1)>';
ctx.renderMemoryPreferences([
  { id: 1, type: 'fact', content: 'private session fact' },
  { id: 7, type: 'pref', content: unsafe },
]);
assert.equal(list.children.length, 1);
assert.equal(list.children[0].children[0].textContent, unsafe);
assert.equal(list.children[0].children[1].tag, 'button');
list.children[0].children[1].handler();
assert.deepEqual(removed, [7]);
ctx.renderMemoryPreferences([{ id: 8, type: 'fact', content: 'hidden' }]);
assert.match(list.children[0].textContent, /No preferences/);
""")


def test_memory_add_delete_and_load_use_authenticated_pref_api():
    run_node(BOOTSTRAP + r"""
const calls = [];
let reloaded = 0;
const status = { textContent: '', classList: { toggle: () => {} } };
const input = { value: '  Prefer mornings  ' };
const ctx = {
  memoryInput: input, memoryStatus: status, memoryActionInFlight: false,
  memoryLoadId: 0, memoryAddBtn: { disabled: false },
  memoryList: { querySelectorAll: () => [] },
  memoryMessage: (message, error) => { status.textContent = message; status.error = error; },
  loadMemoryPreferences: async () => { reloaded++; },
  showToast: () => {},
  readApiError: async () => 'Permission denied',
  window: { API_BASE_URL: 'https://example.test', LOGIN_URL: '/home', confirm: () => false },
  fetch: async (url, options) => { calls.push({ url, options }); return { ok: true, status: 200 }; },
};
vm.createContext(ctx);
vm.runInContext(functionBody('setMemoryBusy') + '\n' + functionBody('addMemoryPreference') + '\n' + functionBody('removeMemoryPreference'), ctx);
(async () => {
  await ctx.addMemoryPreference();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://example.test/api/memory');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.credentials, 'include');
  assert.deepEqual(JSON.parse(calls[0].options.body), { type: 'pref', content: 'Prefer mornings' });
  assert.equal(input.value, '');
  assert.equal(reloaded, 1);
  await ctx.removeMemoryPreference(7);  // cancelled
  assert.equal(calls.length, 1);
  ctx.window.confirm = () => true;
  await ctx.removeMemoryPreference(7);
  assert.equal(calls[1].url, 'https://example.test/api/memory/7');
  assert.equal(calls[1].options.method, 'DELETE');
  assert.equal(calls[1].options.credentials, 'include');
  assert.equal(reloaded, 2);
  ctx.fetch = async () => ({ ok: false, status: 403 });
  input.value = 'retry me';
  await ctx.addMemoryPreference();
  assert.equal(input.value, 'retry me');
  assert.equal(status.error, true);
  assert.match(status.textContent, /Permission denied/);
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_memory_load_filters_fact_and_ignores_stale_responses():
    run_node(BOOTSTRAP + r"""
const replies = [];
const shown = [];
const status = [];
const ctx = {
  memoryLoadId: 0, memoryMessage: (message, error) => status.push([message, error]),
  renderMemoryPreferences: items => shown.push(items),
  window: { API_BASE_URL: '', LOGIN_URL: '/home' },
  fetch: (url, options) => { assert.equal(url, '/api/memory'); assert.equal(options.credentials, 'include');
    return new Promise(resolve => replies.push(resolve)); },
  readApiError: async () => 'Access denied',
};
vm.createContext(ctx);
vm.runInContext(functionBody('loadMemoryPreferences'), ctx);
(async () => {
  const first = ctx.loadMemoryPreferences();
  const second = ctx.loadMemoryPreferences();
  replies[1]({ ok: true, status: 200, json: async () => [{ id: 2, type: 'pref', content: 'new' }] });
  await second;
  replies[0]({ ok: true, status: 200 });
  await first;
  assert.equal(shown.length, 1);
  assert.equal(shown[0][0].content, 'new');
  ctx.fetch = async () => ({ ok: false, status: 403 });
  await ctx.loadMemoryPreferences();
  assert.deepEqual(status.at(-1), ['Access denied', true]);
})().catch(err => { console.error(err); process.exitCode = 1; });
""")


def test_cancellation_and_one_time_template_date():
    live = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert "if(!window.confirm(`Apply" in live
    assert "body: JSON.stringify({clear_existing: true})" in live
    assert live.count("date: repeatDays.length ? null : dateStr(currentDate)") >= 2
    assert "date: selectedDays.length ? null : dateStr(currentDate)" in live
    assert "Delete this recurring block on every matching day?" in live
    assert "including blocks on other days" in live
