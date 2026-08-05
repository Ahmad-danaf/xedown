"""WebKit-backed preview surface. Owns the WebView and its handlers."""

import json

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import GLib, WebKit2

_MESSAGE_HANDLER = "xedown"


class PreviewView:
    """Wraps a WebView. Not a widget subclass — `widget` is the thing to pack."""

    def __init__(self, on_link=None, on_image_error=None):
        self.on_link = on_link
        self.on_image_error = on_image_error
        self.last_scroll = 0.0
        self._loaded = False
        self._pending_scroll = 0.0

        self._content_manager = WebKit2.UserContentManager()
        self._content_manager.register_script_message_handler(_MESSAGE_HANDLER)
        self._message_handler_id = self._content_manager.connect(
            "script-message-received::" + _MESSAGE_HANDLER, self._on_script_message
        )

        self.widget = WebKit2.WebView.new_with_user_content_manager(
            self._content_manager
        )
        self.widget.set_hexpand(True)
        self.widget.set_vexpand(True)

        settings = self.widget.get_settings()
        settings.set_property("enable-javascript", True)
        settings.set_property("enable-developer-extras", False)
        settings.set_property("enable-html5-database", False)
        settings.set_property("enable-html5-local-storage", False)
        settings.set_property("enable-page-cache", False)
        settings.set_property("enable-write-console-messages-to-stdout", False)
        settings.set_property("javascript-can-access-clipboard", False)

        self._policy_handler_id = self.widget.connect(
            "decide-policy", self._on_decide_policy
        )
        self._context_menu_handler_id = self.widget.connect(
            "context-menu", lambda *_args: True
        )
        self._load_changed_handler_id = self.widget.connect(
            "load-changed", self._on_load_changed
        )

    # --- loading -----------------------------------------------------------

    def load_document(self, html, base_uri=None, restore_scroll=0.0):
        """Load a complete page. Resets scroll reporting.

        `load_html` is asynchronous, so a scroll fraction to apply once the
        new page is actually in the DOM is remembered here rather than set
        immediately — setting it right after this call would run against
        the outgoing page, not the one being loaded.
        """
        self.last_scroll = 0.0
        self._loaded = False
        self._pending_scroll = restore_scroll
        self.widget.load_html(html, base_uri)

    def update_body(self, fragment_html):
        """Swap the body in place, preserving scroll, without a reload."""
        script = f"if (window.xedown) {{ window.xedown.replaceBody({json.dumps(fragment_html)}); }}"
        self._run(script)

    def set_scroll(self, fraction):
        self._run(
            f"if (window.xedown) {{ window.xedown.setScroll({json.dumps(fraction)}); }}"
        )

    def scroll_to_anchor(self, anchor):
        self._run(
            f"if (window.xedown) {{ window.xedown.scrollToAnchor({json.dumps(anchor)}); }}"
        )

    def _run(self, script):
        try:
            self.widget.run_javascript(script, None, None, None)
        except GLib.Error:
            pass  # the view is being torn down

    # --- host callbacks ----------------------------------------------------

    def _on_script_message(self, _manager, message):
        try:
            payload = json.loads(message.get_js_value().to_string())
        except (ValueError, AttributeError):
            return
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "scroll":
            try:
                self.last_scroll = float(payload.get("value") or 0.0)
            except (TypeError, ValueError):
                pass
        elif kind == "imageError" and self.on_image_error is not None:
            self.on_image_error(payload.get("src") or "")

    def _on_decide_policy(self, _view, decision, decision_type):
        if decision_type != WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            return False
        action = decision.get_navigation_action()
        uri = action.get_request().get_uri()

        # The initial load_html navigation must proceed.
        if not self._loaded:
            self._loaded = True
            decision.use()
            return True

        decision.ignore()
        if self.on_link is not None:
            self.on_link(uri)
        return True

    def _on_load_changed(self, _view, load_event):
        if load_event == WebKit2.LoadEvent.FINISHED:
            self.set_scroll(self._pending_scroll)
            self._pending_scroll = 0.0

    # --- teardown ----------------------------------------------------------

    def destroy(self):
        for owner, handler_id in (
            (self.widget, self._policy_handler_id),
            (self.widget, self._context_menu_handler_id),
            (self.widget, self._load_changed_handler_id),
            (self._content_manager, self._message_handler_id),
        ):
            if handler_id:
                owner.disconnect(handler_id)
        self._policy_handler_id = None
        self._context_menu_handler_id = None
        self._load_changed_handler_id = None
        self._message_handler_id = None
        self._content_manager.unregister_script_message_handler(_MESSAGE_HANDLER)
        self.on_link = None
        self.on_image_error = None
        self.widget.destroy()
