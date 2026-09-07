"""HTTP server that receives CS2 GSI POSTs and drives eDIDIO.

CS2 posts JSON to a local endpoint on every state change. We run a small
threaded HTTP server; each POST is parsed, mapped to intents, and submitted to
the (thread-safe) dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dispatcher import EdidioDispatcher
from .mapper import Cs2Mapper

_LOGGER = logging.getLogger(__name__)


def _make_handler(mapper: Cs2Mapper, dispatcher: EdidioDispatcher, token):
    class GsiHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default noisy logging
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            self.send_response(200)
            self.end_headers()
            try:
                payload = json.loads(body.decode("utf-8"))
            except Exception:  # noqa: BLE001
                return
            # Optional GSI auth token check.
            if token:
                provided = (payload.get("auth") or {}).get("token")
                if provided != token:
                    return
            try:
                for intent in mapper.process(payload):
                    dispatcher.submit(intent)
            except Exception as err:  # noqa: BLE001 - a bad payload must not kill the server
                _LOGGER.error("Error handling GSI payload: %s", err)

    return GsiHandler


async def run(config) -> None:
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    mapper = Cs2Mapper(config.cs2)
    handler = _make_handler(mapper, dispatcher, config.server.token)
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)

    loop = asyncio.get_running_loop()
    _LOGGER.info(
        "CS2 GSI bridge listening on http://%s:%s/ -> eDIDIO %s:%s",
        config.server.host, config.server.port, ctrl.host, ctrl.port,
    )
    # Serve in a background thread; dispatcher.submit is thread-safe.
    await loop.run_in_executor(None, server.serve_forever)  # blocks until shutdown
    await dispatcher.stop()
