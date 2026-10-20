"""Rows asleep keep their own size when what they show changes without a new width (owner 20.10, 3A; review REV1).

A row far from the screen sleeps (chat_row_sleep.js, style.css `> [data-laid]`) only at the size it was laid out at.
Two things change a row's size without touching the feed's width:
- the theme: the dark theme's recorded answer has a `Your choice` line the light one has not, so a theme switch wakes
  every row and they sleep again at their new size, both ways;
- a late canonical answer adding the owner's words to a question far above the passage: the reading owner restores
  the passage inside its write, and the row the write changed is laid out before it does (`flush`), so the passage
  stays where it was, at once, two frames later and once the row sleeps again.
The feed's own scroll anchoring is switched off for the second check, so the reading owner alone holds the passage.
Uses the static-server fixture; never starts the runtime or reads live data."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from tests import test_subscription_setup_browser as setup_browser
from tests.test_design_system_gate_browser import rest, save_evidence, seed_page
from tests.test_header_question_a_browser import SETTLED

subscription_ui = setup_browser.subscription_ui
pytestmark = [pytest.mark.ui_browser, pytest.mark.serial]

FRAMES = "async n => { for (let i = 0; i < n; i += 1) await new Promise(r => requestAnimationFrame(r)); }"
# The answered question's row: the height it keeps, the height it has once woken for a moment, whether it sleeps.
QUESTION = """() => { const row = document.querySelector('#chat-messages [data-quiz-id="q-settled"]').closest('.chat-bubble');
    const laid = row.hasAttribute('data-laid'), kept = row.getBoundingClientRect().height;
    row.removeAttribute('data-laid'); const own = row.getBoundingClientRect().height;
    if (laid) row.setAttribute('data-laid', '');
    return { kept, own, laid, theme: document.documentElement.dataset.theme }; }"""
LATE_ANSWER = """async () => {
    const frame = () => new Promise(r => requestAnimationFrame(r));
    const feed = document.querySelector('#chat-messages'); feed.style.overflowAnchor = 'none';
    feed.dispatchEvent(new WheelEvent('wheel', { deltaY: -1 }));
    feed.scrollTop = feed.scrollHeight / 2;
    for (let i = 0; i < 45; i += 1) await frame();
    const top = feed.getBoundingClientRect().top;
    const passage = [...feed.children].find(n => n.getBoundingClientRect().top >= top);
    const row = document.querySelector('#chat-messages [data-quiz-id="q-settled"]').closest('.chat-bubble');
    const take = () => ({ y: passage.getBoundingClientRect().top, h: row.getBoundingClientRect().height,
        laid: row.hasAttribute('data-laid'), above: row.getBoundingClientRect().bottom < top });
    const before = take();
    window.__ouroWs.emit('quiz_state', { quiz_id: 'q-settled', task_id: 'task-settled', chat_id: 1, state: 'answered',
        answered_index: 1, comment: 'These are my recorded words. '.repeat(100) });
    const sync = take(); await frame(); await frame(); const after = take();
    for (let i = 0; i < 45; i += 1) await frame();
    return { before, sync, after, settled: take() }; }"""


@pytest.fixture(params=['webkit', 'chromium'])
def sleep_ui(request, monkeypatch):
    monkeypatch.setenv('OUROBOROS_UI_BROWSER_ENGINE', request.param)
    ui = request.getfixturevalue('subscription_ui')
    ui['engine'] = request.param
    return ui


def test_rows_asleep_wake_for_a_theme_and_for_a_late_answer_above_the_passage(sleep_ui, tmp_path):
    page = seed_page(sleep_ui, 390, 844, telegram=True)
    page.add_init_script("localStorage.setItem('ouroboros.theme', 'dark')")
    page.emulate_media(color_scheme='dark')
    start = datetime(2026, 10, 19, 15, 20, tzinfo=timezone.utc)
    rows = [{'role': 'assistant', 'msg_type': 'quiz', 'task_id': 'task-settled', 'chat_id': 1, 'ts': SETTLED['asked_at'],
             'text': SETTLED['question'], 'quiz': {k: v for k, v in SETTLED.items() if k != 'question'}}]
    rows += [{'role': 'user', 'chat_id': 1, 'text': f'Reading row {i}. ' + 'Some words to read. ' * 12,
              'ts': (start + timedelta(minutes=i)).isoformat(), 'row_address': f'main-row-{i}'} for i in range(130)]
    page.route('**/api/chat/history*', lambda route: route.fulfill(json={'messages': rows, 'progress': []}))
    facts = {'engine': sleep_ui['engine']}
    try:
        page.goto(sleep_ui['url'] + '/')
        page.wait_for_selector('#chat-input', state='attached')
        page.wait_for_function("document.querySelectorAll('#chat-messages > *').length > 120")
        rest(page)
        page.evaluate(FRAMES, 45)
        page.evaluate("document.querySelector('#chat-messages').scrollTop = document.querySelector('#chat-messages').scrollHeight")
        page.evaluate(FRAMES, 35)
        for theme in ('dark', 'light', 'dark'):
            page.evaluate("theme => window.ouroTheme.set(theme)", theme)
            page.evaluate(FRAMES, 45)
            facts.setdefault('themes', []).append(page.evaluate(QUESTION))
        facts['late'] = page.evaluate(LATE_ANSWER)
    finally:
        save_evidence(tmp_path, f'row-sleep-{sleep_ui["engine"]}', facts)
        print(json.dumps(facts))
        page.close()
    dark, light, again = facts['themes']
    assert dark['laid'] and light['laid'] and again['laid'], ('far from the screen, the answered question sleeps', facts)
    assert light['own'] < dark['own'], ('the light theme has no `Your choice` line: the row is shorter', facts)
    for state in facts['themes']:
        assert abs(state['kept'] - state['own']) <= 0.5, ('asleep, the row keeps its own size in either theme', facts)
    late = facts['late']
    assert late['before']['laid'] and late['before']['above'], ('the question sleeps above the passage', facts)
    assert late['settled']['h'] > late['before']['h'] + 500, ('the late answer grew the row', facts)
    for moment in ('sync', 'after', 'settled'):
        assert abs(late[moment]['y'] - late['before']['y']) <= 1, (f'the passage stays ({moment})', facts)
    assert late['settled']['laid'], ('and the row sleeps again at its new size', facts)
