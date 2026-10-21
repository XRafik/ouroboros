// Settings › Behavior › Safety Supervisor: two coverage levels over one checker — "Your work" (what the owner
// asked for) and "Consciousness" (what Ouroboros does on its own, places included) — the checker and second-check
// facts, and the owner's rules. Every value here is owner-only: the generic settings save never carries it; Save
// writes each changed one through its audited owner endpoint (consciousness_api.js), after the generic save.
import { renderSegmentedField } from './page_header.js';
import { escapeHtmlAttr as escapeHtml } from './utils.js';
import { apiClient } from './api_client.js';
import { openConfirmDialog } from './confirm_dialog.js';
import { settingsWriteFailure, syncEffortSegments } from './settings_controls.js';
import { parseModelSource } from './route_editor_primitives.js';
import { saveSafetyLevel, saveSafetyModel, saveSafetyRecheck, saveSafetyRules, normalizeRecheck } from './consciousness_api.js';
import { SAFETY_KINDS, SAFETY_LEVELS, SAFETY_RANK, safetyLevelOf } from './consciousness_words.js';
import { bindRecheckMarks, recheckDraft, recheckSaved, syncRecheckState } from './safety_recheck.js';

export const CONSCIOUSNESS_SAFETY_KEY = 'OUROBOROS_CONSCIOUSNESS_SAFETY_MODE';
export const SAFETY_RULES_KEY = 'OUROBOROS_SAFETY_OWNER_RULES';
export const SAFETY_MODEL_KEY = 'OUROBOROS_MODEL_SAFETY';

const LEVEL_OPTIONS = SAFETY_LEVELS.map(({ value, label }) => ({ value, label }));
const LOWERING_TITLE = 'Lowering a level asks for confirmation.';

/** The section body under its title (settings_ui.js keeps the `<h3>`). */
export function safetySectionHtml() {
    const notes = SAFETY_LEVELS.map((level) => `<br><code>${escapeHtml(level.label)}</code> &mdash; ${escapeHtml(level.note)}`).join('');
    return `
        <div class="settings-section-copy">
            A second model judges a step before it runs. Your work: what you asked for. Consciousness: what it does on its own, places included.${notes}
            <br><strong>Configuration authority:</strong> outside Cyber Pro, Ouroboros cannot lower its own checks. Changes apply on the next task; every step a lower level lets through is recorded.
        </div>
        <div class="safety-levels">
            <div class="settings-effort-card">
                <label>${escapeHtml(SAFETY_KINDS.your_work)}</label>
                <input id="s-safety-mode" type="hidden" value="full">
                ${renderSegmentedField({ target: 's-safety-mode', title: LOWERING_TITLE, options: LEVEL_OPTIONS })}
                <div class="settings-inline-note" data-policy-state="supervisor" role="status" aria-live="polite"></div>
            </div>
            <div class="settings-effort-card" data-safety-consciousness-row>
                <label>${escapeHtml(SAFETY_KINDS.consciousness)}</label>
                <input id="s-consciousness-safety-mode" type="hidden" value="full">
                ${renderSegmentedField({ target: 's-consciousness-safety-mode', title: LOWERING_TITLE, options: LEVEL_OPTIONS })}
                <div class="settings-inline-note" data-policy-state="supervisor_consciousness" role="status" aria-live="polite"></div>
                <p class="safety-line" data-safety-check-fully-line hidden><button type="button" class="consciousness-inline-link ui-hit-area" data-safety-check-fully>Check consciousness fully</button></p>
            </div>
        </div>
        <p class="safety-line" data-safety-checker></p>
        <p class="safety-line" data-safety-second-check></p>
        <p class="safety-line" data-safety-unmeasured hidden>Not measured yet: no replay of real checks exists.</p>
        <div class="form-field ui-field">
            <label for="s-safety-rules">Your rules</label>
            <textarea id="s-safety-rules" class="ui-control consciousness-owner-words" rows="3" spellcheck="false" aria-describedby="s-safety-rules-help"></textarea>
            <div class="settings-inline-note ui-field-help" id="s-safety-rules-help">Rules the Safety Supervisor reads on every check. Rules for one place live in that place's notes.</div>
        </div>
        <div id="s-safety-skip-counter" class="settings-inline-note"></div>`;
}

/** The one in-page link to another Settings tab («Change in Models»); the section's binder opens the tab. */
export const settingsLinkHtml = (tab, label) => `<button type="button" class="consciousness-inline-link ui-hit-area" data-settings-goto="${escapeHtml(tab)}">${escapeHtml(label)}</button>`;

const levelLabel = (value) => safetyLevelOf(value)?.label || String(value || 'Unknown');
const modelName = (value) => parseModelSource(value).model || String(value || '');

/** «Checked by: <the Safety Supervisor model, or the Light model when empty>». */
export function checkerText(settings = {}) {
    const own = String(settings[SAFETY_MODEL_KEY] ?? '').trim();
    return `Checked by: ${own ? modelName(own) : 'the Light model'}`;
}

