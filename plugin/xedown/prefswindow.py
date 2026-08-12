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

gi.require_version("Gtk", "3.0")

from gi.repository import Atk, GLib, Gtk, Pango

from . import prefs, settings

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
        self._extra_entries = []  # controls that are not rows
        self._theme_help = None
        # Set while writing store values into widgets, so a programmatic
        # change is never mistaken for the user turning a knob.
        self._loading = False

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_border_width(12)
        for group in prefs.GROUPS:
            content.pack_start(self._build_group(group), False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_min_content_height(420)
        scroller.add(content)
        self.pack_start(scroller, True, True, 0)

        self._load_all()
        self._settings_token = self._store.connect(self._on_settings_changed)
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
        for row in group.rows:
            line = self._build_row(grid, row, line)
        return box

    def _build_row(self, grid, row, line):
        label = Gtk.Label(label=row.label)
        label.set_xalign(0.0)
        label.set_hexpand(True)
        label.set_line_wrap(True)
        grid.attach(label, 0, line, 1, 1)

        control = self._build_control(row)
        control.set_halign(Gtk.Align.END)
        # Sets the LABELLED_BY relation, which is the reason to call this even
        # with no mnemonic in the label: the accessible name then comes from
        # the label the user is actually reading.
        label.set_mnemonic_widget(control)
        self._controls[row.setting] = control
        self._entries.append((row.key, control))
        # The box when the control has company, the control itself otherwise.
        attached = (
            self._path_boxes.get(row.setting)
            or self._number_boxes.get(row.setting)
            or control
        )
        grid.attach(attached, 1, line, 1, 1)
        line += 1

        help_label = self._build_help(row)
        if help_label is not None:
            grid.attach(help_label, 0, line, 2, 1)
            self._describe(control, help_label)
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
        return entry

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
        """`[(a11y key, widget), …]` in build order, for the live audit."""
        return list(self._entries)

    def control_for(self, setting_name):
        """The widget bound to `setting_name`. For the probe to drive."""
        return self._controls[setting_name]

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
        control = self._controls[row.setting]
        if row.kind == prefs.SWITCH:
            control.set_active(bool(value))
        elif row.kind == prefs.CHOICE:
            control.set_active_id(str(value))
            if row.setting == settings.PREVIEW_THEME and self._theme_help:
                self._theme_help.set_text(prefs.choice_help(row.setting, value))
        elif row.kind == prefs.NUMBER:
            control.set_value(float(value))
        else:
            control.set_text("" if value is None else str(value))

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

    # --- teardown ----------------------------------------------------------

    def _on_destroy(self, *_args):
        """Leave nothing behind: no subscription, no armed timer.

        A live settings token keeps this panel, its window and the store's
        reference to it alive for the life of the process. An armed timer
        fires into a destroyed widget. Both are what the shutdown scenarios
        exist to catch.
        """
        if self._settings_token is not None:
            self._store.disconnect(self._settings_token)
            self._settings_token = None
        for name in list(self._settle):
            self._cancel_settle(name)
