// The one browser client for consciousness, places and the owner's safety choices (impl_plan
// API_CONTRACT_v1 §1-§4). Every read and owner write of these surfaces goes through here, and every
// JSON shape is read in one place: a field the server renames is one fix in this file. Readers are
// tolerant (unknown extra keys are fine; a missing field stays absent, never a guessed zero); writers
// send exactly the contract's request keys.
import { fetchJson, jsonPost } from './api_client.js';

/** Raised on window after a place write the server confirmed: `{place}` or `{placeId, removed: true}`. */
export const PLACES_CHANGED_EVENT = 'ouro:places-changed';

const text = (value) => (value === null || value === undefined ? '' : String(value));
const list = (value) => (Array.isArray(value) ? value : []);
const object = (value) => (value && typeof value === 'object' && !Array.isArray(value) ? value : null);
const count = (value) => (Number.isInteger(Number(value)) && value !== null && value !== '' ? Number(value) : null);
const amount = (value) => {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
};

/** `{name?, svg?}` or null: the connector's icon as the host projected it (Lane D sanitizes the geometry). */
export function normalizeIcon(raw) {
    if (typeof raw === 'string') return raw ? { name: raw, svg: '' } : null;
    const icon = object(raw);
    if (!icon) return null;
    const name = text(icon.name);
    const svg = text(icon.svg);
    return name || svg ? { name, svg } : null;
}

/** One PlaceSummary (contract §2) in the browser's names. */
export function normalizePlace(raw) {
    const place = object(raw) || {};
    const connector = text(place.connector);
    const connectorLabel = text(place.connector_label) || connector;
    const status = object(place.status);
    return {
        id: text(place.place_id),
        connector,
        connectorLabel,
        provider: text(place.provider),
        accountId: text(place.account_id),
        conversationId: text(place.conversation_id),
        scope: text(place.scope),
        label: text(place.label) || connectorLabel || text(place.place_id),
        state: text(place.state),
        destination: text(place.destination),
        icon: normalizeIcon(place.icon),
        wakes: list(place.wakes).map((item) => ({ fact: text(item?.fact), author: text(item?.author) }))
            .filter((item) => item.fact),
        wakeSuggestions: [...new Set(list(place.wake_suggestions).map(text).filter(Boolean))],
        notes: list(place.notes).map((note) => ({
            id: text(note?.note_id), text: text(note?.text), author: text(note?.author), at: text(note?.at),
        })).filter((note) => note.text),
        ownerAccounts: list(place.owner_accounts).map((account) => ({
            actorId: text(account?.platform_actor_id), label: text(account?.label), confirmedAt: text(account?.confirmed_at),
        })).filter((account) => account.actorId),
        // People the place has seen, offered for «This is me» when the server lists them (not in contract v1).
        accountCandidates: list(place.account_candidates).map((account) => ({
            actorId: text(account?.platform_actor_id), label: text(account?.label || account?.display_name),
        })).filter((account) => account.actorId),
        workingFolder: text(place.working_folder),
        model: text(place.model),
        status: status && text(status.text) ? { text: text(status.text), tone: text(status.tone) || 'muted' } : null,
        unanswered: count(place.unanswered),
        lastActivityAt: text(place.last_activity_at),
        spent24hUsd: amount(place.spent_24h_usd),
    };
}

/** An installed connector with a valid place declaration (`GET /api/places` `connectors`). */
export function normalizeConnector(raw) {
    const connector = object(raw) || {};
    const name = text(connector.connector);
    return {
        connector: name,
        label: text(connector.connector_label) || name,
        icon: normalizeIcon(connector.icon),
        destination: text(connector.destination),
        wakes: [...new Set(list(connector.wakes).map((item) => text(object(item) ? item.fact : item)).filter(Boolean))],
        connected: connector.connected === true,
    };
}

export function normalizePlacesResponse(raw) {
    const data = object(raw) || {};
    return {
        places: list(data.places).map(normalizePlace).filter((place) => place.id),
        connectors: list(data.connectors).map(normalizeConnector).filter((connector) => connector.connector),
    };
}