/** The second-check line from `policy_state.safety_recheck` and the Agents rows that name its row. */
export function secondCheckText(recheck, settings = {}) {
    if (!recheck.rowId) {
        return recheck.known && !recheck.eligibleRows.length
            ? 'Second check: Off. No Agents row can re-check yet: it needs an API model row with Packet delivery.'
            : 'Second check: Off';
    }
    return `Second check: ${agentRowHandle(recheck.rowId, settings)} re-checks flagged actions`;
}

/** An Agents row by the handle the roster shows (its route's model), else its stored id. */
export function agentRowHandle(rowId, settings = {}) {
    let items = [];
    try {
        const raw = settings.OUROBOROS_SUBAGENTS;
        const value = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
        items = Array.isArray(value?.items) ? value.items : [];
    } catch { items = []; }
    const row = items.find((item) => String(item?.subagent_id || '') === rowId);
    return row?.route?.target_id ? modelName(row.route.target_id) : rowId;
}

function paintLines(root, settings) {
    const meta = settings?._meta || {};
    const recheck = normalizeRecheck(meta.policy_state?.safety_recheck);
    const set = (selector, html) => { const node = root.querySelector(selector); if (node) node.innerHTML = html; };
    set('[data-safety-checker]', `${escapeHtml(checkerText(settings))} · ${settingsLinkHtml('models', 'Change in Models')}`);
    set('[data-safety-second-check]', `${escapeHtml(secondCheckText(recheck, settings))}${recheck.known
        ? ` · ${settingsLinkHtml('agents', 'Change in Agents')}` : ''}`);
    const unmeasured = root.querySelector('[data-safety-unmeasured]');
    if (unmeasured) unmeasured.hidden = !(recheck.rowId && !recheck.measured);
    syncRecheckState(recheck, root);
}

function syncCheckFully(root) {
    const line = root.querySelector('[data-safety-check-fully-line]');
    const input = root.querySelector('#s-consciousness-safety-mode');
    if (line && input) line.hidden = input.disabled || input.value === 'full';
}

/** Paint the section from a loaded settings document (values, facts, lines). */
export function applySafetySettings(root, settings = {}) {
    const yourWork = root.querySelector('#s-safety-mode');
    if (yourWork) yourWork.value = settings.OUROBOROS_SAFETY_MODE || 'full';
    const consciousness = root.querySelector('#s-consciousness-safety-mode');
    // A server that does not report the second level yet could only change "Your work" through it.
    const known = CONSCIOUSNESS_SAFETY_KEY in settings;
    if (consciousness) {
        consciousness.value = settings[CONSCIOUSNESS_SAFETY_KEY] || 'full';
        consciousness.disabled = !known;
        root.querySelectorAll('[data-effort-target="s-consciousness-safety-mode"] [data-effort-value]')
            .forEach((button) => { button.disabled = !known; });
        if (!known) {
            const note = root.querySelector('[data-policy-state="supervisor_consciousness"]');
            if (note) note.textContent = 'This server does not report a separate level for consciousness yet.';
        }
    }
    const rules = root.querySelector('#s-safety-rules');
    if (rules) {
        rules.value = String(settings[SAFETY_RULES_KEY] ?? '');
        rules.disabled = !(SAFETY_RULES_KEY in settings);
    }
    syncEffortSegments(root);
    paintLines(root, settings);
    syncCheckFully(root);
    void refreshSafetySkipCounter(root);
}

/**
 * The owner-only draft: both levels, the rules, the second-check row, and the Safety Supervisor model as the
 * Models editor collected it into the generic body (`body`), so one Save writes it through its owner endpoint.
 */
export function safetyOwnerDraft(root, body = {}) {
    return {
        yourWork: root.querySelector('#s-safety-mode')?.value || 'full',
        consciousness: root.querySelector('#s-consciousness-safety-mode')?.value || 'full',
        rules: root.querySelector('#s-safety-rules')?.value ?? null,
        recheck: recheckDraft(),
        model: SAFETY_MODEL_KEY in body ? String(body[SAFETY_MODEL_KEY] ?? '') : null,
        useLocal: typeof body.USE_LOCAL_SAFETY === 'boolean' ? body.USE_LOCAL_SAFETY : undefined,
    };
}

async function confirmLowering(kindLabel, current, next, askOwner) {
    const ok = await askOwner({
        title: 'Lower a safety level',
        body: `Lower the safety level for ${kindLabel.toLowerCase()} from ${levelLabel(current)} to ${levelLabel(next)}?\n\n`
            + 'Fixed rules still guard protected files at every level, and every step the lower level lets through is recorded.',
        confirmLabel: 'Lower the level',
        danger: true,
    });
    if (!ok) throw Object.assign(new Error('The change was not confirmed.'), { body: { saved: false } });
}

/**
 * Write each changed owner-only value through its endpoint, in order: the two levels (lowering asks first),
 * the rules, the Safety Supervisor model, the second-check row. Returns what was saved, what failed and
 * whether any outcome is unknown; one failure never stops the others.
 */
