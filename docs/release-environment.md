# v1.0 release environment

This inventory records the machine used for the v1.0 live desktop verification
on 2026-08-17. It identifies the runtime in which the integration, shutdown,
and manual checks were performed. The older Orca measurements record only the
environment stated in their own evidence document and are not attributed to
this inventory.

Commands:

```bash
python3 --version
xed --version
printf 'session=%s\n' "$XDG_SESSION_TYPE"
cat /etc/os-release
dpkg-query -W -f='${Package}\t${Version}\n' \
  python3 python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  libwebkit2gtk-4.1-0
```

Relevant output:

```text
Python 3.12.3
xed - Version 3.8.9
session=x11
NAME="Linux Mint"
VERSION="22.3 (Zena)"
VERSION_ID="22.3"
gir1.2-gtk-3.0             3.24.41-4ubuntu1.3
gir1.2-webkit2-4.1         2.52.3-0ubuntu0.24.04.1
libwebkit2gtk-4.1-0        2.52.3-0ubuntu0.24.04.1
python3                    3.12.3-0ubuntu2.1
python3-gi                 3.48.2-1
```

The API versions used by xedown are GTK `3.0` and WebKit2 `4.1`. Package
versions above retain their distribution revisions; the public compatibility
table uses their upstream version portions.
