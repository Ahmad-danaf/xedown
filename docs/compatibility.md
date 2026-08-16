# Compatibility

"Works on Linux Mint" is not a claim anyone can check. This page says exactly
what xedown is tested on, what it requires, and what it does not promise.

`install.sh` enforces this page. The same matrix lives as constants in
`plugin/xedown/preflight.py`, and `tests/unit/test_compatibility.py` fails if
the two ever disagree.

## Supported

Tested, and what xedown 1.0 claims.

| Component | Supported | Evidence |
| --- | --- | --- |
| Linux Mint | `22.x` | measured on 22.3 (Ubuntu 24.04 base); every integration, shutdown and Orca harness run |
| xed | `3.8.x` | measured on 3.8.9; `known-issues.md` pins 3.8.9 behaviours by version |
| Python | `3.10`, `3.11`, `3.12` | the CI matrix, which runs the unit tests without GTK; 3.12.3 at runtime on the live machine |
| WebKit2GTK | `4.1` | measured on 2.52.3 — and **required**, see below |
| GTK | `3.0` | as above |
| Display server | `x11` | every harness; Wayland was never tried ([known-issues.md](known-issues.md)) |

### WebKit2GTK 4.1 is a requirement, not a measurement

`preview.py` and `imagescheme.py` call `gi.require_version("WebKit2", "4.1")`.
This is not a question of what has been tested: a system carrying only
**WebKit2GTK 4.0** cannot run xedown at all, and `install.sh` refuses rather
than installing something that would never load. Debian and Ubuntu ship the
4.1 typelib as `gir1.2-webkit2-4.1`.

## Anything else

Any other distribution, any other desktop, any xed in the 3.x line outside
3.8, Python 3.13 or newer, and Wayland fall outside the table above. They
**may work** and are **not officially tested**. `install.sh` will install on
those systems and print a warning naming what it did not recognise. Reports
are welcome; they are how rows move into the table above.

The one thing known *not* to work is a system without WebKit2GTK 4.1, for the
reason in the section above.

## What the installer does with this

- Something xedown cannot run without — `python3-gi`, the GTK 3.0 typelib, the
  WebKit2 4.1 typelib, Python 3.10 or newer, xed itself — is a refusal, naming
  the package that fixes it. `install.sh --force` proceeds anyway.
- Something merely outside the table is a warning, and the install continues.
- Something the installer could not determine is also only a warning. A probe
  that failed is not evidence of absence.
