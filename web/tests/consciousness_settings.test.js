// The owner's consciousness, places and safety surfaces in Settings, read against the contract's shapes
// (fixtures/consciousness_contract.json): the words, the one client module, the Safety Supervisor section and
// its owner-only saves, the Agents second-check mark and the Consciousness section.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

import {
    AUTONOMY_LEVELS, PLACE_STATES, SAFETY_LEVELS, SILENT_CARD, durationText, placeStatusText, usdText, wakesForText,
} from '../modules/consciousness_words.js';
import {
    connectPlace, normalizeConsciousness, normalizePlacesResponse, recheckFromSettings, saveSafetyLevel, saveSafetyModel,
    saveSafetyRecheck, saveSafetyRules, updatePlace, disconnectPlace,
} from '../modules/consciousness_api.js';
import {
    agentRowHandle, checkerText, safetyOwnerDraft, safetySectionHtml, saveSafetyOwnerChanges, secondCheckText,
} from '../modules/settings_safety.js';
import { chooseRecheckRow, recheckDraft, recheckMarkHtml, syncRecheckState } from '../modules/safety_recheck.js';
import { consciousnessModelText, consciousnessSectionHtml, settingsPlacesHtml } from '../modules/settings_consciousness.js';
import { parseAvailableSubagentsSetting, buildAvailableSubagentsSetting } from '../modules/subagents_settings.js';

const FIXTURE = JSON.parse(fs.readFileSync(new URL('./fixtures/consciousness_contract.json', import.meta.url), 'utf8'));

/** Record every request the client sends and answer from `reply(url, body)`. */
function stubFetch(reply) {
    const calls = [];
    const previous = globalThis.fetch;
    globalThis.fetch = async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : null;
        calls.push({ url: String(url), method: init.method || 'GET', body });
        const answer = reply(String(url), body, init);
        return { ok: answer.status ? answer.status < 400 : true, status: answer.status || 200, json: async () => answer.json ?? answer };
    };
    return { calls, restore: () => { globalThis.fetch = previous; } };
}

test('the owner names stand with their notes; stored values never change', () => {
    assert.deepEqual(AUTONOMY_LEVELS.map((level) => [level.value, level.label]), [['observe', 'Advises'], ['act', 'Acts'], ['full', 'Evolves']]);
    assert.equal(AUTONOMY_LEVELS[0].note, 'On its own it studies, keeps its memory and tells you; it changes nothing outside.');
    assert.equal(AUTONOMY_LEVELS[1].note, 'Also acts on its own: starts work, runs commands, speaks and acts in places. It does not change itself.');
    assert.equal(AUTONOMY_LEVELS[2].note, 'Also changes itself: its own code, its settings, connecting new places.');
    assert.deepEqual(PLACE_STATES.map((state) => [state.value, state.label]), [['active', 'Active'], ['silent', 'Silent'], ['paused', 'Paused']]);
    assert.equal(SILENT_CARD, "Writes through this connector's declared tools and delivery queue are blocked. Scripts, browser actions and unintegrated code may still write.");
    assert.deepEqual(SAFETY_LEVELS.map((level) => level.label), ['Off', 'Light', 'Full']);
    assert.equal(SAFETY_LEVELS[1].note, 'A second model checks steps that reach other people and services: messages, posts, skills, connectors, starting work. Not shell commands.');
});

test('a place row says its state, what wakes it and what waits; absent money is the dash', () => {
    const { places } = normalizePlacesResponse(FIXTURE.places);
    assert.equal(placeStatusText(places[0]), 'active · wakes for direct messages, mentions and replies · 2 unanswered');
    assert.equal(placeStatusText(places[1]), 'silent', 'a Silent place is not woken by its list');
    assert.equal(placeStatusText({ state: 'gone' }), 'state unknown');
    assert.equal(wakesForText([]), '');
    assert.equal(usdText(null), '—');
    assert.equal(usdText(0), '$0.00');
    assert.equal(usdText(0.88), '$0.88');
    assert.equal(durationText('2026-10-20T11:51:00Z', '2026-10-20T11:51:40Z'), '40 s');
    assert.equal(durationText('', '2026-10-20T11:51:40Z'), '');
});

