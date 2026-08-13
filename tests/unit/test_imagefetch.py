"""Fetching a remote image: the cache, the limits, and the coalescing."""

import email.message
import io
import urllib.error

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


class RaisingCloseResponse(StubResponse):
    """A response whose `close()` misbehaves, like a socket in a bad state.

    `http.client.HTTPResponse.close()` can raise `OSError`/`ConnectionResetError`
    /`ssl.SSLError` on a connection that is already broken -- this stands in for
    that, on top of otherwise-ordinary status/body behaviour.
    """

    def close(self):
        raise RuntimeError("close boom")


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


def http_error(status, message, headers=None, body=b""):
    """A non-2xx in the shape urllib really produces: raised, not returned.

    `urllib.error.HTTPError` is both an exception and a response, and the
    opener *raises* it -- there is no returned object with a `.status` on it
    to inspect. The stub above models the other shape; both occur, and only
    this one occurs in the field.
    """
    headers_message = email.message.Message()
    for name, value in (headers or {}).items():
        headers_message[name] = value
    return urllib.error.HTTPError(
        "https://e.com/a.png", status, message, headers_message, io.BytesIO(body)
    )


def test_a_raised_http_error_is_reported_with_its_code():
    # `HTTPError` is a subclass of `URLError`, so the `except URLError`
    # branch used to swallow it first and every 404 in the field was
    # reported as "it could not be reached (Not Found)" -- a transport
    # failure, which it is not. Confirmed against a real server before the
    # fix and after it.
    result = fetch("https://e.com/a.png", StubOpener(http_error(404, "Not Found")))
    assert result.error == imagefetch.HTTP_ERROR
    assert "404" in result.detail


def test_a_redirect_raised_as_an_http_error_is_still_followed():
    # The same trap, and the worse half of it: `_urllib_opener` removes
    # urllib's redirect handler on purpose (it permits an https -> http
    # downgrade), which means a 3xx is *raised* as an HTTPError too. Read as
    # an error, it silently ended the hop-by-hop following this module
    # implements by hand -- so no redirect worked at all outside the tests.
    opener = StubOpener(
        http_error(302, "Found", headers={"Location": "https://cdn.e.com/b.png"}),
        StubResponse(body=PNG_1X1),
    )
    result = fetch("https://e.com/a.png", opener)
    assert result.ok and result.mime == "image/png"
    assert [call["url"] for call in opener.calls] == [
        "https://e.com/a.png",
        "https://cdn.e.com/b.png",
    ]


def test_a_redirect_raised_as_an_http_error_cannot_downgrade_to_http():
    opener = StubOpener(
        http_error(302, "Found", headers={"Location": "http://cdn.e.com/b.png"})
    )
    result = fetch("https://e.com/a.png", opener)
    assert result.error == imagefetch.REDIRECT_REFUSED


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


# A `finally` that raises replaces whatever the `try`/`except` was about to
# return, so a misbehaving `close()` must never be allowed to escape
# `fetch_once` -- on a success path, a clean-error path, or a malformed-
# response path alike. Each assertion below is "the right result still came
# back", not merely "nothing raised".


def test_a_close_that_raises_does_not_lose_a_successful_result():
    opener = StubOpener(RaisingCloseResponse(body=PNG_1X1))
    result = fetch("https://e.com/a.png", opener)
    assert result.ok and result.mime == "image/png"


def test_a_close_that_raises_does_not_lose_an_http_error():
    opener = StubOpener(RaisingCloseResponse(status=404))
    result = fetch("https://e.com/a.png", opener)
    assert result.error == imagefetch.HTTP_ERROR
    assert "404" in result.detail


def test_a_close_that_raises_does_not_lose_a_malformed_response_error():
    opener = StubOpener(RaisingCloseResponse(status="not-an-int"))
    result = fetch("https://e.com/a.png", opener)
    assert result.error == imagefetch.NETWORK
    assert result.data is None


class ManualExecutor:
    """Runs nothing until told, so a fetch can be observed mid-flight."""

    def __init__(self):
        self.jobs = []

    def submit(self, function):
        self.jobs.append(function)

    def run_all(self):
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()


