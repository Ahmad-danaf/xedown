"""The settings window's widgets. Needs the host — imports Gtk.

Two hosts, one panel. `SettingsPanel` is what libpeas-gtk embeds in the
plugin manager's own Preferences dialog, and what `SettingsWindow` puts in
ours. Everything the user must be able to reach — Restore defaults included —
lives inside the panel, because peas owns its dialog's action area and we
cannot add to it.

*What* the panel contains is `prefs.py`'s to say. This module only turns that
description into widgets and keeps them in step with the store.

Cleanup hangs off `GtkWidget::destroy` rather than off any window, because on
the peas path there is no lifecycle callback at all: peas creates the
extension, takes the widget, and destroys it with its dialog. `destroy` is the
only signal both hosts share.
"""

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import Atk, Gdk, GLib, Gtk, Pango

from . import a11y, errors, prefs, settings, stylewatcher

# Long enough that a four-tick drag on a spin button is one write and one
# render rather than four, short enough that letting go feels immediate.
# Enter, focus-out and the file chooser all commit without waiting for it.
SETTLE_MS = 300


class SettingsPanel(Gtk.Box):
    """Every xedown setting, bound live to the store in both directions."""

    __gtype_name__ = "XedownSettingsPanel"

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._store = settings.get_settings()
        self._controls = {}  # setting name -> the widget bound to it
        # A number row and a path row each sit in a box with something beside
        # them -- a unit label, a Browse button -- so the grid attaches the
        # box while the row stays bound to the control inside it.
        self._number_boxes = {}  # setting name -> box holding spin + unit
        self._path_boxes = {}  # setting name -> box holding entry + browse
        self._settle = {}  # setting name -> GLib source id
        self._entries = []  # (a11y key, widget), in build order
        # A control that lives *inside* a row -- the stylesheet Browse button
        # -- keyed by setting, so `_build_row` can put it in the entry list
        # where it physically sits instead of at the end.
        self._row_extras = {}
        self._extra_entries = []  # controls after every row, in build order
        self._theme_help = None
        # Set while writing store values into widgets, so a programmatic
        # change is never mistaken for the user turning a knob.
        self._loading = False
        # Exists even for a panel whose stylesheet row has not been reached
        # yet -- `_build_row` replaces this once it gets there.
        self._stylesheet_bar = None

        self._quarantine_bar = self._build_notice()
        self.pack_start(self._quarantine_bar, False, False, 0)
        self._save_bar = self._build_notice()
        self.pack_start(self._save_bar, False, False, 0)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_border_width(12)
        for group in prefs.GROUPS:
            content.pack_start(self._build_group(group), False, False, 0)
        content.pack_start(self._build_footer(), False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(420)
        scroller.add(content)
        self.pack_start(scroller, True, True, 0)

        self._load_all()
        self._settings_token = self._store.connect(self._on_settings_changed)
        # Connect before reading current(): the first connect is what
        # performs the initial load, so current() beforehand returns the
        # unset default rather than the live setting.
        self._watcher_token = stylewatcher.get_watcher().connect(
            self._on_stylesheet_changed
        )
        self._on_stylesheet_changed(stylewatcher.get_watcher().current())
        self._show_quarantine()
        self._after_commit()
        self.connect("destroy", self._on_destroy)
        self.show_all()

    # --- construction ------------------------------------------------------

    def _build_group(self, group):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        heading = Gtk.Label(label=group.title)
        heading.set_xalign(0.0)
        # Bold at 1.1 scale: the idiom xed's own preferences pages use, set
        # through Pango attributes rather than markup so the title is never
        # parsed as anything but text.
        attributes = Pango.AttrList()
        attributes.insert(Pango.attr_weight_new(Pango.Weight.BOLD))
        attributes.insert(Pango.attr_scale_new(1.1))
        heading.set_attributes(attributes)
        box.pack_start(heading, False, False, 0)

        grid = Gtk.Grid(column_spacing=12, row_spacing=6)
        grid.set_margin_start(12)
        # One column that takes the slack, so controls sit against the
        # trailing edge under either text direction without a hardcoded side.
        grid.set_column_homogeneous(False)
        box.pack_start(grid, False, False, 0)

        line = 0
        attachments = []
        for row in group.rows:
            line = self._build_row(attachments, row, line)
        # Attached last-first, deliberately. `Gtk.Grid` *prepends* each child,
        # so `get_children()` -- and with it the order ATK hands a screen
        # reader, and the order the live audit walks -- comes back reversed,
        # which for rows stacked top to bottom means bottom to top. Where a
        # child lands on screen is decided by the coordinates below and by
        # nothing else, so reversing the calls costs the layout nothing and
        # buys an accessible child order that matches what the user sees.
        for widget, left, top, width, height in reversed(attachments):
            grid.attach(widget, left, top, width, height)
        return box

    def _build_row(self, attachments, row, line):
        label = Gtk.Label(label=row.label)
        label.set_xalign(0.0)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        attachments.append((label, 0, line, 1, 1))

        control = self._build_control(row)
        control.set_halign(Gtk.Align.END)
        # Sets the LABELLED_BY relation, which is the reason to call this even
        # with no mnemonic in the label: the accessible name then comes from
        # the label the user is actually reading.
        label.set_mnemonic_widget(control)
        self._controls[row.setting] = control
        self._entries.append((row.key, control))
        # A Browse button belongs to the row it sits in, so it is recorded
        # here rather than after every row: it is the next thing the user
        # reaches after the entry beside it, and the audit compares this list
        # against the real tree.
        beside = self._row_extras.pop(row.setting, None)
        if beside is not None:
            self._entries.append(beside)
        # The box when the control has company, the control itself otherwise.
        attached = (
            self._path_boxes.get(row.setting)
            or self._number_boxes.get(row.setting)
            or control
        )
        attachments.append((attached, 1, line, 1, 1))
        line += 1

        help_label = self._build_help(row)
        if help_label is not None:
            attachments.append((help_label, 0, line, 2, 1))
            self._describe(control, help_label)
            line += 1

        if row.setting == settings.CUSTOM_STYLESHEET:
            self._stylesheet_bar = self._build_notice()
            attachments.append((self._stylesheet_bar, 0, line, 2, 1))
            line += 1
        return line

    def _build_help(self, row):
        """The dim explanation under a row, or None.

        `dim-label` is GTK's own class rather than a colour of ours: brief
        13's contrast gate measures xedown's CSS, and nothing in CI can
        measure the desktop theme, so the honest move is to add no colour
        surface at all.
        """
        text = row.help_text
        if text is None and row.setting == settings.PREVIEW_THEME:
            text = prefs.choice_help(row.setting, self._store.get(row.setting))
        if not text:
            return None
        label = Gtk.Label(label=text)
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        label.set_max_width_chars(52)
        label.get_style_context().add_class("dim-label")
        if row.setting == settings.PREVIEW_THEME:
            self._theme_help = label
        return label

    def _build_control(self, row):
        if row.kind == prefs.SWITCH:
            return self._build_switch(row)
        if row.kind == prefs.CHOICE:
            return self._build_choice(row)
        if row.kind == prefs.NUMBER:
            return self._build_number(row)
        return self._build_path(row)

    def _build_switch(self, row):
        control = Gtk.Switch()
        control.set_valign(Gtk.Align.CENTER)
        self._name(control, row.label)
        control.connect("notify::active", self._on_switch, row)
        return control

    def _build_choice(self, row):
        control = Gtk.ComboBoxText()
        for value, display in row.choices:
            control.append(value, display)
        self._name(control, row.label)
        control.connect("changed", self._on_choice, row)
        return control

    def _build_number(self, row):
        minimum, maximum, _integer = prefs.bounds(row)
        adjustment = Gtk.Adjustment(
            # `value` matters: without it the adjustment starts at 0, which is
            # below every one of our minimums. `_load_all` overwrites it a
            # moment later, but not before GTK has warned about it.
            value=minimum,
            lower=minimum,
            upper=maximum,
            step_increment=row.step,
            page_increment=row.page_step,
        )
        spin = Gtk.SpinButton(adjustment=adjustment, digits=0)
        # `numeric` refuses letters outright and the adjustment clamps on
        # commit, so the field snaps visibly to the limit. That is the
        # brief's "enforce the limit rather than silently correct it later".
        spin.set_numeric(True)
        # Whole steps only, so what the field displays is what it holds. A
        # hand-edited 46.5 still *displays* as 46 without being written back
        # -- `set_value` does not snap, only a user edit does.
        spin.set_snap_to_ticks(True)
        spin.set_width_chars(6)
        self._name(spin, row.label)
        spin.connect("value-changed", self._on_number, row)
        spin.connect("activate", self._commit_now, row)
        spin.connect("focus-out-event", self._on_focus_out, row)

        if row.unit is None:
            return spin
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(spin, False, False, 0)
        unit = Gtk.Label(label=row.unit)
        unit.get_style_context().add_class("dim-label")
        box.pack_start(unit, False, False, 0)
        # The spin button is what the row is bound to and what the audit
        # walks; the box is only how the unit sits beside it.
        box.set_halign(Gtk.Align.END)
        self._number_boxes[row.setting] = box
        return spin

    def _build_path(self, row):
        entry = Gtk.Entry()
        entry.set_width_chars(24)
        entry.set_hexpand(False)
        entry.set_icon_from_icon_name(
            Gtk.EntryIconPosition.SECONDARY, "edit-clear-symbolic"
        )
        entry.set_icon_tooltip_text(Gtk.EntryIconPosition.SECONDARY, "Clear")
        self._name(entry, row.label)
        entry.connect("changed", self._on_text, row)
        entry.connect("activate", self._commit_now, row)
        entry.connect("focus-out-event", self._on_focus_out, row)
        entry.connect("icon-release", self._on_clear, row)

        browse = Gtk.Button(label="Browse…")
        browse_name = a11y.NAMES["prefs_stylesheet_browse"]
        browse.set_tooltip_text(browse_name)
        self._name(browse, browse_name)
        browse.connect("clicked", self._on_browse, row, entry)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(entry, False, False, 0)
        box.pack_start(browse, False, False, 0)
        box.set_halign(Gtk.Align.END)
        self._path_boxes[row.setting] = box
        self._row_extras[row.setting] = ("prefs_stylesheet_browse", browse)
        return entry

    def _on_browse(self, button, row, entry):
        """Pick a stylesheet. Commits on accept, changes nothing on cancel."""
        dialog = Gtk.FileChooserDialog(
            title=a11y.NAMES["prefs_stylesheet_browse"],
            transient_for=button.get_toplevel(),
            action=Gtk.FileChooserAction.OPEN,
        )
        dialog.set_modal(True)
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, "_Select", Gtk.ResponseType.ACCEPT
        )
        css = Gtk.FileFilter()
        css.set_name("Stylesheets")
        css.add_pattern("*.css")
        dialog.add_filter(css)
        every = Gtk.FileFilter()
        every.set_name("All files")
        every.add_pattern("*")
        dialog.add_filter(every)
        current = entry.get_text().strip()
        if current:
            dialog.set_filename(current)
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                entry.set_text(dialog.get_filename() or "")
                self._commit_now(entry, row)
        finally:
            dialog.destroy()

    def _build_footer(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name = a11y.NAMES["prefs_restore_defaults"]
        self._restore = Gtk.Button(label=name + "…")
        self._name(self._restore, name)
        self._restore.connect("clicked", self._on_restore)
        # Inside the panel, not in an action area: peas owns its dialog's
        # buttons, so anything out there would exist on one entry point and
        # not the other.
        box.pack_end(self._restore, False, False, 0)
        self._extra_entries.append(("prefs_restore_defaults", self._restore))
        return box

    def _on_restore(self, button):
        dialog = Gtk.MessageDialog(
            transient_for=button.get_toplevel(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text="Restore all xedown settings to their defaults?",
        )
        dialog.format_secondary_text(
            "This affects every open preview. Your custom stylesheet will be "
            "forgotten — the file itself is not deleted."
        )
        dialog.add_buttons(
            "_Cancel", Gtk.ResponseType.CANCEL, "_Restore", Gtk.ResponseType.ACCEPT
        )
        try:
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                # One set_many, so one write and one broadcast carrying every
                # name that moved. Every panel and every controller follows.
                self._store.reset()
                self._after_commit()
        finally:
            dialog.destroy()

    @staticmethod
    def _name(widget, name):
        """An accessible name, which a tooltip is not."""
        accessible = widget.get_accessible()
        if accessible is not None:
            accessible.set_name(name)

    @staticmethod
    def _describe(control, help_label):
        """Attach the help line as the control's description.

        A relation rather than a tooltip, so a reader delivers it after the
        label instead of leaving it as text floating near the control.
        """
        target = control.get_accessible()
        source = help_label.get_accessible()
        if target is None or source is None:
            return
        target.add_relationship(Atk.RelationType.DESCRIBED_BY, source)

    # --- what the panel offers ---------------------------------------------

    def accessible_entries(self):
        """`[(a11y key, widget), …]` in tree order, for the live audit.

        Build order and tree order are the same thing here, and are kept that
        way: the Browse button is listed with the stylesheet row it sits in,
        and only Restore defaults — which really is the last control in the
        panel — comes after every row.
        """
        return list(self._entries) + list(self._extra_entries)

    def control_for(self, setting_name):
        """The widget bound to `setting_name`. For the probe to drive."""
        return self._controls[setting_name]

    # --- notices -------------------------------------------------------------

    def _build_notice(self):
        """A one-line warning bar, hidden and pinned hidden.

        `set_no_show_all` for the reason the mode bar's refresh button and the
        search bar carry it: xed forces widgets visible on save and revert,
        and a stray `show_all()` must not raise a warning nobody earned.
        """
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.set_border_width(6)
        label = Gtk.Label()
        label.set_xalign(0.0)
        label.set_line_wrap(True)
        label.set_selectable(True)
        bar.pack_start(label, True, True, 0)
        bar._label = label
        bar.show_all()
        bar.set_no_show_all(True)
        bar.hide()
        return bar

    @staticmethod
    def _set_notice(bar, text):
        if bar is None:
            return
        if text:
            bar._label.set_text(text)
            bar.show()
        else:
            bar.hide()

    def _show_quarantine(self):
        """What was found at startup, if anything was wrong with it."""
        if self._store.quarantine is None:
            return
        reason, preserved = self._store.quarantine
        kept = (
            f" Your copy was kept at {preserved}."
            if preserved
            else " It was left where it is."
        )
        self._set_notice(
            self._quarantine_bar,
            f"Your settings file {reason}, so xedown started from " f"defaults.{kept}",
        )

    def _after_commit(self):
        """Whether the last write actually reached the disk.

        Called from `_commit` — add that call now; Task 3 left none, so that
        it never shipped an empty method waiting to be filled in.
        """
        error = self._store.write_error
        self._set_notice(
            self._save_bar,
            (
                f"Settings could not be saved: {error}. Your change applies for "
                "this session, but will not survive a restart."
                if error
                else ""
            ),
        )

    def _on_stylesheet_changed(self, user):
        """The custom stylesheet's own notice, worded by `errors.py`.

        Read from the watcher rather than loaded here, so the window and the
        preview's in-page notice cannot describe the same file differently —
        and so fixing the file clears this bar without touching the setting.
        """
        if user.problem is None:
            self._set_notice(self._stylesheet_bar, "")
            return
        phrase = errors.stylesheet_problem_phrase(user.problem, user.detail)
        self._set_notice(self._stylesheet_bar, f"{user.path} {phrase}.")

    # --- store -> panel ----------------------------------------------------

    def _load_all(self):
        self._apply_from_store({row.setting for row in prefs.rows()})

    def _on_settings_changed(self, changed):
        self._apply_from_store(changed)

    def _apply_from_store(self, names):
        """Write the store's values into their widgets.

        Guarded, so a value arriving here never looks like the user turning a
        knob and never schedules a write back. A name with a settle timer
        pending has that timer cancelled and adopts the incoming value: a
        restore performed in another window must win over a half-finished
        local edit rather than be overwritten by it a moment later.
        """
        self._loading = True
        try:
            for row in prefs.rows():
                if row.setting not in names:
                    continue
                self._cancel_settle(row.setting)
                self._apply_row(row, self._store.get(row.setting))
            self._apply_sensitivity()
        finally:
            self._loading = False

    def _apply_row(self, row, value):
        """Put `value` in the row's control, but only if it is not there yet.

        The store notifies synchronously and this panel is one of its own
        listeners, so a change the user makes here comes straight back: the
        control's own signal handler is still on the stack when this runs.
        Writing the value in again would be a reentrant call into the widget
        that is mid-emission -- for a `Gtk.ComboBoxText` that means
        `set_active_id` inside its own `changed`, which GTK answers with
        `gtk_tree_model_get_column_type: assertion 'GTK_IS_TREE_MODEL
        (tree_model)' failed` and then hangs the editor outright. Every kind
        is guarded, not just the combo: the same loop exists for all of them.

        The test is *what the widget shows*, never *who caused the change*.
        A value arriving from a second panel or from Restore defaults is not
        already displayed here, so it still gets written -- which is what
        keeps two open windows in step. `_loading` remains the thing that
        stops that write turning into a write back.
        """
        control = self._controls[row.setting]
        if row.kind == prefs.SWITCH:
            wanted = bool(value)
            if control.get_active() != wanted:
                control.set_active(wanted)
        elif row.kind == prefs.CHOICE:
            wanted = str(value)
            if control.get_active_id() != wanted:
                control.set_active_id(wanted)
            # Outside the guard on purpose: the help line under the theme row
            # follows the value, and a first load or a re-selection that finds
            # the combo already right still has to leave the right text there.
            if row.setting == settings.PREVIEW_THEME and self._theme_help:
                self._theme_help.set_text(prefs.choice_help(row.setting, value))
        elif row.kind == prefs.NUMBER:
            wanted = float(value)
            if control.get_value() != wanted:
                control.set_value(wanted)
        else:
            wanted = "" if value is None else str(value)
            if control.get_text() != wanted:
                control.set_text(wanted)

    def _apply_sensitivity(self):
        """A row's `enabled_by` decides whether it can be used at all.

        Re-evaluated on every broadcast, not only at build time, so *Wait
        before updating* greys out whether auto-refresh was switched off here,
        in another panel, or by a restore.
        """
        for row in prefs.rows():
            if row.enabled_by is None:
                continue
            enabled = bool(self._store.get(row.enabled_by))
            control = self._controls[row.setting]
            control.set_sensitive(enabled)
            box = self._number_boxes.get(row.setting)
            if box is not None:
                box.set_sensitive(enabled)

    # --- panel -> store ----------------------------------------------------

    def _on_switch(self, control, _param, row):
        if self._loading:
            return
        self._commit(row, control.get_active())

    def _on_choice(self, control, row):
        if self._loading:
            return
        value = control.get_active_id()
        if value is None:
            return
        self._commit(row, value)

    def _on_number(self, control, row):
        if self._loading:
            return
        self._schedule_settle(row, control.get_value())

    def _on_text(self, control, row):
        if self._loading:
            return
        self._schedule_settle(row, control.get_text())

    def _on_clear(self, control, position, _event, row):
        if position != Gtk.EntryIconPosition.SECONDARY:
            return
        control.set_text("")
        self._commit_now(control, row)

    def _on_focus_out(self, control, _event, row):
        self._commit_now(control, row)
        return False

    def _commit_now(self, control, row):
        """Commit whatever is in `control` at once, cancelling any timer."""
        if self._loading:
            return
        self._cancel_settle(row.setting)
        if row.kind == prefs.NUMBER:
            # `update` first: a value typed but not yet activated is still
            # only text, and committing without it would store the old number.
            control.update()
            self._commit(row, control.get_value())
        else:
            self._commit(row, control.get_text())

    def _schedule_settle(self, row, value):
        self._cancel_settle(row.setting)
        self._settle[row.setting] = GLib.timeout_add(
            SETTLE_MS, self._on_settled, row, value
        )

    def _on_settled(self, row, value):
        self._settle.pop(row.setting, None)
        self._commit(row, value)
        return False

    def _cancel_settle(self, name):
        source = self._settle.pop(name, None)
        if source:
            GLib.source_remove(source)

    def _commit(self, row, value):
        """Hand one value to the store, coerced the way the store expects.

        A number row's value arrives as a float from the adjustment; an
        integer setting has to be handed an int, because `NumberSetting`
        rejects nothing here but `set_many` compares against the stored value
        and 250.0 != 250 would look like a change on every commit.
        """
        if row.kind == prefs.NUMBER:
            _, _, integer = prefs.bounds(row)
            value = round(value) if integer else float(value)
        elif row.kind == prefs.PATH:
            value = value.strip() or None
        try:
            self._store.set(row.setting, value)
        except ValueError:
            # Unreachable through these widgets -- every control is built from
            # the same descriptor the validator uses -- but a raise here would
            # take the whole dialog down, and losing one keystroke is the
            # smaller failure.
            return
        self._after_commit()

    # --- teardown ----------------------------------------------------------

    def _on_destroy(self, *_args):
        """Leave nothing behind: no subscription, no armed timer.

        A live settings token keeps this panel, its window and the store's
        reference to it alive for the life of the process. An armed timer
        fires into a destroyed widget. Both are what the shutdown scenarios
        exist to catch.

        Timers are cancelled first, before either token is released: they are
        the cleanup that must not be skippable, while the token releases are
        the fallible part (`StylesheetWatcher.disconnect` can reach an
        unguarded `Gio.FileMonitor.cancel()`). If a token release ever
        raised, cancelling the timers afterwards would never run, leaving an
        armed `GLib.timeout` to fire into this now-destroyed widget.
        """
        for name in list(self._settle):
            self._cancel_settle(name)
        if self._settings_token is not None:
            self._store.disconnect(self._settings_token)
            self._settings_token = None
        if self._watcher_token is not None:
            stylewatcher.get_watcher().disconnect(self._watcher_token)
            self._watcher_token = None


class SettingsWindow(Gtk.Window):
    """Our own host for the panel: the View-menu entry point.

    Non-modal on purpose. Watching previews change behind it while a choice is
    made is the point of applying settings live, and a modal window would hide
    exactly what the user is trying to see.
    """

    __gtype_name__ = "XedownSettingsWindow"

    def __init__(self, parent=None):
        super().__init__(title="Markdown Preview Settings")
        self.set_transient_for(parent)
        self.set_destroy_with_parent(True)
        self.set_modal(False)
        self.set_default_size(520, 560)

        self.panel = SettingsPanel()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.pack_start(self.panel, True, True, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions.set_border_width(6)
        close_name = a11y.NAMES["prefs_close"]
        self._close = Gtk.Button(label="_" + close_name, use_underline=True)
        SettingsPanel._name(self._close, close_name)
        self._close.connect("clicked", lambda *_: self.destroy())
        actions.pack_end(self._close, False, False, 0)
        box.pack_start(actions, False, False, 0)

        self.add(box)
        self.connect("key-press-event", self._on_key_press)
        self.show_all()

    def accessible_entries(self):
        """The panel's controls plus this window's own Close button."""
        return self.panel.accessible_entries() + [("prefs_close", self._close)]

    def _on_key_press(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        return False
