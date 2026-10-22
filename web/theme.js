/* Client-local appearance: Light / Dark / System, and the shell's layout switch.
   Runs synchronously before CSS to avoid a dark flash and a wrong-shell flash. No
   server setting: the owner's WebView and each browser retain their own choice, so
   one device can differ from another on purpose.

   `ouroboros.theme` stores the CHOICE, not the painted theme. An absent value
   means System (the default for a new client); a previously saved 'light' or
   'dark' keeps its exact old meaning, so an owner who already picked Light is
   still on Light after this upgrade. */
(() => {
    'use strict';
    const KEY = 'ouroboros.theme';
    // Display order is the owner-facing order: Light / Dark / System.
    const CHOICES = ['light', 'dark', 'system'];
    const LABELS = { light: 'Light', dark: 'Dark', system: 'System' };
    const root = document.documentElement;
    const isChoice = (value) => CHOICES.includes(value);

    let choice = 'system';
    let storageAvailable = true;
    try {
        const saved = localStorage.getItem(KEY);
        if (isChoice(saved)) choice = saved;
    } catch { storageAvailable = false; }

    const query = typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-color-scheme: light)')
        : null;
    /* A host can stand in for the OS as the "System" source (the Telegram mini app follows
       Telegram's own colour scheme, which can differ from the OS: host_telegram.js). The
       source answers 'light', 'dark' or '' (defer to the OS query). Dark is the fallback when
       no one reports a preference. */
    let systemSource = null;
    const systemScheme = () => {
        const answer = systemSource ? systemSource() : '';
        if (answer === 'light' || answer === 'dark') return answer;
        return query?.matches ? 'light' : 'dark';
    };
    const resolve = (value) => (value === 'system' ? systemScheme() : value);
    let resolved = resolve(choice);

    const statusText = () => {
        if (!storageAvailable) return 'Appearance applies until this window reloads; this device blocks storage.';
        if (choice === 'system' && !query) return 'This client reports no OS appearance, so System uses Dark.';
        return '';
    };

    const fill = (host) => {
        host.classList.add('theme-choice-group');
        host.setAttribute('role', 'radiogroup');
        host.replaceChildren(...CHOICES.map((value) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'theme-choice';
            button.dataset.themeChoice = value;
            button.setAttribute('role', 'radio');
            button.textContent = LABELS[value];
            return button;
        }));
    };

    const controls = () => Array.from(document.querySelectorAll('[data-theme-control]'));

    const syncControls = () => {
        for (const host of controls()) {
            if (!host.querySelector('[data-theme-choice]')) fill(host);
            for (const button of host.querySelectorAll('[data-theme-choice]')) {
                const active = button.dataset.themeChoice === choice;
                button.classList.toggle('active', active);
                button.setAttribute('aria-checked', String(active));
                // Roving tabindex: the group is one tab stop, arrows move inside it.
                button.tabIndex = active ? 0 : -1;
            }
        }
        for (const status of document.querySelectorAll('[data-theme-status]')) {
            status.textContent = statusText();
        }
    };

    const paint = () => {
        root.dataset.theme = resolved;
        root.dataset.themeChoice = choice;
        syncControls();
    };

    /* The shell's one layout switch (docs/DESIGN.md "Shell"): `docked` keeps the
       sidebar as a column from LAYOUT.dockedMinWidth up; `stack` below it folds the
       sidebar into a drawer and every room into a full-width layer. Written here,
       before CSS, so the first paint is already the right shell, and kept current by
       the window's own media-query change (a resize, a rotation). The number lives
       here once; web/modules/layout.js is the ES-module door everything else reads it
       through (tests/test_shell_layout_static.py). */
    const LAYOUT = Object.freeze({ dockedMinWidth: 720 });
    const layoutQuery = typeof window.matchMedia === 'function'
        ? window.matchMedia(`(min-width: ${LAYOUT.dockedMinWidth}px)`)
        : null;
    // A client that cannot answer the query is a desktop window: docked.
    const resolveLayout = () => (layoutQuery && !layoutQuery.matches ? 'stack' : 'docked');
    let layout = resolveLayout();
    const paintLayout = () => { root.dataset.layout = layout; };
    const onLayoutQuery = () => {
        const next = resolveLayout();
        if (next === layout) return;
        layout = next;
        paintLayout();
        window.dispatchEvent(new CustomEvent('ouro:layout-changed', { detail: { layout } }));
    };
    paintLayout();
    layoutQuery?.addEventListener?.('change', onLayoutQuery);
    window.ouroLayout = Object.freeze({ ...LAYOUT, get layout() { return layout; } });

    /* The desktop window's ordinary system caption takes the light or dark tint of
       the painted palette (launcher_appearance.py). Only a top-level document speaks
       for its window: a framed copy (the onboarding overlay) never drives its
       parent's frame. pywebview runs each bridge call on its own thread, so calls
       can arrive out of order, even a replaced page's after its successor's: each
       carries when this document became the window's page (its time origin on the
       browser's monotonic clock, renewed when the back-forward cache restores it)
       and its count there, and the launcher keeps only a request newer by that
       pair. A browser, or a desktop app built before the bridge, has none. */
    const ownsWindow = (() => { try { return window.top === window; } catch { return false; } })();
    const clock = window.performance;
    let pageSince = clock?.timeOrigin;
    let nativeSequence = 0;
    const syncNativeFrame = () => {
        const api = ownsWindow ? window.pywebview?.api : null;
        if (typeof api?.set_native_appearance !== 'function') return;
        nativeSequence += 1;
        try {
            Promise.resolve(api.set_native_appearance(resolved, pageSince, nativeSequence)).catch(() => {});
        } catch { /* the frame keeps its tint; the page is unaffected */ }
    };
    // Restored from the back-forward cache after a newer page: this one is the window's again.
    const onPageShow = (event) => {
        if (!event.persisted || !clock) return;
        pageSince = clock.timeOrigin + clock.now();
        syncNativeFrame();
    };

    // Re-resolve, repaint, and tell mounted views only when the PAINTED theme
    // moved. Switching Dark -> System on a dark OS changes the choice without
    // changing a single colour, and must not churn charts or diagrams.
    const settle = () => {
        const next = resolve(choice);
        const changed = next !== resolved;
        resolved = next;
        paint();
        if (changed) {
            syncNativeFrame();
            window.dispatchEvent(new CustomEvent('ouro:theme-changed', { detail: { theme: resolved, choice } }));
        }
    };

    const choose = (value) => {
        if (!isChoice(value)) return;
        choice = value;
        try { localStorage.setItem(KEY, choice); storageAvailable = true; }
        catch { storageAvailable = false; }
        settle();
    };

    paint();
    // The first paint announces nothing; the bridge, injected after load, hears it then.
    syncNativeFrame();

    const onClick = (event) => {
        const button = event.target.closest?.('[data-theme-choice]');
        if (button?.closest('[data-theme-control]')) choose(button.dataset.themeChoice);
    };

    const onKeydown = (event) => {
        const button = event.target.closest?.('[data-theme-choice]');
        if (!button?.closest('[data-theme-control]')) return;
        const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
        let next = '';
        if (step) next = CHOICES[(CHOICES.indexOf(choice) + step + CHOICES.length) % CHOICES.length];
        else if (event.key === 'Home') next = CHOICES[0];
        else if (event.key === 'End') next = CHOICES[CHOICES.length - 1];
        else return;
        event.preventDefault();
        choose(next);
        button.closest('[data-theme-control]')?.querySelector(`[data-theme-choice="${next}"]`)?.focus();
    };

    // Another window of the same client (browser tab, or the desktop shell's
    // onboarding window next to the main one) wrote a new choice.
    const onStorage = (event) => {
        if (event.key !== KEY && event.key !== null) return;
        let saved = 'system';
        try {
            const raw = localStorage.getItem(KEY);
            if (isChoice(raw)) saved = raw;
            storageAvailable = true;
        } catch {
            storageAvailable = false;
            syncControls();
            return;
        }
        choice = saved;
        settle();
    };

    const onSystemChange = () => { if (choice === 'system') settle(); };

    const ready = () => syncControls();
    const cleanup = (event) => {
        if (event.persisted) return;
        document.removeEventListener('click', onClick);
        document.removeEventListener('keydown', onKeydown);
        document.removeEventListener('DOMContentLoaded', ready);
        window.removeEventListener('storage', onStorage);
        window.removeEventListener('pywebviewready', syncNativeFrame);
        window.removeEventListener('pageshow', onPageShow);
        window.removeEventListener('pagehide', cleanup);
        query?.removeEventListener?.('change', onSystemChange);
        layoutQuery?.removeEventListener?.('change', onLayoutQuery);
    };
    document.addEventListener('click', onClick);
    document.addEventListener('keydown', onKeydown);
    document.addEventListener('DOMContentLoaded', ready, { once: true });
    window.addEventListener('storage', onStorage);
    if (ownsWindow) {
        window.addEventListener('pywebviewready', syncNativeFrame);
        window.addEventListener('pageshow', onPageShow);
    }
    window.addEventListener('pagehide', cleanup);
    query?.addEventListener?.('change', onSystemChange);

    /* Views rendered after boot (the Settings page is injected by app.js) call
       mount() once their markup is in the document; the delegated handlers above
       already work, mount() only paints the current state into fresh buttons. */
    window.ouroTheme = {
        get choice() { return choice; },
        get theme() { return resolved; },
        set: choose,
        mount: syncControls,
        /* The host's System source: install (settles at once), returns its release. */
        setSystemSource(source) {
            systemSource = typeof source === 'function' ? source : null;
            settle();
            return () => { if (systemSource === source) { systemSource = null; settle(); } };
        },
        /* The installed source changed its answer (Telegram's themeChanged). */
        refreshSystem: () => { if (choice === 'system') settle(); },
    };
})();