def make_fetcher(opener, executor=None, **kwargs):
    return imagefetch.Fetcher(
        opener=opener,
        resolver=public,
        network_available=kwargs.pop("network_available", lambda: True),
        executor=executor,
        **kwargs,
    )


def test_many_requests_while_one_fetch_is_in_flight_make_one_network_call():
    # The core of the coalescing requirement: 20 re-renders during a single
    # slow fetch must not produce 20 fetches.
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor)

    seen = []
    for _ in range(20):
        fetcher.request("https://e.com/a.png", seen.append)

    assert len(executor.jobs) == 1, "only the first request starts a fetch"
    executor.run_all()

    assert len(opener.calls) == 1
    assert len(seen) == 20
    assert all(result.ok for result in seen)


def test_a_second_url_still_gets_its_own_fetch():
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1), StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor)
    fetcher.request("https://e.com/a.png", lambda r: None)
    fetcher.request("https://e.com/b.png", lambda r: None)
    assert len(executor.jobs) == 2


def test_a_completed_fetch_is_served_from_cache_without_the_executor():
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor)
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    assert executor.jobs == []
    assert len(opener.calls) == 1
    assert seen[0].ok


def test_a_failure_is_served_from_cache_too():
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(status=404))
    fetcher = make_fetcher(opener, executor)
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    assert executor.jobs == [], "a cached failure must not re-fetch"
    assert seen[0].error == imagefetch.HTTP_ERROR


def test_a_failed_image_refetches_after_an_explicit_retry():
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(status=404), StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor)
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()

    fetcher.invalidate_failures()  # what Refresh and [Load] do

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    executor.run_all()
    assert len(opener.calls) == 2
    assert seen[0].ok


def test_an_evicted_success_is_fetched_again():
    # The cache is bounded, so "one request per URL per session" is not a
    # guarantee the implementation makes.
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1), StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor)
    fetcher.cache.max_bytes = 1  # nothing real can stay
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()
    assert len(opener.calls) == 2


def test_pending_work_is_bounded():
    executor = ManualExecutor()
    fetcher = make_fetcher(StubOpener(*[StubResponse(body=PNG_1X1)] * 200), executor)
    seen = []
    for index in range(remoteimages.MAX_PENDING_URLS + 5):
        fetcher.request(f"https://e.com/{index}.png", seen.append)
    assert len(executor.jobs) == remoteimages.MAX_PENDING_URLS
    refused = [r for r in seen if r.error == imagefetch.TOO_MANY]
    assert len(refused) == 5


def test_being_offline_fails_immediately_without_dialling():
    opener = StubOpener()
    fetcher = make_fetcher(opener, ManualExecutor(), network_available=lambda: False)
    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    assert seen[0].error == imagefetch.OFFLINE
    assert opener.calls == []


def test_an_offline_refusal_is_cached_and_invalidate_failures_clears_it():
    # `controller._on_image_error` (host-bound, so untestable here) looks a
    # failure up by `cached(url)` alone -- without this, the reader never
    # saw the offline-specific sentence, only the generic fallback text,
    # because the lookup always missed. `invalidate_failures()` is the same
    # "try again" mechanism a normal cached failure gets (called on
    # reconnect, on Refresh, and on Load), and the placeholder's own wording
    # ("Refresh once you are back online") promises exactly that lifetime.
    opener = StubOpener()
    fetcher = make_fetcher(opener, ManualExecutor(), network_available=lambda: False)
    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    assert seen[0].error == imagefetch.OFFLINE

    cached = fetcher.cached("https://e.com/a.png")
    assert cached is not None and cached.error == imagefetch.OFFLINE

    fetcher.invalidate_failures()  # what reconnecting, Refresh and [Load] do
    assert fetcher.cached("https://e.com/a.png") is None


