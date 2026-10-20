import test from 'node:test';
import assert from 'node:assert/strict';

import { createRowSleep } from '../modules/chat_row_sleep.js';

// A feed of rows, its observers and its frames, by hand: a test fires what the browser would.
function stand() {
    const frames = [];
    const observers = { changes: null, size: null };
    const fonts = new Map();
    const doc = { fonts: { addEventListener: (type, fn) => fonts.set(type, fn), removeEventListener: (type) => fonts.delete(type) } };
    const element = (tag = 'div') => {
        const attrs = new Map();
        const node = {
            nodeType: 1, tagName: tag.toUpperCase(), parentElement: null, children: [], ownerDocument: doc,
            listeners: new Map(), complete: true,
            hasAttribute: (name) => attrs.has(name),
            setAttribute: (name, value) => { attrs.set(name, String(value)); },
            removeAttribute: (name) => { attrs.delete(name); },
            append(...kids) { for (const kid of kids) { kid.parentElement = node; node.children.push(kid); } },
            remove() {
                const parent = node.parentElement;
                if (parent) parent.children.splice(parent.children.indexOf(node), 1);
                node.parentElement = null;
            },
            querySelectorAll(selector) {
                const found = [];
                const walk = (el) => { for (const kid of el.children) { if (kid.tagName.toLowerCase() === selector) found.push(kid); walk(kid); } };
                walk(node);
                return found;
            },
            addEventListener(type, fn) { node.listeners.set(type, fn); },
            emit(type) { const fn = node.listeners.get(type); node.listeners.delete(type); fn?.(); },
        };
        return node;
    };
    const feed = element();
    feed.clientWidth = 0;
    const win = {
        requestAnimationFrame: (fn) => { frames.push(fn); return frames.length; },
        MutationObserver: class {
            constructor(callback) { this.callback = callback; observers.changes = this; this.connected = false; }
            observe(target, options) { this.target = target; this.options = options; this.connected = true; }
            disconnect() { this.connected = false; }
        },
        ResizeObserver: class {
            constructor(callback) { this.callback = callback; observers.size = this; this.connected = false; }
            observe() { this.connected = true; }
            disconnect() { this.connected = false; }
        },
    };
    const run = (count = 1) => { for (let i = 0; i < count; i += 1) frames.splice(0).forEach((fn) => fn()); };
    const show = (width) => { feed.clientWidth = width; observers.size.callback([]); };
    const added = (...rows) => { feed.append(...rows); observers.changes.callback([{ target: feed, addedNodes: rows }]); };
    const changed = (node) => observers.changes.callback([{ target: node, addedNodes: [] }]);
    const laid = () => feed.children.map((row) => row.hasAttribute('data-laid'));
    return { feed, win, doc, fonts, observers, element, run, show, added, changed, laid, frames };
}

test('rows sleep only once laid out at a shown feed\'s width, two frames after they arrive', () => {
    const s = stand();
    s.feed.append(s.element(), s.element());
    const sleep = createRowSleep({ feed: s.feed, win: s.win });
    s.run(5);
    assert.deepEqual(s.laid(), [false, false], 'a feed not shown lays nothing out: its rows stay awake');
    s.show(390);
    s.run(1);
    assert.deepEqual(s.laid(), [false, false], 'shown: laid out first');
    s.run(1);
    assert.deepEqual(s.laid(), [true, true]);
    const row = s.element();
    s.added(row);
    s.run(1);
    assert.equal(row.hasAttribute('data-laid'), false, 'a row that just arrived is laid out first');
    s.run(1);
    assert.equal(row.hasAttribute('data-laid'), true);
    assert.equal(s.frames.length, 0, 'nothing due: no frame is asked for');
    sleep.destroy();
    assert.equal(s.observers.changes.connected || s.observers.size.connected, false);
    assert.equal(s.fonts.size, 0);
});

test('a row stays awake until its pictures arrive, then sleeps', () => {
    const s = stand();
    createRowSleep({ feed: s.feed, win: s.win });
    s.show(390);
    const row = s.element(), picture = s.element('img');
    picture.complete = false;
    row.append(picture);
    s.added(row);
    s.run(4);
    assert.equal(row.hasAttribute('data-laid'), false, 'a picture still loading has no size yet');
    picture.complete = true;
    picture.emit('load');
    s.run(1);
    assert.equal(row.hasAttribute('data-laid'), false);
    s.run(1);
    assert.equal(row.hasAttribute('data-laid'), true, 'laid out with its picture, it sleeps');
});

test('a row that changes wakes at once and sleeps again once it held still', () => {
    const s = stand();
    const row = s.element(), text = s.element('p');
    row.append(text);
    s.feed.append(row);
    createRowSleep({ feed: s.feed, win: s.win });
    s.show(390);
    s.run(2);
    assert.equal(row.hasAttribute('data-laid'), true);
    s.changed(text);
    assert.equal(row.hasAttribute('data-laid'), false, 'woken in the same task: it is laid out with what changed');
    s.run(20);
    s.changed(text);  // a streaming answer keeps changing: it stays awake
    s.run(29);
    assert.equal(row.hasAttribute('data-laid'), false);
    s.run(1);
    assert.equal(row.hasAttribute('data-laid'), true);
    assert.deepEqual(s.observers.changes.options.attributeFilter.includes('data-laid'), false,
        'its own mark is no change of the row');
});

test('a new width wakes every row; they sleep again once the width held and the reading owner\'s mark is gone', () => {
    const s = stand();
    s.feed.append(s.element(), s.element(), s.element());
    createRowSleep({ feed: s.feed, win: s.win });
    s.show(390);
    s.run(2);
    assert.deepEqual(s.laid(), [true, true, true]);
    s.feed.setAttribute('data-resizing', '');
    s.show(380);
    assert.deepEqual(s.laid(), [false, false, false], 'each row is laid out again at the new width');
    s.run(3);
    s.show(370);
    s.run(30);
    assert.deepEqual(s.laid(), [false, false, false], 'nothing sleeps while the width moves');
    s.feed.removeAttribute('data-resizing');
    s.run(11);
    assert.deepEqual(s.laid(), [false, false, false]);
    s.run(1);
    assert.deepEqual(s.laid(), [true, true, true], 'the width held: laid out at it, the rows sleep');
    s.show(0);
    s.show(370);
    assert.deepEqual(s.laid(), [true, true, true], 'hidden and shown again at its width: nothing to lay out again');
    s.fonts.get('loadingdone')();
    assert.deepEqual(s.laid(), [false, false, false], 'new fonts: every row is laid out again');
});

test('a row added while the feed is hidden sleeps only after the feed is shown', () => {
    const s = stand();
    createRowSleep({ feed: s.feed, win: s.win });
    s.show(390);
    s.show(0);
    const row = s.element();
    s.added(row);
    s.run(10);
    assert.equal(row.hasAttribute('data-laid'), false, 'never laid out: its size is not known');
    assert.equal(s.frames.length, 0, 'and no frame is asked for while hidden');
    s.show(390);
    s.run(2);
    assert.equal(row.hasAttribute('data-laid'), true);
});
