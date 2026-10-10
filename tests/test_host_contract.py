"""The printer-host contract, for every registered host.

A host declares its capabilities; each declared one works against a fake server, each it does not
declare raises NotSupported naming the host. Read-only is checked four ways (see
``tests/hostcontract.py``): the one network function refuses every method but GET and HEAD, the
source keeps network use inside that function, every connection is made from inside it, and the server
saw only GET and HEAD. The controls are hosts written to break the contract: each must fail the check
that is meant to catch it, which shows the checks can fail.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

from agentcad import hosts
from agentcad.hosts import CAPABILITIES, NotSupported, PrinterHost
from tests import hostcontract as contract
from tests.hostfakes import FAKES, loopback_only  # noqa: F401  (the fixture)

pytestmark = pytest.mark.usefixtures("loopback_only")

REGISTERED = hosts.list_hosts()


@pytest.fixture
def served(request):
    """(host, fake) for the registered host named by the test's ``name`` parameter."""
    name = request.node.callspec.params["name"]
    fake = FAKES[name]()
    try:
        yield hosts.get_host(name, fake.settings), fake
    finally:
        fake.close()


def test_every_registered_host_has_a_fake_server_for_these_tests():
    missing = [n for n in REGISTERED if n not in FAKES]
    assert not missing, f"register a fake server for {missing} in tests/hostfakes.py (FAKES); the contract runs against it"


@pytest.mark.parametrize("name", REGISTERED)
def test_declared_capabilities_work_and_are_shaped_as_the_contract_says(name, served):
    host, fake = served
    assert isinstance(host, PrinterHost) and host.name == name and set(host.capabilities) <= set(CAPABILITIES)
    ran = contract.exercise(host, fake)
    assert not ran["errors"], ran["errors"]
    results = ran["results"]
    if "list_printers" in results:
        assert results["list_printers"] and all({"id", "name"} <= set(p) for p in results["list_printers"])
    if "list_files" in results:
        listing = results["list_files"]
        assert {"storage", "path", "entries"} <= set(listing)
        assert listing["entries"] and all({"name", "display_name", "kind"} <= set(e) for e in listing["entries"])
    if "download_file" in results:
        assert results["download_file"]["bytes"] == len(ran["downloaded"]) > 0
    if "job_status" in results:
        assert isinstance(results["job_status"]["printer"], dict) and "job" in results["job_status"]


@pytest.mark.parametrize("name", REGISTERED)
def test_the_one_network_function_refuses_anything_but_get_and_head(name, served, monkeypatch):
    contract.check_refuses_writes(served[0], monkeypatch)


@pytest.mark.parametrize("name", REGISTERED)
def test_network_use_stays_inside_the_one_function_in_the_source(name):
    contract.check_source(type(hosts.get_host(name, settings=object())))


def test_the_shared_host_modules_do_no_network_io():
    package = Path(hosts.__file__).parent
    for module in ("__init__.py", "credentials.py", "digest.py"):
        contract.check_module_is_network_free(package / module)


@pytest.mark.parametrize("name", REGISTERED)
def test_every_connection_comes_from_the_one_function_and_only_get_and_head_cross_the_wire(name, served, monkeypatch):
    ran = contract.check_wire(*served, monkeypatch)
    assert not ran["errors"], ran["errors"]


def test_a_host_with_fewer_capabilities_names_itself_when_asked_for_the_rest():
    class Stub(PrinterHost):
        name = "stub"

    class Lister(PrinterHost):
        name = "lister"
        capabilities = frozenset({"list_files"})

    hosts.register_host("stub", Stub)
    hosts.register_host("lister", Lister)
    try:
        listed = {h["name"]: h["capabilities"] for h in hosts.describe()}
        assert listed["stub"] == [] and listed["lister"] == ["list_files"]
        with pytest.raises(NotSupported, match=r"host 'stub' does not job status"):
            Stub().job_status()
        with pytest.raises(NotSupported, match="lister"):
            Lister().download_file("x", lambda entry: None)
        with pytest.raises(NotSupported, match="does not list printers"):
            Lister().list_printers()
        with pytest.raises(NotSupported, match="stub"):
            Stub().list_files()
        with pytest.raises(NotSupported, match="its capabilities: list_files"):
            Lister().require("job_status")
        with pytest.raises(ValueError, match="registered: .*lister"):
            hosts.get_host("nope")
    finally:
        hosts.unregister_host("stub")
        hosts.unregister_host("lister")


