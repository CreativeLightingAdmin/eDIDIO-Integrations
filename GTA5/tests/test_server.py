"""Server test: POST GTA V state to the actual handler."""

import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_gta5.config import BridgeConfig  # noqa: E402
from edidio_gta5.mapper import Gta5Mapper  # noqa: E402
from edidio_gta5.server import _make_handler  # noqa: E402


class FakeDispatcher:
    def __init__(self):
        self.intents = []

    def submit(self, intent):
        self.intents.append(intent)


def test_http_post_produces_intents():
    cfg = BridgeConfig({
        "server": {"host": "127.0.0.1", "port": 0},
        "controller": {"host": "10.0.0.1"},
        "gta5": {"health": {"enabled": False},
                 "wanted": {"actions": {
                     0: {"kind": "dali_scene", "line": 1, "scene": 1},
                     3: {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START"}}}},
    })
    disp = FakeDispatcher()
    handler = _make_handler(Gta5Mapper(cfg.gta5), disp, None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        def post(obj):
            req = urllib.request.Request(f"http://127.0.0.1:{port}/", data=json.dumps(obj).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=2).read()

        post({"wanted": 3})
        post({"wanted": 0})
    finally:
        server.shutdown()

    assert {"kind": "spektra", "type": "SEQUENCE", "zone": 1, "index": 1, "action": "START"} in disp.intents
    assert {"kind": "dali_scene", "line": 1, "scene": 1} in disp.intents
