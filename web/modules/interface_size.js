/** Interface size (docs/DESIGN.md "Appearance"): one per-device size the owner sets with a slider, applied by whoever
 * owns the viewport, never by scaling the page itself (CSS `zoom` on the page pushed the composer off screen and made
 * every measured length disagree with the pointer). One setter serves the slider and the desktop keys.
 *
 * The route is whatever answers. The desktop app zooms its own window through its bridge (`set_interface_size`:
 * WKWebView `pageZoom`, the WebView2 control's `ZoomFactor`, WebKitGTK's zoom level) and keeps the size for its next
 * window, so there the app's value is the setting. A touch screen lays the page out at another width
 * (`window.ouroViewportScale`, web/theme.js), stored by this browser. A browser on a computer keeps its own zoom,
 * which no page can set, so the control names its keys. Anywhere else (a Mini App in Telegram for Android, Telegram
 * Desktop, a desktop app older than the bridge) the size stays 100 % and the control says so. */

import { fmtInto } from './i18n.js';
import { isTelegramHost } from './host_telegram.js';

/** The desktop window's range; the keys move in tens, the slider in fives. */
export const DESK = Object.freeze({ min: 50, max: 200, step: 5, key: 10 });

/** The key the owner pressed, as a zoom command: ⌘ on a Mac, Ctrl elsewhere, no Alt; the physical key, so any
 * keyboard layout works ('in' | 'out' | 'reset' | ''). */
export function zoomKey(event, { mac = false } = {}) {
    if (!event || event.altKey || !(mac ? event.metaKey : event.ctrlKey)) return '';
    if (event.code === 'Equal' || event.code === 'NumpadAdd') return 'in';
    if (event.code === 'Minus' || event.code === 'NumpadSubtract') return 'out';
    if (event.code === 'Digit0' || event.code === 'Numpad0') return 'reset';
    return '';
}

/** The next size a zoom key gives: up or down to the next whole ten, inside the range. */
export function stepped(percent, direction, { min = DESK.min, max = DESK.max, key = DESK.key } = {}) {
    const current = Number(percent) || 100;
    const next = direction > 0 ? Math.floor(current / key) * key + key : Math.ceil(current / key) * key - key;
    return Math.min(max, Math.max(min, next));
}

function bridgeOf(win) {
    const api = win?.pywebview?.api;
    return typeof api?.set_interface_size === 'function' ? api : null;
}

const isMac = (win) => /Mac|iPhone|iPad/.test(String(win?.navigator?.platform || win?.navigator?.userAgent || ''));

/** The one controller of this page's Interface size. */
export function createInterfaceSize({ win = globalThis.window, doc = globalThis.document } = {}) {
    const listeners = new Set();
    let native = null;  // the desktop bridge's answer: {min, max, percent}
    let nativeChecked = false;
    let sequence = 0;
    const since = win?.performance?.timeOrigin ?? Date.now();

    const viewport = () => win?.ouroViewportScale || null;
    const notify = () => { for (const listener of listeners) { try { listener(state()); } catch { /* one view */ } } };

    function state() {
        if (native) {
            return { route: 'app', percent: native.percent, min: native.min, max: native.max, step: DESK.step };
        }
        const vp = viewport();
        if (vp && vp.state !== 'unavailable') {
            return { route: 'screen', percent: vp.percent, min: vp.min, max: vp.max, step: vp.step,
                pending: vp.state === 'pending' };
        }
        const shell = Boolean(win?.pywebview);
        const topLevel = (() => { try { return win.top === win; } catch { return false; } })();
        if (shell && nativeChecked) return { route: 'none', reason: 'app', percent: 100 };
        if (isTelegramHost({ win, doc }) && topLevel) return { route: 'none', reason: 'telegram', percent: 100 };
        return { route: 'browser', percent: 100 };
    }

    async function readNative() {
        const api = bridgeOf(win);
        if (!api || typeof api.shell_info !== 'function') {
            nativeChecked = Boolean(win?.pywebview);
            notify();
            return;
        }
        try {
            const info = (await api.shell_info())?.interface_size;
            native = info && info.supported ? {
                min: Number(info.min) || DESK.min, max: Number(info.max) || DESK.max,
                percent: Number(info.percent) || 100,
            } : null;
        } catch {
            native = null;
        }
        nativeChecked = true;
        notify();
    }

    /** Set the size in percent; resolves with the state the route reports. */
    async function set(value) {
        const now = state();
        if (now.route === 'app') {
            const percent = Math.min(now.max, Math.max(now.min, Math.round(Number(value) / DESK.step) * DESK.step));
            sequence += 1;
            try {
                const answer = await bridgeOf(win)?.set_interface_size(percent, since, sequence);
                if (answer?.ok && Number.isFinite(Number(answer.percent))) native = { ...native, percent: Number(answer.percent) };
            } catch { /* the window keeps the size it has; the control shows what the app holds */ }
            notify();
            return state();
        }
        if (now.route === 'screen') {
            await viewport().set(value);
            notify();
            return state();
        }
        return now;
    }

    const step = (direction) => set(stepped(state().percent, direction, state()));
    const reset = () => set(100);

    // The desktop keys: ⌘/Ctrl + − 0 change this window's size, as a browser's do. A browser keeps its own keys.
    function onKey(event) {
        if (state().route !== 'app') return;
        const command = zoomKey(event, { mac: isMac(win) });
        if (!command) return;
        event.preventDefault();
        if (command === 'reset') reset(); else step(command === 'in' ? 1 : -1);
    }

    const offViewport = viewport()?.subscribe?.(notify);
    doc?.addEventListener?.('keydown', onKey, true);
    win?.addEventListener?.('pywebviewready', readNative);
    if (bridgeOf(win)) readNative();

    return {
        state, set, step, reset,
        subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
        dispose() {
            offViewport?.();
            doc?.removeEventListener?.('keydown', onKey, true);
            win?.removeEventListener?.('pywebviewready', readNative);
            listeners.clear();
        },
    };
}

