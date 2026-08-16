# Security

xedown renders Markdown files you did not necessarily write yourself — a
repository you cloned, an attachment, a document someone sent you. The rule
the whole design serves is one sentence:

> **Markdown may display content, but it must never execute content.**

This file says how to report a case where that does not hold, what counts as
one, and what the plugin does with hostile content today.

## Reporting a vulnerability

**Please do not open a public issue for a security report.** xedown renders
untrusted documents, so a working bypass is useful to somebody else the
moment it is public and before there is a release to upgrade to.

Email **ahmad.danf@gmail.com** with `xedown security` in the subject.

Useful to include, roughly in order of how much time each saves:

- **A sample document that reproduces it.** Almost always the fastest route
  — the payload as a `.md` file beats a description of the payload.
- Which xedown version, from *Preferences → Plugins*, or the release archive
  you installed.
- Your xed and WebKitGTK versions, if you have them to hand — several
  behaviours here are the host's rather than the plugin's.
- What you expected to happen and what happened instead.

What to expect: an acknowledgement within about a week. xedown is written
and maintained by one person, in their own time, so there is no fixed fix
timeline and no bounty — but a report that lands will be answered, credited
if you want it to be, and fixed in the open.

## Supported versions

The most recent release is the only one that gets fixes. xedown ships as a
tarball that extracts into `~/.local/share/xed/plugins` with no `pip` step
and no dependency resolution, so upgrading is replacing that directory —
there is no supported-branch matrix to maintain and no reason to backport.

## Scope

**In scope** — anything that breaks the rule at the top of this file, or the
network boundary below it:

- Script execution of any kind inside the preview, or any escape from the
  sanitizer's element, attribute or URI-scheme allowlist.
- A network request that happens without the reader having allowed remote
  images, or that goes anywhere the fetcher's guarantees say it cannot —
  `http://`, a non-public address, a URL carrying credentials.
- Reading or writing any file the document did not name, or writing to the
  document's own text buffer, which the plugin never does.
- The preview reaching xed itself: a custom stylesheet or a rendered
  document affecting the editor rather than the preview pane.
- Any way a document can cause code to run without the confirmation dialog
  that `links.classify_link` requires for an executable or a code-running
  file type.

**Not in scope** — please don't send these; they are known, deliberate, or
somebody else's:

- The residuals in *Known residuals* below. Each is written up in
  [docs/known-issues.md](docs/known-issues.md) with what was measured and
  why it was accepted. A report showing one is *worse than documented* is
  very much in scope; a report that one exists is not.
- Anything that assumes the attacker can already run code as your user.
  xedown is a plugin inside your own editor, under your own account: it is
  not a privilege boundary and does not try to be.
- A link opening in the desktop's handler after you clicked it. That is what
  the feature does; the confirmation dialog for code-running files is the
  boundary, and a way *around that dialog* is in scope.
- A document being slow or large to render. There are limits
  (`perflimits.py`, `imagelimits.py`) and they are documented in
  [docs/performance.md](docs/performance.md), but resource use is not
  treated as a security boundary here.
- Scanner output against the vendored copies of Python-Markdown or
  highlight.js in `plugin/xedown/vendor/` with no demonstrated path through
  xedown's own use of them. With such a path, it is in scope.
- Bugs in xed or WebKitGTK reachable without xedown installed. The known one
  is in [docs/known-issues.md](docs/known-issues.md); `XEDOWN_CONTROL=1` on
  either test harness runs a scenario with xedown uninstalled, which is how
  to tell the two apart.

## The network boundary

