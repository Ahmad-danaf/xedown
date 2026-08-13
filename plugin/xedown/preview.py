"""WebKit-backed preview surface. Owns the WebView and its handlers."""

import json
import urllib.parse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import GLib, Gtk, WebKit2

from . import a11y

_MESSAGE_HANDLER = "xedown"


class PreviewView:
    """Wraps a WebView. Not a widget subclass — `widget` is the thing to pack."""

    # A code block larger than this is a pathology, not a copy. Refused
    # rather than shipped through the message channel and into the
    # clipboard, and reported as a failure so the button says so.
    MAX_COPY_CHARS = 1024 * 1024

    def __init__(self, on_link=None, on_image_error=None, on_search=None):
        self.on_link = on_link
        self.on_image_error = on_image_error
        self.on_search = on_search
        self.last_scroll = 0.0
        self._loaded = False
        self._pending_scroll = 0.0
        # The live search, remembered so a full page load can re-issue it: a
        # fresh page is a fresh JS context and knows nothing about it. Body
        # swaps need no help -- preview.js re-applies the search itself.
        self._search_request = None
        # Whichever of the page's own "ready" message or LoadEvent.FINISHED
        # arrives first does the post-load work; the other is then a no-op.
        # Reset on every load_document, not only here, or the second document
        # loaded into this view would never restore its scroll.
        self._settled = False

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

        accessible = self.widget.get_accessible()
        if accessible is not None:
            # Focus lands here on every switch into Preview, so this name is
            # what a screen reader reads out at the moment the mode changes.
            # It is the mode announcement -- see the design's section 3.3.
            accessible.set_name(a11y.NAMES["preview"])

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
            "context-menu", self._on_context_menu
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
        self._settled = False
        self.widget.load_html(html, base_uri)

    def update_body(self, fragment_html, text_direction=None):
        """Swap the body in place, preserving scroll, without a reload.

        The direction travels with the fragment rather than through a setter
        of its own: under `auto` it is decided by the content, so a body that
        changes can change it, and the two must never be applied a frame
        apart. `None` leaves the loaded page's own direction alone.
        """
        script = (
            "if (window.xedown) { window.xedown.replaceBody("
            + json.dumps(fragment_html)
            + ", "
            + json.dumps(text_direction)
            + "); }"
        )
        self._run(script)

    def set_scroll(self, fraction):
        self._run(
            f"if (window.xedown) {{ window.xedown.setScroll({json.dumps(fraction)}); }}"
        )

    def set_metrics(self, width_rem, size_px):
        """Apply a content width and text size to the loaded page, in place.

        No reload: these are two custom properties the stylesheet already
        reads. CSP's `style-src` governs inline styles the HTML parser
        encounters, not programmatic CSSOM writes, so the nonce-only policy
        permits this — the integration probe reads the computed value back
        out of the page to keep that an observation rather than a claim.
        """
        script = (
            "if (window.xedown) { window.xedown.setMetrics("
            + json.dumps(float(width_rem))
            + ", "
            + json.dumps(float(size_px))
            + "); }"
        )
        self._run(script)

    def set_config(self, code_copy_buttons, image_display):
        """Tell an already-loaded page what the settings now say.

        The same two values a fresh page receives in its `window.xedownConfig`
        block, so the two routes cannot disagree. No reload: copy buttons are
        added or removed in place, and the image display mode only affects
        the client-side fallback, since the body itself is re-rendered by the
        controller.
        """
        payload = json.dumps(
            {"codeCopy": bool(code_copy_buttons), "imageFallback": str(image_display)}
        )
        self._run(f"if (window.xedown) {{ window.xedown.setConfig({payload}); }}")

    def set_image_message(self, src, text):
        """Tell the page why one image did not load."""
        self._run(
            "if (window.xedown) { window.xedown.setImageMessage("
            + json.dumps(src)
            + ", "
            + json.dumps(text)
            + "); }"
        )

    def scroll_to_anchor(self, anchor):
        self._run(
            f"if (window.xedown) {{ window.xedown.scrollToAnchor({json.dumps(anchor)}); }}"
        )

    def search(self, query, case_sensitive, token):
        """Ask the page to mark `query`. The count comes back as a message.

        `run_javascript` cannot be awaited, which is why the token travels
        with the request and comes back with the answer: without it the count
        for `he` can arrive after the count for `hell` and overwrite it.
        """
        self._search_request = (query, bool(case_sensitive), int(token))
        self._run(
            "if (window.xedown) { window.xedown.search("
            + json.dumps(query)
            + ", "
            + json.dumps(bool(case_sensitive))
            + ", "
            + json.dumps(int(token))
            + "); }"
        )

    def rearm_search(self, query, case_sensitive, token):
        """Update the pending-request bookkeeping without touching the page.

        Used when the page a request would go to is already on its way out
        (an error page about to replace it): there is nothing to usefully
        ask right now, and `search()` would ask it anyway -- `load_html`'s
        navigation is asynchronous, so at the moment this is called the OLD
        page can still be the one actually loaded, and `search()`'s
        immediate `run_javascript` would land on it, not on nothing. That
        produces a real answer for a page that is already gone, tagged with
        the token this request is arming -- which is exactly the token the
        session will accept, so it would overwrite the "no matches" answer
        this call exists to protect. Setting `_search_request` directly,
        with no page interaction, is what makes the *next* page's own
        `LoadEvent.FINISHED` reissue this request with a current token
        (see `_on_load_changed` below), without asking the current page
        anything at all.
        """
        self._search_request = (query, bool(case_sensitive), int(token))

    def set_search_index(self, index):
        """Make match `index` the current one, and scroll it into view."""
        self._run(
            "if (window.xedown) { window.xedown.setSearchIndex("
            + json.dumps(int(index))
            + "); }"
        )

    def clear_search(self):
        """Take every mark back out of the page."""
        self._search_request = None
        self._run("if (window.xedown) { window.xedown.clearSearch(); }")

    def copy_selection(self):
        """Copy the page's selection, on xedown's behalf.

        Runs in the UI process, which is what keeps the existing restriction
        intact: `javascript-can-access-clipboard` stays off and nothing in
        the page gains clipboard access of its own. The code-block copy
        channel above exists precisely because the page has none, and is
        untouched by this.
        """
        self.widget.execute_editing_command(WebKit2.EDITING_COMMAND_COPY)

    def select_all(self):
        """Select the rendered document."""
        self.widget.execute_editing_command(WebKit2.EDITING_COMMAND_SELECT_ALL)

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
        elif kind == "search" and self.on_search is not None:
            try:
                count = int(payload.get("count") or 0)
                token = int(payload.get("token") or 0)
            except (TypeError, ValueError):
                return
            self.on_search(count, bool(payload.get("capped")), token)
        elif kind == "copy":
            self._copy_to_clipboard(payload.get("token"), payload.get("text"))
        elif kind == "ready":
            self._on_page_ready()

    def _copy_to_clipboard(self, token, text):
        """Put a code block on the clipboard on the page's behalf.

        The page has no clipboard access of its own — `javascript-can-access-
        clipboard` stays off, so nothing running in the preview can read or
        write it — which makes this the only route, and it is one-way:
        xedown writes what the page asked to copy and never reads anything
        back out.

        Failure is answered, never raised: the button says "Copy failed"
        rather than sitting on "Copy" as though the click did nothing.
        """
        ok = False
        if isinstance(text, str) and len(text) <= self.MAX_COPY_CHARS:
            try:
                clipboard = Gtk.Clipboard.get_default(self.widget.get_display())
                clipboard.set_text(text, -1)
                ok = True
            except Exception:  # noqa: BLE001 - a failed copy is reported, not raised
                ok = False
        self.copy_result(token, ok)

    def copy_result(self, token, ok):
        """Tell the page how its copy went, so the button can confirm it."""
        self._run(
            "if (window.xedown) { window.xedown.copyResult("
            + json.dumps(token)
            + ", "
            + json.dumps(bool(ok))
            + "); }"
        )

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
            self.on_link(self._as_link_target(uri))
        return True

    def _on_context_menu(self, _view, menu, _event, hit_test):
        """A reading menu, not a browser's.

        Rebuilt from empty rather than filtered: WebKit's default menu grows
        entries between versions, and a filter would quietly let a new one
        through. Copy only when there is something selected to copy; nothing
        for links, images, frames, navigation or developer tools.
        """
        menu.remove_all()
        if hit_test.context_is_selection():
            menu.append(
                WebKit2.ContextMenuItem.new_from_stock_action(
                    WebKit2.ContextMenuAction.COPY
                )
            )
        menu.append(
            WebKit2.ContextMenuItem.new_from_stock_action(
                WebKit2.ContextMenuAction.SELECT_ALL
            )
        )
        return False

    def _as_link_target(self, uri):
        """Recover a bare `#fragment` for an in-page anchor click.

        WebKit never delivers `href="#section"` back verbatim: it resolves
        the link against the page's own URI first, so `on_link` would
        otherwise see something like `file:///…/docs/#section` (or, for an
        unsaved document, `about:blank#section`) — indistinguishable from a
        link to a different page at first glance, and in fact misclassified
        as one by `classify_link`, which only recognises a leading `#`.

        A same-document navigation is detected by comparing `uri` and the
        WebView's current URI with any fragment stripped; when they match,
        the bare fragment (possibly empty, for a link to the page itself or
        a lone `#`) is handed back so the existing anchor-scrolling path can
        take over instead.
        """
        base = self.widget.get_uri() or "about:blank"
        stripped_uri, fragment = urllib.parse.urldefrag(uri)
        stripped_base, _base_fragment = urllib.parse.urldefrag(base)
        if stripped_uri == stripped_base:
            return "#" + fragment
        return uri

    def _on_load_changed(self, _view, load_event):
        if load_event == WebKit2.LoadEvent.FINISHED:
            self._on_page_ready()

    def _on_page_ready(self):
        """Restore scroll and re-issue a search, once per load.

        Driven by whichever arrives first: the page's own DOMContentLoaded
        message, or `LoadEvent.FINISHED`. They are not interchangeable --
        FINISHED waits for every subresource, so a remote image still in
        flight would hold back the scroll restore for as long as the fetch
        takes.
        """
        if self._settled:
            return
        self._settled = True
        self.set_scroll(self._pending_scroll)
        self._pending_scroll = 0.0
        # A reload (theme change, revert, external change) replaced the JS
        # context, so a search that is still live has to be asked for
        # again -- the page has no memory of it.
        if self._search_request is not None:
            self.search(*self._search_request)

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
        self.on_search = None
        self._search_request = None
        self.widget.destroy()