test('the client reads the contract shapes once: places, connectors, the snapshot and its wakes', () => {
    const { places, connectors } = normalizePlacesResponse(FIXTURE.places);
    assert.equal(places.length, 3);
    assert.deepEqual(places[0].wakes.map((item) => item.author), ['connector', 'connector', 'owner']);
    assert.equal(places[0].notes[0].id, 'n1');
    assert.equal(places[0].ownerAccounts[0].label, '@anton.r');
    assert.equal(places[1].icon.name, 'chat');
    assert.equal(places[2].icon, null);
    assert.equal(places[1].spent24hUsd, null, 'an unknown spend stays unknown');
    assert.equal(places[2].spent24hUsd, 0, 'a real zero is a fact');
    assert.deepEqual(connectors.map((entry) => [entry.connector, entry.connected]), [['slack-bridge', true], ['agentrq-bridge', false]]);

    const state = normalizeConsciousness(FIXTURE.state.bg_consciousness_state, { enabled: FIXTURE.state.bg_consciousness_enabled });
    assert.equal(state.enabled, true);
    assert.equal(state.spendByCause[2].unmeteredCalls, 3);
    assert.equal(state.countedRoots[0].causeLabel, 'Slack · Acme');
    assert.equal(state.placesBrief.length, 2);
    assert.equal(state.recentWakes, null, '/api/state carries no wakes');

    const full = normalizeConsciousness(FIXTURE.consciousness);
    assert.equal(full.recentWakes.length, 4);
    assert.deepEqual(full.recentWakes[2].checks.map((check) => check.chip), ['checked', 'sent_despite']);
    assert.equal(full.recentWakes[3].costUsd, null);
    assert.equal(normalizeConsciousness({}).enabled, null, 'an absent control is unknown, never off');
});

test('every write sends exactly the contract keys and announces the confirmed place', async () => {
    const place = FIXTURE.places.places[0];
    const stub = stubFetch((url) => (url.startsWith('/api/places') ? { ok: true, place } : { ok: true }));
    try {
        assert.equal((await connectPlace({ connector: 'agentrq-bridge' })).id, 'slack-acme');
        await updatePlace('slack acme', { state: 'silent' });
        await disconnectPlace('slack-acme');
        await saveSafetyLevel('light');
        await saveSafetyLevel('full', 'consciousness');
        await saveSafetyRules('No posts from my folders.');
        await saveSafetyModel('', false);
        await saveSafetyRecheck('', FIXTURE.settings);
    } finally { stub.restore(); }
    assert.deepEqual(stub.calls.map(({ url, method, body }) => [method, url, body]), [
        ['POST', '/api/places', { connector: 'agentrq-bridge' }],
        ['POST', '/api/places/slack%20acme', { state: 'silent' }],
        ['DELETE', '/api/places/slack-acme', null],
        ['POST', '/api/owner/safety-mode', { mode: 'light' }],
        ['POST', '/api/owner/safety-mode', { mode: 'full', kind: 'consciousness' }],
        ['POST', '/api/owner/safety-rules', { rules: 'No posts from my folders.' }],
        ['POST', '/api/owner/safety-model', { settings: { OUROBOROS_MODEL_SAFETY: '' } }],
        ['POST', '/api/owner/safety-model', { settings: { OUROBOROS_SUBAGENTS: { ...FIXTURE.settings.OUROBOROS_SUBAGENTS,
            items: FIXTURE.settings.OUROBOROS_SUBAGENTS.items.map((item) => ({ ...item, rechecks_flags: false })) } } }],
    ]);
});

test('a refused write says the server\'s words and saves nothing in the browser', async () => {
    const stub = stubFetch(() => ({ status: 409, json: { ok: false, error: 'Place changed since you opened it.' } }));
    try {
        await assert.rejects(updatePlace('slack-acme', { state: 'paused' }), /Place changed since you opened it/);
    } finally { stub.restore(); }
});

