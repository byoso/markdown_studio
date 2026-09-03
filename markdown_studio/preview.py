"""Live HTML preview of the Markdown being edited, rendered via WebKit2Gtk.

To avoid the flicker of reloading the whole page on every keystroke, a static
"shell" page is loaded once (see `markdown_renderer.render_shell_html`), and
further updates patch `#md-content` in place via `run_javascript`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk as gtk, GObject, WebKit2

from .markdown_renderer import render_shell_html


class PreviewPane(gtk.Box):
    __gsignals__ = {
        # Fired on user scroll inside the preview, with the scroll position as a 0..1 fraction.
        "scrolled": (GObject.SignalFlags.RUN_FIRST, None, (float,)),
    }

    # Posts the scroll fraction to Python whenever the page is scrolled, so the editor can follow.
    _SCROLL_LISTENER_SCRIPT = """
(function () {
    window.addEventListener('scroll', function () {
        var maxY = Math.max(1, document.body.scrollHeight - window.innerHeight);
        var pct = Math.min(1, Math.max(0, window.scrollY / maxY));
        window.webkit.messageHandlers.scrollSync.postMessage(pct);
    });
})();
"""

    def __init__(self):
        super().__init__(orientation=gtk.Orientation.VERTICAL)
        self.content_manager = WebKit2.UserContentManager()
        self.content_manager.register_script_message_handler("scrollSync")
        self.content_manager.connect("script-message-received::scrollSync", self._on_scroll_message)
        self.web_view = WebKit2.WebView.new_with_user_content_manager(self.content_manager)
        self.pack_start(self.web_view, True, True, 0)

        self._loaded_key: tuple | None = None
        self._ready = False
        self._pending_call: str | None = None
        self.web_view.connect("load-changed", self._on_load_changed)

    def refresh(
        self,
        css_href: str | None,
        base_path: str | Path,
        body_html: str,
        reset_scroll: bool,
        follow_bottom: bool,
        force_reload: bool = False,
    ) -> None:
        key = (css_href, str(base_path))
        if force_reload or key != self._loaded_key:
            self._load_shell(css_href, base_path)
            self._loaded_key = key
            reset_scroll = True
        self.set_content(body_html, reset_scroll=reset_scroll, follow_bottom=follow_bottom)

    def _load_shell(self, css_href: str | None, base_path: str | Path) -> None:
        if css_href:
            # Bust WebKit's resource cache so on-disk CSS edits show up immediately.
            css_href = f"{css_href}?t={time.time()}"
        html = render_shell_html(css_href=css_href)
        self._ready = False
        self.web_view.load_html(html, f"file://{base_path}/")

    def set_content(self, body_html: str, reset_scroll: bool, follow_bottom: bool) -> None:
        script = self._build_script(body_html, reset_scroll, follow_bottom)
        if self._ready:
            self.web_view.run_javascript(script, None, None)
        else:
            self._pending_call = script

    @staticmethod
    def _build_script(body_html: str, reset_scroll: bool, follow_bottom: bool) -> str:
        if reset_scroll:
            scroll_call = "window.scrollTo(0, 0);"
        elif follow_bottom:
            scroll_call = "window.scrollTo(0, document.body.scrollHeight);"
        else:
            scroll_call = ""
        return (
            f"document.getElementById('md-content').innerHTML = {json.dumps(body_html)};"
            f"{scroll_call}"
        )

    def _on_load_changed(self, _web_view, load_event) -> None:
        if load_event != WebKit2.LoadEvent.FINISHED:
            return
        self._ready = True
        self.web_view.run_javascript(self._SCROLL_LISTENER_SCRIPT, None, None)
        if self._pending_call is not None:
            self.web_view.run_javascript(self._pending_call, None, None)
            self._pending_call = None

    def _on_scroll_message(self, _content_manager, js_value) -> None:
        self.emit("scrolled", js_value.get_js_value().to_double())

    def scroll_to_percent(self, percent: float) -> None:
        script = f"window.scrollTo(0, {percent} * Math.max(1, document.body.scrollHeight - window.innerHeight));"
        if self._ready:
            self.web_view.run_javascript(script, None, None)
