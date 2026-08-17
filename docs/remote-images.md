# Remote images and privacy

Markdown can contain an image hosted on somebody else's server, including a
one-pixel image you cannot see. Fetching it tells that server your IP address,
roughly where you are, when you opened the document, and the requested URL.
For that reason, xedown blocks remote images by default.

When a document contains blocked HTTPS images, xedown shows a placeholder and
the mode bar reports how many it found. **Load** permits them for that tab until
the tab closes. It does not change any other tab or your global preference.

To permit HTTPS images in every document, open *View → Markdown Preview
Settings* and change **Remote images** to **Load them over HTTPS**. Turning the
global preference off again does not revoke a Load grant already given to an
open tab; close that tab to end its grant.

## What xedown permits

xedown itself makes network requests only for permitted remote images. Its
preview page never receives general web access.

For an allowed image, xedown:

- accepts only `https://` URLs without embedded credentials;
- checks that the hostname resolves only to public internet addresses;
- repeats the policy and destination checks at every redirect;
- refuses redirects to HTTP, private networks, credentials, or unsupported
  schemes;
- sends a xedown `User-Agent`, an image-format `Accept` header, and
  `Accept-Encoding: identity`, but no cookie, `Referer`, or authorization
  header;
- accepts PNG, JPEG, GIF, WebP, and BMP responses;
- caps a download at 8 MiB, follows at most three redirects, and limits one
  fetch to 15 seconds overall;
- refuses measurable images above 25 megapixels or 32,768 pixels on either
  side; and
- keeps xedown's cache in process memory rather than writing image results to
  disk.

HTTP images are never fetched. Remote AVIF is unsupported because xedown
cannot measure it before decoding. Up to four images fetch concurrently and at
most 64 URLs wait in the queue.

External links are separate: clicking one asks your default browser to open
it. The statement above describes requests made by xedown itself, not what an
external application may do after you ask it to open a link.

## Remaining risks

Loading an image necessarily discloses your network request to its host and
network intermediaries. There is also an accepted, blind DNS-rebinding race
between xedown's destination check and the connection made afterward. The
preview cannot read fetched bytes or send findings back to the document, which
limits this residual to a blind request/timing effect.

A fetch already running can delay xed shutdown by up to its 15-second overall
deadline. Separate `xed --standalone` processes have separate in-memory caches
and permissions.

For the complete security boundary and vulnerability-reporting policy, see
[SECURITY.md](../SECURITY.md). For display choices and preference details, see
[Preferences](preferences.md).
