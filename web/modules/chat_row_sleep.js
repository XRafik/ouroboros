// Rows that sleep (owner 20.10, 3A step 3). The browser skips a feed row far from the screen (content-visibility:
// auto under [data-laid], style.css) only once that row was laid out at the feed's width with everything in it: the
// size it keeps while skipped (contain-intrinsic-size: auto) is then its real size, and the passage being read never
// moves when it wakes (tests/test_chat_lazy_rows_browser.py). Skipped rows keep a long history cheap to move: the room
// card sliding under the drawer no longer restyles and repaints every row.
//
// A row sleeps a moment after it arrived, after it last changed, and after every picture in it has arrived (a picture
// still loading has no size yet, so its row stays awake until it loads or fails). A row that changes wakes at once and
// is laid out like any other row; inside the reading owner's write (chat_reading_position.js `mutate`) the owner
// settles it before it restores the passage (`flush`), so the place it restores is measured with the row's new size.
// A new width, new fonts, another theme, layout or language wake every row (a row's size can depend on any of them:
// the dark theme's recorded answer has a line the light one has not); they sleep again once the width has held.
// A feed that is not shown lays nothing out: its rows wait until it is.

const MARK = 'data-laid';
const ADDED_FRAMES = 2;     // a row added is laid out by the next frame; it sleeps after the one after
const CHANGED_FRAMES = 30;  // a row that changes often (a streaming answer, a live card) stays awake while it does
const HELD_FRAMES = 12;     // a width that held this long has stopped moving (chat_reading_position.js)
// What changes a row's size besides its text and children: its classes, a part hidden or opened, an inline size,
// a picture's source.
const RESIZING = ['class', 'hidden', 'open', 'style', 'src'];
// What on the page's root restyles every row: the theme, the layout, the language and its direction.
const RESTYLING = ['data-theme', 'data-layout', 'lang', 'dir'];

export function createRowSleep({ feed, win = globalThis.window } = {}) {
    if (!feed || typeof win?.requestAnimationFrame !== 'function' || typeof win.MutationObserver !== 'function') {
        return { destroy() {} };
    }
    const doc = feed.ownerDocument;
    const due = new Map();  // row → the frame it may sleep at
    const waiting = new WeakSet();  // rows awake until a picture in them arrives
    // The feed's width and whether it is shown, as its ResizeObserver last saw them (read there, after layout: a
    // frame callback never forces one). Without the observer the feed is taken as shown at its first width.
    const observes = typeof win.ResizeObserver === 'function';
    let destroyed = false, frame = 0, ticking = false, held = HELD_FRAMES;
    let width = observes ? 0 : feed.clientWidth, shown = !observes;

    const rowOf = (node) => {
        let el = node?.nodeType === 1 ? node : node?.parentElement;
        while (el && el.parentElement !== feed) el = el.parentElement;
        return el || null;
    };
    const queue = (row, frames) => {
        due.set(row, Math.max(due.get(row) || 0, frame + frames));
        if (!ticking) { ticking = true; win.requestAnimationFrame(tick); }
    };
    const wake = (row, frames = CHANGED_FRAMES) => {
        if (row.hasAttribute(MARK)) row.removeAttribute(MARK);
        queue(row, frames);
    };
    const wakeAll = () => { for (const row of feed.children) wake(row, ADDED_FRAMES); };

    function sleep(row) {
        const pictures = [...row.querySelectorAll('img')].filter((img) => !img.complete);
        if (!pictures.length) { row.setAttribute(MARK, ''); return; }
        if (waiting.has(row)) return;
        waiting.add(row);
        const arrived = () => {
            if (!waiting.delete(row) || destroyed || row.parentElement !== feed) return;
            queue(row, ADDED_FRAMES);
        };
        for (const img of pictures) {
            img.addEventListener('load', arrived, { once: true });
            img.addEventListener('error', arrived, { once: true });
        }
    }

    function tick() {
        // A feed that is not shown lays nothing out: the count stops, and its observer starts it again when it shows.
        if (destroyed || !shown) { ticking = false; return; }
        frame += 1;
        // Nothing sleeps while the width moves (the reading owner's lazy rows): a row that was not laid out at this
        // width would keep a size that is not its own.
        const settled = !feed.hasAttribute('data-resizing') && ++held >= HELD_FRAMES;
        if (settled) {
            for (const [row, at] of due) {
                if (at > frame) continue;
                due.delete(row);
                if (row.parentElement === feed) sleep(row);
            }
        }
        if (due.size) win.requestAnimationFrame(tick);
        else ticking = false;
    }

    const settle = (records) => {
        for (const record of records) {
            if (record.target === feed) {
                for (const node of record.addedNodes) if (node.nodeType === 1) queue(node, ADDED_FRAMES);
                continue;
            }
            const row = rowOf(record.target);
            if (row) wake(row);
        }
    };
    const changes = new win.MutationObserver(settle);
    changes.observe(feed, { childList: true, subtree: true, characterData: true, attributes: true,
        attributeFilter: RESIZING });
    const restyled = doc?.documentElement ? new win.MutationObserver(() => wakeAll()) : null;
    restyled?.observe(doc.documentElement, { attributes: true, attributeFilter: RESTYLING });

    // A new width wakes every row: each is laid out again at it. A hidden feed reads 0 and keeps its rows as they are;
    // shown again at its width, the rows that arrived meanwhile (never laid out) sleep once they have been.
    const resized = observes ? new win.ResizeObserver(() => {
        const now = feed.clientWidth;
        shown = now > 0;
        if (!shown) return;
        if (width && now !== width) { width = now; held = 0; wakeAll(); return; }
        width = now;
        if (due.size && !ticking) { ticking = true; win.requestAnimationFrame(tick); }
    }) : null;
    resized?.observe(feed);
    const fontsLoaded = () => wakeAll();
    doc?.fonts?.addEventListener?.('loadingdone', fontsLoaded);

    for (const row of feed.children) queue(row, ADDED_FRAMES);

    return {
        // The changes written so far wake their rows now, not at the next microtask: a reader's place measured right
        // after a write sees every changed row at its new size.
        flush() { if (!destroyed) settle(changes.takeRecords()); },
        destroy() {
            if (destroyed) return;
            destroyed = true;
            changes.disconnect();
            restyled?.disconnect();
            resized?.disconnect();
            doc?.fonts?.removeEventListener?.('loadingdone', fontsLoaded);
            due.clear();
        },
    };
}
