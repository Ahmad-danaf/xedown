# Installation

xedown installs as a per-user xed plugin. Markdown and syntax highlighting are
bundled, so there is no `pip install` step.

## Requirements

The officially supported runtime is Linux Mint 22.3, xed 3.8.9, Python 3.12.3,
GTK 3.24.41 through the GTK 3.0 API, WebKitGTK 2.52.3 through the WebKit2 4.1
API, and X11. Nearby versions may work but have not been verified; see
[Compatibility](compatibility.md).

Assuming xed is already installed, install its additional runtime dependencies
on Linux Mint with:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

The installer checks these requirements and xed itself. It reports missing
packages but does not install them for you.

## Install a release

Download these three assets from the v1.0 release and put them in the same
directory:

- `xedown-1.0.0.tar.gz`
- `install.sh`
- `uninstall.sh`

Then run:

```bash
chmod +x install.sh uninstall.sh
./install.sh --from xedown-1.0.0.tar.gz
```

The installer validates the archive and this machine before replacing an
existing xedown installation. An upgrade replaces the old plugin rather than
merging files into it, and keeps everything in `~/.config/xedown/`.

If xed is closed, the installer offers to enable xedown. Use `--enable` to do
that without a prompt or `--no-enable` to skip it. A non-interactive run never
silently enables a plugin.

Open xed and, if necessary, enable **Xedown** under *Preferences → Plugins*.
Open a `.md` or `.markdown` file to verify that the
**Preview | Markdown** bar appears.

## Install from a checkout

From the repository root:

```bash
./install.sh
```

This is mainly useful for development. It applies the same checks and safe
replacement behavior as a release install.

## Manual installation

If you cannot use the installer:

```bash
mkdir -p ~/.local/share/xed/plugins
tar -xzf xedown-1.0.0.tar.gz -C ~/.local/share/xed/plugins
```

Then enable **Xedown** in xed's plugin preferences. Manual extraction bypasses
the compatibility checks, archive validation, and safe upgrade replacement in
`install.sh`.

With a custom `XDG_DATA_HOME`, the plugin directory is
`$XDG_DATA_HOME/xed/plugins` instead.

## Warnings, refusals, and `--force`

- Missing xed, Python 3.10 or newer, `python3-gi`, GTK 3, or WebKit2 4.1 is a
  refusal because xedown cannot run as detected.
- A system outside the verified matrix is a warning; installation continues.
- A fact the installer cannot determine is a warning, not proof that a
  requirement is missing.
- `--force` overrides a requirement refusal. It is intended for people who
  know why a probe is wrong; the plugin may otherwise fail to load.

See [Troubleshooting](troubleshooting.md) if the plugin does not appear or the
preview reports an incomplete installation.
