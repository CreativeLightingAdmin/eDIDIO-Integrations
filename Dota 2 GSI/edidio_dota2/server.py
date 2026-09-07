"""HTTP server that receives Dota 2 GSI POSTs and drives eDIDIO."""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dispatcher import EdidioDispatcher
from .mapper import Dota2Mapper

_LOGGER = logging.getLogger(__name__)


def _make_handler(mapper: Dota2Mapper, dispatcher: EdidioDispatcher, token):
    class GsiHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
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
            if token:
                provided = (payload.get("auth") or {}).get("token")
                if provided != token:
                    return
            try:
                for intent in mapper.process(payload):
                    dispatcher.submit(intent)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error handling GSI payload: %s", err)

    return GsiHandler


async def run(config) -> None:
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    mapper = Dota2Mapper(config.dota2)
    handler = _make_handler(mapper, dispatcher, config.server.token)
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)

    loop = asyncio.get_running_loop()
    _LOGGER.info("Dota 2 GSI bridge on http://%s:%s/ -> eDIDIO %s:%s",
                 config.server.host, config.server.port, ctrl.host, ctrl.port)
    await loop.run_in_executor(None, server.serve_forever)
    await dispatcher.stop()
