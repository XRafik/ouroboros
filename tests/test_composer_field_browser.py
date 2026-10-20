"""The composer's field (docs/DESIGN.md "The composer field"; owner 20.10, 1C and 2A; web/modules/send_flight.js).

In WebKit and Chromium, on a phone and a desk: the field is one object whose corner is the sheet radius and never grows
with the words, so a one-line field is a capsule and a paragraph a card with the same corner; "+" and Send ride on the
words' last line, never their middle; the text row inside the field has no surface of its own; a staged reply is the
field's first line, a concentric panel inside it. An accepted Send lifts a copy of the new bubble from the draft to its
place in the feed and leaves the bubble shown; asked for reduced motion, nothing flies. Uses the static-server/API
fixture.
"""
from __future__ import annotations

import json

import pytest

from tests import test_subscription_setup_browser as setup_browser
from tests.test_design_system_gate_browser import seed_page, settle
from tests.test_shell_interactions_browser import boot, evidence, shell_ui

subscription_ui = setup_browser.subscription_ui
pytestmark = [pytest.mark.ui_browser, pytest.mark.serial]
__all__ = ['shell_ui', 'subscription_ui']

# A staged reply as chat_reply.js keeps it for the room (Main's key), restored when the room opens.
REPLY = {'address': 'row:1@2026-10-20T19:17:10+00:00#a1', 'chat_id': 0, 'role': 'assistant', 'kind': 'message',
         'author_label': 'Ouroboros', 'snippet': 'Сейчас реально работают две задачи.', 'ts': '2026-10-20T19:17:10+00:00'}
PARAGRAPH = 'Первая строка черновика\nвторая\nтретья\nчетвёртая\nпятая'
FACTS = """() => {
    const page = document.querySelector('#page-chat');
    const field = page.querySelector('.chat-field'), row = field.querySelector('.chat-text-row');
    const input = page.querySelector('#chat-input'), strip = page.querySelector('.chat-quote--composer');
    const box = (el) => { const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, height: r.height }; };
    const mid = (el) => { const r = el.getBoundingClientRect(); return r.top + r.height / 2; };
    const words = getComputedStyle(input);
    return {
        radius: getComputedStyle(field).borderTopLeftRadius, field: box(field), fieldMid: mid(field),
        plusMid: mid(page.querySelector('#chat-plus')), sendMid: mid(page.querySelector('.chat-send-group')),
        // The middle of the words' last visible line.
        lastLine: input.getBoundingClientRect().bottom - parseFloat(words.paddingBottom) - parseFloat(words.lineHeight) / 2,
        rowBg: getComputedStyle(row).backgroundColor, rowShadow: getComputedStyle(row).boxShadow,
        rowRadius: getComputedStyle(row).borderTopLeftRadius,
        strip: strip ? { inField: field.contains(strip), box: box(strip), radius: getComputedStyle(strip).borderTopLeftRadius,
            border: getComputedStyle(strip).borderTopWidth } : null,
    };
}"""
# From the press of Send: whether a copy of the bubble flew, where it stood first and a few frames later, and, once it
# should have landed, whether it left and the sent bubble shows.
FLIGHT = """() => new Promise((resolve) => {
    const seen = [];
    const observer = new MutationObserver(() => {
        const copy = document.querySelector('.chat-send-flight');
        if (copy && !seen.length) seen.push(copy.getBoundingClientRect().top);
    });
    observer.observe(document.body, { childList: true });
    const field = document.querySelector('#page-chat .chat-field').getBoundingClientRect();
    document.querySelector('#page-chat #chat-send').click();
    const sample = () => { const copy = document.querySelector('.chat-send-flight');
        if (copy) seen.push(copy.getBoundingClientRect().top); };
    setTimeout(sample, 120);
    setTimeout(sample, 220);
    setTimeout(() => {
        observer.disconnect();
        const rows = document.querySelectorAll('#chat-messages .chat-bubble.user');
        const sent = rows[rows.length - 1];
        resolve({ seen, fieldTop: field.top, left: Boolean(document.querySelector('.chat-send-flight')),
            sentTop: sent ? sent.getBoundingClientRect().top : null,
            sentOpacity: sent ? getComputedStyle(sent).opacity : null, sentText: sent ? sent.textContent : '' });
    }, 900);
})"""


def _open(ui, width, reply=False):
    page = seed_page(ui, width, 844 if width < 720 else 900)
    if reply:
        page.add_init_script(f"sessionStorage.setItem('ouro_chat_reply', {json.dumps(json.dumps(REPLY))})")
    boot(page, ui)
    return page


