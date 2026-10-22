import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

import { DESK, createInterfaceSize, mountInterfaceSize, sizeNote, stepped, zoomKey } from '../modules/interface_size.js';

const tick = () => new Promise((done) => setTimeout(done, 0));

function fakeWindow({ bridge = null, viewport = null, top = true, telegram = false, mac = true } = {}) {
    const listeners = new Map();
    const win = {
        navigator: { platform: mac ? 'MacIntel' : 'Win32', userAgent: '' },
        performance: { timeOrigin: 1000 },
        addEventListener(type, fn) { listeners.set(type, fn); },
        removeEventListener(type) { listeners.delete(type); },
        fire(type) { listeners.get(type)?.(); },
        ouroViewportScale: viewport,
        Telegram: telegram ? { WebApp: { initData: 'x' } } : undefined,
    };
    win.top = top ? win : {};
    if (bridge) win.pywebview = { api: bridge };
    return win;
}

function fakeDocument() {
    const listeners = new Map();
    return {
        documentElement: { dataset: {} },
        addEventListener(type, fn) { listeners.set(type, fn); },
        removeEventListener(type) { listeners.delete(type); },
        key(event) { listeners.get('keydown')?.(event); },
    };
}

function desktopBridge({ supported = true, percent = 100 } = {}) {
    const calls = [];
    return {
        calls,
        shell_info: async () => ({ interface_size: { supported, min: 50, max: 200, step: 5, percent } }),
        set_interface_size: async (value, page, sequence) => {
            calls.push({ value, page, sequence });
            return { ok: true, percent: value };
        },
    };
}

test('a zoom key is the physical key with the platform modifier, never with Alt', () => {
    assert.equal(zoomKey({ metaKey: true, code: 'Equal' }, { mac: true }), 'in');
    assert.equal(zoomKey({ metaKey: true, code: 'NumpadSubtract' }, { mac: true }), 'out');
    assert.equal(zoomKey({ metaKey: true, code: 'Digit0' }, { mac: true }), 'reset');
    assert.equal(zoomKey({ ctrlKey: true, code: 'Minus' }, { mac: false }), 'out');
    assert.equal(zoomKey({ ctrlKey: true, code: 'Equal' }, { mac: true }), '', 'Ctrl on a Mac is not the zoom key');
    assert.equal(zoomKey({ metaKey: true, altKey: true, code: 'Equal' }, { mac: true }), '');
    assert.equal(zoomKey({ metaKey: true, code: 'KeyA' }, { mac: true }), '');
});

test('the keys step to the next whole ten inside the range', () => {
    assert.equal(stepped(100, 1), 110);
    assert.equal(stepped(105, 1), 110);
    assert.equal(stepped(105, -1), 100);
    assert.equal(stepped(100, -1), 90);
    assert.equal(stepped(DESK.max, 1), DESK.max);
    assert.equal(stepped(DESK.min, -1), DESK.min);
});

test('the desktop app is the size: its bridge answers, the slider and the keys set it there', async () => {
    const bridge = desktopBridge({ percent: 120 });
    const win = fakeWindow({ bridge });
    const doc = fakeDocument();
    const size = createInterfaceSize({ win, doc });
    await tick();
    assert.deepEqual(size.state(), { route: 'app', percent: 120, min: 50, max: 200, step: 5 });
    await size.set(133);
    assert.equal(bridge.calls.at(-1).value, 135, 'a 5 % grid');
    let prevented = false;
    doc.key({ metaKey: true, code: 'Equal', preventDefault: () => { prevented = true; } });
    await tick();
    assert.ok(prevented);
    assert.equal(bridge.calls.at(-1).value, 140);
    assert.ok(bridge.calls.at(-1).sequence > bridge.calls.at(-2).sequence, 'each call carries its order');
    doc.key({ metaKey: true, code: 'Digit0', preventDefault() {} });
    await tick();
    assert.equal(size.state().percent, 100);
    size.dispose();
});

