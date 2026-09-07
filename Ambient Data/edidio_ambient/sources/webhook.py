"""Webhook source: receive HTTP POSTs and emit a value or an event label.

Unlocks any push feed — Grafana/Prometheus alerts, Foundry/Roll20 (D&D), a POS
or booking system, IFTTT/Zapier, custom scripts. Runs a small single-threaded
HTTP server (handlers serialised, so the engine sees one value at a time).

Config:
  host, port           where to listen (e.g. 0.0.0.0:8100)
  json_path            dot-path to a NUMBER to emit (for gradient/threshold/level)
  label_path           dot-path to a STRING label to emit (for an event mapping)
  token                optional shared secret required as ?token= or X-Token header

Provide either json_path (numeric) or label_path (event). The value-extraction is
pure and unit tested; the server itself is exercised like the CS2 bridge.
"""

from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

_LOGGER = logging.getLogger(__name__)


def walk(data, path):
    """Follow a dot-path (numeric indices allowed) into decoded JSON, or None."""
    cur = data
    for part in path.split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def extract_emission(payload, json_path, label_path):
    """Return the value to emit from a webhook payload: a float (json_path) or a
    string label (label_path), or None if it can't be extracted."""
    if label_path:
        v = walk(payload, label_path)
        return None if v is None else str(v)
    if json_path:
        v = walk(payload, json_path)
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    # No path: emit a bare-number body, or 1.0 as a plain trigger.
    if isinstance(payload, (int, float)):
        return float(payload)
    return 1.0


class WebhookSource:
    def __init__(self, cfg: dict):
        self.name = cfg.get("name", "webhook")
        self.host = cfg.get("host", "0.0.0.0")
        self.port = int(cfg.get("port", 8100))
        self.json_path = cfg.get("json_path")
        self.label_path = cfg.get("label_path")
        self.token = cfg.get("token")

    def _authorised(self, handler) -> bool:
        if not self.token:
            return True
        q = parse_qs(urlparse(handler.path).query)
        if q.get("token", [None])[0] == self.token:
            return True
        return handler.headers.get("X-Token") == self.token

    async def run(self, emit):
        source = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                self.send_response(200)
                self.end_headers()
                if not source._authorised(self):
                    return
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:  # noqa: BLE001
                    return
                value = extract_emission(payload, source.json_path, source.label_path)
                if value is not None:
                    emit(value)

        server = HTTPServer((self.host, self.port), Handler)
        _LOGGER.info("%s listening for webhooks on http://%s:%s/", self.name, self.host, self.port)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, server.serve_forever)
