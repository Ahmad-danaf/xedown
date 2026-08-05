import pathlib
import sys

PLUGIN_DIR = pathlib.Path(__file__).resolve().parent.parent / "plugin"
if str(PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR))
