"""Remember each controller's TLS certificate, and refuse one that changes.

eDIDIO certificates cannot be verified (the fleet's RSA-1024 certificates are bound to
the device's own ID, not an address; see controller.legacy_tls_context), so TLS alone
would let anything on the LAN answer as the controller. This adds what SSH does with
known_hosts: the first TLS connection to an address records the certificate's SHA-256
fingerprint, later connections must present the same one, and a different one is
refused until it is accepted on purpose (the controller was replaced or re-provisioned,
or the address now belongs to another controller).

Stored in $SPEKTRA_AI_STATE/known_controllers.json (default ~/.spektra_ai).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path


class CertificateChanged(RuntimeError):
    """The controller at this address presented a different certificate than before."""


def store_path() -> Path:
    base = os.environ.get("SPEKTRA_AI_STATE") or str(Path.home() / ".spektra_ai")
    return Path(base) / "known_controllers.json"


def _load() -> dict:
    try:
        return json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    p = store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)


def fingerprint(client) -> str | None:
    """SHA-256 of the certificate the controller presented, or None (plain TCP, or a
    client that does not expose its stream, such as a test stub)."""
    writer = getattr(client, "_writer", None)
    ssl_obj = writer.get_extra_info("ssl_object") if writer is not None else None
    if ssl_obj is None:
        return None
    der = ssl_obj.getpeercert(binary_form=True)   # given even when not verified
    return hashlib.sha256(der).hexdigest() if der else None


def short(fp: str) -> str:
    return ":".join(fp[i:i + 2] for i in range(0, 16, 2)).upper()


def check(host: str, port: int, fp: str, accept_new: bool = False) -> str:
    """Compare with what this address presented before. Returns a note for the user
    ('' when nothing changed); raises CertificateChanged on a different certificate
    unless accept_new."""
    key = f"{host}:{port}"
    data = _load()
    known = data.get(key)
    now = time.strftime("%Y-%m-%d %H:%M")
    if known and known["sha256"] == fp:
        if known.get("last_seen", "")[:10] != now[:10]:
            known["last_seen"] = now
            _save(data)
        return ""
    if known and not accept_new:
        raise CertificateChanged(
            f"The controller at {host} presented a different TLS certificate "
            f"({short(fp)}) than before ({short(known['sha256'])}, first seen "
            f"{known.get('first_seen', '?')}). Not connected. This happens when the "
            "controller was replaced or re-provisioned, or the address now belongs to "
            "another controller - or something else on the network is answering as it. "
            "If the change is expected, connect again with accept_new_certificate=true.")
    data[key] = {"sha256": fp, "first_seen": now, "last_seen": now}
    _save(data)
    if known:
        return f"New TLS certificate for {host} accepted and remembered ({short(fp)})."
    return (f"First TLS connection to {host}: its certificate ({short(fp)}) is remembered; "
            "a different one at this address will be refused.")
