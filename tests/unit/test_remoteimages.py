"""Which remote references may be fetched, and the private scheme's codec."""

from xedown import remoteimages


def test_https_is_fetchable():
    decision = remoteimages.classify_remote("https://example.com/a.png")
    assert decision.status == remoteimages.FETCHABLE
    assert decision.url == "https://example.com/a.png"


def test_http_is_insecure_rather_than_merely_unsupported():
    decision = remoteimages.classify_remote("http://example.com/a.png")
    assert decision.status == remoteimages.INSECURE


def test_credentials_in_the_url_are_refused_by_policy():
    # urllib would fail on this anyway, with a confusing "nonnumeric port"
    # error. Refusing by policy is what makes the refusal deliberate.
    decision = remoteimages.classify_remote("https://user:pass@example.com/a.png")
    assert decision.status == remoteimages.CREDENTIALS


def test_a_username_alone_is_still_credentials():
    decision = remoteimages.classify_remote("https://user@example.com/a.png")
    assert decision.status == remoteimages.CREDENTIALS


def test_mailto_is_unsupported():
    assert remoteimages.classify_remote("mailto:a@b.c").status == (
        remoteimages.UNSUPPORTED
    )


def test_an_unparseable_reference_is_malformed_rather_than_raising():
    decision = remoteimages.classify_remote("https://[oops/a.png")
    assert decision.status == remoteimages.MALFORMED


def test_a_scheme_uri_round_trips():
    url = "https://example.com/a b/ünïcode.png?x=1&y=2#frag"
    assert remoteimages.parse_scheme_uri(remoteimages.scheme_uri(url)) == url


def test_the_payload_is_fully_escaped_so_it_carries_no_bare_slash():
    encoded = remoteimages.scheme_uri("https://example.com/a/b.png")
    assert "/" not in encoded[len(remoteimages.SCHEME) + 1 :]


def test_parse_refuses_a_non_https_payload():
    # The handler is an entry point. It must not trust that the DOM only
    # contains URLs the renderer put there.
    assert (
        remoteimages.parse_scheme_uri("xedown-image:http%3A%2F%2Fe.com%2Fa.png") is None
    )
    assert (
        remoteimages.parse_scheme_uri("xedown-image:file%3A%2F%2F%2Fetc%2Fpasswd")
        is None
    )


def test_parse_refuses_credentials_and_junk():
    assert (
        remoteimages.parse_scheme_uri(
            "xedown-image:https%3A%2F%2Fu%3Ap%40e.com%2Fa.png"
        )
        is None
    )
    assert remoteimages.parse_scheme_uri("not-our-scheme:https%3A%2F%2Fe.com") is None
    assert remoteimages.parse_scheme_uri("xedown-image:") is None
