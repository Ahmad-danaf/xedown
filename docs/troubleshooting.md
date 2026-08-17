# Troubleshooting

## Xedown does not appear in xed

Confirm that these exist:

```text
~/.local/share/xed/plugins/xedown.plugin
~/.local/share/xed/plugins/xedown/__init__.py
```

Close and reopen xed, then enable **Xedown** under *Preferences → Plugins*. If
xed was running during installation, the installer deliberately
did not change its active-plugin list.

With `XDG_DATA_HOME` set, look under `$XDG_DATA_HOME/xed/plugins` instead.

## The installer refuses to continue

Read the `ERROR` lines above the refusal. If xed is already installed on Linux
Mint, install its additional runtime dependencies with:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

xedown requires Python 3.10 or newer, xed, GTK 3, and the WebKit2 4.1 typelib.
WebKit2 4.0 alone cannot load it. `--force` bypasses a failed probe but cannot
make a genuinely missing runtime work.

Python older than 3.10 is a refusal. A newer-than-tested Python, an untested
distribution or xed series, or a session positively identified as Wayland
produces a warning and does not stop installation. An absent or unrecognized
session value produces no display-server finding. See
[Compatibility](compatibility.md).

## “Installation incomplete” appears in Preview

A bundled module, stylesheet, script, Markdown library, or highlight.js file
is missing or unreadable. Reinstall from the complete release archive with
`install.sh`; do not copy a partial `xedown/` directory over an older one.

## “The Markdown could not be rendered” appears

The preview caught an unexpected rendering failure rather than leaving a
blank pane. Save the document and include the error text and a minimal sample
when reporting the bug. If the sample may be security-sensitive, follow
[SECURITY.md](../SECURITY.md) instead of opening a public issue.

## A local image or link does not work

- Save a new document first; relative paths have no directory before that.
- Resolve the path relative to the Markdown file, not xed's working directory.
- Check filename case and read permissions.
- SVG files are accepted as local files, but inline `data:image/svg+xml` is
  refused because SVG is a scriptable document format.
- xedown refuses missing links and asks before opening files that can run code.

## A remote image does not load

Remote images are blocked by default. Use the tab's **Load** button or enable
HTTPS images in preferences. xedown still refuses HTTP, URL credentials,
private/local destinations, unsafe redirects, remote AVIF, responses above
8 MiB, and images above the decode limits. Offline, TLS, timeout, HTTP, and
queue failures produce distinct placeholders.

Press **Refresh** after connectivity returns. See
[Remote images and privacy](remote-images.md).

## A custom stylesheet is ignored

The preview notice explains the reason. The file must be a regular, readable,
non-empty UTF-8 file no larger than 512 KiB and cannot contain `</style`.
Network imports, web fonts, and local font-file URLs are blocked by the page's
content security policy. Install a font normally and refer to its family name.

## Preview and Markdown show different text after an external edit

Preview can follow the file on disk without rewriting xed's source buffer.
Switch to Markdown and accept xed's **Reload** prompt, or use *File → Revert*.
Unsaved changes are never silently discarded.

File monitoring does not follow a document opened through a symbolic link and
may miss writes made from another machine to NFS or SMB storage.

## A large file opens in Markdown or stops refreshing live

Past 131,072 characters, xedown stops automatic renders while you type and
offers **Refresh**. Past 262,144 characters, a newly opened tab starts in
Markdown and offers **Preview** on demand. Manual preview remains available at
any size. Rendering, saving, and reverting can still pause xed because the
renderer runs on its main thread. See [Performance](performance.md).

## Preview Copy or Select All uses the source text

On a non-Latin keyboard layout, `Ctrl+C` and `Ctrl+A` can fall through to xed's
hidden source view. Right-click Preview and use **Copy** or **Select All**.

## Preferences do not survive restart

Open the preferences window and check for a save warning. A read-only or full
configuration filesystem leaves changes active only for the current process.
A damaged file is normally preserved as `settings.json.corrupt`.

## xed crashes after moving a tab between windows

xed 3.8.9 has an intermittent clipboard/action-group crash that reproduces
without xedown installed. Save before moving tabs between windows. The stack,
control runs, and workaround are recorded in [Known issues](known-issues.md).
