"""Fetching a remote image: the cache, the limits, and the coalescing."""

from xedown import imagefetch


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
