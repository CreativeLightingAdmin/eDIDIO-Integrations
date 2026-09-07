"""HTTP server that receives GTA V mod POSTs and drives eDIDIO."""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .dispatcher import EdidioDispatcher
from .mapper import Gta5Mapper

_LOGGER = logging.getLogger(__name__)


def _make_handler(mapper: Gta5Mapper, dispatcher: EdidioDispatcher, token):
    class Handler(BaseHTTPRequestHandler):
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
            if token and payload.get("token") != token:
                return
            try:
                for intent in mapper.process(payload):
                    dispatcher.submit(intent)
            except Exception as err:  # noqa: BLE001
                _LOGGER.error("Error handling GTA5 payload: %s", err)

    return Handler


async def run(config) -> None:
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    mapper = Gta5Mapper(config.gta5)
    handler = _make_handler(mapper, dispatcher, config.server.token)
    server = ThreadingHTTPServer((config.server.host, config.server.port), handler)

    loop = asyncio.get_running_loop()
    _LOGGER.info("GTA5 bridge on http://%s:%s/ -> eDIDIO %s:%s",
                 config.server.host, config.server.port, ctrl.host, ctrl.port)
    await loop.run_in_executor(None, server.serve_forever)
    await dispatcher.stop()
