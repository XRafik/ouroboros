// The word-cut fitter's one shared ResizeObserver (text_fit.js) keeps no removed element alive: an element that left the
// page leaves the observer on its last size report, while a connected one is re-fitted. Its own file: the observer is
// created once per module instance.
import assert from 'node:assert/strict';
import test from 'node:test';
import { installDom, restoreDom } from './chat_dom_fixture.js';

test('a removed element leaves the shared observer; a connected one stays observed', async () => {
    const env = installDom();
    const unobserved = [];
    let report = null;
    globalThis.ResizeObserver = class {
        constructor(callback) { report = callback; }
        observe() {}
        unobserve(el) { unobserved.push(el); }
    };
    try {
        const { fitText, fullText } = await import('../modules/text_fit.js');
        const kept = document.createElement('div');
        const gone = document.createElement('div');
        env.mount.append(kept);
        fitText(kept, 'kept words', 2);
        fitText(gone, 'gone words', 2);
        report([{ target: gone }, { target: kept }]);
        assert.deepEqual(unobserved, [gone], 'only the element that left the page');
        assert.equal(fullText(gone), 'gone words', 'its own text stays readable');
        assert.equal(fullText(kept), 'kept words');
    } finally { restoreDom(env.prior); }
});

test('a width change re-fits on the next frame, never inside the observer, so the observer cannot loop in one', async () => {
    const env = installDom();
    const frames = [];
    let report = null;
    const prior = { raf: globalThis.requestAnimationFrame, ro: globalThis.ResizeObserver, style: globalThis.getComputedStyle };
    globalThis.requestAnimationFrame = (fn) => { frames.push(fn); return frames.length; };
    globalThis.getComputedStyle = () => ({ lineHeight: '20px', fontSize: '14px', whiteSpace: 'normal' });
    globalThis.ResizeObserver = class {
        constructor(callback) { report = callback; }
        observe() {}
        unobserve() {}
    };
    try {
        const { fitText } = await import(`../modules/text_fit.js?frame=${Date.now()}`);
        const el = document.createElement('div');
        env.mount.append(el);
        const fits = [];
        fitText(el, 'words that would be fitted', 1, (cut) => fits.push(cut));
        const initial = fits.length;
        Object.defineProperty(el, 'clientWidth', { configurable: true, get: () => 120 });
        Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => 20 });  // it fits whole
        report([{ target: el }]);
        report([{ target: el }]);
        assert.equal(fits.length, initial, 'nothing is fitted inside the observer\'s callback');
        assert.equal(frames.length, 1, 'one frame for every width change reported before it');
        frames.splice(0).forEach((fn) => fn());
        assert.equal(fits.length, initial + 1, 'the element is fitted once, on that frame');
    } finally {
        globalThis.requestAnimationFrame = prior.raf;
        globalThis.ResizeObserver = prior.ro;
        globalThis.getComputedStyle = prior.style;
        restoreDom(env.prior);
    }
});
