"""eDIDIO lighting driver for Extron ControlScript.

Wraps an Extron ``EthernetClientInterface`` and the zero-dependency
``edidio_frames`` encoder into a clean control API you can call from button /
event handlers in your ControlScript project:

    from edidio_extron import EdidioController

    lights = EdidioController("192.168.1.50")   # plain TCP, port 23
    lights.connect()

    @event(button, "Pressed")
    def on_press(button, state):
        lights.set_level(line=1, address=5, level=254)   # full
        lights.recall_scene(line=1, scene=3)
        lights.dmx_color(line=2, hex="#FF0000")
        lights.spektra(zone=1, target="sequence", index=0, action="start")

The controller keeps the socket alive with a periodic heartbeat and can be
targeted at a TLS unit by passing ``port=443`` (ControlScript negotiates TLS via
the interface's Protocol; see the README).

Runs on a real Extron processor or ControlScript Studio's virtual runtime. For
off-device unit tests, a small extronlib stub is provided under
``extronlib_stub/`` (see tests/).
"""

from extronlib.interface import EthernetClientInterface
from extronlib.system import ProgramLog, Timer

import edidio_frames as frames

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


class EdidioController:
    """A managed connection to one eDIDIO controller with a lighting control API."""

    def __init__(self, host, port=23, protocol="TCP", keepalive_seconds=7):
        self._client = EthernetClientInterface(host, port, Protocol=protocol)
        self._keepalive_seconds = keepalive_seconds
        self._keepalive_timer = None
        self._mid = 0
        self.host = host
        self.port = port

    # --- connection lifecycle ---------------------------------------------
    def connect(self, timeout=5):
        """Open the connection and start the keep-alive heartbeat.

        Returns the interface's Connect() result string
        (e.g. 'Connected' / 'ConnectedAlready')."""
        result = self._client.Connect(timeout)
        if result in ("Connected", "ConnectedAlready"):
            self._start_keepalive()
        else:
            ProgramLog("eDIDIO connect to %s:%s -> %s" % (self.host, self.port, result), "warning")
        return result

    def disconnect(self):
        self._stop_keepalive()
        self._client.Disconnect()

    @property
    def interface(self):
        """The underlying EthernetClientInterface (for status subscriptions)."""
        return self._client

    # --- DALI --------------------------------------------------------------
    def set_level(self, line, address, level):
        """Set a DALI address (0-63) to an arc level (0-254)."""
        self._send(frames.dali_arc_level(self._next_mid(), frames.line_mask(line), address, level))

    def set_group_level(self, line, group, level):
        """Set a DALI group (0-15) to an arc level (0-254)."""
        self._send(frames.dali_group_arc_level(self._next_mid(), frames.line_mask(line), group, level))

    def on(self, line, address):
        """Turn a DALI address on (max level)."""
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, "on"))

    def off(self, line, address):
        """Turn a DALI address off."""
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, "off"))

    def command(self, line, address, cmd, arg=0):
        """Send a named or numeric DALI command to an address."""
        self._send(frames.dali_command(self._next_mid(), frames.line_mask(line), address, cmd, arg))

    def recall_scene(self, line, scene, group=None):
        """Recall a stored scene: broadcast on the line, or on a group."""
        if group is None:
            self._send(frames.dali_broadcast_scene(self._next_mid(), frames.line_mask(line), scene))
        else:
            self._send(frames.dali_scene_on_group(self._next_mid(), frames.line_mask(line), group, scene))

    # --- DMX ---------------------------------------------------------------
    def dmx_levels(self, line, levels, channel=1, repeat=1, zone=0, fade_ms=0):
        """Write raw DMX channel levels (list of 0-255) from ``channel``."""
        self._send(frames.dmx_level(
            self._next_mid(), zone, frames.line_mask(line), channel, repeat, levels, fade_ms // 10))

    def dmx_color(self, line, hex, fixtures=None, zone=0xFF, fade_ms=0):
        """Paint an RGB colour (#RRGGBB) across a DMX line."""
        rgb = _parse_hex(hex)
        if fixtures is None:
            fixtures = 512 // len(rgb)
        self._send(frames.dmx_level(
            self._next_mid(), zone, frames.line_mask(line), 1, fixtures, rgb, fade_ms // 10))

    # --- SpektraPlus -------------------------------------------------------
    def spektra(self, zone, target="sequence", index=0, action="start"):
        """Start/stop/pause a SpektraPlus sequence, theme, or static scene."""
        t = _SPEKTRA_TARGET.get(str(target).lower())
        a = _SPEKTRA_ACTION.get(str(action).lower())
        if t is None:
            raise ValueError("unknown Spektra target: %s" % target)
        if a is None:
            raise ValueError("unknown Spektra action: %s" % action)
        self._send(frames.spektra_control(self._next_mid(), t, zone, index, a))

    def spektra_stop(self, zone):
        """Stop SpektraPlus playback on a zone and turn the output off."""
        self._send(frames.spektra_stop(self._next_mid(), zone))

    # --- internals ---------------------------------------------------------
    def _send(self, frame):
        self._client.Send(frame)

    def _next_mid(self):
        self._mid = (self._mid + 1) & 0xFFFFFF
        return self._mid

    def _start_keepalive(self):
        self._stop_keepalive()
        self._keepalive_timer = Timer(self._keepalive_seconds, self._send_keepalive)

    def _stop_keepalive(self):
        if self._keepalive_timer is not None:
            self._keepalive_timer.Stop()
            self._keepalive_timer = None

    def _send_keepalive(self, *args):
        try:
            self._client.Send(frames.KEEP_ALIVE)
        except Exception as err:  # keep-alive must never raise into the timer
            ProgramLog("eDIDIO keep-alive failed: %s" % err, "warning")
