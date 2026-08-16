# Compatibility

This page separates configurations exercised inside a live xed session from
nearby versions that are expected to work and Python versions that run only the
desktop-independent unit suite.

## Officially supported runtime

This is the exact stack used on the v1.0 live verification machine. Its
checked-in [release-environment inventory](release-environment.md) records the
commands and package versions. The older Orca measurements independently
record Orca 46.1, xed 3.8.9, and X11, but did not record their WebKitGTK patch
version.

| Component | Supported version | Evidence |
| --- | --- | --- |
| Linux Mint | `22.3` | Release-machine inventory and live verification |
| xed | `3.8.9` | Release-machine inventory and lifecycle harnesses |
| Python | `3.12.3` | Release-machine inventory |
| GTK | `3.24.41` using GTK API `3.0` | Release-machine inventory |
| WebKitGTK | `2.52.3` using WebKit2 API `4.1` | Release-machine inventory |
| Display server | `X11` | Release-machine inventory and live harnesses |

“Supported” means this precise environment has automated lifecycle and manual
release evidence. The separate Orca evidence supports only the versions it
records itself. Neither body of evidence means every patch version in the
surrounding series was tested.

## CI unit-tested only

Python `3.10` and `3.11` run the complete desktop-independent unit suite in
GitHub Actions, alongside 3.12. This provides evidence for pure rendering,
sanitizing, settings, path, fetch-policy, and related logic. It is not evidence
that those interpreters were exercised as the plugin runtime inside xed, GTK,
or WebKitGTK.

## Expected to work, but unverified

Nearby Linux Mint 22.x releases, other xed 3.8.x patch releases, compatible
Python 3.10–3.12 runtimes, nearby WebKitGTK releases exposing the 4.1 API, and
Wayland are expected to work where their APIs behave compatibly. They are not
officially supported until they receive a live run.

Other distributions and desktops may also work. Reports are welcome,
especially when they name the exact versions and distinguish unit tests from a
live xed session.

## Hard requirements and known negatives

`preview.py` and `imagescheme.py` require `WebKit2` API version `4.1`. A system
whose WebKitGTK provides only the `WebKit2` `4.0` API cannot run xedown. Debian
and Ubuntu family systems normally provide the 4.1 typelib as
`gir1.2-webkit2-4.1`.

xedown also requires:

- Python `3.10` or newer;
- `python3-gi`;
- the GTK `3.0` typelib;
- xed; and
- the WebKit2 `4.1` typelib.

## What the installer checks

The installer uses a broader series-level matrix to make safe installation
decisions; that is not an expansion of the exact support claim above.

- A positively missing hard requirement is a refusal with the relevant package
  name. `--force` can override it.
- Python older than `3.10` is a refusal. Python newer than the CI-tested `3.12`
  ceiling produces a warning and continues.
- A detected system outside Linux Mint `22` or xed `3.8` produces a warning and
  continues.
- A session positively identified as Wayland produces a warning. Other absent
  or unrecognized session information does not, because it does not establish
  which display server xed will use.
- An undetermined dependency or version fact produces a warning. Failure to
  detect something is not treated as proof that it is absent; session
  detection follows the narrower rule above.

Installation success on an unverified system means the preflight found no
known blocker; it does not turn that system into an officially supported one.
