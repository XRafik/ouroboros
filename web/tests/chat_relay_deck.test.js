// Notes between works (chat_relay_deck.js) over the DOM double: a run of notes is one deck over its hidden relay rows,
// the owner's words keep a card of their own, a row between notes splits the run, a later note joins its deck, a note
// without the teller's line opens with its own words in the meta ink, the deck fans out and folds back, a note opens
// as written with Reply and Copy, and a quote's jump lands on the note's card. Motion and layout run in the browser lane.
import assert from 'node:assert/strict';
import test from 'node:test';
import { createRelayDecks } from '../modules/chat_relay_deck.js';
import { createChatReplies } from '../modules/chat_reply.js';
import { installDomDouble } from './dom_double.js';

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

function fixture() {
    const env = installDomDouble();
    const feed = env.el('div', { className: 'chat-messages' });
    env.doc.body.append(feed);
    const replied = [], copied = [];
    const decks = createRelayDecks({ feed, reply: (bubble) => replied.push(bubble), copy: (text) => copied.push(text),
        relayQuote: (relay) => env.el('div', { className: 'chat-quote', dataset: { mode: 'relay' }, text: relay.text }) });
    let seq = 0;
    const note = (text, { summary = '', sender = { name: 'Main', chat_id: 1 }, quote = '', source = null } = {}) => {
        seq += 1;
        const ts = `2026-10-21T23:${String(10 + seq).padStart(2, '0')}:00Z`;
        const bubble = env.el('div', { className: 'chat-bubble assistant',
            dataset: { systemType: 'relay_entry', ts: String(Date.parse(ts)), rowAddress: `row:${seq}@r#${seq}` } },
        env.el('div', { className: 'sender', text: 'Ouroboros' }), env.el('div', { className: 'message', text }));
        feed.append(bubble);
        const relay = { relay_id: `r${seq}`, text: quote, quotes: quote ? [{ text: quote }] : [],
            ...(summary ? { summary } : {}), ...(sender ? { sender } : {}), ...(source ? { source } : {}) };
        decks.adopt(bubble, { text, ts, relay }, Boolean(quote));
        return bubble;
    };
    const row = (text) => {
        const bubble = env.el('div', { className: 'chat-bubble user', text });
        feed.append(bubble);
        return bubble;
    };
    const objects = () => feed.children.filter((child) => child.classList.contains('chat-relay-deck'));
    const cards = (obj) => obj.querySelectorAll('.chat-relay-card');
    const front = (obj) => cards(obj)[cards(obj).length - 1];
    return { env, feed, decks, note, row, objects, cards, front, replied, copied,
        close() { decks.destroy(); env.restore(); } };
}

test('a run of notes is one deck over its hidden rows, the latest note in front', async () => {
    const f = fixture();
    try {
        const rows = Array.from({ length: 7 }, (_, i) => f.note(`raw${i}:glued-work-words`, { summary: `Line ${i} for the owner` }));
        await settle();
        const [deck] = f.objects();
        assert.equal(f.objects().length, 1, 'seven notes are one object, not seven bubbles');
        assert.equal(f.feed.children[0], deck, 'the deck stands where its first note is');
        assert.ok(rows.every((bubble) => bubble.hidden && bubble.dataset.relayDeck === '1'), 'every relay row stays, hidden');
        assert.equal(deck.dataset.n, '3', 'the front card and two edges');
        assert.equal(f.cards(deck).length, 7);
        const card = f.front(deck);
        assert.equal(card.querySelector('.chat-relay-from').textContent, 'Main');
        assert.equal(card.querySelector('.chat-relay-gist').textContent, 'Line 6 for the owner');
        assert.equal(card.querySelector('.chat-relay-act').textContent, 'Show 7 notes');
        assert.equal(card.getAttribute('inert'), null, 'the front card takes presses');
        assert.ok(f.cards(deck).slice(0, 6).every((edge) => edge.getAttribute('inert') === ''), 'the edges behind it do not');
    } finally { f.close(); }
});