/** One recent wake (contract §1), newest first as the server orders them. */
export function normalizeWake(raw) {
    const wake = object(raw) || {};
    return {
        taskId: text(wake.task_id),
        cause: text(wake.cause),
        placeId: text(wake.place_id),
        placeLabel: text(wake.place_label),
        startedAt: text(wake.started_at),
        firstReplyAt: text(wake.first_reply_at),
        finishedAt: text(wake.finished_at),
        outcome: text(wake.outcome),
        costUsd: amount(wake.accounted_upper_bound_usd),  // an accounted upper bound, not settled spend
        unmetered: wake.unmetered === true,
        checks: list(wake.checks).map((check) => ({ chip: text(check?.chip), tool: text(check?.tool) }))
            .filter((check) => check.chip),
        summary: text(wake.summary),
    };
}

/**
 * The consciousness snapshot: `/api/state`'s `bg_consciousness_state` (plus the separate `enabled` it
 * carries), or `GET /api/consciousness`, which adds `places` and `recent_wakes`. Missing facts stay null.
 */
export function normalizeConsciousness(raw, { enabled } = {}) {
    const top = object(raw) || {};
    const nested = object(top.bg_consciousness_state);
    const bg = nested ? { ...nested, ...top } : top;
    const known = typeof enabled === 'boolean' ? enabled : typeof bg.enabled === 'boolean' ? bg.enabled : null;
    return {
        enabled: known,
        status: text(bg.status),
        detail: text(bg.detail),
        level: text(bg.level),
        nextWakeAt: text(bg.next_wake_at),
        lastWakeAt: text(bg.last_wake_at),
        lastWakeOutcome: text(bg.last_wake_outcome),
        liveWakeTaskId: text(bg.live_wake_task_id),
        spentUsd: amount(bg.spent_24h_usd),
        dailyUsd: amount(bg.daily_usd),
        unknownUnmetered: count(bg.unknown_unmetered) || 0,
        integrityDegraded: bg.integrity_degraded === true,
        allowanceResetsAt: text(bg.allowance_resets_at),
        tasksRunning: count(bg.tasks_running),
        maxTasks: count(bg.max_tasks),
        spendByCause: list(bg.spend_by_cause).map((row) => ({
            cause: text(row?.cause), label: text(row?.label), usd: amount(row?.usd), unmeteredCalls: count(row?.unmetered_calls) || 0,
        })).filter((row) => row.cause),
        countedRoots: list(bg.counted_roots).map((row) => ({
            taskId: text(row?.task_id), title: text(row?.title), cause: text(row?.cause), causeLabel: text(row?.cause_label),
        })).filter((row) => row.taskId),
        placesBrief: list(bg.places_brief).map((row) => ({
            id: text(row?.place_id), label: text(row?.label), state: text(row?.state), unanswered: count(row?.unanswered),
        })).filter((row) => row.id),
        places: Array.isArray(bg.places) ? bg.places.map(normalizePlace).filter((place) => place.id) : null,
        recentWakes: Array.isArray(bg.recent_wakes) ? bg.recent_wakes.map(normalizeWake).slice(0, 50) : null,
    };
}

function announce(detail) {
    globalThis.window?.dispatchEvent?.(new CustomEvent(PLACES_CHANGED_EVENT, { detail }));
}

// ---- reads ---------------------------------------------------------------------------------------
export async function readConsciousness(init = {}) {
    return normalizeConsciousness(await fetchJson('/api/consciousness', { cache: 'no-store', ...init }));
}

/** The status the Dashboard falls back to when the full snapshot cannot be read: `/api/state`. */
export async function readConsciousnessFromState(init = {}) {
    const data = await fetchJson('/api/state', { cache: 'no-store', ...init });
    if (!object(data?.bg_consciousness_state) && typeof data?.bg_consciousness_enabled !== 'boolean') {
        throw new Error('Consciousness state unavailable');
    }
    return normalizeConsciousness(data?.bg_consciousness_state || {}, { enabled: data?.bg_consciousness_enabled });
}

export async function readPlaces(init = {}) {
    return normalizePlacesResponse(await fetchJson('/api/places', { cache: 'no-store', ...init }));
}

// ---- place writes (owner-authored on the server) ----------------------------------------------------
function placeAnswer(data) {
    if (!data || data.ok !== true || !object(data.place)) {
        throw Object.assign(new Error(text(data?.error) || 'The place was not saved.'), { body: data });
    }
    const place = normalizePlace(data.place);
    announce({ place });
    return place;
}

