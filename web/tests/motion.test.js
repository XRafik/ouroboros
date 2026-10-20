// When has a motion ended, and may anything move (motion.js): the element's own transition of one property ends the
// wait, a child's or another property's never does; with no event the computed duration plus one frame does; with
// nothing to wait for, the next frame. The motion preference is read in one place and followed while the app runs.
import test from 'node:test';
import assert from 'node:assert/strict';

import { afterMotion, reducedMotion, onReducedMotionChange } from '../modules/motion.js';

function world(style = {}) {
    const timers = [];
    const frames = [];
    const listeners = new Map();
    const el = {
        addEventListener: (type, fn) => listeners.set(type, fn),
        removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
        fire: (type, init) => listeners.get(type)?.({ type, target: el, ...init }),
        listeners,
    };
    const win = {
        getComputedStyle: () => ({ transitionProperty: 'transform, opacity', transitionDuration: '0.28s, 180ms',
            transitionDelay: '0s, 0s', ...style }),
        setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
        clearTimeout: (id) => { if (timers[id - 1]) timers[id - 1].fn = null; },
        requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
    };
    const runTimers = () => timers.splice(0).forEach((t) => t.fn?.());
    const runFrames = () => frames.splice(0).forEach((fn) => fn());
    return { el, win, timers, frames, runTimers, runFrames };
}

const outcome = async (promise) => Promise.race([promise, new Promise((r) => setTimeout(() => r('pending'), 5))]);

test('the element\'s own transition of the property ends the wait; a child\'s or another property\'s does not', async () => {
    const w = world();
    const wait = afterMotion(w.el, { win: w.win });
    w.el.fire('transitionend', { propertyName: 'opacity' });
    w.el.fire('transitionend', { propertyName: 'transform', target: { child: true } });
    assert.equal(await outcome(wait.done), 'pending');
    w.el.fire('transitionend', { propertyName: 'transform' });
    assert.equal(await outcome(wait.done), 'end');
    assert.equal(w.el.listeners.size, 0, 'it lets go of the element');
    const cancelled = afterMotion(w.el, { win: w.win });
    w.el.fire('transitioncancel', { propertyName: 'transform' });
    assert.equal(await outcome(cancelled.done), 'cancel', 'an interrupted transition has ended too');
});

test('with no event the computed duration and delay, then one frame, end it; nothing to wait for ends it next frame', async () => {
    const w = world({ transitionDelay: '0.04s, 0s' });
    const wait = afterMotion(w.el, { win: w.win });
    assert.deepEqual(w.timers.map((t) => t.ms), [320], 'transform: 280 ms + 40 ms delay, read from the stylesheet');
    w.runTimers();
    assert.equal(await outcome(wait.done), 'pending', 'and then one frame');
    w.runFrames();
    assert.equal(await outcome(wait.done), 'timeout');
    const opacity = world();
    afterMotion(opacity.el, { property: 'opacity', win: opacity.win });
    assert.deepEqual(opacity.timers.map((t) => t.ms), [180], 'milliseconds are read as written');
    const all = world({ transitionProperty: 'all', transitionDuration: '0.34s' });
    afterMotion(all.el, { win: all.win });
    assert.deepEqual(all.timers.map((t) => t.ms), [340], '`all` covers the property');
    for (const style of [{ transitionProperty: 'none', transitionDuration: '0s' }, { transitionDuration: '0s, 0s' },
        { transitionProperty: 'opacity', transitionDuration: '0.2s' }]) {
        const still = world(style);
        const next = afterMotion(still.el, { win: still.win });
        assert.equal(still.timers.length, 0, JSON.stringify(style));
        still.runFrames();
        assert.equal(await outcome(next.done), 'none', JSON.stringify(style));
    }
});

test('cancel ends the wait at once and once; a missing element ends it as nothing', async () => {
    const w = world();
    const wait = afterMotion(w.el, { win: w.win });
    wait.cancel();
    assert.equal(await outcome(wait.done), 'cancel');
    assert.equal(w.el.listeners.size, 0);
    w.runTimers(); w.runFrames();
    wait.cancel();
    assert.equal(await outcome(wait.done), 'cancel');
    assert.equal(await outcome(afterMotion(null, { win: w.win }).done), 'none');
});

test('the motion preference is read in one place and followed while the app runs', () => {
    const handlers = new Set();
    const query = { matches: false, addEventListener: (type, fn) => handlers.add(fn), removeEventListener: (type, fn) => handlers.delete(fn) };
    const win = { matchMedia: (q) => { assert.equal(q, '(prefers-reduced-motion: reduce)'); return query; } };
    assert.equal(reducedMotion(win), false);
    query.matches = true;
    assert.equal(reducedMotion(win), true);
    const seen = [];
    const off = onReducedMotionChange((reduce) => seen.push(reduce), win);
    handlers.forEach((fn) => fn({ matches: false }));
    assert.deepEqual(seen, [false]);
    off();
    assert.equal(handlers.size, 0);
    assert.equal(reducedMotion({}), false, 'no matchMedia: motion allowed');
    assert.equal(typeof onReducedMotionChange(() => {}, {}), 'function');
});

test('an end from a transition that was replaced ends nothing while the new one runs', async () => {
    const w = world();
    let animations = [{ transitionProperty: 'transform', playState: 'running' }];
    w.el.getAnimations = () => animations;
    const wait = afterMotion(w.el, { win: w.win });
    w.el.fire('transitioncancel', { propertyName: 'transform' });  // the opening transition, cancelled by the close
    assert.equal(await outcome(wait.done), 'pending', 'the close still runs');
    animations = [];
    w.el.fire('transitionend', { propertyName: 'transform' });
    assert.equal(await outcome(wait.done), 'end');
});
