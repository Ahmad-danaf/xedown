# Security

xedown renders Markdown files you did not necessarily write yourself — a
repository you cloned, an attachment, a document someone sent you. This file
describes what the plugin will and will not do with content like that, and
in particular the one place it reaches the network.

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
by a dedicated regression test in `tests/unit/`:

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
6. **No non-public destination is ever contacted.** The check runs on
   resolved addresses via `getaddrinfo`, never on the hostname string —
   `127.0.0.1`, `0x7f000001`, `0177.0.0.1` and `localhost` are all caught
   the same way, and so is an IPv4-mapped or IPv4-compatible IPv6 literal
   that hides a private address.
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
    measure at all (AVIF, SVG) is passed through unmeasured, deliberately —
    refusing an inline image that has always rendered would be a worse
    regression than the bug being fixed. A *remote* image in such a format
    is refused instead, because refusing a fetch takes nothing away that
    already worked. See
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

## Reporting a vulnerability

Please open an issue at
[github.com/Ahmad-danaf/xedown](https://github.com/Ahmad-danaf/xedown), or
contact the maintainer directly if the report should not be public. Include
enough to reproduce it — a sample document is usually the fastest way.
