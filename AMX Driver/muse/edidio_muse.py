"""eDIDIO lighting driver for AMX Muse (Python).

AMX Muse runs a full CPython on Linux, so this driver talks to the controller
over a standard TCP socket and reuses the zero-dependency ``edidio_frames``
encoder (byte-verified against ``edidio_control_py``). No third-party packages
are required, so it installs cleanly in the Muse environment.

Usage inside a Muse program:

    from edidio_muse import EdidioController

    lights = EdidioController("192.168.1.50")   # plain TCP, port 23
    lights.connect()
    lights.set_level(line=1, address=5, level=254)
    lights.recall_scene(line=1, scene=3)
    lights.dmx_color(line=2, hex="#FF0000")
    lights.spektra(zone=1, target="sequence", index=0, action="start")

For unit tests (and any non-socket transport), pass ``transport=`` an object
with a ``send(bytes)`` method; the driver then never opens a socket.
"""

import socket
import threading

import edidio_frames as frames


class EdidioController:
    """A managed TCP connection to one eDIDIO controller with a control API."""

    def __init__(self, host, port=23, keepalive_seconds=7, connect_timeout=5.0, transport=None):
        self.host = host
        self.port = port
        self._keepalive_seconds = keepalive_seconds
        self._connect_timeout = connect_timeout
        self._transport = transport  # injectable for testing; None => real socket
        self._sock = None
        self._mid = 0
        self._ka_timer = None
        self._lock = threading.Lock()
        self._connected = False

    # --- connection lifecycle ---------------------------------------------
    def connect(self):
        """Open the connection and start the keep-alive heartbeat."""
        if self._transport is None:
            self._sock = socket.create_connection((self.host, self.port), self._connect_timeout)
        self._connected = True
        if self._keepalive_seconds and self._keepalive_seconds > 0:
            self._start_keepalive()
        return self._connected

    def disconnect(self):
        self._stop_keepalive()
        self._connected = False
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    @property
    def connected(self):
        return self._connected

    # --- DALI --------------------------------------------------------------
    def set_level(self, line, address, level):
        self._send(frames.dali_arc_level(self._next_mid(), frames.line_mask(line), address, level))

    def set_group_level(self, line, group, level):
        self._send(frames.dali_group_arc_level(self._next_mid(), frames.line_mask(line), group, level))

    def on(self, line, address):
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, "on"))

    def off(self, line, address):
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, "off"))

    def command(self, line, address, cmd, arg=0):
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, cmd, arg))

    def recall_scene(self, line, scene, group=None):
        if group is None:
            self._send(frames.dali_broadcast_scene(self._next_mid(), frames.line_mask(line), scene))
        else:
            self._send(frames.dali_scene_on_group(self._next_mid(), frames.line_mask(line), group, scene))

    # --- DMX ---------------------------------------------------------------
    def dmx_levels(self, line, levels, channel=1, repeat=1, zone=0, fade_ms=0):
        self._send(frames.dmx_level(
            self._next_mid(), zone, frames.line_mask(line), channel, repeat, levels, fade_ms // 10))

    def dmx_color(self, line, hex, fixtures=None, zone=0xFF, fade_ms=0):
        rgb = _parse_hex(hex)
        if fixtures is None:
            fixtures = 512 // len(rgb)
        self._send(frames.dmx_level(
            self._next_mid(), zone, frames.line_mask(line), 1, fixtures, rgb, fade_ms // 10))

    # --- SpektraPlus -------------------------------------------------------
    def spektra(self, zone, target="sequence", index=0, action="start"):
        t = _SPEKTRA_TARGET.get(str(target).lower())
        a = _SPEKTRA_ACTION.get(str(action).lower())
        if t is None:
            raise ValueError("unknown Spektra target: %s" % target)
        if a is None:
            raise ValueError("unknown Spektra action: %s" % action)
        self._send(frames.spektra_control(self._next_mid(), t, zone, index, a))

    def spektra_stop(self, zone):
        self._send(frames.spektra_stop(self._next_mid(), zone))

    # --- internals ---------------------------------------------------------
    def _send(self, frame):
        with self._lock:
            if self._transport is not None:
                self._transport.send(frame)
            elif self._sock is not None:
                self._sock.sendall(frame)
            else:
                raise RuntimeError("eDIDIO controller not connected")

    def _next_mid(self):
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    def _start_keepalive(self):
        self._stop_keepalive()
        if not self._keepalive_seconds or self._keepalive_seconds <= 0:
            return
        self._ka_timer = threading.Timer(self._keepalive_seconds, self._keepalive_tick)
        self._ka_timer.daemon = True
        self._ka_timer.start()

    def _stop_keepalive(self):
        if self._ka_timer is not None:
            self._ka_timer.cancel()
            self._ka_timer = None

    def _keepalive_tick(self):
        if not self._connected:
            return
        try:
            self._send(frames.KEEP_ALIVE)
        except Exception:
            pass  # heartbeat must never raise; reconnection is the caller's concern
        finally:
            if self._connected and self._keepalive_seconds and self._keepalive_seconds > 0:
                self._start_keepalive()  # reschedule


_SPEKTRA_TARGET = {
    "sequence": frames.SPEKTRA_SEQUENCE,
    "theme": frames.SPEKTRA_THEME,
    "static": frames.SPEKTRA_STATIC,
}
_SPEKTRA_ACTION = {
    "start": frames.SPEKTRA_START,
    "stop": frames.SPEKTRA_STOP,
    "pause": frames.SPEKTRA_PAUSE,
}


def _parse_hex(value):
    text = value.lstrip("#").strip()
    if len(text) != 6:
        raise ValueError("colour must be #RRGGBB")
    return [int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)]
