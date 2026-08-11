"""The parts of the file watch CI can reach.

Everything past `start()` needs Gio and a main loop, and is covered by the
integration probe instead. What is testable here is the boundary that keeps
this module importable in the first place, and the lifecycle promises the
controller relies on: `stop()` before `start()` is safe, `stop()` twice is
safe, and `repoint` moves the path.
"""

import pathlib

from xedown import filewatch
from xedown.filewatch import FileWatch


def test_the_module_imports_without_a_host():
    """`gi` must be imported inside the methods, never at module level.

    A module-level `gi` import here would take this file out of CI's reach
    entirely -- and would break `import xedown.controller` for anyone
    inspecting the plugin outside xed. Asserted against column zero, since
    the lazy imports inside the methods are indented.
    """
    source = pathlib.Path(filewatch.__file__).read_text()
    assert "\nimport gi" not in source
    assert "\nfrom gi" not in source


def test_the_settle_window_is_the_documented_one():
    assert filewatch.SETTLE_DELAY_MS == 300


def test_a_fresh_watch_holds_its_path():
    watch = FileWatch("/notes/a.md", lambda: None)
    assert watch.path == "/notes/a.md"


def test_stop_before_start_is_safe():
    FileWatch("/notes/a.md", lambda: None).stop()


def test_stop_is_idempotent():
    watch = FileWatch("/notes/a.md", lambda: None)
    watch.stop()
    watch.stop()


def test_repoint_to_the_same_path_does_not_re_arm():
    """Guarded, because re-arming means tearing down a live monitor.

    An ordinary save does not move the file, and must not cost the watch its
    monitor for the window between the disconnect and the reconnect.
    """
    watch = FileWatch("/notes/a.md", lambda: None)
    armed = []
    watch.start = lambda: armed.append(watch.path)
    watch.repoint("/notes/a.md")
    assert armed == []
    assert watch.path == "/notes/a.md"


def test_repoint_moves_the_path_and_re_arms():
    watch = FileWatch("/notes/a.md", lambda: None)
    armed = []
    watch.start = lambda: armed.append(watch.path)
    watch.repoint("/notes/b.md")
    assert watch.path == "/notes/b.md"
    assert armed == ["/notes/b.md"]
