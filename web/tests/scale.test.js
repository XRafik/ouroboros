import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../scale.js', import.meta.url), 'utf8');
function boot(saved = null) {
    const handlers = new Map();
    const control = { value: '', matches: () => true };
    const document = {
        documentElement: { dataset: {} },
        querySelectorAll: (selector) => selector === '[data-ui-scale]' ? [control] : [],
        addEventListener: (name, handler) => handlers.set(name, handler),
        removeEventListener: (name) => handlers.delete(name),
    };
    const window = {
        addEventListener: (name, handler) => handlers.set(name, handler),
        removeEventListener: (name) => handlers.delete(name),
        dispatchEvent() {},
    };
    const localStorage = { getItem: () => saved, setItem: (key, value) => { saved = value; }, removeItem: () => { saved = null; } };
    vm.runInNewContext(source, { document, window, localStorage, Event: class {} });
    return { document, window, control, handlers, saved: () => saved };
}
test('scale preserves default, restores choice and ignores corrupt storage', () => {
    assert.equal(boot().control.value, 'system');
    assert.equal(boot('70').document.documentElement.dataset.uiScale, '70');
    assert.equal(boot('0').control.value, 'system');
});
test('scale applies, persists, resets and mounts newly rendered controls', () => {
    const state = boot();
    state.control.value = '70';
    state.handlers.get('change')({ target: state.control });
    assert.equal(state.saved(), '70');
    state.control.value = '';
    state.window.ouroScale.mount();
    assert.equal(state.control.value, '70');
    state.control.value = '100';
    state.handlers.get('change')({ target: state.control });
    assert.equal(state.document.documentElement.dataset.uiScale, '100');
});
test('scale releases listeners on final pagehide, not bfcache', () => {
    const state = boot();
    state.handlers.get('pagehide')({ persisted: true });
    assert.equal(state.handlers.size, 4);
    state.handlers.get('pagehide')({ persisted: false });
    assert.equal(state.handlers.size, 0);
});
test('buttons shrink immediately and System removes the stored override', () => {
    const state = boot();
    const press = (step) => state.handlers.get('click')({ target: { closest: () => ({ dataset: { uiScaleStep: step } }) } });
    press('-1');
    assert.equal(state.saved(), '90');
    press('-1');
    press('-1');
    assert.equal(state.document.documentElement.dataset.uiScale, '70');
    press('reset');
    assert.equal(state.saved(), null);
    assert.equal(state.document.documentElement.dataset.uiScale, 'system');
});