test('a desktop app older than the bridge says it cannot change its size, and its keys stay the system\'s', async () => {
    const bridge = { shell_info: async () => ({}) };  // a launcher built before set_interface_size
    const win = fakeWindow({ bridge });
    const doc = fakeDocument();
    const size = createInterfaceSize({ win, doc });
    win.fire('pywebviewready');
    await tick();
    assert.equal(size.state().route, 'none');
    assert.equal(size.state().reason, 'app');
    let prevented = false;
    doc.key({ metaKey: true, code: 'Equal', preventDefault: () => { prevented = true; } });
    assert.equal(prevented, false);
    size.dispose();
});

test('a touch screen sets the size through the viewport; a browser keeps its own zoom; Telegram says so', async () => {
    let applied = null;
    const viewport = { state: 'active', percent: 100, min: 75, max: 120, step: 5,
        set: async (value) => { applied = value; viewport.percent = value; return 'active'; }, subscribe: () => () => {} };
    const touch = createInterfaceSize({ win: fakeWindow({ viewport }), doc: fakeDocument() });
    assert.equal(touch.state().route, 'screen');
    await touch.set(110);
    assert.equal(applied, 110);
    assert.equal(touch.state().percent, 110);

    const browser = createInterfaceSize({ win: fakeWindow({ viewport: { state: 'unavailable' } }), doc: fakeDocument() });
    assert.equal(browser.state().route, 'browser');
    assert.equal((await browser.set(150)).percent, 100, 'a page cannot set a browser\'s zoom');

    const telegram = createInterfaceSize({ win: fakeWindow({ viewport: { state: 'unavailable' }, telegram: true }), doc: fakeDocument() });
    assert.deepEqual(telegram.state(), { route: 'none', reason: 'telegram', percent: 100 });
});

test('the note names this surface\'s way and keys', () => {
    assert.match(sizeNote({ route: 'app' }, { mac: true })[1].keys, /⌘ \+/);
    assert.match(sizeNote({ route: 'browser' }, { mac: false })[1].keys, /Ctrl \+/);
    assert.deepEqual(sizeNote({ route: 'screen', min: 75, max: 120 })[1], { min: 75, max: 120 });
    assert.match(sizeNote({ route: 'none', reason: 'telegram' })[0], /Telegram/);
});

function fakeBlock() {
    const handlers = {};
    const element = (extra = {}) => ({ hidden: false, disabled: false, textContent: '', dataset: {}, ...extra,
        addEventListener(type, fn) { handlers[`${extra.name}:${type}`] = fn; }, removeEventListener() {} });
    const row = element({ name: 'row' });
    const input = element({ name: 'input', min: '', max: '', step: '', value: '' });
    const output = element({ name: 'output' });
    const reset = element({ name: 'reset' });
    const note = element({ name: 'note' });
    const map = { '[data-interface-size-row]': row, '[data-interface-size-input]': input,
        '[data-interface-size-value]': output, '[data-interface-size-reset]': reset, '[data-interface-size-note]': note };
    const block = { querySelector: (selector) => map[selector] };
    const root = { querySelector: (selector) => (selector === '[data-interface-size]' ? block : null) };
    return { root, row, input, output, reset, note, handlers };
}

test('the slider shows the value while it moves and applies it only when let go', async () => {
    const bridge = desktopBridge({ percent: 100 });
    const win = fakeWindow({ bridge });
    const size = createInterfaceSize({ win, doc: fakeDocument() });
    await tick();
    const ui = fakeBlock();
    const dispose = mountInterfaceSize(ui.root, size, { win });
    assert.equal(ui.row.hidden, false);
    assert.equal(ui.input.min, '50');
    assert.equal(ui.input.max, '200');
    assert.equal(ui.reset.disabled, true, 'nothing to reset at 100 %');
    ui.input.value = '80';
    ui.handlers['input:input']();
    assert.equal(ui.output.textContent, '80%');
    assert.equal(bridge.calls.length, 0, 'no size while the slider moves');
    ui.handlers['input:change']();
    await tick();
    assert.equal(bridge.calls.at(-1).value, 80);
    assert.equal(ui.reset.disabled, false);
    dispose();
});

