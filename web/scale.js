(() => {
    'use strict';
    const key = 'ouroboros.scale';
    const choices = ['70', '80', '90', '100', '110', '120'];
    let value = 'system';
    const read = () => {
        try {
            const saved = localStorage.getItem(key);
            return choices.includes(saved) ? saved : 'system';
        } catch { return 'system'; }
    };
    const paint = () => {
        document.documentElement.dataset.uiScale = value;
        for (const control of document.querySelectorAll('[data-ui-scale]')) control.value = value;
        for (const label of document.querySelectorAll('[data-ui-scale-label]')) label.textContent = value === 'system' ? 'System' : `${value}%`;
    };
    const change = (event) => {
        if (!event.target.matches?.('[data-ui-scale]') || ![...choices, 'system'].includes(event.target.value)) return;
        value = event.target.value;
        try {
            if (value === 'system') localStorage.removeItem(key);
            else localStorage.setItem(key, value);
        } catch { }
        paint();
        window.dispatchEvent(new Event('resize'));
    };
    const storage = (event) => {
        if (event.key !== key && event.key !== null) return;
        value = read();
        paint();
        window.dispatchEvent(new Event('resize'));
    };
    const click = (event) => {
        const button = event.target.closest?.('[data-ui-scale-step]');
        if (!button) return;
        const step = button.dataset.uiScaleStep;
        const index = choices.indexOf(value === 'system' ? '100' : value);
        const next = step === 'reset' ? 'system' : choices[Math.max(0, Math.min(choices.length - 1, index + Number(step)))];
        change({ target: { value: next, matches: () => true } });
    };
    const cleanup = (event) => {
        if (event.persisted) return;
        document.removeEventListener('change', change);
        document.removeEventListener('click', click);
        window.removeEventListener('storage', storage);
        window.removeEventListener('pagehide', cleanup);
    };
    value = read();
    paint();
    window.ouroScale = { mount: paint };
    document.addEventListener('change', change);
    document.addEventListener('click', click);
    window.addEventListener('storage', storage);
    window.addEventListener('pagehide', cleanup);
})();
