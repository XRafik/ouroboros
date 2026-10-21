import assert from 'node:assert/strict';
import test from 'node:test';
import { createChatInstance } from '../modules/chat.js';
import { cardRowSummary } from '../modules/chat_activity.js';
import { mergeHistoricalTimelineItem } from '../modules/chat_history_replay.js';
import { updateLiveTimelineItem } from '../modules/chat_render_batch.js';
import { summarizeChatLiveEvent, summarizeLogEvent } from '../modules/log_events.js';
import { ElementStub, installDom, restoreDom, walkCard } from './chat_dom_fixture.js';

const TASK = 'reasoning-task';
const stamp = index => `2026-10-21T08:00:0${index}Z`;
const text = count => `Earlier reasoning not replayed after ${count} conversation changes (${count * 2} turns, ${count * 3} blocks).`;
const checkpoint = (count, main = true) => ({
    type: 'task_checkpoint', task_id: TASK, checkpoint_kind: 'prompt_prefix_break', round: count,
    reasoning_retired: { index: 2, cause: 'messages', turns: 2, blocks: 3 }, ts: stamp(count),
    ...(main ? { progress_row_emitted: true } : {
        system_type: 'task_checkpoint', text: text(count), card_row: 'timeline', card_row_id: `${TASK}:reasoning_retired`,
    }),
});
const progress = count => ({
    role: 'system', system_type: 'host_progress', is_progress: true, narration: false, task_id: TASK,
    card_row: 'timeline', card_row_id: `${TASK}:reasoning_retired`, text: text(count), content: text(count), ts: stamp(count),
});
const stored = (row, index) => ({ ...row, history_id: `progress:${index}`,
    history_position: { source: 'progress', offset: index } });

test('retirement checkpoints stay labelled in Logs while the progress row owns the Main timeline', () => {
    for (const count of [1, 2]) {
        const event = checkpoint(count);
        const view = summarizeChatLiveEvent(event);
        assert.equal(view.visible, false);
        assert.equal(view.promote, false);
        assert.equal(view.human, false);
        assert.equal(view.terminal, false);
        assert.equal('receipt' in view, false);
        assert.equal(summarizeLogEvent(event).headline, 'Earlier reasoning not replayed (2 turns, 3 blocks)');
    }
    const ordinary = { type: 'task_checkpoint', task_id: TASK, checkpoint_kind: 'prompt_prefix_break', round: 3 };
    assert.equal(summarizeChatLiveEvent(ordinary).visible, true);
    assert.equal(summarizeLogEvent(ordinary).headline, 'Prompt prefix rebuilt');
    assert.notEqual(summarizeChatLiveEvent(checkpoint(1, false)).dedupeKey,
        summarizeChatLiveEvent({ ...checkpoint(1, false), task_id: 'another-task' }).dedupeKey);
});

test('the one retirement row keeps its latest cumulative count across ordered and reverse history reloads', () => {
    const live = { items: [] };
    for (const count of [1, 2]) {
        const row = progress(count), summary = cardRowSummary(row, 'working', row.ts);
        updateLiveTimelineItem(live, summary, { ts: row.ts, rawTs: row.ts, syntheticKey: summary.dedupeKey,
            headline: summary.headline, inPlaceByKey: true });
    }
    assert.equal(live.items.length, 1);
    assert.equal(live.items[0].headline, text(2));
    for (const order of [[1, 2], [2, 1], [1, 2, 1, 2]]) {
        const replay = { items: [] };
        for (const count of order) {
            const row = stored(progress(count), count);
            mergeHistoricalTimelineItem(replay, cardRowSummary(row, 'working', row.ts), row, row.ts);
        }
        assert.equal(replay.items.length, 1);
        assert.equal(replay.items[0].headline, text(2));
        assert.equal(replay.items[0].sourceHistoryId, 'progress:2');
    }
});

function fixture(t, history = []) {
    const handlers = new Map();
    const rendered = [];
    const html = Object.getOwnPropertyDescriptor(ElementStub.prototype, 'innerHTML');
    Object.defineProperty(ElementStub.prototype, 'innerHTML', { ...html, set(value) {
        if (/class="chat-live-line /.test(String(value))) rendered.push(String(value));
        html.set.call(this, value);
    } });
    const env = installDom(async url => ({ ok: true, json: async () => String(url).startsWith('/api/chat/history')
        ? { messages: history, window: { complete: true } } : { active_direct_turns: [] } }));
    document.body = new ElementStub('body', document);
    const instance = createChatInstance({
        ws: { on(type, handler) { handlers.set(type, handler); return () => handlers.delete(type); },
            isConnected: () => true, send() {} },
        state: { activePage: 'chat', projectChatIds: new Set(), unreadCount: 0 }, updateUnreadBadge() {},
        stateSnapshots: { begin: () => ({ generation: 1, requestedAt: Date.now() }),
            gate() { return Promise.resolve(this.begin()); }, isCurrent: () => true, apply() {} },
        chatId: 1, idPrefix: 'chat', mountEl: env.mount,
    });
    t.after(() => {
        instance.destroy(); restoreDom(env.prior);
        Object.defineProperty(ElementStub.prototype, 'innerHTML', html);
    });
    const feed = document.byId.get('chat-messages');
    return {
        instance, feed, card: () => walkCard(feed, TASK),
        latestRetirement: () => rendered.findLast(value => value.includes('Earlier reasoning not replayed')) || '',
        log: row => handlers.get('log')({ chat_id: 1, data: { chat_id: 1, ...row } }),
        progress: row => handlers.get('chat')({ chat_id: 1, ...row }),
    };
}

test('live Main retirement updates stay in one task row without chat bubbles or toasts', t => {
    const f = fixture(t);
    f.progress({ role: 'assistant', is_progress: true, narration: true, task_id: TASK,
        text: 'Inspecting context', content: 'Inspecting context', ts: stamp(0) });
    const timeline = f.card().querySelector('.chat-live-timeline');
    const before = timeline.children.length;
    for (const count of [1, 2]) {
        f.progress(progress(count));
        f.log(checkpoint(count));
        assert.equal(timeline.children.length, before + 1);
        assert.ok(f.latestRetirement().includes(text(count)));
        assert.equal(f.feed.querySelectorAll('.chat-bubble').filter(row => !row.classList.contains('typing-bubble')).length, 0);
        assert.equal(document.body.querySelectorAll('.toast').length, 0);
    }
});

test('a helper checkpoint reuses its one row when live events are followed by durable history', async t => {
    const start = { role: 'assistant', is_progress: true, narration: true,
        task_id: TASK, text: 'Inspecting context', content: 'Inspecting context', ts: stamp(0) };
    const history = [stored(start, 0), ...[2, 1].map(count => stored({
        role: 'system', is_progress: true, ...checkpoint(count, false),
    }, count))];
    const f = fixture(t, history);
    f.progress(start);
    const timeline = f.card().querySelector('.chat-live-timeline');
    const before = timeline.children.length;
    for (const count of [1, 2]) {
        f.log(checkpoint(count, false));
        assert.ok(f.latestRetirement().includes(text(count)));
    }
    assert.equal(timeline.children.length, before + 1);
    await f.instance.refreshHistory({ revision: 1 });
    assert.equal(f.card().querySelector('.chat-live-timeline').children.length, before + 1);
    assert.ok(f.latestRetirement().includes(text(2)));
    assert.equal(f.feed.querySelectorAll('.chat-bubble').filter(row => !row.classList.contains('typing-bubble')).length, 0);
    assert.equal(document.body.querySelectorAll('.toast').length, 0);
});
