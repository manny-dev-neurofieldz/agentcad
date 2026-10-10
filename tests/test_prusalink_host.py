"""The prusalink host against a fake PrusaLink that issues real Digest challenges and checks the answers.

Listing, download by either name, status, and each way a printer can go wrong: a wrong password, a
nonce that expired, a redirect, a 404, a server error, a truncated download, no answer, only Basic.
Every test runs under the loopback guard, so nothing here can reach a real printer.
"""

import io
import socket

import pytest

from agentcad import hosts
from agentcad.hosts import (HostAuthError, HostError, HostNotFound, HostServerError, HostUnreachable,
                            ReadOnlyViolation)
from agentcad.hosts.credentials import HostSettings
from tests.hostfakes import PASSWORD, USER, FakePrusaLink, blob, default_tree, file_node, loopback_only  # noqa: F401

pytestmark = pytest.mark.usefixtures("loopback_only")


@pytest.fixture
def serve():
    started = []

    def make(**options):
        fake = FakePrusaLink(**options)
        started.append(fake)
        return hosts.get_host("prusalink", fake.settings), fake
    yield make
    for fake in started:
        fake.close()


def _fetch(host, name, **kwargs):
    sink = io.BytesIO()
    info = host.download_file(name, lambda entry: sink, **kwargs)
    return info, sink.getvalue()


def test_a_listing_has_both_names_newest_first_and_folders_open_by_either_name(serve):
    host, fake = serve()
    listing = host.list_files()
    assert listing["storage"] == "usb" and listing["path"] == ""
    assert [e["name"] for e in listing["entries"]] == ["BRACKE~1.BGC", "BRACKE~2.BGC", "LID~1.BGC", "OLD"]
    first = listing["entries"][0]
    assert first["display_name"].startswith("bracket_v2") and first["kind"] == "file" and first["modified"] == 1790000300
    assert first["size"] == 200003 and listing["entries"][1]["size"] is None       # a printer may leave the size out
    assert first["download"] == "/usb/BRACKE~1.BGC"
    assert [e["kind"] for e in listing["entries"]][-1] == "folder"
    for folder in ("old", "OLD", "/old/"):
        inner = host.list_files(folder)
        assert inner["path"] == "OLD" and [e["name"] for e in inner["entries"]] == ["SPARE~1.BGC"]
    with pytest.raises(HostNotFound, match="no folder named 'lid.bgcode'"):
        host.list_files("lid.bgcode")


def test_a_file_downloads_byte_for_byte_by_short_name_display_name_or_either_in_other_case(serve):
    host, fake = serve()
    want = default_tree()[1]["data"]
    display = default_tree()[1]["display_name"]
    for name in ("BRACKE~1.BGC", display, "bracke~1.bgc", display.upper()):
        info, data = _fetch(host, name)
        assert data == want and info["bytes"] == len(want) == 200003
        assert info["name"] == "BRACKE~1.BGC" and info["download"] == "/usb/BRACKE~1.BGC"
    assert fake.requests[-1]["target"] == "/usb/BRACKE~1.BGC" and fake.requests[-1]["authorized"]
    info, data = _fetch(host, "old/spare_part_0.15mm.bgcode")                      # a file in a folder
    assert data == default_tree()[3]["children"][0]["data"] and info["path"] == "OLD/SPARE~1.BGC"


def test_the_download_comes_from_the_path_the_printer_names_and_never_from_an_unsafe_one(serve):
    host, fake = serve(refs="none")                                                 # no refs: built from the short name
    assert _fetch(host, "lid.bgcode")[1] == default_tree()[2]["data"]
    assert fake.requests[-1]["target"] == "/usb/LID~1.BGC"
    for unsafe in ("http://elsewhere.invalid/x", "//elsewhere.invalid/x", "/usb/../../etc/x", "/usb/a b"):
        host2, fake2 = serve(refs=unsafe)
        assert _fetch(host2, "lid.bgcode")[1] == default_tree()[2]["data"]          # fell back to /usb/LID~1.BGC
        assert fake2.requests[-1]["target"] == "/usb/LID~1.BGC"


def test_an_unknown_name_suggests_close_ones_and_an_ambiguous_one_lists_the_candidates(serve):
    host, fake = serve()
    with pytest.raises(HostNotFound, match=r"no file named 'bracket_v3.*did you mean: bracket_v"):
        _fetch(host, "bracket_v3_x1_PETG_MK4_0.4n_0.2mm_PETG_MK4IS_44m.bgcode")
    with pytest.raises(HostNotFound, match="no file named 'old'"):                  # a folder is not a file
        _fetch(host, "old")
    twins = [file_node("TWIN~1.BGC", "Twin.bgcode", 10, b"1"), file_node("TWIN~2.BGC", "twin.bgcode", 20, b"2")]
    host2, _ = serve(tree=twins)
    assert _fetch(host2, "twin.bgcode")[1] == b"2"                                  # an exact name wins over a case match
    with pytest.raises(HostError, match=r"names 2 files here; use a short name: TWIN~1.BGC, TWIN~2.BGC"):
        _fetch(host2, "TWIN.BGCODE")                                                # only ignoring case, both fit


