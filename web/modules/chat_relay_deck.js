// Notes between works (docs/DESIGN.md "Replies"): a note one work leaves another (`tell_task`) is written for that
// work, so its room draws it as a note card, never as an Ouroboros reply. The card says who wrote to this work and
// when, then the teller's one line for the owner (its `summary`; a note without one opens with its own first words in
// the meta ink), and `Show note` opens the note as written in a tray with Reply and Copy. Consecutive notes make one
// deck: the latest card in front, the edges of up to two cards behind it, `Show N notes` fanning the deck out in
// place (the third height fold the bible sanctions, on the sheet curve) and `Hide` folding it back. A relay that
// passes the owner's own words is a card of its own, his words in their quote panel above the summary line.
// The relay bubbles stay in the feed, hidden, as the rows they are (address, Reply, history order and paging): this
// module only draws over them and never decides what a note says.
import { fmt, tr } from './i18n.js';
import { formatMsgTime } from './utils.js';
import { fitText } from './text_fit.js';
import { motionMs, reducedMotion } from './motion.js';
import { PAGE_ICONS } from './page_icons.js';
import { copyTextWithToast } from './ui_helpers.js';

const EDGES = 3;           // the front card and at most two edges behind it
const EDGE_HEIGHT = 56;    // what a card keeps of itself as an edge behind the front one (the stylesheet's recipe)

const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text != null) el.textContent = text;
    return el;
};
const control = (cls, text) => {
    const el = node('button', `btn btn-default btn-sm ui-hit-area ${cls}`, text);
    el.type = 'button';
    return el;
};
const setInert = (el, on) => {
    if (on) el.setAttribute('inert', ''); else el.removeAttribute('inert');
    el.setAttribute('aria-hidden', on ? 'true' : 'false');
};
const isDeck = (el) => Boolean(el?.classList?.contains('chat-relay-deck'));
const isCarrier = (el) => Boolean(el?.__relayNote) && el.dataset?.systemType === 'relay_entry';
const transparent = (el) => isDeck(el) || el.hidden || Boolean(el.classList?.contains('typing-bubble'));

/**
 * One instance per room feed (chat_reply.js creates it beside the replies). `relayQuote(relay)` builds the owner's
 * quote panel (the product's own component, chat_reply_quote.js), `reply(bubble)` stages a reply to a note's row,
 * `onDomWrite` is the room's stable-viewport seam: every change that moves heights runs inside it.
 */