test('the owner\'s words keep a card of their own, and any other row ends a run', async () => {
    const f = fixture();
    try {
        f.note('first');
        f.note('second');
        f.row('owner says something');
        f.note('third, passing his words', { quote: 'please check the logs', summary: 'Asks the work to check the logs' });
        f.note('fourth');
        await settle();
        const [pair, quoted, single] = f.objects();
        assert.equal(f.objects().length, 3);
        assert.equal(f.cards(pair).length, 2, 'two notes in a row are one deck');
        assert.equal(f.cards(quoted).length, 1, 'a relay with his words is a card of its own');
        assert.equal(quoted.querySelector('.chat-quote').textContent, 'please check the logs', 'his words in their panel');
        assert.equal(f.cards(single).length, 1, 'a note after his words starts a new deck');
        assert.equal(pair.querySelector('.chat-quote'), null, 'a note without his words carries no panel');
    } finally { f.close(); }
});

test('a later note joins its deck; a row landing between notes splits the run', async () => {
    const f = fixture();
    try {
        const first = f.note('one');
        const second = f.note('two');
        await settle();
        const [deck] = f.objects();
        f.note('three');
        await settle();
        assert.equal(f.objects()[0], deck, 'the same deck takes the arriving note');
        assert.equal(f.cards(deck).length, 3);
        assert.equal(f.front(deck).querySelector('.chat-relay-act').textContent, 'Show 3 notes');
        const between = f.env.el('div', { className: 'chat-bubble user', text: 'between' });
        f.feed.insertBefore(between, second);
        f.decks.schedule();
        await settle();
        const [before, after] = f.objects();
        assert.equal(f.objects().length, 2, 'a row between notes makes two decks');
        assert.equal(f.cards(before).length, 1);
        assert.equal(f.cards(after).length, 2);
        assert.equal(f.feed.children.indexOf(before) < f.feed.children.indexOf(first), true);
        assert.equal(f.feed.children.indexOf(after) > f.feed.children.indexOf(between), true);
        assert.equal(deck.parentElement, null, 'the deck drawn before the split leaves');
    } finally { f.close(); }
});

test('a note without the teller\'s line opens with its own words, in the meta ink; a summary leads otherwise', async () => {
    const f = fixture();
    try {
        f.note('a0e1:research-done,no-safe-restore');
        f.row('break');
        f.note('a0e1:research-done', { summary: 'Research is done; no safe fix yet' });
        await settle();
        const [raw, summarized] = f.objects().map((obj) => f.front(obj).querySelector('.chat-relay-gist'));
        assert.equal(raw.dataset.raw, '1');
        assert.equal(raw.textContent, 'a0e1:research-done,no-safe-restore');
        assert.equal(summarized.dataset.raw, undefined, 'the teller\'s line reads in the voice\'s ink');
        assert.equal(summarized.textContent, 'Research is done; no safe fix yet');
    } finally { f.close(); }
});

test('a note saved before its room was recorded says Main only when it came from Main', async () => {
    const f = fixture();
    try {
        f.note('from main', { sender: null, source: { chat_id: 1, label: 'Main' } });
        f.row('break');
        f.note('from a project', { sender: null, source: { chat_id: 52601710, label: 'Main' } });
        f.row('break');
        f.note('named', { sender: { name: 'Claudexor 478', chat_id: 52601710 } });
        await settle();
        const [main, unknown, named] = f.objects().map((obj) => f.front(obj));
        assert.equal(main.querySelector('.chat-relay-from').textContent, 'Main');
        assert.equal(main.dataset.kind, 'main');
        assert.equal(unknown.querySelector('.chat-relay-from').textContent, 'Another work', 'never an invented room');
        assert.equal(unknown.dataset.kind, 'project');
        assert.equal(named.querySelector('.chat-relay-from').textContent, 'Claudexor 478');
        assert.equal(named.dataset.kind, 'project');
    } finally { f.close(); }
});

