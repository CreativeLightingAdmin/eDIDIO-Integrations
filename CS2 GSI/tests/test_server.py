"""Server test: POST real GSI payloads to the actual HTTP handler and assert the
correct intents reach a fake dispatcher (no eDIDIO, no CS2)."""

import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_cs2.config import BridgeConfig  # noqa: E402
from edidio_cs2.mapper import Cs2Mapper  # noqa: E402
from edidio_cs2.server import _make_handler  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


def test_http_post_produces_intents():
    cfg = BridgeConfig({
        "server": {"host": "127.0.0.1", "port": 0},
        "controller": {"host": "10.0.0.1"},
        "cs2": {"health": {"line": 2, "colors": ["#FF0000", "#00FF00"]},
                "bomb": {"action": {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]}}},
    })
    disp = FakeDispatcher()
    mapper = Cs2Mapper(cfg.cs2)
    handler = _make_handler(mapper, disp, None)

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        def post(obj):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/", data=json.dumps(obj).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=2).read()

        post({"player": {"state": {"health": 100, "flashed": 0}}, "round": {"bomb": None}})
        post({"player": {"state": {"health": 100, "flashed": 0}}, "round": {"bomb": "planted"}})
    finally:
        server.shutdown()

    # full-health green, then bomb red
    assert {"kind": "dmx_color", "line": 2, "rgb": [0, 255, 0]} in disp.intents
    assert {"kind": "dmx_color", "line": 2, "rgb": [255, 0, 0]} in disp.intents
