"""The desktop window's page zoom: the owner's Interface size for this window (Settings → Appearance, ⌘/Ctrl + − 0).

The engine zooms the page the way a browser's Cmd+ does: the page is laid out in a narrower or wider viewport of CSS
pixels, so its media queries, viewport units and measured lengths stay in one coordinate space. A real WKWebView at
``pageZoom`` 1.25 reports innerWidth 880 of an 1100 pt window and devicePixelRatio 2.5, nothing overflowing; CSS
``zoom`` on the page instead made it taller than its window. macOS: WKWebView ``pageZoom`` (public since macOS 11) on
the main thread, then the title band is measured again (``launcher_window_chrome`` divides by ``pageZoom``).
Windows: the WebView2 control's ``ZoomFactor`` on the form's UI thread (a host value applies across navigations).
Linux: WebKitGTK's zoom level on the GTK main loop. Another backend reports no capability, and the page says the
window cannot change its size.

The app keeps the size in ``state/desktop_page_zoom.json`` so the next window opens at it before its first paint
(``before_show``): here the app's value is the setting, and the page reads it through ``shell_info`` and changes it
through the bridge. Bridge calls arrive on pywebview's worker threads, possibly out of order, so each carries when its
document became the window's page and its count there, as the caption tint's do (``launcher_appearance``): only a
request newer by that pair is kept.
"""

from __future__ import annotations

import json
import logging
import math
import pathlib
import sys
import threading
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("launcher.page_zoom")

PERCENT_MIN, PERCENT_MAX, PERCENT_STEP = 50, 200, 5
STATE_NAME = "desktop_page_zoom.json"


