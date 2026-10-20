/** The sent draft rises into the feed (owner 20.10, 2A; docs/DESIGN.md "The composer field").
 *
 * On an accepted Send a copy of the new owner bubble stands where the draft stood in the field, its words where the
 * draft's words were, and glides to the bubble's place: its box moves and resizes (never a scale, so the words keep
 * their size), the field's surface turns into the owner's voice, the field's corner into the bubble's and the float
 * shadow into the rest one, on the iOS sheet curve. The bubble itself stays hidden under the copy and shows as it
 * lands, and the copy's sender line grows in over the flight. Reduced motion, a hidden page, a draft that was not on
 * screen, or a bubble that never came or lies outside its feed's view: the bubble simply appears. The copy is inert
 * and leaves when the motion ends or is cancelled.
 */

export const FLIGHT = Object.freeze({ ms: 340, easing: 'cubic-bezier(0.32, 0.72, 0, 1)', landing: 0.62 });

const px = (n) => `${Math.round(n * 100) / 100}px`;

/** Where the draft stands now, read before the field empties: its box, the left edge of its words and its surface. */
export function draftPlace(field, input, win = globalThis.window) {
    if (!field?.getClientRects?.().length || !input?.getBoundingClientRect || !win?.getComputedStyle) return null;
    const box = field.getBoundingClientRect();
    const look = win.getComputedStyle(field);
    return {
        top: box.top, bottom: box.bottom, right: box.right,
        textLeft: input.getBoundingClientRect().left + (parseFloat(win.getComputedStyle(input).paddingLeft) || 0),
        background: look.backgroundColor, radius: look.borderTopLeftRadius, shadow: look.boxShadow,
    };
}

/** The look of `row` without what identifies it (ids and the row's own data: its address, keys and history place). */
function copyOf(row) {
    const copy = row.cloneNode(true);
    for (const name of copy.getAttributeNames()) if (name === 'id' || name.startsWith('data-')) copy.removeAttribute(name);
    copy.querySelectorAll('[id]').forEach((node) => node.removeAttribute('id'));
    copy.classList.add('chat-send-flight');
    copy.setAttribute('aria-hidden', 'true');
    copy.inert = true;
    return copy;
}

/** Fly `row` (the bubble an accepted send just added) up from `from` (draftPlace). Returns the copy, or null. */
export function flySent({ from, row, win = globalThis.window, doc = globalThis.document } = {}) {
    if (!from || !row?.isConnected || typeof row.animate !== 'function' || !doc?.body) return null;
    if (doc.hidden || win?.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return null;
    const look = win.getComputedStyle(row);
    // The copy's words start where the draft's did: its left edge is the draft's words less the bubble's own inset.
    const left = from.textLeft - (parseFloat(look.paddingLeft) || 0);
    const start = { left: px(left), top: px(from.top), width: px(Math.max(0, from.right - left)),
        height: px(Math.max(0, from.bottom - from.top)), backgroundColor: from.background, borderRadius: from.radius,
        boxShadow: from.shadow };
    const ghost = copyOf(row);
    Object.assign(ghost.style, start);
    // The sender line is not in the draft: it grows in over the flight, so the words start where the draft's were.
    const sender = row.querySelector(':scope > .sender');
    const name = ghost.querySelector(':scope > .sender');
    if (name) Object.assign(name.style, { overflow: 'hidden', maxHeight: '0px', marginBottom: '0px', opacity: '0' });
    doc.body.append(ghost);
    // The row hides before it is painted in place, and shows as the copy lands.
    const held = row.style.opacity;
    row.style.opacity = '0';
    let landing = null;
    const done = () => {
        ghost.remove();
        landing?.cancel();
        row.style.opacity = held;
    };
    // The row's place, once its feed has laid it out at its newest end (two frames).
    win.requestAnimationFrame(() => win.requestAnimationFrame(() => {
        if (!row.isConnected || !ghost.isConnected) { done(); return; }
        const last = row.getBoundingClientRect();
        const view = row.parentElement?.getBoundingClientRect?.();
        if (!last.height || (view && (last.bottom <= view.top || last.top >= view.bottom))) { done(); return; }
        const timing = { duration: FLIGHT.ms, easing: FLIGHT.easing, fill: 'forwards' };
        landing = row.animate([{ opacity: 0 }, { opacity: 0, offset: FLIGHT.landing }, { opacity: 1 }],
            { duration: FLIGHT.ms, easing: 'linear', fill: 'both' });
        const flight = ghost.animate([start, { left: px(last.left), top: px(last.top), width: px(last.width),
            height: px(last.height), backgroundColor: look.backgroundColor, borderRadius: look.borderTopLeftRadius,
            boxShadow: look.boxShadow }], timing);
        if (sender && name) {
            const height = px(sender.getBoundingClientRect().height);
            const gap = win.getComputedStyle(sender).marginBottom;
            name.animate([{ maxHeight: '0px', marginBottom: '0px', opacity: 0 },
                { maxHeight: height, marginBottom: gap, opacity: 0, offset: 0.5 },
                { maxHeight: height, marginBottom: gap, opacity: 1 }], timing);
        }
        flight.finished.then(done, done);
    }));
    return ghost;
}
