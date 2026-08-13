"""Fetching a remote image: the cache, the limits, and the coalescing."""

from xedown import imagefetch, remoteimages


def success(payload=b"12345"):
    return imagefetch.FetchResult(data=payload, mime="image/png")


def failure(kind=imagefetch.TIMEOUT):
    return imagefetch.FetchResult(error=kind, detail="nope")


def test_a_success_comes_back_out():
    cache = imagefetch.ResultCache(max_bytes=1000)
    cache.put("https://e.com/a.png", success())
    assert cache.get("https://e.com/a.png").data == b"12345"


def test_a_failure_is_cached_too():
    # Failures are re-requested by WebKit on every body swap -- four times a
    # second while the reader types. The negative entry is what stops that.
    cache = imagefetch.ResultCache(max_bytes=1000)
    cache.put("https://e.com/a.png", failure())
    cached = cache.get("https://e.com/a.png")
    assert cached is not None and cached.ok is False


def test_invalidate_failures_clears_failures_and_keeps_successes():
    cache = imagefetch.ResultCache(max_bytes=1000)
    cache.put("https://e.com/good.png", success())
    cache.put("https://e.com/bad.png", failure())
    cache.invalidate_failures()
    assert cache.get("https://e.com/good.png") is not None
    assert cache.get("https://e.com/bad.png") is None


def test_the_cache_evicts_least_recently_used_when_over_its_byte_cap():
    cache = imagefetch.ResultCache(max_bytes=10)
    cache.put("a", success(b"12345"))
    cache.put("b", success(b"12345"))
    cache.get("a")  # a is now the most recent
    cache.put("c", success(b"12345"))  # pushes over the cap
    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


def test_an_entry_larger_than_the_whole_cache_is_simply_not_stored():
    cache = imagefetch.ResultCache(max_bytes=4)
    cache.put("a", success(b"1234567890"))
    assert cache.get("a") is None
    assert cache.bytes_held == 0


def test_bytes_held_tracks_eviction():
    cache = imagefetch.ResultCache(max_bytes=10)
    cache.put("a", success(b"12345"))
    cache.put("b", success(b"12345"))
    assert cache.bytes_held == 10
    cache.put("c", success(b"12345"))
    assert cache.bytes_held == 10


class StubResponse:
    def __init__(self, status=200, headers=None, body=b"", url="https://e.com/a.png"):
        self.status = status
        self.headers = headers if headers is not None else {"Content-Type": "image/png"}
        self._body = body
        self._url = url
        self._read = 0

    def read(self, amount):
        chunk = self._body[self._read : self._read + amount]
        self._read += len(chunk)
        return chunk

    def geturl(self):
        return self._url

    def close(self):
        pass


