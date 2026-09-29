"""Minimal asyncio HTTP server exposing ``/metrics`` (and ``/`` for humans).

A scrape polls every controller's health concurrently — at most once per
``min_poll_interval`` — then renders all collectors plus exporter self-metrics.
"""

from __future__ import annotations

import asyncio
import logging
import time

from . import __version__
from .collector import ControllerCollector
from .exposition import CONTENT_TYPE, render

_LOGGER = logging.getLogger(__name__)


class Exporter:
    def __init__(self, collectors: list[ControllerCollector], min_poll_interval: float = 10.0):
        self.collectors = collectors
        self.min_poll_interval = min_poll_interval
        self._last_poll = 0.0
        self._lock: asyncio.Lock | None = None   # created in the running loop (py3.9)
        self.scrapes = 0

    async def start(self) -> None:
        await asyncio.gather(*(c.start() for c in self.collectors))

    async def stop(self) -> None:
        await asyncio.gather(*(c.stop() for c in self.collectors), return_exceptions=True)

    async def metrics(self) -> str:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if time.monotonic() - self._last_poll >= self.min_poll_interval:
                await asyncio.gather(*(c.poll() for c in self.collectors))
                self._last_poll = time.monotonic()
        self.scrapes += 1
        merged: dict = {}
        for c in self.collectors:
            for name, mtype, help_text, samples in c.families():
                merged.setdefault(name, (mtype, help_text, []))[2].extend(samples)
        families = [(n, t, h, s) for n, (t, h, s) in merged.items()]
        families.append(("edidio_exporter_build_info", "gauge", "Exporter version.",
                         [({"version": __version__}, 1)]))
        families.append(("edidio_exporter_scrapes_total", "counter", "Scrapes served.",
                         [({}, self.scrapes)]))
        return render(families)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = await asyncio.wait_for(reader.readline(), timeout=10)
            # Drain headers.
            while (line := await asyncio.wait_for(reader.readline(), timeout=10)) not in (b"\r\n", b"\n", b""):
                pass
            parts = request.decode("latin-1").split()
            method, path = (parts[0], parts[1]) if len(parts) >= 2 else ("", "")
            path = path.split("?", 1)[0]
            if method != "GET":
                status, ctype, body = "405 Method Not Allowed", "text/plain", "method not allowed\n"
            elif path == "/metrics":
                status, ctype, body = "200 OK", CONTENT_TYPE, await self.metrics()
            elif path == "/":
                status, ctype = "200 OK", "text/html; charset=utf-8"
                body = ("<html><head><title>eDIDIO exporter</title></head><body>"
                        '<h1>eDIDIO Prometheus exporter</h1><p><a href="/metrics">/metrics</a></p>'
                        "</body></html>")
            else:
                status, ctype, body = "404 Not Found", "text/plain", "not found\n"
            data = body.encode("utf-8")
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode("latin-1") + data)
            await writer.drain()
        except (asyncio.TimeoutError, ConnectionError) as err:
            _LOGGER.debug("request error: %s", err)
        finally:
            writer.close()


async def run(config) -> None:
    collectors = [
        ControllerCollector(c.name, c.host, c.port, use_tls=c.use_tls,
                            timeout=c.timeout, events=c.events)
        for c in config.controllers
    ]
    exporter = Exporter(collectors, config.min_poll_interval)
    await exporter.start()
    server = await asyncio.start_server(exporter.handle, config.host, config.port)
    _LOGGER.info("eDIDIO exporter on http://%s:%s/metrics (%d controllers)",
                 config.host, config.port, len(collectors))
    try:
        async with server:
            await server.serve_forever()
    finally:
        await exporter.stop()