def clamp_percent(value: Any) -> Optional[int]:
    """A size in whole percent inside the window's range, on its 5 % grid; None when it is no number."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    stepped = int(round(number / PERCENT_STEP) * PERCENT_STEP)
    return max(PERCENT_MIN, min(PERCENT_MAX, stepped))


def _backend() -> str:
    if sys.platform == "darwin":
        return "cocoa"
    if sys.platform == "win32":
        return "edgechromium"
    if sys.platform.startswith("linux"):
        return "gtk"
    return ""


class PageZoom:
    """One window's page zoom: stored by the app, applied by its engine, changed by its page."""

    def __init__(self, state_dir: Callable[[], pathlib.Path] | None = None,
                 on_changed: Callable[[], None] | None = None) -> None:
        self._state_dir = state_dir or _default_state_dir
        self._on_changed = on_changed  # macOS: the title band is measured again after a change
        self._lock = threading.Lock()
        self._window: Any = None
        self._view: Any = None   # the engine's web view, once before_show found it
        self._form: Any = None   # Windows: the form whose UI thread owns the control
        self._kind = ""          # the backend that applies it ("" = no capability)
        self._percent = 100
        self._order: tuple[float, int] = (-math.inf, 0)
        self._closed = False

    # -- lifecycle -------------------------------------------------------------------------------------------------
    def attach(self, window: Any) -> None:
        """Register on ``window`` before ``webview.start``."""
        if window is None or not _backend():
            return
        self._window = window
        self._percent = self._load()
        window.events.before_show += self._before_show
        window.events.closed += self._close

    def _before_show(self) -> None:
        """pywebview ``before_show`` (synchronous, the GUI thread, before the first load): find the engine's view and
        give it the stored size, so the first paint is already at it."""
        kind = _backend()
        try:
            view, form = _find_view(kind, self._window)
        except Exception:
            log.info("No page zoom for this window: its web view is not reachable.", exc_info=True)
            return
        if view is None:
            return
        with self._lock:
            if self._closed:
                return
            self._view, self._form, self._kind, percent = view, form, kind, self._percent
        if percent != 100:
            self._apply_now(kind, view, percent / 100)

    def _close(self) -> None:
        with self._lock:
            self._closed = True
            self._view = self._form = None

    # -- the bridge ------------------------------------------------------------------------------------------------
    def info(self) -> Dict[str, Any]:
        """For ``shell_info``: whether this window can change its size, its range and its size now."""
        with self._lock:
            supported = bool(self._kind) and not self._closed
            return {"supported": supported, "min": PERCENT_MIN, "max": PERCENT_MAX, "step": PERCENT_STEP,
                    "percent": self._percent}

    def request(self, percent: Any, page: Any = None, sequence: Any = None) -> Dict[str, Any]:
        """The page's new size for this window: keep the newest request of the newest page, store it, apply it."""
        value = clamp_percent(percent)
        if value is None:
            return {"ok": False, "state": "invalid_size"}
        try:
            order = (float(page), int(sequence))
        except (TypeError, ValueError):
            return {"ok": False, "state": "invalid_order"}
        if not math.isfinite(order[0]):
            return {"ok": False, "state": "invalid_order"}
        with self._lock:
            if self._closed:
                return {"ok": False, "state": "closed"}
            if not self._kind:
                return {"ok": False, "state": "unsupported", "percent": self._percent}
            if order <= self._order:
                return {"ok": True, "state": "stale", "percent": self._percent}
            self._order, self._percent = order, value
            kind, view, form = self._kind, self._view, self._form
        self._store(value)
        scheduled = self._post(kind, view, form, value / 100)
        return {"ok": scheduled, "state": "scheduled" if scheduled else "unavailable", "percent": value}

    # -- engines ---------------------------------------------------------------------------------------------------
    def _post(self, kind: str, view: Any, form: Any, factor: float) -> bool:
        """Run the engine's write on the thread that owns the view."""
        try:
            if kind == "cocoa":
                from PyObjCTools import AppHelper

                AppHelper.callAfter(self._apply_now, kind, view, factor)
            elif kind == "edgechromium":
                from System import Action

                form.BeginInvoke(Action(lambda: self._apply_now(kind, view, factor)))
            elif kind == "gtk":
                from gi.repository import GLib

                GLib.idle_add(lambda: self._apply_now(kind, view, factor) and False)
            else:
                return False
            return True
        except Exception:
            log.warning("The window's size change could not be scheduled.", exc_info=True)
            return False

    def _apply_now(self, kind: str, view: Any, factor: float) -> bool:
        """The engine's own page zoom (on its GUI thread)."""
        with self._lock:
            if self._closed:
                return False
        try:
            if kind == "cocoa":
                view.setPageZoom_(factor)
            elif kind == "edgechromium":
                view.ZoomFactor = factor
            elif kind == "gtk":
                view.set_zoom_level(factor)
        except Exception:
            log.warning("The engine refused the window's size %.2f.", factor, exc_info=True)
            return False
        if kind == "cocoa" and self._on_changed is not None:
            try:
                self._on_changed()
            except Exception:
                log.debug("The title band was not measured again after a size change.", exc_info=True)
        return True

    # -- the stored size -------------------------------------------------------------------------------------------
    def _path(self) -> pathlib.Path:
        return pathlib.Path(self._state_dir()) / STATE_NAME

    def _load(self) -> int:
        try:
            value = clamp_percent(json.loads(self._path().read_text(encoding="utf-8")).get("percent"))
        except (OSError, ValueError, AttributeError):
            return 100
        return value if value is not None else 100

    def _store(self, percent: int) -> None:
        try:
            from ouroboros.utils import atomic_write_json

            path = self._path()
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, {"percent": percent})
        except Exception:
            log.warning("The window's size is not kept for the next launch.", exc_info=True)


def _default_state_dir() -> pathlib.Path:
    from ouroboros.config import DATA_DIR

    return pathlib.Path(DATA_DIR) / "state"


def _find_view(kind: str, window: Any) -> tuple[Any, Any]:
    """The engine's web view of ``window`` in the bundled pywebview, and the Windows form that owns it."""
    if window is None:
        return None, None
    if kind == "cocoa":
        from webview.platforms.cocoa import BrowserView

        view = BrowserView.instances[window.uid].webview
        return (view if hasattr(view, "setPageZoom_") else None), None
    if kind == "edgechromium":
        form = getattr(window, "native", None)
        view = getattr(form, "webview", None)
        if view is None or not hasattr(view, "ZoomFactor"):  # the legacy MSHTML control has no page zoom
            return None, None
        return view, form
    if kind == "gtk":
        import webview

        guilib = getattr(webview, "guilib", None)  # the Linux backend pywebview chose: GTK has a page zoom, Qt none here
        if not str(getattr(guilib, "__name__", "")).endswith(".gtk"):
            return None, None
        view = guilib.BrowserView.instances[window.uid].webview
        return (view if hasattr(view, "set_zoom_level") else None), None
    return None, None
