"""The find bar under the preview. Emits signals; holds no policy of its own.

Everything it displays was decided in `search.py`, and everything it reports is
a raw event. The one thing it owns is being operable: names on every control,
Enter and Shift+Enter on the entry, and Escape leaving.
"""

from typing import ClassVar

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Gdk, GObject, Gtk

from . import a11y


class SearchBar(Gtk.Box):
    """Entry, case toggle, two steps, a count and a close. Nothing else."""

    __gtype_name__ = "XedownSearchBar"

    __gsignals__: ClassVar = {
        "query-changed": (GObject.SignalFlags.RUN_FIRST, None, (str, bool)),
        "step-requested": (GObject.SignalFlags.RUN_FIRST, None, (bool,)),
        "close-requested": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)

        # A separator rather than a CSS border: this widget installs no style
        # provider of its own, so it cannot fight the user's GTK theme.
        self.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0
        )

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_border_width(4)
        self.pack_start(row, False, False, 0)

        self._entry = Gtk.SearchEntry()
        # GtkSearchEntry brings its own ~150 ms debounce on `search-changed`
        # and its own clear icon, which is why it is used rather than a plain
        # entry with a timer bolted on.
        self._entry.set_width_chars(28)
        self._entry.set_placeholder_text(a11y.NAMES["search_entry"])
        self._name(self._entry, a11y.NAMES["search_entry"])
        self._entry.connect("search-changed", self._on_changed)
        self._entry.connect("activate", self._on_activate)
        self._entry.connect("key-press-event", self._on_entry_key)
        self._entry.connect("stop-search", self._on_stop)
        row.pack_start(self._entry, False, False, 0)

        self._case = Gtk.ToggleButton(label="Aa")
        self._case.set_tooltip_text(a11y.NAMES["search_case"])
        self._name(self._case, a11y.NAMES["search_case"])
        self._case.connect("toggled", self._on_changed)
        row.pack_start(self._case, False, False, 0)

        self._previous = self._step_button(
            "go-up-symbolic", "‹", a11y.NAMES["search_previous"], False
        )
        row.pack_start(self._previous, False, False, 0)
        self._next = self._step_button(
            "go-down-symbolic", "›", a11y.NAMES["search_next"], True
        )
        row.pack_start(self._next, False, False, 0)

        self._status = Gtk.Label(label="")
        self._status.set_xalign(0.0)
        self._name(self._status, "Match count")
        row.pack_start(self._status, False, False, 6)

        close = self._icon_button(
            "window-close-symbolic", "×", a11y.NAMES["search_close"]
        )
        close.connect("clicked", self._on_stop)
        row.pack_end(close, False, False, 0)

        # Shown child by child, then the bar itself is hidden and pinned: the
        # same mitigation the mode bar's refresh button and the WebView carry,
        # because xed forces widgets visible on save and revert and a stray
        # show_all() on the tab must not raise a search bar nobody asked for.
        self.show_all()
        self.set_no_show_all(True)
        self.hide()

    # --- construction ------------------------------------------------------

    @staticmethod
    def _name(widget, name):
        """An accessible name, which a tooltip is not."""
        accessible = widget.get_accessible()
        if accessible is not None:
            accessible.set_name(name)

    def _icon_button(self, icon_name, fallback, name):
        button = Gtk.Button()
        theme = Gtk.IconTheme.get_default()
        if theme is not None and theme.has_icon(icon_name):
            button.add(Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.MENU))
        else:
            button.add(Gtk.Label(label=fallback))
        button.set_tooltip_text(name)
        self._name(button, name)
        return button

    def _step_button(self, icon_name, fallback, name, forward):
        button = self._icon_button(icon_name, fallback, name)
        button.connect("clicked", self._on_step, forward)
        return button

    # --- what the controller asks ------------------------------------------

    def set_status(self, text):
        self._status.set_text(text or "")

    def get_query(self):
        return self._entry.get_text() or ""

    def get_case_sensitive(self):
        return self._case.get_active()

    def set_query(self, text):
        """Put a query in the entry as though it had been typed.

        Exists for the integration probe, which has no keyboard to type with;
        it goes through the entry so the same `search-changed` path runs.
        """
        self._entry.set_text(text or "")

    def set_case_sensitive(self, active):
        """Move the case toggle as though it had been clicked."""
        self._case.set_active(bool(active))

    def focus_entry(self):
        """Focus the entry with its text selected, so typing replaces it."""
        self._entry.grab_focus()
        self._entry.select_region(0, -1)

    def owns_focus(self, widget):
        """True when `widget` is this bar's entry.

        This is what tells xedown's own entry apart from xed's find bar for
        `shortcuts.route_key`: both are GtkEditables, and only one of them is
        ours. Deliberately narrower than `contains_focus` below: the question
        it answers is "is the focused editable ours", and only the entry is
        an editable at all.
        """
        return widget is self._entry

    def contains_focus(self, widget):
        """True when `widget` is this bar or any part of it.

        The controller asks this to decide whether the focus xed just took
        away was the user's own place in the search -- which the case toggle,
        the two step buttons and the close button all are, just as much as
        the entry. Asked of the bar rather than reasoned about from outside,
        so the answer follows this widget's own structure.
        """
        return widget is not None and (widget is self or widget.is_ancestor(self))

    # --- what the widgets report -------------------------------------------

    def _on_changed(self, *_args):
        self.emit("query-changed", self.get_query(), self.get_case_sensitive())

    def _on_activate(self, *_args):
        self.emit("step-requested", True)

    def _on_step(self, _button, forward):
        self.emit("step-requested", forward)

    def _on_stop(self, *_args):
        self.emit("close-requested")

    def _on_entry_key(self, _entry, event):
        """Shift+Enter is the only key the entry does not already handle.

        `activate` fires for Return whether or not Shift is held, so the
        backward step has to be caught before it gets there.
        """
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        if not event.state & Gdk.ModifierType.SHIFT_MASK:
            return False
        self.emit("step-requested", False)
        return True
