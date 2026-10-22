"""Settings → Appearance → Interface size on the real SPA (owner 23.10: one slider, smaller than 90 % too).

Static-server fixture with synthetic API rows (test_subscription_setup_browser); no runtime starts. Three surfaces:
a browser on a computer (the slider gives way to the browser's own zoom keys), the desktop app (a recorder stands in
for its bridge: the slider and ⌘ + − 0 set the window's size there) and a phone (mobile Chromium honours the viewport
meta, so the page is laid out at another width). The engines' own page zoom was measured on a real WKWebView for the
design, not here.
"""
from __future__ import annotations

import pytest

from tests import test_subscription_setup_browser as setup_browser
from tests.test_design_system_gate_browser import open_nav, rest, seed_page

subscription_ui = setup_browser.subscription_ui
pytestmark = [pytest.mark.ui_browser, pytest.mark.serial]

BRIDGE = """(() => {
    window.__sizes = [];
    window.pywebview = {api: {
        shell_info: async () => ({interface_size: {supported: true, min: 50, max: 200, step: 5, percent: 100}}),
        set_interface_size: async (percent, page, sequence) => { window.__sizes.push(percent); return {ok: true, percent}; },
    }};
    addEventListener('DOMContentLoaded', () => setTimeout(() => dispatchEvent(new Event('pywebviewready')), 50));
})();"""
FACTS = """() => {
    const block = document.querySelector('[data-interface-size]');
    const input = block.querySelector('[data-interface-size-input]');
    return {rowHidden: block.querySelector('[data-interface-size-row]').hidden, min: input.min, max: input.max,
            value: input.value, shown: block.querySelector('[data-interface-size-value]').textContent,
            note: block.querySelector('[data-interface-size-note]').textContent, innerWidth,
            meta: document.querySelector('meta[name="viewport"]').getAttribute('content')};
}"""


def _appearance(page):
    open_nav(page, 'settings')
    page.locator('#page-settings [data-settings-tab="appearance"]').click()
    page.locator('[data-interface-size]').scroll_into_view_if_needed()
    rest(page)


def _slide_to(page, value):
    page.locator('[data-interface-size-input]').evaluate(
        """(el, value) => { el.value = String(value); el.dispatchEvent(new Event('input', {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true})); }""", value)


@pytest.fixture(params=['chromium', 'webkit'])
def size_ui(request, monkeypatch):
    monkeypatch.setenv('OUROBOROS_UI_BROWSER_ENGINE', request.param)
    ui = request.getfixturevalue('subscription_ui')
    ui['engine'] = request.param
    return ui


def test_a_browser_keeps_its_own_zoom_and_the_control_names_its_keys(size_ui):
    page = seed_page(size_ui, 1280, 860)
    try:
        page.goto(size_ui['url'])
        _appearance(page)
        facts = page.evaluate(FACTS)
        assert facts['rowHidden'], facts
        assert 'This browser sets the size of the page' in facts['note'], facts
    finally:
        page.close()


def test_the_desktop_app_slider_and_keys_set_the_windows_own_size(size_ui):
    page = seed_page(size_ui, 1280, 860)
    page.add_init_script(BRIDGE)
    try:
        page.goto(size_ui['url'])
        _appearance(page)
        page.wait_for_function("!document.querySelector('[data-interface-size-row]').hidden")
        facts = page.evaluate(FACTS)
        assert facts['min'] == '50' and facts['max'] == '200' and facts['value'] == '100', facts
        assert 'For this window' in facts['note'], facts
        _slide_to(page, 80)
        page.wait_for_function("window.__sizes.length === 1")
        assert page.evaluate('window.__sizes') == [80], 'below 90 % (owner 23.10)'
        modifier = 'Meta' if page.evaluate("/Mac/.test(navigator.platform)") else 'Control'
        page.keyboard.press(f'{modifier}+Equal')
        page.wait_for_function("window.__sizes.length === 2")
        page.keyboard.press(f'{modifier}+Digit0')
        page.wait_for_function("window.__sizes.length === 3")
        assert page.evaluate('window.__sizes') == [80, 90, 100]
        assert page.evaluate(FACTS)['shown'] == '100%'
    finally:
        page.close()


def test_a_phone_lays_the_page_out_at_another_width(subscription_ui, monkeypatch):
    monkeypatch.setenv('OUROBOROS_UI_BROWSER_ENGINE', 'chromium')
    page = subscription_ui['new_page'](viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
    try:
        page.goto(subscription_ui['url'])
        _appearance(page)
        page.wait_for_function("!document.querySelector('[data-interface-size-row]').hidden")
        facts = page.evaluate(FACTS)
        assert facts['min'] == '75' and facts['max'] == '120' and facts['innerWidth'] == 390, facts
        _slide_to(page, 120)
        page.wait_for_function("innerWidth === 325")
        facts = page.evaluate(FACTS)
        assert facts['meta'].startswith('width=325, initial-scale=1.2'), facts
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), 'nothing scrolls sideways'
        page.reload()
        page.wait_for_function("innerWidth === 325")  # the stored size is the first layout after a reload
    finally:
        page.close()