/* Interface size on a touch screen (docs/DESIGN.md "Appearance"; web/modules/interface_size.js owns the setting).
   A phone's own page zoom is its viewport: the meta's layout width (`width = the width at 100 % ÷ scale`,
   `initial-scale = scale`) lays the page out narrower or wider and the screen shows it at the owner's size, with every
   length, query and coordinate still in one CSS pixel (CSS `zoom` on the page instead pushed the composer off screen).
   Written here, before CSS, so the first layout already has the stored size. A host that ignores the meta (a Mini App
   in Telegram for Android, a desktop engine, a frame inside another page) keeps 100 %: a size is kept only once the
   layout width really became the one asked for. Per device, like the theme. */
(() => {
    'use strict';
    const KEY = 'ouroboros.interface-size';
    const STEP = 5;
    const MIN = 75;      // smaller, a finger's targets fall far under their 44 px
    const FLOOR = 320;   // never laid out narrower than this many CSS px (WCAG 1.4.10's reflow width)
    const meta = document.querySelector?.('meta[name="viewport"]') || null;
    const original = meta?.getAttribute('content') || '';
    const coarse = typeof window.matchMedia === 'function' && window.matchMedia('(pointer: coarse)').matches;
    const topLevel = (() => { try { return window.top === window; } catch { return false; } })();
    const listeners = new Set();
    let base = 0;       // the layout width at 100 %, in CSS px
    let percent = 100;  // the size in effect
    let state = meta && coarse && topLevel && typeof requestAnimationFrame === 'function' ? 'pending' : 'unavailable';
    let generation = 0;

    const stored = () => {
        try {
            const value = Number(localStorage.getItem(KEY));
            return Number.isFinite(value) && value > 0 ? value : 100;
        } catch { return 100; }
    };
    const store = (value) => {
        try { if (value === 100) localStorage.removeItem(KEY); else localStorage.setItem(KEY, String(value)); }
        catch { /* the size holds until the page reloads */ }
    };
    const width = () => Number(document.documentElement.clientWidth) || Number(window.innerWidth) || 0;
    const max = () => Math.max(100, Math.floor(((base / FLOOR) * 100) / STEP) * STEP);
    const clamp = (value) => Math.min(max(), Math.max(MIN, Math.round(Number(value) / STEP) * STEP));
    const asked = (value) => Math.round(base / (value / 100));
    const frames = () => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)));
    const notify = () => { for (const listener of listeners) { try { listener(); } catch { /* one view's fault */ } } };
    const write = (value) => {
        meta.setAttribute('content', value === 100 ? original
            : `width=${asked(value)}, initial-scale=${value / 100}, viewport-fit=cover`);
        // The touch field guard keeps a field's text at 16 device px whatever the size (style.css).
        document.documentElement.style.setProperty('--interface-scale', String(value / 100));
    };

    /* Apply `value` %, keeping it only if the host laid the page out at the width asked for. */
    const apply = async (value) => {
        if (state === 'unavailable') return state;
        const mine = ++generation;
        const next = clamp(value);
        write(next);
        await frames();
        if (mine !== generation) return state;
        if (next !== 100 && Math.abs(width() - asked(next)) > 2) {
            write(100);
            percent = 100;
            state = 'unavailable';  // this host ignores the meta: 100 % stays, and the control says so
        } else {
            percent = next;
            state = 'active';
        }
        notify();
        return state;
    };

    /* A rotation or a new window width changes the width at 100 %: measure it again at 100 %, then reapply. */
    const remeasure = async () => {
        if (state === 'unavailable') return;
        const keep = percent;
        const mine = ++generation;
        write(100);
        await frames();
        if (mine !== generation) return;
        base = width();
        if (keep !== 100) await apply(keep);
        else notify();
    };

    if (state === 'pending') {
        base = width();
        const wanted = stored();
        if (wanted === 100) {
            state = 'active';
        } else {
            apply(wanted);
        }
        window.matchMedia('(orientation: portrait)')?.addEventListener?.('change', () => { remeasure(); });
    }

    window.ouroViewportScale = {
        get state() { return state; },  // 'active' | 'pending' | 'unavailable'
        get percent() { return percent; },
        get min() { return MIN; },
        get max() { return base ? max() : 100; },
        get step() { return STEP; },
        async set(value) {
            const next = await apply(value);
            if (next === 'active') store(percent);
            return next;
        },
        subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    };
})();