@pytest.mark.parametrize('width', [390, 1280])
def test_the_field_keeps_its_corner_and_its_controls_ride_on_the_last_line(shell_ui, tmp_path, width):
    page = _open(shell_ui, width)
    facts = {'engine': shell_ui['engine'], 'width': width}
    try:
        page.locator('#chat-input').fill('Одна строка')
        settle(page)
        facts['one'] = page.evaluate(FACTS)
        page.locator('#chat-input').fill(PARAGRAPH)
        settle(page)
        facts['paragraph'] = page.evaluate(FACTS)
    finally:
        evidence(tmp_path, f'composer-field-{width}-{shell_ui["engine"]}', facts)
        page.close()
    one, para = facts['one'], facts['paragraph']
    assert one['radius'] == para['radius'] == '24px', ('the corner is the sheet radius, never growing with the words', facts)
    assert one['field']['height'] <= 2 * 24 + 2, ('one line is a capsule: no taller than its corner rounds', one)
    assert abs(one['plusMid'] - one['fieldMid']) <= 1.5 and abs(one['sendMid'] - one['fieldMid']) <= 1.5, one
    assert para['field']['height'] >= one['field']['height'] + 80, ('setup: a paragraph', facts)
    for control in ('plusMid', 'sendMid'):
        assert abs(para[control] - para['lastLine']) <= 1.5, (f'{control} rides on the words\' last line', para)
    assert para['plusMid'] - para['fieldMid'] >= 30, ('never on the middle of the paragraph', para)
    assert (para['rowBg'], para['rowShadow'], para['rowRadius']) == ('rgba(0, 0, 0, 0)', 'none', '0px'), (
        'the text row inside the field has no surface of its own', para)


@pytest.mark.parametrize('width', [390, 1280])
def test_a_staged_reply_is_the_fields_first_line(shell_ui, tmp_path, width):
    page = _open(shell_ui, width, reply=True)
    facts = {'engine': shell_ui['engine'], 'width': width}
    try:
        page.wait_for_selector('#page-chat .chat-quote--composer', state='attached')
        settle(page)
        facts['reply'] = page.evaluate(FACTS)
    finally:
        evidence(tmp_path, f'composer-field-reply-{width}-{shell_ui["engine"]}', facts)
        page.close()
    reply = facts['reply']
    strip, field = reply['strip'], reply['field']
    assert strip and strip['inField'], ('the staged reply lives inside the field', reply)
    assert strip['radius'] == '16px' and strip['border'] == '0px', (
        'concentric with the field (its corner less the 8 px inset), no hairline of its own', reply)
    insets = (strip['box']['top'] - field['top'], strip['box']['left'] - field['left'], field['right'] - strip['box']['right'])
    assert all(abs(inset - 8) <= 1 for inset in insets), ('8 px in from the field\'s top and sides', insets, reply)
    assert reply['radius'] == '24px' and field['height'] > 2 * 24 + 20, ('the field with its reply is a card', reply)


@pytest.mark.parametrize('motion', ['no-preference', 'reduce'])
def test_an_accepted_send_rises_from_the_draft_into_the_feed(shell_ui, tmp_path, motion):
    page = _open(shell_ui, 390)
    page.emulate_media(reduced_motion=motion)
    facts = {'engine': shell_ui['engine'], 'motion': motion}
    try:
        page.locator('#chat-input').fill('Проверка полёта: черновик поднимается в ленту')
        settle(page)
        facts['flight'] = page.evaluate(FLIGHT)
        facts['field'] = page.evaluate(FACTS)
    finally:
        evidence(tmp_path, f'composer-send-flight-{motion}-{shell_ui["engine"]}', facts)
        page.close()
    flight = facts['flight']
    assert 'Проверка полёта' in flight['sentText'], ('setup: the send shows in the feed', flight)
    assert flight['left'] is False and flight['sentOpacity'] == '1', ('no copy is left; the sent bubble shows', flight)
    if motion == 'reduce':
        assert flight['seen'] == [], ('reduced motion: nothing flies, the bubble simply appears', flight)
    else:
        assert len(flight['seen']) >= 2, ('a copy of the bubble flew', flight)
        assert abs(flight['seen'][0] - flight['fieldTop']) <= 2, ('it starts where the draft stood', flight)
        assert flight['seen'][-1] < flight['seen'][0] - 20, ('and rises toward the bubble\'s place', flight)
