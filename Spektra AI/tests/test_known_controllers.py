"""TLS certificates are remembered per address, and a different one is refused until
accepted on purpose (known_controllers.py)."""
import asyncio
import json

import pytest

from edidio_spektra_ai import known_controllers as K
from edidio_spektra_ai import server as srv
from edidio_spektra_ai.controller import SpektraController


@pytest.fixture(autouse=True)
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPEKTRA_AI_STATE", str(tmp_path))
    return tmp_path


A, B = "a" * 64, "b" * 64


def test_first_connection_is_remembered(state_dir):
    note = K.check("10.0.0.5", 443, A)
    assert "First TLS connection to 10.0.0.5" in note
    stored = json.loads((state_dir / "known_controllers.json").read_text())
    assert stored["10.0.0.5:443"]["sha256"] == A


def test_same_certificate_is_quiet():
    K.check("10.0.0.5", 443, A)
    assert K.check("10.0.0.5", 443, A) == ""


def test_changed_certificate_is_refused_and_not_stored():
    K.check("10.0.0.5", 443, A)
    with pytest.raises(K.CertificateChanged) as err:
        K.check("10.0.0.5", 443, B)
    assert "different TLS certificate" in str(err.value)
    assert "accept_new_certificate=true" in str(err.value)
    assert K.check("10.0.0.5", 443, A) == ""                 # the old one still stands


def test_accepting_a_new_certificate_replaces_it():
    K.check("10.0.0.5", 443, A)
    assert "accepted and remembered" in K.check("10.0.0.5", 443, B, accept_new=True)
    assert K.check("10.0.0.5", 443, B) == ""


def test_addresses_are_independent():
    K.check("10.0.0.5", 443, A)
    assert "First TLS connection" in K.check("10.0.0.6", 443, B)


def test_unreadable_store_starts_afresh(state_dir):
    (state_dir / "known_controllers.json").write_text("{not json")
    assert "First TLS connection" in K.check("10.0.0.5", 443, A)


# --- through SpektraController.connect and connect_controller ---

class _SSL:
    def __init__(self, der):
        self.der = der

    def getpeercert(self, binary_form=False):
        return self.der if binary_form else {}


class _Writer:
    def __init__(self, der):
        self.ssl = _SSL(der)

    def get_extra_info(self, name):
        return self.ssl if name == "ssl_object" else None


class TLSStub:
    """A client that presents a certificate (CERT is swapped by the tests)."""
    CERT = b"controller-one"

    def __init__(self, host, port, use_tls):
        self.connected, self.sent = False, []
        self._writer = _Writer(TLSStub.CERT)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def request(self, frame):          # wrapped by connect (read retries)
        self.sent.append(frame)


def _fresh():
    srv._controller = SpektraController(client_factory=lambda h, p, t: TLSStub(h, p, t))
    srv._pending.clear()
    return srv._controller


def test_connect_reports_a_new_certificate_and_refuses_a_swap():
    _fresh()
    TLSStub.CERT = b"controller-one"
    first = asyncio.run(srv.connect_controller("10.0.0.7", 443, True))
    assert first.startswith("Connected to 10.0.0.7.") and "is remembered" in first
    assert asyncio.run(srv.connect_controller("10.0.0.7", 443, True)) == "Connected to 10.0.0.7."
    TLSStub.CERT = b"something-else"
    refused = asyncio.run(srv.connect_controller("10.0.0.7", 443, True))
    assert refused.startswith("Error:") and "different TLS certificate" in refused
    assert not srv._controller.connected                       # closed before anything was sent
    accepted = asyncio.run(srv.connect_controller("10.0.0.7", 443, True, accept_new_certificate=True))
    assert accepted.startswith("Connected") and "accepted and remembered" in accepted


def test_plain_tcp_is_not_pinned(state_dir):
    _fresh()
    out = asyncio.run(srv.connect_controller("10.0.0.8", 23, False))
    assert out == "Connected to 10.0.0.8."
    assert not (state_dir / "known_controllers.json").exists()