test('Show N notes fans the deck out; Show note opens the note as written with Reply and Copy; Hide folds it', async () => {
    const f = fixture();
    try {
        const rows = [f.note('w1'), f.note('w2:as-written'), f.note('w3')];
        await settle();
        const [deck] = f.objects();
        f.front(deck).querySelector('.chat-relay-act').click();
        assert.equal(deck.dataset.open, '1');
        assert.ok(f.cards(deck).every((card) => card.getAttribute('inert') === null), 'every card takes presses');
        assert.match(deck.querySelector('.chat-relay-deck-caption').textContent, /^3 notes/);
        const middle = f.cards(deck)[1];
        const act = middle.querySelector('.chat-relay-act');
        assert.equal(act.textContent, 'Show note');
        act.click();
        assert.equal(middle.querySelector('.chat-relay-raw').hidden, false);
        assert.equal(middle.querySelector('.chat-relay-raw-text').textContent, 'w2:as-written');
        assert.equal(act.textContent, 'Hide note');
        middle.querySelector('.chat-relay-copy').click();
        assert.deepEqual(f.copied, ['w2:as-written']);
        middle.querySelector('.chat-relay-reply').click();
        assert.deepEqual(f.replied, [rows[1]], 'Reply answers the note\'s own row');
        act.click();
        assert.equal(middle.querySelector('.chat-relay-raw').hidden, true);
        deck.querySelector('.chat-relay-hide').click();
        assert.equal(deck.dataset.open, '0');
        assert.equal(f.front(deck).querySelector('.chat-relay-act').textContent, 'Show 3 notes');
    } finally { f.close(); }
});

test('a quote\'s jump lands on the note\'s card, its deck opened; any other row stays itself', async () => {
    const f = fixture();
    try {
        const first = f.note('one');
        f.note('two');
        const owner = f.row('mine');
        await settle();
        const [deck] = f.objects();
        assert.equal(f.decks.surface(first), f.cards(deck)[0]);
        assert.equal(deck.dataset.open, '1', 'a card behind the front one is shown by opening the deck');
        assert.equal(f.decks.surface(owner), null);
    } finally { f.close(); }
});

test('a relay row the room decorates is drawn as a note; a bubble without the relay type stays a bubble', async () => {
    const env = installDomDouble();
    const feed = env.el('div', { className: 'chat-messages' });
    const input = env.el('textarea', { attrs: { id: 'chat-input' } });
    env.doc.body.append(feed, env.el('div', { className: 'chat-text-row' }, input));
    const replies = createChatReplies({ chatId: 7, feed, input, reading: () => ({ cancel() {}, scroll() {}, remember() {}, stick: true }) });
    try {
        const relayRow = env.el('div', { className: 'chat-bubble assistant', dataset: { systemType: 'relay_entry' } },
            env.el('div', { className: 'sender', text: 'Ouroboros' }), env.el('div', { className: 'message', text: 'note words' }));
        const plain = env.el('div', { className: 'chat-bubble assistant' },
            env.el('div', { className: 'sender', text: 'Ouroboros' }), env.el('div', { className: 'message', text: 'an answer' }));
        feed.append(relayRow, plain);
        const relay = { relay_id: 'r', text: '', quotes: [], summary: 'Tells the work what to check', sender: { name: 'Main', chat_id: 1 } };
        replies.decorate(relayRow, { row_address: 'row:1@a#1', role: 'assistant', text: 'note words', relay });
        replies.decorate(plain, { row_address: 'row:2@a#2', role: 'assistant', text: 'an answer', relay });
        await settle();
        assert.equal(relayRow.hidden, true);
        assert.equal(feed.children[0].classList.contains('chat-relay-deck'), true);
        assert.equal(plain.hidden, false, 'only a relay row becomes a note');
    } finally { replies.destroy(); env.restore(); }
});
