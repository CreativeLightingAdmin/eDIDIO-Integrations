"""Stub of extronlib.interface for off-device testing.

Implements the subset of EthernetClientInterface used by edidio_extron.py:
Connect / Send / Disconnect / SubscribeStatus. Sent frames are captured in
`.sent` for assertions.
"""


class EthernetClientInterface:
    def __init__(self, Hostname, IPPort, Protocol="TCP", **kwargs):
        self.Hostname = Hostname
        self.IPPort = IPPort
        self.Protocol = Protocol
        self.sent = []
        self.connected = False
        self._status_subs = []

    def Connect(self, timeout=None):
        self.connected = True
        self._notify("Connected", "Connected")
        return "Connected"

    def Disconnect(self):
        self.connected = False
        self._notify("Connected", "Disconnected")

    def Send(self, data):
        if not self.connected:
            raise Exception("EthernetClientInterface not connected")
        # Extron accepts str or bytes; capture as bytes for inspection.
        if isinstance(data, str):
            data = data.encode("latin-1")
        self.sent.append(bytes(data))

    def SubscribeStatus(self, state, callback):
        self._status_subs.append((state, callback))

    def _notify(self, state, value):
        for sub_state, cb in self._status_subs:
            if sub_state == state:
                cb(self, state, value)