**The preview page itself is never granted `http:` or `https:`.** Its
content security policy is `default-src 'none'`, and `img-src` never lists
either scheme, whatever the settings say. Only xedown's own fetch code
(`imagefetch.py`, served to the page through the private `xedown-image:`
scheme in `imagescheme.py`) reaches the network — only for images, only over
`https://`, only to public addresses, and only when the reader has allowed
it: globally with `remote_images` in Preferences, or for one document at a
time from the mode bar's **Load** button. See
[docs/settings.md](docs/settings.md#remote-images).

Nothing else in xedown reaches the network. No font, stylesheet, script,
frame, XHR, WebSocket or favicon is ever fetched, by the page or by xedown's
own code — see [docs/themes.md](docs/themes.md#what-a-custom-stylesheet-cannot-do)
for what a custom stylesheet cannot do, which is exactly this. `http://` is
never fetched under any setting or button; there is no escape hatch.

## What the image fetcher guarantees

Each of these is enforced in code, not merely intended, and most are pinned
by a dedicated regression test in `tests/unit/`. The rule at the top of this
file is tested end to end in `tests/unit/test_security.py`, which drives
attacker-authored *Markdown* through the whole pipeline and audits the
rendered page against the sanitizer's allowlists rather than grepping it for
known payloads:

1. **The page cannot reach the network.** `default-src 'none'` is unchanged
   and `img-src` never lists `http:` or `https:`.
2. **Document content cannot mint a fetchable URL.** `xedown-image:` is not
   in the sanitizer's allowed URI schemes, and never will be — a document
   that contained one literally would still have it stripped.
3. **A blocked document's CSP does not list the scheme at all.** Permission
   is decided once, at render time; a blocked render never emits a URL there
   is anything to fetch with, so there is no per-request authorization check
   to get wrong later.
4. **No `http://` is ever fetched, including through a redirect.** urllib's
   own redirect handling permits an https→http downgrade, so it is disabled
   entirely; redirects are followed manually, one hop at a time.
5. **No redirect leaves https, and every hop is destination-checked** the
   same way the original URL is.
6. **No non-public destination is ever knowingly contacted.** The check runs
   on resolved addresses via `getaddrinfo`, never on the hostname string —
   `127.0.0.1`, `0x7f000001`, `0177.0.0.1` and `localhost` are all caught
   the same way, and so is an IPv4-mapped or IPv4-compatible IPv6 literal
   that hides a private address. **The residual:** the address this check
   validates and the address the connection ultimately uses are resolved
   separately, so a hostile resolver can answer differently twice — a DNS
   rebinding race. It is blind, and what it can yield is bounded; see
   *Known residuals* below.
7. **No credentials are ever sent.** A URL carrying `user:pass@` is refused
   outright, on the original URL and on every redirect hop.
8. **No cookies, no `Referer` and no `Authorization` ever leave this
   machine.** The only header xedown adds is a fixed `User-Agent` naming the
   project and where to find it.
9. **No SVG and no format xedown cannot measure is ever fetched.** A format
   whose dimensions cannot be read cheaply and safely is refused rather than
   guessed at — this is also why AVIF cannot be fetched remotely; see
   [docs/known-issues.md](docs/known-issues.md).
10. **No image is handed to WebKit above 25 megapixels or 32768 pixels on a
    side**, remote or inline `data:` alike, enforced from one shared module
    (`imagelimits.py`) so the two paths cannot drift apart. This is what a
    byte cap on the download alone cannot prevent: a file a few kilobytes
    long can still declare dimensions that would cost hundreds of megabytes
    to decode. An inline payload is measured in whichever form it is written
    — base64 or percent-encoded — and a payload that *claims* one of the
    measured formats and then cannot be read is refused rather than passed
    on. **The residual:** an inline `data:` image in a format xedown cannot
    measure at all (AVIF is the case that exists) is passed through
    unmeasured, deliberately — refusing an inline image that has always
    rendered would be a worse regression than the bug being fixed. A
    *remote* image in such a format is refused instead, because refusing a
    fetch takes nothing away that already worked. SVG is not part of this
    residual: an inline `data:image/svg+xml` URI is refused outright by the
    sanitizer's own image-format allowlist, for an unrelated reason — SVG is
    itself a scriptable document format, not merely one xedown cannot
    measure — so no inline SVG image is ever rendered, capped or not. See
    [docs/known-issues.md](docs/known-issues.md).
11. **Nothing is written to disk by xedown.** The result cache — successes
    and failures both — lives in memory only, and disappears when xed exits.
    A disk cache would also be a durable record of which documents you
    opened. What WebKit does internally with a response handed to it is
    WebKit's own business; nothing here establishes that it keeps no copy of
    its own.
12. **A failed or hostile response can never break the preview.**
    `render_document` never raises; the worst any of this produces is a
    placeholder explaining what happened.

## Known residuals

A few things are accepted deliberately rather than closed, each with its own
reasoning: a blind DNS-rebinding race that yields at most a timing oracle,
the reader's IP address being disclosed to whatever a permitted document
references (the point of the feature, mitigated by asking first), a shutdown
that can be delayed by up to 15 seconds — one fetch's wall-clock deadline —
by a fetch already in flight, an inline `data:` image in an unmeasurable
format being passed through uncapped, and AVIF being unfetchable over the
network. All of them are written up in
[docs/known-issues.md](docs/known-issues.md), each with what was checked and
why the residual is acceptable.

Deliberately out of scope, by design rather than oversight: a disk cache,
per-directory or per-host trust, authentication and client certificates, and
`file://` images changing behaviour at all. None of these were left out by
accident, and none of them are planned.

## Everything else

Sanitization is allowlist-based: the sanitizer parses and rebuilds HTML from
an explicit element, attribute and URI-scheme allowlist rather than by
regular expression or string replacement, so content xedown does not
recognize is dropped rather than passed through. The plugin never writes to
your document's text buffer — mode switching only hides and shows widgets —
and a custom stylesheet cannot reach xed itself, only the preview.