test('Safety Supervisor: two rows of Off · Light · Full, the short copy, the rules and the honesty lines', () => {
    const html = safetySectionHtml();
    assert.match(html, /A second model judges a step before it runs\. Your work: what you asked for\. Consciousness: what it does on its own, places included\./);
    assert.match(html, /<label>Your work<\/label>\s*<input id="s-safety-mode" type="hidden"/);
    assert.match(html, /<label>Consciousness<\/label>\s*<input id="s-consciousness-safety-mode" type="hidden"/);
    const order = [...html.matchAll(/data-effort-value="(\w+)"/g)].map((match) => match[1]);
    assert.deepEqual(order, ['off', 'light', 'full', 'off', 'light', 'full']);
    assert.match(html, /data-policy-state="supervisor_consciousness"/);
    assert.match(html, />Check consciousness fully</);
    assert.match(html, /Not measured yet: no replay of real checks exists\./);
    assert.match(html, /Rules the Safety Supervisor reads on every check\. Rules for one place live in that place's notes\./);
    assert.match(html, /outside Cyber Pro, Ouroboros cannot lower its own checks/);
    assert.match(html, /id="s-safety-skip-counter"/);
});

test('the checker and second-check lines name what really checks', () => {
    const settings = FIXTURE.settings;
    assert.equal(checkerText(settings), 'Checked by: the Light model');
    assert.equal(checkerText({ ...settings, OUROBOROS_MODEL_SAFETY: 'anthropic::claude-opus-5.5' }), 'Checked by: claude-opus-5.5');
    const recheck = recheckFromSettings(settings);
    assert.equal(agentRowHandle('packet_checker', settings), 'gpt-5.6');
    assert.equal(secondCheckText(recheck, settings), 'Second check: gpt-5.6 re-checks flagged actions');
    const unmarked = { enabled: true, items: settings.OUROBOROS_SUBAGENTS.items.map((item) => ({ ...item, rechecks_flags: false })) };
    assert.equal(secondCheckText(recheckFromSettings({ OUROBOROS_SUBAGENTS: unmarked }), settings), 'Second check: Off');
    assert.match(secondCheckText(recheckFromSettings({ OUROBOROS_SUBAGENTS: { enabled: true, items: [] } }), settings), /^Second check: Off\. No Agents row can re-check yet/);
    assert.equal(secondCheckText(recheckFromSettings({}), settings), 'Second check: Off', 'an unreadable roster says nothing more');
});

function draftRoot(values) {
    const node = (value) => ({ value });
    return { querySelector: (selector) => ({ '#s-safety-mode': node(values.yourWork), '#s-consciousness-safety-mode': node(values.consciousness),
        '#s-safety-rules': node(values.rules) }[selector] || null) };
}

test('Save writes only what changed, each through its owner endpoint; lowering asks first', async () => {
    const settings = { ...FIXTURE.settings, OUROBOROS_SAFETY_MODE: 'full', OUROBOROS_CONSCIOUSNESS_SAFETY_MODE: 'full' };
    syncRecheckState(recheckFromSettings(settings), null);
    const stub = stubFetch(() => ({ ok: true }));
    const asked = [];
    let result;
    try {
        const draft = safetyOwnerDraft(draftRoot({ yourWork: 'light', consciousness: 'full', rules: settings.OUROBOROS_SAFETY_OWNER_RULES }),
            { OUROBOROS_MODEL_SAFETY: 'anthropic::claude-opus-5.5' });
        result = await saveSafetyOwnerChanges(draft, settings, { askOwner: async (dialog) => { asked.push(dialog.title); return true; } });
    } finally { stub.restore(); }
    assert.deepEqual(asked, ['Lower a safety level']);
    assert.deepEqual(stub.calls.map(({ url, body }) => [url, body]), [
        ['/api/owner/safety-mode', { mode: 'light' }],
        ['/api/owner/safety-model', { settings: { OUROBOROS_MODEL_SAFETY: 'anthropic::claude-opus-5.5' } }],
    ]);
    assert.equal(result.error, '');
    assert.match(result.saved, /Safety for your work saved as Light\. Safety Supervisor model saved as claude-opus-5\.5\./);
});

test('a refused lowering keeps the level and still saves the rest; an unknown server key is never written', async () => {
    const settings = { OUROBOROS_SAFETY_MODE: 'full', OUROBOROS_SAFETY_OWNER_RULES: '' };
    const stub = stubFetch(() => ({ ok: true }));
    let result;
    try {
        const draft = { yourWork: 'off', consciousness: 'off', rules: 'Ask before paying.', recheck: null, model: 'x', useLocal: undefined };
        result = await saveSafetyOwnerChanges(draft, settings, { askOwner: async () => false });
    } finally { stub.restore(); }
    // No OUROBOROS_CONSCIOUSNESS_SAFETY_MODE / OUROBOROS_MODEL_SAFETY in the document: those rows are not written.
    assert.deepEqual(stub.calls.map(({ url }) => url), ['/api/owner/safety-rules']);
    assert.match(result.error, /Safety for your work was not changed: The change was not confirmed\./);
    assert.equal(result.unknown, false);
});

test('the second-check mark shows only on eligible rows, one row at a time, and saves as the owner chose', async () => {
    const packet = (id, marked = false) => ({ subagent_id: id, route: { kind: 'api_model', target_id: 'openai::gpt-5.6' }, delivery: 'packet', rechecks_flags: marked });
    const roster = { enabled: true, items: [packet('a', true), packet('b')] };
    syncRecheckState(recheckFromSettings({ OUROBOROS_SUBAGENTS: roster }), null);
    assert.match(recheckMarkHtml({ subagent_id: 'a', _uiKey: 'k1' }, 1), /checked> Re-checks flagged actions/);
    assert.match(recheckMarkHtml({ subagent_id: 'b' }, 2), /data-recheck-row="b"><input/);
    assert.doesNotMatch(recheckMarkHtml({ subagent_id: 'b' }, 2), /checked>/);
    assert.match(recheckMarkHtml({ subagent_id: 'c' }, 3), /data-recheck-row="c" hidden>/);
    assert.match(recheckMarkHtml({ subagent_id: 'a', _uiKey: 'k1' }, 1), /id="s-recheck-k1"/, 'its id joins the Settings draft');
    assert.equal(recheckDraft(), null, 'untouched');
    chooseRecheckRow('b', true, null);
    assert.equal(recheckDraft(), 'b');
    assert.doesNotMatch(recheckMarkHtml({ subagent_id: 'a' }, 1), /checked>/, 'one row at a time');
    chooseRecheckRow('b', false, null);
    assert.equal(recheckDraft(), '', 'unticked: no row re-checks');
    const stub = stubFetch(() => ({ ok: true }));
    try {
        const result = await saveSafetyOwnerChanges({ yourWork: 'full', consciousness: 'full', rules: null, recheck: recheckDraft(), model: null }, { OUROBOROS_SUBAGENTS: roster });
        assert.equal(result.saved, 'Second check turned off.');
    } finally { stub.restore(); }
    assert.deepEqual(stub.calls.map(({ url, body }) => [url, body]), [['/api/owner/safety-model', { settings: { OUROBOROS_SUBAGENTS: {
        enabled: true, items: [packet('a'), packet('b')] } } }]]);
});

test('the roster keeps the owner\'s second-check mark exactly as loaded and refuses a malformed one', () => {
    const parsed = parseAvailableSubagentsSetting(FIXTURE.settings.OUROBOROS_SUBAGENTS);
    assert.equal(parsed.error, '');
    assert.equal(buildAvailableSubagentsSetting(parsed.setting).items[0].rechecks_flags, true);
    const unmarked = parseAvailableSubagentsSetting({ enabled: true, items: [{ ...FIXTURE.settings.OUROBOROS_SUBAGENTS.items[0], rechecks_flags: undefined }] });
    assert.equal('rechecks_flags' in buildAvailableSubagentsSetting(unmarked.setting).items[0], false, 'an unmarked row writes no new key');
    const bad = parseAvailableSubagentsSetting({ enabled: true, items: [{ ...FIXTURE.settings.OUROBOROS_SUBAGENTS.items[0], rechecks_flags: 'yes' }] });
    assert.match(bad.error, /second-check mark must be true or false/);
});

test('Consciousness: Advises · Acts · Evolves with notes, the allowance and task copy, the moved fields keep their ids', () => {
    const html = consciousnessSectionHtml();
    assert.match(html, /What Ouroboros does when nobody asked: on its own clock, and in the places you connected\./);
    assert.deepEqual([...html.matchAll(/data-effort-value="(\w+)">(\w+)</g)].map((m) => [m[1], m[2]]), [['observe', 'Advises'], ['act', 'Acts'], ['full', 'Evolves']]);
    assert.match(html, /<strong>Acts<\/strong> &mdash; Also acts on its own/);
    assert.match(html, />Daily allowance \(USD\)</);
    assert.match(html, /Spending cap over a rolling 24 hours: its own wakes, wakes in places, and the work they start\. Settled dollars only; a subscription shows as unmetered\./);
    assert.match(html, />Max concurrent tasks</);
    assert.match(html, /How many of its own tasks may run at once\. Work you asked for never counts\./);
    for (const id of ['s-consciousness-autonomy', 's-consciousness-daily-usd', 's-consciousness-max-tasks', 's-bg-wakeup-min', 's-bg-wakeup-max', 's-presence-max-active']) {
        assert.equal(html.split(`id="${id}"`).length, 2, `${id} is rendered once`);
    }
    assert.match(html, /<details class="consciousness-more"[^>]*>\s*<summary>.*More<\/summary>/s);
    assert.match(html, />Concurrent conversations</);
    assert.match(html, />Connect a place</);
    assert.equal(consciousnessModelText({}), 'Uses Main');
    assert.equal(consciousnessModelText({ OUROBOROS_MODEL_CONSCIOUSNESS: 'openai::gpt-5.6' }), 'gpt-5.6');
});

test('the Settings places list: icon, label, state word, unanswered count; each row opens its sheet', () => {
    const { places } = normalizePlacesResponse(FIXTURE.places);
    const html = settingsPlacesHtml({ places });
    assert.equal((html.match(/data-place-open=/g) || []).length, 3);
    assert.match(html, /<span class="consciousness-place-name">Slack · Acme<\/span>\s*<span class="consciousness-place-facts">active · 2 unanswered<\/span>/);
    assert.match(html, /aria-label="Open Mail · inbox: paused"/);
    assert.match(settingsPlacesHtml({ places: [] }), /No place yet\. Connect one/);
    assert.match(settingsPlacesHtml({ error: 'Places could not be read: HTTP 404' }), /data-tone="warn"/);
});