test('where the page cannot set the size the slider is hidden and the note says why', () => {
    const win = fakeWindow({ viewport: { state: 'unavailable' }, telegram: true });
    const size = createInterfaceSize({ win, doc: fakeDocument() });
    const ui = fakeBlock();
    mountInterfaceSize(ui.root, size, { win });
    assert.equal(ui.row.hidden, true);
    assert.match(ui.note.textContent, /Telegram/);
});

// theme.js's touch half, run as the page runs it: before CSS, with the viewport meta it rewrites.
function bootViewport({ width = 390, stored = null, honoured = true, coarse = true } = {}) {
    let content = 'width=device-width, initial-scale=1.0, viewport-fit=cover';
    let layoutWidth = width;
    const storage = new Map(stored ? [['ouroboros.interface-size', String(stored)]] : []);
    const meta = {
        getAttribute: () => content,
        setAttribute: (_key, value) => {
            content = value;
            const asked = /width=(\d+)/.exec(value);
            layoutWidth = honoured && asked ? Number(asked[1]) : width;
        },
    };
    const props = {};
    const listeners = new Map();
    const doc = {
        querySelector: (selector) => (selector === 'meta[name="viewport"]' ? meta : null),
        querySelectorAll: () => [],
        documentElement: { get clientWidth() { return layoutWidth; }, style: { setProperty: (k, v) => { props[k] = v; } }, dataset: {} },
        addEventListener() {}, removeEventListener() {},
    };
    const win = {
        matchMedia: (query) => ({ matches: query.includes('coarse') ? coarse : false, addEventListener: () => {} }),
        addEventListener: (type, fn) => listeners.set(type, fn), removeEventListener() {},
        get innerWidth() { return layoutWidth; },
    };
    win.top = win;
    const context = {
        window: win, document: doc,
        localStorage: { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v), removeItem: (k) => storage.delete(k) },
        requestAnimationFrame: (fn) => setTimeout(fn, 0), CustomEvent: class {}, console,
    };
    vm.runInNewContext(fs.readFileSync(new URL('../theme.js', import.meta.url), 'utf8'), context);
    return { scale: win.ouroViewportScale, content: () => content, props, storage };
}

test('a phone lays the page out at another width and keeps the size the host honours', async () => {
    const phone = bootViewport({ width: 390 });
    assert.equal(phone.scale.state, 'active');
    assert.equal(phone.scale.max, 120, '390 / 320 CSS px allows up to 120 %');
    assert.equal(await phone.scale.set(125), 'active');
    assert.equal(phone.scale.percent, 120, 'clamped to the width floor');
    assert.match(phone.content(), /^width=325, initial-scale=1.2,/);
    assert.equal(phone.props['--interface-scale'], '1.2');
    assert.equal(phone.storage.get('ouroboros.interface-size'), '120');
    await phone.scale.set(80);
    assert.match(phone.content(), /^width=488, initial-scale=0.79918,/, 'the screen shows all 488 px, not 487.5 of them');
    assert.equal(phone.props['--interface-scale'], '0.79918');
    await phone.scale.set(60);
    assert.equal(phone.scale.percent, 75, 'no smaller than 75 % under a finger');
});

test('a stored size is applied before the first layout; a host that ignores the meta keeps 100 %', async () => {
    const stored = bootViewport({ width: 400, stored: 110 });
    await new Promise((done) => setTimeout(done, 20));
    assert.equal(stored.scale.percent, 110);
    assert.match(stored.content(), /^width=364, initial-scale=1.098901,/, 'the exact ratio of the two widths');

    const ignored = bootViewport({ width: 390, stored: 110, honoured: false });  // a Mini App in Telegram for Android
    await new Promise((done) => setTimeout(done, 20));
    assert.equal(ignored.scale.state, 'unavailable');
    assert.equal(ignored.scale.percent, 100);
    assert.match(ignored.content(), /^width=device-width/, 'the original meta is back');

    const desk = bootViewport({ coarse: false });
    assert.equal(desk.scale.state, 'unavailable', 'a fine pointer keeps the browser\'s own zoom');
});