def test_too_many_refusal_is_not_cached():
    # Deliberately asymmetric with OFFLINE above: TOO_MANY is a fact about
    # the pending queue being full right now, not about the URL, so caching
    # it would strand the URL failed long after the queue has drained and a
    # fresh request would have succeeded.
    executor = ManualExecutor()
    fetcher = make_fetcher(StubOpener(*[StubResponse(body=PNG_1X1)] * 200), executor)
    seen = []
    for index in range(remoteimages.MAX_PENDING_URLS + 1):
        fetcher.request(f"https://e.com/{index}.png", seen.append)

    refused_url = f"https://e.com/{remoteimages.MAX_PENDING_URLS}.png"
    assert seen[-1].error == imagefetch.TOO_MANY
    assert fetcher.cached(refused_url) is None


def test_a_raising_callback_does_not_stop_the_other_waiters():
    executor = ManualExecutor()
    fetcher = make_fetcher(StubOpener(StubResponse(body=PNG_1X1)), executor)
    seen = []

    def explode(_result):
        raise RuntimeError("callback trouble")

    fetcher.request("https://e.com/a.png", explode)
    fetcher.request("https://e.com/a.png", seen.append)
    executor.run_all()
    assert len(seen) == 1


def test_proxies_for_is_consulted_with_the_url_and_reaches_the_opener():
    # The brief's own `proxies` dict was rejected in favour of a callable so
    # that a later task never has to reach into `fetcher._proxies` to change
    # what one request needs -- it asks `proxies_for(url)` instead.
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1))
    seen_urls = []

    def proxies_for(url):
        seen_urls.append(url)
        return {"https": "http://chosen:8080"}

    fetcher = make_fetcher(opener, executor, proxies_for=proxies_for)
    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()

    assert seen_urls == ["https://e.com/a.png"]
    assert opener.calls[0]["proxies"] == {"https": "http://chosen:8080"}


def _exploding_proxies_for(_url):
    raise RuntimeError("proxy lookup exploded")


def test_a_raising_proxies_for_does_not_leak_the_in_flight_slot():
    # `on_done` is guarded by `_deliver_one`, but `proxies_for` runs inside
    # `work()` too, unguarded: an exception there used to leave `_settle`
    # never scheduled, so the URL stayed in `_waiting` forever -- a permanent
    # loading spinner and one of MAX_PENDING_URLS gone for the life of the
    # process. Checking only "a result arrived" would not catch that, so the
    # slot itself is asserted, not just the callback.
    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor, proxies_for=_exploding_proxies_for)

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    executor.run_all()

    assert len(seen) == 1
    assert seen[0].ok is False
    assert "https://e.com/a.png" not in fetcher._waiting


def test_a_raising_proxies_for_on_the_inline_path_does_not_propagate():
    # executor=None runs `work()` synchronously inside `request()` -- the
    # exception must still be turned into a FetchResult there, not escape
    # out of `request()` itself.
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor=None, proxies_for=_exploding_proxies_for)

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)  # must not raise

    assert len(seen) == 1
    assert seen[0].ok is False
    assert "https://e.com/a.png" not in fetcher._waiting


def test_a_reclaimed_slot_lets_the_next_request_fetch_again():
    # The real proof the slot was released: after the (now-cached) failure is
    # invalidated, a following request for the same URL must actually start a
    # fresh fetch. If `_waiting` still held the leaked entry from the
    # unguarded exception, this request would instead be silently absorbed
    # into that phantom waiter list -- no job submitted to the executor, and
    # a callback nobody would ever hear from.
    def explode_once():
        calls = {"count": 0}

        def proxies_for(_url):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("proxy lookup exploded")

        return proxies_for

    executor = ManualExecutor()
    opener = StubOpener(StubResponse(body=PNG_1X1))
    fetcher = make_fetcher(opener, executor, proxies_for=explode_once())

    fetcher.request("https://e.com/a.png", lambda r: None)
    executor.run_all()

    fetcher.invalidate_failures()  # what Refresh and [Load] do

    seen = []
    fetcher.request("https://e.com/a.png", seen.append)
    assert len(executor.jobs) == 1, "a fresh fetch must actually start"
    executor.run_all()

    assert len(opener.calls) == 1
    assert seen[0].ok
