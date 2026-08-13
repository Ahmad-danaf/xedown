"""Which remote references may be fetched, and the private scheme's codec."""

import pytest
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


def resolver_returning(*addresses):
    def resolve(_host):
        return list(addresses)

    return resolve


def test_a_public_address_is_allowed():
    verdict = remoteimages.check_destination(
        "example.com", resolver=resolver_returning("93.184.216.34")
    )
    assert verdict.ok is True


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",  # loopback
        "::1",  # loopback v6
        "10.0.0.5",  # private
        "192.168.1.1",  # private
        "172.16.0.1",  # private
        "169.254.169.254",  # link-local: the cloud metadata endpoint
        "fe80::1",  # link-local v6
        "fc00::1",  # unique local v6
        "0.0.0.0",  # unspecified
        "100.64.0.1",  # carrier NAT: neither global NOR private
        "::ffff:127.0.0.1",  # loopback wearing a v6 mapping
        "::127.0.0.1",  # IPv4-compatible: loopback, but is_global says True
        "::169.254.169.254",  # IPv4-compatible: the cloud metadata endpoint
        "::10.0.0.5",  # IPv4-compatible: private
        "::7f00:1",  # the same address, hex spelling
    ],
)
def test_non_public_addresses_are_refused(address):
    verdict = remoteimages.check_destination(
        "anything.example", resolver=resolver_returning(address)
    )
    assert verdict.ok is False


@pytest.mark.parametrize(
    "address",
    [
        "224.0.0.1",  # the IPv4 all-hosts group
        "239.1.1.1",  # administratively scoped multicast
        "ff02::1",  # the IPv6 all-nodes group
        "ff0e::1",  # global-scope multicast
    ],
)
def test_multicast_is_not_the_public_internet(address):
    # Neither reserved nor private, and `is_global` says True for all four.
    # Nothing is reachable over TCP this way, so no hole is being closed --
    # but a predicate named for the public internet must not answer yes here.
    verdict = remoteimages.check_destination(
        "group.example", resolver=resolver_returning(address)
    )
    assert verdict.ok is False


def test_a_host_resolving_to_both_public_and_private_is_refused():
    # Refusing needs only one bad address: a round-robin that sometimes
    # answers privately would otherwise be allowed on a lucky ordering.
    verdict = remoteimages.check_destination(
        "split.example", resolver=resolver_returning("93.184.216.34", "10.0.0.5")
    )
    assert verdict.ok is False


def test_a_host_that_resolves_to_nothing_is_refused():
    verdict = remoteimages.check_destination(
        "void.example", resolver=resolver_returning()
    )
    assert verdict.ok is False


def test_a_resolver_failure_is_refused_rather_than_raised():
    def explode(_host):
        raise OSError("no such host")

    assert remoteimages.check_destination("x.example", resolver=explode).ok is False


def test_a_refusal_says_whether_the_host_resolved_at_all():
    # Both are refusals, and they are not the same statement. Reported alike,
    # an ordinary typo or DNS outage reached the reader as "that address is
    # not on the public internet" -- an accusation about an address nobody
    # managed to look up.
    def explode(_host):
        raise OSError("no such host")

    assert remoteimages.check_destination("x.example", resolver=explode).unresolved
    assert remoteimages.check_destination(
        "void.example", resolver=resolver_returning()
    ).unresolved
    private = remoteimages.check_destination(
        "internal.example", resolver=resolver_returning("10.0.0.5")
    )
    assert private.ok is False
    assert private.unresolved is False


def test_the_real_resolver_rejects_the_numeric_spellings_of_loopback():
    # The whole reason the check is on resolved addresses and not on the
    # hostname string. These are real DNS-free resolutions.
    for spelling in ("2130706433", "0x7f000001", "0177.0.0.1", "localhost"):
        assert remoteimages.check_destination(spelling).ok is False


def test_a_v4_mapped_public_address_is_still_allowed():
    # The fix adds `not is_reserved`, which must be read AFTER the ipv4_mapped
    # unwrap: the ::ffff:0:0/96 block is itself reserved, so applying it to the
    # outer address would refuse every v4-mapped public host.
    verdict = remoteimages.check_destination(
        "mapped.example", resolver=resolver_returning("::ffff:93.184.216.34")
    )
    assert verdict.ok is True
