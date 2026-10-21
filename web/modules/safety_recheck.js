// The second check's one control: a row-level mark «Re-checks flagged actions» on the Agents rows the server
// says can re-check (`policy_state.safety_recheck.eligible_rows`: an API model row with Packet delivery). At
// most one row carries it. The mark is a draft like the other Settings fields; Save writes the chosen row
// through the owner endpoint (settings_safety.js), never through the roster, so the agent cannot set it.

const state = { eligible: new Set(), saved: '', draft: null, known: false };

const escapeAttr = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** The row the draft marks: a row id, '' for none, or null while the owner has not touched the marks. */
export const recheckDraft = () => state.draft;
export const recheckSaved = () => state.saved;
const marked = () => (state.draft === null ? state.saved : state.draft);

/** The mark in an Agents row's head; hidden on rows the server does not list as eligible. */
export function recheckMarkHtml(row, ordinal = 1) {
    const id = String(row?.subagent_id || '');
    if (!id) return '';
    const key = String(row?._uiKey || id);
    return `<label class="available-subagent-recheck" data-recheck-row="${escapeAttr(id)}"${state.eligible.has(id) ? '' : ' hidden'}><input class="ui-checkbox" type="checkbox" id="s-recheck-${escapeAttr(key)}" data-recheck-mark="${escapeAttr(id)}" aria-label="Subagent ${Number(ordinal) || 1} re-checks flagged actions"${marked() === id ? ' checked' : ''}> Re-checks flagged actions</label>`;
}

function paint(root) {
    root?.querySelectorAll?.('[data-recheck-row]').forEach((label) => {
        const id = label.dataset.recheckRow;
        label.hidden = !state.eligible.has(id);
        const box = label.querySelector('[data-recheck-mark]');
        if (box) box.checked = marked() === id;
    });
}

/** Adopt the server's facts after a load (the draft starts over) and repaint the marks in place. */
export function syncRecheckState(recheck, root = globalThis.document) {
    state.known = Boolean(recheck?.known);
    state.eligible = new Set(recheck?.eligibleRows || []);
    state.saved = String(recheck?.rowId || '');
    state.draft = null;
    paint(root);
}

/** One owner press on a mark: it becomes the one marked row, or none when unticked. */
export function chooseRecheckRow(rowId, checked, root = globalThis.document) {
    state.draft = checked ? String(rowId || '') : '';
    paint(root);
}

/** Delegated binding for the marks the Agents editor renders and re-renders. Capture: the one-mark rule is
 * applied before the page's own change listener takes its draft snapshot. */
export function bindRecheckMarks(root) {
    const onChange = (event) => {
        const box = event.target?.closest?.('[data-recheck-mark]');
        if (box) chooseRecheckRow(box.dataset.recheckMark, box.checked, root);
    };
    root.addEventListener('change', onChange, true);
    return () => root.removeEventListener('change', onChange, true);
}
