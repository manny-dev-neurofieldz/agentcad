"""HTTP Digest, from the published examples and by hand-computed hashes.

The known answers are the worked examples of RFC 2617 section 3.5 (MD5) and RFC 7616 section 3.9.1
(MD5 and SHA-256): if these pass, the client computes what any conforming server computes, whatever
the fake server in the other tests happens to accept.
"""

import hashlib
import re

import pytest

from agentcad.hosts import digest

RFC2617 = dict(user="Mufasa", password="Circle Of Life", realm="testrealm@host.com",
               nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", uri="/dir/index.html", cnonce="0a4f113b",
               opaque="5ccc069c403ebaf9f0171e9517f40e41")
RFC7616 = dict(user="Mufasa", password="Circle of Life", realm="http-auth@example.org",
               nonce="7ypf/xlj9XXwfDPEoM4URrv/xwf94BcCAzFZH4GiTo0v", uri="/dir/index.html",
               cnonce="f2/wE4q74E6zIJEtWaHKaf5wv/H5QzzpXusqGemxURZJ",
               opaque="FQhe/qaU925kfnzjCev0ciny7QMkPqMAFRtzCUYo5tdS")


def _challenge(v, algorithm="MD5", qop=("auth",)):
    return digest.Challenge(realm=v["realm"], nonce=v["nonce"], opaque=v["opaque"], algorithm=algorithm,
                            algorithm_named=True, qop=list(qop))


@pytest.mark.parametrize("vector,algorithm,expected", [
    (RFC2617, "MD5", "6629fae49393a05397450978507c4ef1"),
    (RFC7616, "MD5", "8ca523f5e9506fed4657c9700eebdbec"),
    (RFC7616, "SHA-256", "753927fa0e85d155564e2e272a28d1802ca10daf4496794697cf8db5856cb6c1"),
])
def test_the_rfc_worked_examples(vector, algorithm, expected):
    ch = _challenge(vector, algorithm)
    got = digest.response_value(ch, "GET", vector["uri"], vector["user"], vector["password"], 1, vector["cnonce"])
    assert got == expected
    header = digest.authorization(ch, "GET", vector["uri"], vector["user"], vector["password"], 1, vector["cnonce"])
    assert header.startswith("Digest username=\"Mufasa\", realm=") and f'response="{expected}"' in header
    assert "nc=00000001" in header and "qop=auth" in header and f"algorithm={algorithm}" in header


def test_a_header_with_several_challenges_is_split_and_the_digest_ones_parsed():
    value = ('Basic realm="x", Digest realm="Printer API", nonce="n\\"1", qop="auth,auth-int", '
             'algorithm=SHA-256, opaque="o,p", stale=TRUE')
    assert [s for s, _ in digest.split_challenges(value)] == ["Basic", "Digest"]
    (ch,) = digest.parse_challenges([value])
    assert (ch.realm, ch.nonce, ch.opaque, ch.algorithm, ch.qop, ch.stale) == \
        ("Printer API", 'n"1', "o,p", "SHA-256", ["auth", "auth-int"], True)
    assert digest.offered_schemes([value]) == ["Basic", "Digest"]
    assert digest.offered_schemes(['Bearer realm="a"']) == ["Bearer"]


def test_the_strongest_usable_challenge_is_chosen_and_an_unanswerable_one_is_refused():
    both = digest.parse_challenges(['Digest realm="r", nonce="a", algorithm=MD5, qop="auth"',
                                    'Digest realm="r", nonce="a", algorithm=SHA-256, qop="auth"'])
    assert digest.choose(both).algorithm == "SHA-256"
    with pytest.raises(digest.DigestError, match="auth-int"):
        digest.choose(digest.parse_challenges(['Digest realm="r", nonce="a", qop="auth-int"']))
    with pytest.raises(digest.DigestError, match="SHA3-999"):
        digest.choose(digest.parse_challenges(['Digest realm="r", nonce="a", algorithm=SHA3-999, qop="auth"']))
    assert digest.parse_challenges(['Digest realm="r"']) == []                      # no nonce: nothing to answer


def test_the_older_form_without_qop_and_the_session_variant():
    v = RFC2617
    plain = digest.Challenge(realm=v["realm"], nonce=v["nonce"])                    # no qop, no algorithm named
    ha1 = hashlib.md5(f"{v['user']}:{v['realm']}:{v['password']}".encode()).hexdigest()
    ha2 = hashlib.md5(f"GET:{v['uri']}".encode()).hexdigest()
    want = hashlib.md5(f"{ha1}:{v['nonce']}:{ha2}".encode()).hexdigest()
    assert digest.response_value(plain, "GET", v["uri"], v["user"], v["password"], 1, "ignored") == want
    header = digest.authorization(plain, "GET", v["uri"], v["user"], v["password"])
    assert "qop=" not in header and "nc=" not in header and "algorithm=" not in header and f'response="{want}"' in header
    sess = digest.Challenge(realm=v["realm"], nonce=v["nonce"], algorithm="MD5-SESS", qop=["auth"])
    ha1s = hashlib.md5(f"{ha1}:{v['nonce']}:{v['cnonce']}".encode()).hexdigest()
    want_s = hashlib.md5(f"{ha1s}:{v['nonce']}:00000001:{v['cnonce']}:auth:{ha2}".encode()).hexdigest()
    assert digest.response_value(sess, "GET", v["uri"], v["user"], v["password"], 1, v["cnonce"]) == want_s


def test_quoting_nonce_counts_and_a_fresh_cnonce_per_answer():
    ch = digest.Challenge(realm='a"b', nonce="n", qop=["auth"])
    first = digest.authorization(ch, "GET", "/x", 'us"er', "pw", nc=11)
    assert 'username="us\\"er"' in first and 'realm="a\\"b"' in first and "nc=0000000b" in first
    second = digest.authorization(ch, "GET", "/x", 'us"er', "pw", nc=11)
    cnonce = lambda h: re.search(r'cnonce="([0-9a-f]{16})"', h).group(1)
    assert cnonce(first) != cnonce(second)


def test_a_session_algorithm_without_qop_still_sends_the_client_nonce():
    ch = digest.Challenge(realm="r", nonce="n", algorithm="MD5-SESS")
    header = digest.authorization(ch, "GET", "/x", "u", "p", cnonce="abcd1234")
    assert 'cnonce="abcd1234"' in header and "nc=" not in header and "qop=" not in header