# ---- the controls: hosts written to break the contract -----------------------------------------------

_PREAMBLE = '''
from agentcad.hosts import HostResponse, require_read_only
from agentcad.hosts.prusalink import PrusaLinkHost
'''

_CONNECT = '''
        import http.client
        from urllib.parse import urlsplit
        parts = urlsplit(self.settings.url)
        conn = http.client.HTTPConnection(parts.hostname, parts.port, timeout=2)
'''

CONTROLS = {
    # no guard at all, and a POST spelled out
    "forgetful": (_PREAMBLE + '''
class BadHost(PrusaLinkHost):
    name = "forgetful"

    def _http(self, method, path, *, sink=None, accept="application/json", limit=0):''' + _CONNECT + '''        conn.request("POST", path, body=b"x")
        reply = conn.getresponse()
        reply.read()
        conn.close()
        return HostResponse(reply.status, reply.reason)
''', {"refuses_writes": "sent or accepted", "source": "require_read_only", "wire": "POST"}),
    # the guard is there and the source has no write method in it, but the method on the wire is built at run time
    "sneaky": (_PREAMBLE + '''
class BadHost(PrusaLinkHost):
    name = "sneaky"

    def _http(self, method, path, *, sink=None, accept="application/json", limit=0):
        require_read_only(method)''' + _CONNECT + '''        conn.request("PO" + "ST", path, body=b"x")
        reply = conn.getresponse()
        reply.read()
        conn.close()
        return HostResponse(reply.status, reply.reason)
''', {"wire": "POST"}),
    # the one function is fine (inherited); another method opens its own socket
    "leaky": (_PREAMBLE + '''
class BadHost(PrusaLinkHost):
    name = "leaky"

    def _peek(self):
        import socket
        from urllib.parse import urlsplit
        parts = urlsplit(self.settings.url)
        socket.create_connection((parts.hostname, parts.port), timeout=2).close()

    def list_printers(self):
        self._peek()
        return super().list_printers()
''', {"source": "socket", "wire": "connected from outside"}),
}


def _load_bad_host(tmp_path, variant):
    path = tmp_path / f"bad_{variant}.py"
    path.write_text(CONTROLS[variant][0])
    spec = importlib.util.spec_from_file_location(f"bad_{variant}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.BadHost


@pytest.mark.parametrize("variant", sorted(CONTROLS))
def test_the_contract_fails_for_a_host_that_breaks_it(variant, tmp_path, monkeypatch):
    """Each control must fail the checks meant to catch it, and the message must say what was found."""
    expect = CONTROLS[variant][1]
    cls = _load_bad_host(tmp_path, variant)
    hosts.register_host(variant, cls)
    fake = FAKES["prusalink"]()
    try:
        assert variant in hosts.list_hosts()
        host = hosts.get_host(variant, fake.settings)
        checks = {"refuses_writes": lambda: contract.check_refuses_writes(host, monkeypatch),
                  "source": lambda: contract.check_source(cls),
                  "wire": lambda: contract.check_wire(host, fake, monkeypatch)}
        for check, call in checks.items():
            if check in expect:
                with pytest.raises(AssertionError, match=expect[check]):
                    call()
            else:                                         # a check that is not meant to catch this host passes
                call()
    finally:
        fake.close()
        hosts.unregister_host(variant)
        sys.modules.pop(f"bad_{variant}", None)