export async function saveSafetyOwnerChanges(draft, current = {}, { askOwner = openConfirmDialog } = {}) {
    const saved = [];
    const errors = [];
    let unknown = false;
    const run = async (label, step) => {
        try {
            const message = await step();
            if (message) saved.push(message);
        } catch (error) {
            const failure = settingsWriteFailure(error, label);
            errors.push(failure.text);
            unknown ||= failure.unknown;
        }
    };
    for (const [kind, next, key] of [['your_work', draft.yourWork, 'OUROBOROS_SAFETY_MODE'],
        ['consciousness', draft.consciousness, CONSCIOUSNESS_SAFETY_KEY]]) {
        if (kind === 'consciousness' && !(key in current)) continue;
        const now = current[key] || 'full';
        if (!next || next === now) continue;
        const kindLabel = SAFETY_KINDS[kind];
        await run(`Safety for ${kindLabel.toLowerCase()}`, async () => {
            if ((SAFETY_RANK[next] ?? 2) < (SAFETY_RANK[now] ?? 2)) await confirmLowering(kindLabel, now, next, askOwner);
            await saveSafetyLevel(next, kind);
            return `Safety for ${kindLabel.toLowerCase()} saved as ${levelLabel(next)}.`;
        });
    }
    if (draft.rules !== null && SAFETY_RULES_KEY in current && draft.rules !== String(current[SAFETY_RULES_KEY] ?? '')) {
        await run('Your rules', async () => { await saveSafetyRules(draft.rules); return 'Your rules saved.'; });
    }
    const localChanged = typeof draft.useLocal === 'boolean'
        && draft.useLocal !== ['true', true].includes(current.USE_LOCAL_SAFETY);
    if (draft.model !== null && SAFETY_MODEL_KEY in current
            && (draft.model !== String(current[SAFETY_MODEL_KEY] ?? '') || localChanged)) {
        await run('The Safety Supervisor model', async () => {
            await saveSafetyModel(draft.model, draft.useLocal);
            return draft.model ? `Safety Supervisor model saved as ${modelName(draft.model)}.` : 'Safety Supervisor uses the Light model.';
        });
    }
    if (draft.recheck !== null && draft.recheck !== recheckSaved()) {
        await run('The second check', async () => {
            await saveSafetyRecheck(draft.recheck);
            return draft.recheck ? 'Second check saved.' : 'Second check turned off.';
        });
    }
    return { saved: saved.join(' '), error: errors.join(' '), unknown };
}

/** Waved-through checks among the inspected recent events (the Light/Off audit), counted within 24 h. */
export async function refreshSafetySkipCounter(root, { logsTail = apiClient.logsTail, now = Date.now() } = {}) {
    const el = root?.querySelector?.('#s-safety-skip-counter');
    if (!el) return;
    try {
        const data = await logsTail('events', 2000);
        const cutoff = now - 24 * 3600 * 1000;
        const n = (data?.entries || []).filter((entry) => {
            if (String(entry?.type || '') !== 'safety_mode_skip') return false;
            const time = Date.parse(String(entry?.ts || ''));
            return Number.isFinite(time) && time >= cutoff;
        }).length;
        // The tail may cover less than a day, including when it has no matches.
        el.textContent = n > 0
            ? `${n} safety check(s) waved through among inspected recent events dated within 24h.`
            : 'No waved-through safety checks found among inspected recent events dated within 24h.';
    } catch {
        el.textContent = '';
    }
}

/**
 * Bind the section once: "Check consciousness fully" raises only that row to Full at once through the owner
 * endpoint (raising never asks), the in-page links open the tab they name, and the Agents rows' second-check
 * marks keep their one-row rule.
 */
export function bindSafetySettings(root, { save = saveSafetyLevel } = {}) {
    const section = root.querySelector('[data-safety-consciousness-row]')?.closest('.form-section') || root;
    const onClick = async (event) => {
        const goto = event.target.closest?.('[data-settings-goto]');
        if (goto && section.contains(goto)) { root.activateSettingsTab?.(goto.dataset.settingsGoto); return; }
        if (event.target.closest?.('[data-effort-target="s-consciousness-safety-mode"]')) {
            queueMicrotask(() => syncCheckFully(root));
            return;
        }
        const button = event.target.closest?.('[data-safety-check-fully]');
        if (!button || button.disabled) return;
        const note = root.querySelector('[data-policy-state="supervisor_consciousness"]');
        button.disabled = true;
        try {
            await save('full', 'consciousness');
            const input = root.querySelector('#s-consciousness-safety-mode');
            if (input) input.value = 'full';
            syncEffortSegments(root);
            syncCheckFully(root);
            globalThis.window?.dispatchEvent?.(new CustomEvent('ouro:settings-updated', { detail: { reason: 'consciousness checked fully', source: 'safety' } }));
        } catch (error) {
            if (note) note.textContent = settingsWriteFailure(error, 'Safety for consciousness').text;
        } finally {
            button.disabled = false;
        }
    };
    section.addEventListener('click', onClick);
    const disposeMarks = bindRecheckMarks(root);
    return () => { section.removeEventListener('click', onClick); disposeMarks(); };
}