def test_status_reports_the_state_and_the_running_job_or_none(serve):
    host, _ = serve(printer_state="PRINTING", job={"id": 7, "state": "PRINTING", "progress": 42.5, "time_remaining": 1800,
                                                    "time_printing": 600, "file": {"name": "BRACKE~1.BGC",
                                                                                   "display_name": "bracket_v2.bgcode",
                                                                                   "path": "/usb"}})
    status = host.job_status()
    assert status["printer"]["state"] == "PRINTING" and status["printer"]["temp_bed"] == 31.3
    assert status["job"] == {"id": 7, "state": "PRINTING", "progress": 42.5, "time_remaining": 1800, "time_printing": 600,
                             "file": {"name": "BRACKE~1.BGC", "display_name": "bracket_v2.bgcode", "path": "/usb"}}
    assert status["storage"]["name"] == "usb"
    idle, _ = serve()
    assert idle.job_status()["job"] is None                                         # the job route answers 204
    (printer,) = idle.list_printers()
    assert (printer["id"], printer["name"], printer["state"], printer["nozzle_mm"]) == ("bench-mk4", "bench-printer", "IDLE", 0.4)
    assert printer["url"] == idle.settings.url


@pytest.mark.parametrize("algorithms,qop,keep_alive,expected", [
    (("MD5",), "auth", True, "MD5"), (("MD5",), "auth", False, "MD5"), (("SHA-256",), "auth", True, "SHA-256"),
    (("SHA-512-256",), "auth", True, "SHA-512-256"), (("MD5",), None, True, "MD5"),
    (("MD5", "SHA-256"), "auth", True, "SHA-256")])
def test_the_digest_answer_is_accepted_across_algorithms_qop_and_connection_modes(serve, algorithms, qop, keep_alive, expected):
    host, fake = serve(algorithms=algorithms, qop=qop, keep_alive=keep_alive)
    assert host.job_status()["printer"]["state"] == "IDLE" and len(_fetch(host, "lid.bgcode")[1]) == 5000
    assert fake.algorithm_used == expected
    # every route is asked for twice: once bare, once with the answer to the challenge
    assert [r["authorized"] for r in fake.requests][:2] == [False, True]


def test_a_wrong_password_is_one_clear_error_after_one_answer(serve):
    host, fake = serve()
    bad = hosts.get_host("prusalink", HostSettings(url=fake.url, user=USER, password="wrong-" + PASSWORD, timeout=2, source="test"))
    with pytest.raises(HostAuthError, match="rejected the credentials") as caught:
        bad.job_status()
    assert [r["authorized"] for r in fake.requests] == [False, False]               # asked, answered once, stopped
    assert PASSWORD not in str(caught.value) and USER not in str(caught.value)
    wrong_user = hosts.get_host("prusalink", HostSettings(url=fake.url, user="nobody", password=PASSWORD, timeout=2, source="test"))
    with pytest.raises(HostAuthError, match="rejected the credentials"):
        wrong_user.job_status()


def test_an_expired_nonce_is_answered_once_more_and_a_basic_only_host_is_refused_by_name(serve):
    host, fake = serve(stale_first=True)
    assert host.job_status()["job"] is None
    assert [r["authorized"] for r in fake.requests][:3] == [False, False, True]    # bare, answered stale, answered fresh
    basic, _ = serve(basic_only=True)
    with pytest.raises(HostAuthError, match=r"asks for Basic authentication; agentcad speaks Digest only"):
        basic.job_status()


def test_http_errors_become_named_errors_with_the_servers_own_words(serve):
    host, _ = serve(fail={"/api/v1/status": 500, "/api/v1/info": 503})
    with pytest.raises(HostServerError, match=r"/api/v1/status: HTTP 500 .*the printer is having a bad day"):
        host.job_status()
    with pytest.raises(HostServerError, match="HTTP 503"):
        host.list_printers()
    healthy, _ = serve()
    with pytest.raises(HostNotFound, match=r"/api/v1/files/nope/: HTTP 404"):
        healthy.list_files(storage="nope")
    with pytest.raises(HostNotFound, match="HTTP 404"):
        healthy._get_json("/api/v1/nothing-here")


def test_a_redirect_is_reported_and_not_followed_and_no_credential_is_sent_anywhere(serve):
    elsewhere = FakePrusaLink()
    try:
        host, fake = serve(redirect_to=elsewhere.url)
        with pytest.raises(HostServerError, match="HTTP 301"):
            host.job_status()
        assert elsewhere.requests == [] and [r["authorized"] for r in fake.requests] == [False]
    finally:
        elsewhere.close()


def test_a_truncated_download_is_an_error_and_a_failing_sink_is_not_a_network_error(serve):
    host, _ = serve(truncate=True)
    with pytest.raises(HostError, match=r"incomplete reply: \d+ of 200003 bytes arrived"):
        _fetch(host, "BRACKE~1.BGC")

    class Full(io.BytesIO):
        def write(self, data):
            raise OSError(28, "No space left on device")
    healthy, _ = serve()
    with pytest.raises(HostError, match="cannot write the download: No space left on device") as caught:
        healthy.download_file("lid.bgcode", lambda entry: Full())
    assert not isinstance(caught.value, HostUnreachable)