export function createRelayDecks({ feed, relayQuote = () => null, reply = () => {}, onDomWrite = (write) => write(),
    formatTime = formatMsgTime, copy = (text) => copyTextWithToast(text, { okMessage: tr('chat.relay.copied', 'Note copied.') }) } = {}) {
    const fresh = new Set();     // notes adopted since the last reconcile
    let scheduled = false, settled = false, destroyed = false;

    const timing = () => {
        let ease = '';
        try {
            const win = globalThis.window;
            ease = win.getComputedStyle(win.document.documentElement).getPropertyValue('--ease-sheet').trim();
        } catch { ease = ''; }
        return { open: motionMs('--motion-open'), close: motionMs('--motion-close'), ease: ease || 'cubic-bezier(0.2, 0.8, 0.2, 1)' };
    };
    const moving = (el) => Boolean(el) && typeof el.animate === 'function' && !reducedMotion() && timing().open > 0;
    // One Web Animation that rests on the element's own CSS afterwards; reduced motion or no engine plays nothing.
    const play = (el, frames, opts) => {
        if (!moving(el) || !opts.duration) return null;
        try { return el.animate(frames, { easing: timing().ease, fill: 'backwards', ...opts }); } catch { return null; }
    };
    const done = (anim, fn) => (anim ? anim.finished.then(fn, fn) : fn());

    /* ---- a note ------------------------------------------------------------------------------------------------- */
    function noteOf(bubble) {
        const { row, quoted } = bubble.__relayNote;
        const relay = row?.relay && typeof row.relay === 'object' ? row.relay : {};
        const sender = relay.sender && typeof relay.sender === 'object' ? relay.sender : null;
        // A note saved before its room was recorded: Main when it came from Main, never an invented room.
        const fromMain = sender ? Number(sender.chat_id) === 1 : !quoted && Number(relay.source?.chat_id) === 1;
        const time = formatTime(row?.ts) || null;
        return {
            bubble, quoted, relay,
            words: String(row?.text ?? bubble.querySelector(':scope > .message')?.textContent ?? '').trim(),
            summary: String(relay.summary || '').trim(),
            name: String(sender?.name || '').trim() || (fromMain ? 'Main' : tr('chat.relay.another_work', 'Another work')),
            kind: fromMain ? 'main' : 'project', time: time?.short || '', when: time?.full || '',
        };
    }

    function buildCard(note) {
        const card = node('article', 'chat-relay-card');
        card.dataset.kind = note.kind;
        const body = node('div', 'chat-relay-card-body');
        const head = node('div', 'chat-relay-card-head');
        const tile = node('span', 'chat-relay-tile');
        tile.innerHTML = note.kind === 'main' ? PAGE_ICONS.chat : PAGE_ICONS.projects;
        const who = node('div', 'chat-relay-who');
        const sub = node('div', 'chat-relay-sub');
        const time = node('time', 'chat-relay-time', note.time);
        if (note.when) time.title = note.when;
        sub.append(node('span', '', tr('chat.relay.to_this_work', 'to this work')), node('span', '', ' · '), time);
        who.append(node('div', 'chat-relay-from', note.name), sub);
        head.append(tile, who, control('chat-relay-act', tr('chat.relay.show_note', 'Show note')));
        body.append(head);
        const quote = note.quoted ? relayQuote(note.relay) : null;
        if (quote) body.append(quote);
        const gist = node('p', 'chat-relay-gist');
        if (!note.summary) gist.dataset.raw = '1';
        body.append(gist);
        fitText(gist, note.summary || note.words, 2);
        const raw = node('div', 'chat-relay-raw');
        raw.hidden = true;
        const foot = node('div', 'chat-relay-raw-foot');
        foot.append(control('chat-relay-reply', tr('chat.reply.reply', 'Reply')), control('chat-relay-copy', tr('code.copy', 'Copy')));
        raw.append(node('div', 'chat-relay-raw-label', tr('chat.relay.as_written', 'Note as written')),
            node('div', 'chat-relay-raw-text', note.words), foot);
        body.append(raw);
        card.append(body);
        card.__note = note;
        return card;
    }

    /* ---- a deck --------------------------------------------------------------------------------------------------- */
    function build(rows) {
        const obj = node('section', 'chat-relay-deck');
        obj.setAttribute('role', 'group');
        obj.setAttribute('aria-label', tr('chat.relay.label', 'Notes between works'));
        const top = node('div', 'chat-relay-deck-top');
        const caption = node('div', 'chat-relay-deck-caption');
        top.append(caption, control('chat-relay-hide', tr('chat.relay.hide', 'Hide')));
        const stack = node('div', 'chat-relay-deck-stack');
        obj.append(top, stack);
        const deck = { obj, stack, caption, rows: [], cards: [], open: false };
        obj.__deck = deck;
        rows.forEach((row) => adoptRow(deck, row));
        wire(deck);
        paint(deck);
        return deck;
    }

    function adoptRow(deck, bubble) {
        const card = buildCard(noteOf(bubble));
        deck.rows.push(bubble);
        deck.cards.push(card);
        deck.stack.append(card);
        bubble.__relayDeck = deck;
        bubble.hidden = true;
        bubble.dataset.relayDeck = '1';
        // The timeline places a later row by timestamps (chat_render_batch.js): the deck stands where its first note is.
        deck.obj.dataset.ts = deck.rows[0].dataset.ts || '';
        return card;
    }

    const range = (cards) => {
        const a = cards[0]?.__note.time, b = cards[cards.length - 1]?.__note.time;
        return a && b && a !== b ? `${a}–${b}` : (b || a || '');
    };

    // `Show 7 notes`: one label, the figure in its own box so it can roll; the button's flex gap never touches the words.
    function setCount(act, n) {
        const [lead = '', tail = ''] = fmt('Show {n} notes', { n }).split(String(n));
        const figure = node('span', 'chat-relay-count');
        figure.append(node('span', 'chat-relay-count-value', String(n)));
        const label = node('span', 'chat-relay-act-label');
        label.append(node('span', '', lead), figure, node('span', '', tail));
        act.replaceChildren(label);
        act.setAttribute('aria-label', fmt('Show {n} notes', { n }));
    }

    function roll(figure, from, to) {
        const current = figure.querySelector('.chat-relay-count-value');
        if (!current || !moving(figure)) return;
        current.textContent = String(from);
        const next = node('span', 'chat-relay-count-value', String(to));
        figure.append(next);
        const { open } = timing();
        done(play(current, [{ transform: 'translateY(0)', opacity: 1 }, { transform: 'translateY(-100%)', opacity: 0 }],
            { duration: Math.round(open * 0.76), fill: 'forwards' }), () => current.remove());
        play(next, [{ transform: 'translateY(100%)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }],
            { duration: Math.round(open * 0.94), delay: 40 });
    }

    // Everything that follows from the count and the state: the edges, the front card's capsule, the caption.
    function paint(deck) {
        const { obj, cards } = deck;
        const n = cards.length;
        obj.dataset.n = String(Math.min(n, EDGES));
        obj.dataset.open = deck.open ? '1' : '0';
        cards.forEach((card, i) => {
            const depth = n - 1 - i;
            card.style.setProperty('--depth', String(Math.min(depth, EDGES - 1)));
            card.dataset.deep = depth >= EDGES ? '1' : '0';
            setInert(card, !deck.open && depth > 0);
            const act = card.querySelector('.chat-relay-act');
            if (!deck.open && n > 1 && depth === 0) {
                setCount(act, n);
                act.setAttribute('aria-expanded', 'false');
                return;
            }
            const on = card.dataset.raw === '1';
            act.textContent = on ? tr('chat.relay.hide_note', 'Hide note') : tr('chat.relay.show_note', 'Show note');
            act.removeAttribute('aria-label');
            act.setAttribute('aria-expanded', String(on));
        });
        const line = node('span', 'chat-relay-deck-line');
        line.append(node('b', '', fmt('{n} notes', { n })), node('span', '', range(cards) ? ` · ${range(cards)}` : ''));
        deck.caption.replaceChildren(line, node('span', 'chat-relay-deck-note',
            tr('chat.relay.not_for_you', 'Written for this work, not for you')));
    }

    function wire(deck) {
        deck.obj.addEventListener('click', (event) => {
            const card = event.target.closest('.chat-relay-card');
            if (event.target.closest('.chat-relay-copy')) { void copy(card.__note.words); return; }
            if (event.target.closest('.chat-relay-reply')) { reply(card.__note.bubble); return; }
            if (event.target.closest('.chat-relay-hide')) {
                setOpen(deck, false);
                deck.cards[deck.cards.length - 1]?.querySelector('.chat-relay-act')?.focus({ preventScroll: true });
                return;
            }
            if (event.target.closest('.chat-relay-act')) {
                if (!deck.open && deck.cards.length > 1) setOpen(deck, true); else toggleRaw(card);
                return;
            }
            // The closed deck answers a press anywhere on its front card (never on its quote, a control or a selection).
            if (!deck.open && deck.cards.length > 1 && card === deck.cards[deck.cards.length - 1]
                && !event.target.closest('.chat-quote, button, a') && !String(globalThis.getSelection?.() || '')) {
                setOpen(deck, true);
            }
        });
    }

    /* ---- the note as written ----------------------------------------------------------------------------------------- */
    function showRaw(card, open) {
        const act = card.querySelector('.chat-relay-act');
        card.dataset.raw = open ? '1' : '0';
        card.querySelector('.chat-relay-raw').hidden = !open;
        act.textContent = open ? tr('chat.relay.hide_note', 'Hide note') : tr('chat.relay.show_note', 'Show note');
        act.setAttribute('aria-expanded', String(open));
    }

    function toggleRaw(card) {
        const raw = card.querySelector('.chat-relay-raw');
        const { open, close } = timing();
        if (raw.hidden) {
            onDomWrite(() => { showRaw(card, true); return true; });
            play(raw, [{ height: '0px', opacity: 0 }, { height: `${raw.offsetHeight}px`, opacity: 1 }], { duration: open });
            return;
        }
        const shut = () => onDomWrite(() => { showRaw(card, false); return true; });
        const anim = play(raw, [{ height: `${raw.offsetHeight}px`, opacity: 1 }, { height: '0px', opacity: 0 }], { duration: close, fill: 'forwards' });
        if (anim) done(anim, () => { shut(); anim.cancel(); }); else shut();
    }

    /* ---- the deck fans out and folds back ----------------------------------------------------------------------- */
    function setOpen(deck, open, { instant = false } = {}) {
        if (deck.open === open || deck.cards.length < 2) return;
        const { obj, cards } = deck;
        const first = cards.map((card) => card.getBoundingClientRect());
        const h0 = obj.getBoundingClientRect().height;
        onDomWrite(() => { deck.open = open; paint(deck); return true; });
        if (instant) return;
        const last = cards.map((card) => card.getBoundingClientRect());
        const h1 = obj.getBoundingClientRect().height;
        const { open: openMs, close } = timing();
        const duration = open ? openMs : close;
        cards.forEach((card, i) => {
            const f = first[i], l = last[i];
            play(card, [
                { transform: `translateY(${f.top - l.top}px) scaleX(${l.width ? f.width / l.width : 1})`, height: `${f.height}px` },
                { transform: 'translateY(0) scaleX(1)', height: `${l.height}px` },
            ], { duration });
            if (i === cards.length - 1) return;
            const body = card.querySelector('.chat-relay-card-body');
            if (open) play(body, [{ opacity: 0 }, { opacity: 1 }], { duration: Math.round(duration * 0.65), delay: Math.round(duration * 0.38) });
            else play(body, [{ visibility: 'visible', opacity: 1 }, { visibility: 'visible', opacity: 0 }], { duration: Math.round(duration * 0.4) });
            // Cards that were not even an edge come out of the deck, or go back into it, fading.
            if (card.dataset.deep === '1' || (open && i < cards.length - EDGES)) {
                play(card, [{ opacity: open ? 0 : 1 }, { opacity: open ? 1 : 0 }], { duration: Math.round(duration * 0.7) });
            }
        });
        if (open) {
            play(obj.querySelector('.chat-relay-deck-top'), [{ opacity: 0, transform: 'translateY(-6px)' }, { opacity: 1, transform: 'none' }],
                { duration: Math.round(duration * 0.76), delay: 90 });
        }
        play(obj, [{ height: `${h0}px` }, { height: `${h1}px` }], { duration, fill: 'none' });
    }

    /* ---- a note arrives ------------------------------------------------------------------------------------------- */
    // Runs inside the reconcile's write; returns the motion to play once the feed has its new shape, or null.
    function addNote(deck, bubble, animate) {
        const before = deck.cards.length;
        const prev = deck.cards[before - 1];
        const sinking = animate && !deck.open && moving(prev);
        const pr = sinking ? prev.getBoundingClientRect() : null;
        const objTop = sinking ? deck.obj.getBoundingClientRect().top : 0;
        let ghost = null;
        if (sinking) {
            // The card in front sinks into the deck as the new one comes up over it: its picture plays that part.
            ghost = prev.cloneNode(true);
            ghost.classList.add('chat-relay-ghost');
            setInert(ghost, true);
            ghost.style.setProperty('top', `${pr.top - objTop}px`);
            ghost.style.setProperty('height', `${pr.height}px`);
            deck.obj.append(ghost);
        }
        const card = adoptRow(deck, bubble);
        paint(deck);
        if (!animate) return null;
        return () => {
            const { open } = timing();
            if (deck.open) {
                play(card, [{ height: '0px', opacity: 0, transform: 'translateY(10px)' }, { height: `${card.offsetHeight}px`, opacity: 1, transform: 'none' }],
                    { duration: open });
                return;
            }
            if (!ghost) return;
            const top = deck.obj.getBoundingClientRect().top;
            const sinkTo = prev.getBoundingClientRect().top - top;
            const sink = play(ghost, [
                { transform: 'translateY(0) scaleX(1)', height: `${pr.height}px` },
                { transform: `translateY(${sinkTo - (pr.top - objTop)}px) scaleX(${pr.width ? (pr.width - 16) / pr.width : 1})`, height: `${EDGE_HEIGHT}px` },
            ], { duration: open, fill: 'both' });
            play(ghost.querySelector('.chat-relay-card-body'), [{ opacity: 1 }, { opacity: 0 }], { duration: Math.round(open * 0.6), fill: 'both' });
            play(prev, [{ opacity: 0 }, { opacity: 0 }], { duration: Math.round(open * 0.9) });
            // The new card comes up from below the deck, solid early, so the sinking card never shows through it.
            play(card, [{ transform: 'translateY(30px) scale(0.985)' }, { transform: 'none' }], { duration: open, delay: 30 });
            play(card, [{ opacity: 0 }, { opacity: 1 }], { duration: Math.round(open * 0.42), delay: 30 });
            play(card.querySelector('.chat-relay-tile'), [{ transform: 'scale(0.6)', opacity: 0 }, { transform: 'scale(1)', opacity: 1 }],
                { duration: Math.round(open * 1.1), delay: 140 });
            done(sink, () => ghost.remove());
            const figure = card.querySelector('.chat-relay-count');
            if (figure && before >= 2) roll(figure, before, before + 1);
        };
    }

    /* ---- the feed ------------------------------------------------------------------------------------------------ */
    // Runs of consecutive notes in feed order: our decks, hidden rows and the typing row are transparent, any other row
    // ends a run, and a relay with the owner's words is a run of its own.
    function runs() {
        const out = [];
        let run = [];
        const flush = () => { if (run.length) out.push(run); run = []; };
        for (const el of [...feed.children]) {
            if (isCarrier(el)) {
                if (el.__relayNote.quoted) { flush(); out.push([el]); } else run.push(el);
            } else if (!transparent(el)) flush();
        }
        flush();
        return out;
    }

    // A note arriving live lands at the newest end: no visible row after it.
    const atNewest = (bubble) => {
        for (let el = bubble.nextElementSibling; el; el = el.nextElementSibling) if (!transparent(el)) return false;
        return true;
    };

    function reconcile() {
        scheduled = false;
        if (destroyed) return;
        const arrived = [...fresh].filter((bubble) => bubble.parentElement === feed);
        fresh.clear();
        // A room without notes costs nothing: no deck to keep and no note waiting to be drawn.
        if (!feed.querySelector(':scope > .chat-relay-deck, :scope > [data-system-type="relay_entry"]:not([data-relay-deck])')) {
            settled = true;
            return;
        }
        // One note landing at the newest end of a room already drawn is an arrival; a history page is not.
        const live = settled && arrived.length === 1 && atNewest(arrived[0]);
        settled = true;
        const motions = [];
        onDomWrite(() => {
            let changed = false;
            const kept = new Set();
            for (const run of runs()) {
                const deck = run[0].__relayDeck;
                if (deck && !kept.has(deck) && deck.obj.isConnected && deck.rows.length <= run.length
                    && deck.rows.every((row, i) => row === run[i])) {
                    kept.add(deck);
                    if (deck.obj.nextElementSibling !== run[0]) { feed.insertBefore(deck.obj, run[0]); changed = true; }
                    for (const row of run.slice(deck.rows.length)) {
                        motions.push(addNote(deck, row, live && row === arrived[0]));
                        changed = true;
                    }
                    continue;
                }
                // Anything else (a run extended upward by an older page, split or joined by a row) is drawn again,
                // keeping what the owner had open.
                const open = run.some((row) => row.__relayDeck?.open);
                const raw = new Set(run.filter((row) => row.__relayDeck?.cards[row.__relayDeck.rows.indexOf(row)]?.dataset.raw === '1'));
                const drawn = build(run);
                kept.add(drawn);
                feed.insertBefore(drawn.obj, run[0]);
                if (open && drawn.cards.length > 1) { drawn.open = true; paint(drawn); }
                drawn.rows.forEach((row, i) => { if (raw.has(row)) showRaw(drawn.cards[i], true); });
                if (live && run.length === 1 && run[0] === arrived[0]) {
                    motions.push(() => play(drawn.obj, [{ transform: 'translateY(18px) scale(0.985)', opacity: 0 }, { transform: 'none', opacity: 1 }],
                        { duration: timing().open }));
                }
                changed = true;
            }
            // Decks whose notes left the feed, or were drawn again, go with them.
            for (const el of [...feed.children]) {
                if (isDeck(el) && !kept.has(el.__deck)) { el.remove(); changed = true; }
            }
            return changed;
        });
        motions.forEach((motion) => motion?.());
    }

    function schedule() {
        if (scheduled || destroyed) return;
        scheduled = true;
        queueMicrotask(reconcile);
    }

    // A row inserted between two notes, or taken out between them, changes the runs: the feed's child list says so where
    // an observer exists (the browser); everywhere else each adopted note and each landed row asks for it.
    const watcher = typeof MutationObserver === 'function' ? new MutationObserver((records) => {
        if (records.some((r) => [...r.addedNodes, ...r.removedNodes].some((el) => el.nodeType === 1 && !isDeck(el)))) schedule();
    }) : null;
    watcher?.observe(feed, { childList: true });

    return {
        /** A relay row's bubble once its quote is decorated: `row` is the history row or live frame, `quoted` whether it
         * passes the owner's words. The bubble is drawn as a note once it stands in the feed. */
        adopt(bubble, row, quoted) {
            if (!bubble || !row) return;
            bubble.__relayNote = { row, quoted: Boolean(quoted) };
            fresh.add(bubble);
            schedule();
        },
        schedule,
        /** The visible stand-in for a note's hidden row (a quote's jump lands on its card, its deck opened); else null. */
        surface(target) {
            const deck = target?.__relayDeck;
            if (!deck?.obj.isConnected) return null;
            const card = deck.cards[deck.rows.indexOf(target)] || null;
            if (card && card !== deck.cards[deck.cards.length - 1]) setOpen(deck, true, { instant: true });
            return card;
        },
        destroy() {
            destroyed = true;
            watcher?.disconnect();
            fresh.clear();
        },
    };
}
