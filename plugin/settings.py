"""User-facing options and their defaults."""

DEFAULTS = {
    "theme": "auto",  # auto | light | dark
    "font_family": "",  # empty means follow the desktop document font
    "font_size": 0,  # 0 means follow the desktop document font
    "open_links_externally": True,
    "sync_scroll": True,
    "live_refresh": True,
    "refresh_delay_ms": 250,
    "markdown_extensions": ["tables", "fenced_code", "toc"],
}


class Settings:
    """Loads, exposes, and persists xedown options."""

    def __init__(self, path: str | None = None):
        self.path = path
        self._values = dict(DEFAULTS)

    def get(self, key: str):
        raise NotImplementedError

    def set(self, key: str, value):
        raise NotImplementedError

    def load(self):
        raise NotImplementedError

    def save(self):
        raise NotImplementedError