let shared = null;
/** The page's one controller, created at boot (app.js). */
export function getInterfaceSize() {
    shared ||= createInterfaceSize();
    return shared;
}

/** The note under the slider, how the size works on this surface: [template, params] for `fmt`. */
export function sizeNote(current, { mac = false } = {}) {
    const keys = mac ? '⌘ +, ⌘ − and ⌘ 0' : 'Ctrl +, Ctrl − and Ctrl 0';
    if (current.route === 'app') return ['For this window; the next one opens at the same size. {keys} work here too.', { keys }];
    if (current.route === 'screen') return ['On this screen from {min}% to {max}%.', { min: current.min, max: current.max }];
    if (current.reason === 'app') {
        return ['This desktop app cannot change its size yet. Restart Ouroboros after updating to set it here.', {}];
    }
    if (current.reason === 'telegram') {
        return ['Telegram does not let a page change its size here. Your system’s display size setting makes everything '
            + 'larger or smaller.', {}];
    }
    return ['This browser sets the size of the page: {keys}.', { keys }];
}

/** Paint and bind the Settings → Appearance block; returns its disposer. */
export function mountInterfaceSize(root, controller = getInterfaceSize(), { win = globalThis.window } = {}) {
    const block = root?.querySelector?.('[data-interface-size]');
    if (!block) return () => {};
    const row = block.querySelector('[data-interface-size-row]');
    const input = block.querySelector('[data-interface-size-input]');
    const output = block.querySelector('[data-interface-size-value]');
    const resetButton = block.querySelector('[data-interface-size-reset]');
    const note = block.querySelector('[data-interface-size-note]');
    const mac = isMac(win);
    let dragging = false;

    const paint = (current = controller.state()) => {
        const adjustable = current.route === 'app' || current.route === 'screen';
        if (row) row.hidden = !adjustable;
        if (input && adjustable) {
            input.min = String(current.min);
            input.max = String(current.max);
            input.step = String(current.step);
            if (!dragging) input.value = String(current.percent);
            input.disabled = Boolean(current.pending);
        }
        if (output && !dragging) output.textContent = `${current.percent}%`;
        if (resetButton) resetButton.disabled = !adjustable || current.percent === 100;
        if (note) { const [template, params] = sizeNote(current, { mac }); fmtInto(note, template, params, template); }
    };
    // The size changes only when the slider is let go: a page zooming under the finger would move the slider itself.
    const onInput = () => { dragging = true; if (output) output.textContent = `${input.value}%`; };
    const onChange = () => { dragging = false; controller.set(Number(input.value)); };
    const onReset = () => controller.reset();
    input?.addEventListener('input', onInput);
    input?.addEventListener('change', onChange);
    resetButton?.addEventListener('click', onReset);
    const off = controller.subscribe(paint);
    paint();
    return () => {
        off();
        input?.removeEventListener('input', onInput);
        input?.removeEventListener('change', onChange);
        resetButton?.removeEventListener('click', onReset);
    };
}