def test_no_listener_and_no_answer_are_unreachable_with_the_address_and_never_the_credentials():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    host = hosts.get_host("prusalink", HostSettings(url=f"http://127.0.0.1:{port}", user=USER, password=PASSWORD, timeout=1, source="test"))
    with pytest.raises(HostUnreachable, match=f"cannot reach 127.0.0.1:{port}") as caught:
        host.list_printers()
    assert PASSWORD not in str(caught.value)
    silent = FakePrusaLink(hang=True, timeout=0.3)
    try:
        slow = hosts.get_host("prusalink", silent.settings)
        with pytest.raises(HostUnreachable, match="timed out after 0.3 s"):
            slow.job_status()
    finally:
        silent.close()


def test_head_is_sent_without_a_body_and_everything_else_is_refused_before_connecting(serve):
    host, fake = serve()
    reply = host._http("HEAD", "/api/v1/status")
    assert (reply.status, reply.body, reply.headers["content-type"]) == (200, b"", "application/json")
    assert fake.requests[-1]["method"] == "HEAD" and fake.requests[-1]["authorized"]
    before = len(fake.requests)
    for method in ("POST", "PUT", "DELETE"):
        with pytest.raises(ReadOnlyViolation, match="read-only"):
            host._http(method, "/api/v1/job")
    assert len(fake.requests) == before
    for path in ("/a b", "/a\r\nX-Evil: 1", "no-slash", "/\x00"):
        with pytest.raises(HostError, match="refusing a request path"):
            host._http("GET", path)
    assert len(fake.requests) == before


def test_a_url_with_a_path_prefix_is_kept_and_the_digest_uri_includes_it(serve):
    host, fake = serve(prefix="/printer")
    assert host.job_status()["printer"]["state"] == "IDLE"
    assert all(r["target"].startswith("/printer/api/v1/") for r in fake.requests)
    assert _fetch(host, "lid.bgcode")[1] == default_tree()[2]["data"]


def test_a_reply_that_is_not_what_the_host_expects_is_a_named_error(serve):
    host, _ = serve(raw={"/api/v1/status": b"<html>maintenance</html>", "/api/v1/files/usb/": b"{}"})
    with pytest.raises(HostServerError, match=r"/api/v1/status: the reply is not JSON"):
        host.job_status()
    with pytest.raises(HostServerError, match=r"/api/v1/files/usb/: the reply is not a folder listing"):
        host.list_files()
    healthy, _ = serve()
    with pytest.raises(HostError, match="the reply is larger than 10 bytes"):
        healthy._http("GET", "/api/v1/files/usb/", limit=10)
    with pytest.raises(HostError, match="no file name given"):
        _fetch(healthy, "/")
    garbled, _ = serve(garbage=True)
    with pytest.raises(HostUnreachable, match=r"sent a reply that is not HTTP \(BadStatusLine\)"):
        garbled.job_status()
    plain, fake = serve()
    https = hosts.get_host("prusalink", HostSettings(url=f"https://127.0.0.1:{fake.port}", user=USER, password=PASSWORD,
                                                      timeout=2, source="test"))
    with pytest.raises(HostUnreachable, match="TLS to 127.0.0.1|cannot reach 127.0.0.1"):         # TLS spoken to a plain server
        https.job_status()


def test_a_challenge_agentcad_cannot_answer_and_endless_stale_nonces_are_refused_not_looped(serve):
    host, fake = serve(qop="auth-int")
    with pytest.raises(HostAuthError, match=r"not one agentcad can answer \(offered: MD5 qop=auth-int\)"):
        host.job_status()
    assert len(fake.requests) == 1                                                  # nothing was sent that it could not stand behind
    host, fake = serve(always_stale=True)
    with pytest.raises(HostAuthError, match="kept asking for authentication"):
        host.job_status()
    assert len(fake.requests) == 3                                                  # bare, answered, answered again: then it stops


def test_a_chunked_download_arrives_whole_and_a_cut_one_is_incomplete(serve):
    host, _ = serve(chunked=True)
    assert _fetch(host, "BRACKE~1.BGC")[1] == default_tree()[1]["data"]
    cut, _ = serve(chunked=True, truncate=True)
    with pytest.raises(HostError, match="incomplete reply") as caught:
        _fetch(cut, "BRACKE~1.BGC")
    assert not isinstance(caught.value, HostUnreachable)


def test_a_firmware_without_the_info_or_job_route_still_reports(serve):
    host, _ = serve(fail={"/api/v1/info": 404, "/api/v1/job": 404}, printer_state="PRINTING")
    (printer,) = host.list_printers()
    assert printer["id"] == "printer" and printer["state"] == "PRINTING" and printer["nozzle_mm"] is None
    status = host.job_status()
    assert status["printer"]["state"] == "PRINTING" and status["job"] is None
