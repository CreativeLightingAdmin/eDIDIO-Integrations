"""UDP discovery of eDIDIO controllers on the local network.

Python port of the JS engine's discovery probe (used by the REST gateway and the
Discord bot). Protocol matches the SpektraPlus app:

  - Send the probe byte "D" to UDP port 30303.
  - Target the DIRECTED SUBNET BROADCAST address of every active IPv4 interface
    (ip | ~netmask), since many networks don't route the global 255.255.255.255.
  - Controllers reply with JSON {NAME,MAC,IP,TLS,FW_VER,LINES} or a legacy
    "NAME\r\nMAC" text payload. We ignore our own "D" echo.
  - `TLS: true` means the unit accepts a TLS connection on port 443 (older units
    are plain TCP on port 23).
"""

from __future__ import annotations

import ipaddress
import json
import socket
import time

DISCOVERY_PORT = 30303
PROBE = b"D"

LINE_LABELS = {0: "Empty", 1: "DALI", 2: "DMX", 3: "DMX-In", 4: "Auto"}


def _broadcast_targets() -> list[str]:
    """Directed broadcast address for every active IPv4 interface."""
    targets: set[str] = set()
    hostname = socket.gethostname()
    try:
        addrs = socket.getaddrinfo(hostname, None, socket.AF_INET)
    except socket.gaierror:
        addrs = []

    for _family, _type, _proto, _canon, sockaddr in addrs:
        ip = sockaddr[0]
        if ip.startswith("127."):
            continue
        # Assume a /24 when we can't read the real netmask from stdlib; this is
        # the common case on lighting LANs. Users can also pass --host directly.
        try:
            net = ipaddress.ip_network(f"{ip}/24", strict=False)
            targets.add(str(net.broadcast_address))
        except ValueError:
            continue

    targets.add("255.255.255.255")  # fallback / same-subnet
    return sorted(targets)


def _parse(text: str, ip: str) -> dict | None:
    text = text.strip()
    if text == "D":
        return None  # our own echo
    if text.startswith("{") and text.endswith("}"):
        try:
            data = json.loads(text)
            data["IP"] = ip
            return data
        except json.JSONDecodeError:
            return None
    parts = text.split("\r\n")
    if len(parts) >= 2:
        return {"NAME": parts[0], "MAC": parts[1], "IP": ip}
    return None


def summarize_lines(lines) -> str:
    """Compact 'Line 1: DALI · Lines 2-4: DMX' summary."""
    if not isinstance(lines, list) or not lines:
        return "Unknown"
    parts = []
    start = 0
    for i in range(1, len(lines) + 1):
        if i == len(lines) or lines[i] != lines[start]:
            label = LINE_LABELS.get(lines[start], f"Type {lines[start]}")
            if start == i - 1:
                parts.append(f"Line {start + 1}: {label}")
            else:
                parts.append(f"Lines {start + 1}-{i}: {label}")
            start = i
    return " · ".join(parts)


def discover(timeout: float = 2.0) -> list[dict]:
    """Broadcast a probe and collect controller replies until `timeout`."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)

    found: dict[str, dict] = {}
    try:
        sock.bind(("0.0.0.0", 0))
        for target in _broadcast_targets():
            try:
                sock.sendto(PROBE, (target, DISCOVERY_PORT))
            except OSError:
                pass  # a single unreachable target shouldn't abort discovery

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            info = _parse(data.decode("utf-8", errors="replace"), addr[0])
            if info and addr[0] not in found:
                found[addr[0]] = info
    finally:
        sock.close()

    return list(found.values())


if __name__ == "__main__":
    devices = discover()
    if not devices:
        print("No eDIDIO controllers found on the local network.")
    for d in devices:
        print(f"{d.get('NAME', '?')}  {d.get('IP')}  MAC={d.get('MAC')}  "
              f"TLS={d.get('TLS')}  FW={d.get('FW_VER')}  "
              f"[{summarize_lines(d.get('LINES'))}]")
