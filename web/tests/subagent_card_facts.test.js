import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import { coordinatorRouteClause, formatCoordinatorProvenance, executorIdentityMarkup } from '../modules/harness_presentation.js';
import { executorChip } from '../modules/log_events.js';

// Python asserts these facts against subagent_message_meta's actual output.
const cases = JSON.parse(readFileSync(new URL('../../tests/fixtures/subagent_card_facts.json', import.meta.url), 'utf8'));
for (const row of cases) {
    test(`producer frame: ${row.name}`, (t) => {
        const priorDocument = globalThis.document;
        globalThis.document = { createElement: () => ({ set textContent(value) {
            this.innerHTML = String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
        } }) };
        t.after(() => { globalThis.document = priorDocument; });
        const frame = { subagent_task_id: 'child', delegation_role: 'subagent', subagent_event: 'running', ...row.facts };
        const chip = executorChip(frame);
        assert.equal(formatCoordinatorProvenance(frame), row.provenance);
        assert.equal(coordinatorRouteClause(frame), row.clause);
        assert.ok(chip.title.includes(row.clause));
        assert.equal(chip.coordinatorProvenance || '', row.provenance);
        const html = executorIdentityMarkup(chip, { agentModel: frame.model, coordinatorProvenance: chip.coordinatorProvenance });
        assert.ok(html.includes(row.clause));
        assert.ok(html.includes('Coordinator:'));
    });
}

test('the chip renders supplied billing and never prices or reclassifies the route', () => {
    for (const model of ['claudexor::codex=gpt-5', 'local-model (local)', 'openai/gpt-5']) {
        assert.match(coordinatorRouteClause({ model, cost_usd: .5 }), /bills as unknown/);
        assert.match(coordinatorRouteClause({ model, coordinator_billing: 'measured' }), /bills as measured/);
    }
    assert.equal(formatCoordinatorProvenance({ model: 'm', effective_model_lane: 'fallback' }), '');
    assert.equal(formatCoordinatorProvenance({ model: 'm', parent_cognitive_route: { model: 'm', source_role: 'fallback' } }), "parent's fallback");
});