/** Connect a place from an installed connector's declaration; no id is typed. */
export async function connectPlace({ connector, accountId = '', conversationId = '' }) {
    const body = { connector };
    if (accountId) body.account_id = accountId;
    if (conversationId) body.conversation_id = conversationId;
    return placeAnswer(await jsonPost('/api/places', body));
}

/**
 * One owner change to a place. `change` uses the contract's keys: `state`, `wakes` (the whole fact list),
 * `add_note`, `remove_note`, `working_folder`, `model`, `confirm_owner_account`, `revoke_owner_account`.
 */
export async function updatePlace(placeId, change) {
    return placeAnswer(await jsonPost(`/api/places/${encodeURIComponent(placeId)}`, change));
}

export async function disconnectPlace(placeId) {
    const data = await fetchJson(`/api/places/${encodeURIComponent(placeId)}`, { method: 'DELETE' });
    if (data?.ok !== true) throw Object.assign(new Error(text(data?.error) || 'The place was not disconnected.'), { body: data });
    announce({ placeId, removed: true });
    return true;
}

// ---- owner safety writes ------------------------------------------------------------------------------
function ownerAnswer(data, what) {
    if (!data || data.ok !== true) {
        throw Object.assign(new Error(text(data?.error) || `${what} was not saved.`), { body: data });
    }
    return data;
}

/** A safety level for one kind (`your_work`, the frozen request without `kind`, or `consciousness`). */
export async function saveSafetyLevel(level, kind = 'your_work') {
    const body = kind === 'consciousness' ? { mode: level, kind } : { mode: level };
    return ownerAnswer(await jsonPost('/api/owner/safety-mode', body), 'The safety level');
}

export async function saveSafetyRules(rules) {
    return ownerAnswer(await jsonPost('/api/owner/safety-rules', { rules: String(rules ?? '') }), 'Your rules');
}

/** One owner transaction for the resolved checker: the Safety Supervisor model and/or the Agents roster. */
async function saveCheckerSettings(settings, what) {
    return ownerAnswer(await jsonPost('/api/owner/safety-model', { settings }), what);
}

/** The Safety Supervisor model; empty inherits the Light model. A local model carries the ` (local)` label. */
export async function saveSafetyModel(model, useLocal = undefined) {
    let value = String(model ?? '').trim();
    if (useLocal === false) value = value.replace(/ \(local\)$/, '');
    if (value && useLocal === true && !value.endsWith(' (local)')) value = `${value} (local)`;
    return saveCheckerSettings({ OUROBOROS_MODEL_SAFETY: value }, 'The Safety Supervisor model');
}

/** The Agents roster as saved (`OUROBOROS_SUBAGENTS`, a JSON string or object), or null when unreadable. */
export function parseRoster(raw) {
    try {
        const value = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
        return object(value) && Array.isArray(value.items) ? value : null;
    } catch { return null; }
}

/** Mark one Agents row (or none, with '') as the row that re-checks flagged actions, in the saved roster. */
export async function saveSafetyRecheck(rowId, settings = {}) {
    const roster = parseRoster(settings.OUROBOROS_SUBAGENTS);
    if (!roster) throw new Error('The Agents roster could not be read, so the second check was not saved.');
    const items = roster.items.map((item) => ({ ...item, rechecks_flags: Boolean(rowId) && text(item?.subagent_id) === rowId }));
    return saveCheckerSettings({ OUROBOROS_SUBAGENTS: { ...roster, items } }, 'The second check');
}

/** The second-check facts read from the saved roster: the marked row, the rows that may be marked
 *  (an enabled API model row with Packet delivery) and whether a replay measured it (never, yet). */
export function recheckFromSettings(settings = {}) {
    const roster = parseRoster(settings.OUROBOROS_SUBAGENTS);
    if (!roster) return { known: false, rowId: '', eligibleRows: [], measured: false };
    const items = roster.items.filter(object);
    const eligible = items.filter((item) => text(item.route?.kind).toLowerCase() === 'api_model'
        && text(item.delivery || 'native').toLowerCase() === 'packet' && item.enabled !== false);
    const marked = items.find((item) => item.rechecks_flags === true);
    return {
        known: true,
        rowId: marked ? text(marked.subagent_id) : '',
        eligibleRows: [...new Set(eligible.map((item) => text(item.subagent_id)).filter(Boolean))],
        measured: false,
    };
}