class StubOpener:
    """Records every call, answers from a scripted list of responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, timeout, proxies):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "timeout": timeout,
                "proxies": proxies,
            }
        )
        if not self.responses:
            raise AssertionError(f"unexpected extra fetch of {url}")
        answer = self.responses.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x00\x00\x00\x00"
)


def public(_host):
    return ["93.184.216.34"]


def fetch(url, opener, resolver=public, proxies=None):
    return imagefetch.fetch_once(url, opener=opener, resolver=resolver, proxies=proxies)


def test_a_good_image_comes_back():
    result = fetch("https://e.com/a.png", StubOpener(StubResponse(body=PNG_1X1)))
    assert result.ok and result.mime == "image/png"


def test_no_cookie_referer_or_authorization_is_ever_sent():
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetch("https://e.com/a.png", opener)
    sent = {k.lower() for k in opener.calls[0]["headers"]}
    assert "cookie" not in sent
    assert "referer" not in sent
    assert "authorization" not in sent
    assert "user-agent" in sent


def test_a_non_public_destination_is_refused_before_any_fetch():
    opener = StubOpener()  # any call at all is an assertion failure
    result = fetch("https://e.com/a.png", opener, resolver=lambda h: ["127.0.0.1"])
    assert result.error == imagefetch.BLOCKED_DESTINATION
    assert opener.calls == []


def test_a_credential_bearing_url_is_refused_before_any_fetch():
    opener = StubOpener()
    result = fetch("https://u:p@e.com/a.png", opener)
    assert result.error == imagefetch.CREDENTIALS
    assert opener.calls == []


def test_a_body_over_the_byte_cap_is_refused():
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (remoteimages.MAX_BYTES + 10)
    result = fetch("https://e.com/a.png", StubOpener(StubResponse(body=oversized)))
    assert result.error == imagefetch.TOO_LARGE


def test_a_lying_content_length_does_not_get_past_the_cap():
    # Content-Length is a claim. The cap is enforced by what is actually read.
    oversized = b"\x89PNG\r\n\x1a\n" + b"x" * (remoteimages.MAX_BYTES + 10)
    response = StubResponse(
        headers={"Content-Type": "image/png", "Content-Length": "10"}, body=oversized
    )
    assert fetch("https://e.com/a.png", StubOpener(response)).error == (
        imagefetch.TOO_LARGE
    )


def test_a_decompression_bomb_inside_the_byte_cap_is_refused_on_pixels():
    import struct
    import zlib

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    bomb = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", 10000, 10000, 8, 0, 0, 0, 0)
    )
    result = fetch("https://e.com/a.png", StubOpener(StubResponse(body=bomb)))
    assert result.error == imagefetch.TOO_MANY_PIXELS
    assert "10000" in result.detail


def test_an_unmeasurable_format_is_refused_rather_than_passed_through():
    response = StubResponse(headers={"Content-Type": "image/avif"}, body=b"ftypavif")
    assert fetch("https://e.com/a.avif", StubOpener(response)).error == (
        imagefetch.NOT_AN_IMAGE
    )


def test_svg_is_refused_by_content_type():
    response = StubResponse(headers={"Content-Type": "image/svg+xml"}, body=b"<svg/>")
    assert fetch("https://e.com/a.svg", StubOpener(response)).error == (
        imagefetch.NOT_AN_IMAGE
    )


def test_a_damaged_png_is_refused_as_not_an_image_not_as_too_many_pixels():
    # A payload whose magic bytes match a format we parse, but which yields no
    # dimensions, is a different case from "measured and too big": it must not
    # be reported as a pixel-size problem, and the detail must not claim a size
    # that was never read.
    truncated = b"\x89PNG\r\n\x1a\n\x00\x00\x00"  # signature plus a stub, no IHDR
    response = StubResponse(headers={"Content-Type": "image/png"}, body=truncated)
    result = fetch("https://e.com/a.png", StubOpener(response))
    assert result.error == imagefetch.NOT_AN_IMAGE
    assert "pixel" not in result.detail
    assert "size" not in result.detail


def test_an_http_error_status_is_reported_with_its_code():
    result = fetch("https://e.com/a.png", StubOpener(StubResponse(status=404)))
    assert result.error == imagefetch.HTTP_ERROR
    assert "404" in result.detail


def test_a_redirect_to_https_is_followed():
    opener = StubOpener(
        StubResponse(status=302, headers={"Location": "https://cdn.e.com/b.png"}),
        StubResponse(body=PNG_1X1),
    )
    assert fetch("https://e.com/a.png", opener).ok
    assert opener.calls[1]["url"] == "https://cdn.e.com/b.png"


def test_a_redirect_down_to_http_is_refused():
    # urllib's own redirect handler permits this. Ours must not.
    opener = StubOpener(
        StubResponse(status=302, headers={"Location": "http://cdn.e.com/b.png"})
    )
    assert fetch("https://e.com/a.png", opener).error == imagefetch.REDIRECT_REFUSED


def test_a_redirect_to_a_private_address_is_refused():
    def resolver(host):
        return ["10.0.0.5"] if host == "internal.e.com" else ["93.184.216.34"]

    opener = StubOpener(
        StubResponse(status=302, headers={"Location": "https://internal.e.com/b.png"})
    )
    result = fetch("https://e.com/a.png", opener, resolver=resolver)
    assert result.error == imagefetch.BLOCKED_DESTINATION


def test_a_redirect_to_a_credential_bearing_url_is_refused():
    opener = StubOpener(
        StubResponse(status=302, headers={"Location": "https://u:p@cdn.e.com/b.png"})
    )
    assert fetch("https://e.com/a.png", opener).error == imagefetch.REDIRECT_REFUSED


def test_a_redirect_chain_longer_than_the_limit_is_refused():
    hops = [
        StubResponse(status=302, headers={"Location": f"https://e.com/{i}.png"})
        for i in range(remoteimages.MAX_REDIRECTS + 2)
    ]
    assert fetch("https://e.com/a.png", StubOpener(*hops)).error == (
        imagefetch.REDIRECT_REFUSED
    )


def test_a_redirect_with_no_location_is_refused():
    opener = StubOpener(StubResponse(status=302, headers={}))
    assert fetch("https://e.com/a.png", opener).error == imagefetch.REDIRECT_REFUSED


def test_a_timeout_is_reported_as_a_timeout():
    opener = StubOpener(TimeoutError("timed out"))
    assert fetch("https://e.com/a.png", opener).error == imagefetch.TIMEOUT


def test_proxies_are_passed_through_and_never_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("https_proxy", "http://should-not-be-used:3128")
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetch("https://e.com/a.png", opener, proxies={"https": "http://chosen:8080"})
    assert opener.calls[0]["proxies"] == {"https": "http://chosen:8080"}


def test_the_timeout_passed_to_the_opener_is_the_configured_one():
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetch("https://e.com/a.png", opener)
    assert opener.calls[0]["timeout"] == remoteimages.TIMEOUT_S
