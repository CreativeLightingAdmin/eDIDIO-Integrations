"""Exporter tests: exposition format, health polling, live levels from events,
and a real HTTP scrape. Fake clients stand in for the controller."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb  # noqa: E402
import pytest  # noqa: E402
from edidio_control_py.exceptions import EDIDIOConnectionError  # noqa: E402

from edidio_prometheus.collector import ControllerCollector  # noqa: E402
from edidio_prometheus.config import ConfigError, ExporterConfig  # noqa: E402
from edidio_prometheus.exposition import render  # noqa: E402
from edidio_prometheus.server import Exporter  # noqa: E402


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.connected = False

    async def connect(self):
        if self.fail:
            raise EDIDIOConnectionError("unreachable")
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def request(self, frame):
        return pb.EdidioMessage(diag_system=pb.DiagnosticSystemInfoResponse(
            firmware="1.5.7", hardware="S10", proto_version=3, vendor_id="CF",
            spektra_seq_count=144, list_count=32, selected_profile=1))


class FakeStream:
    running = True
    connected = True
    reconnects = 2
    on_event = None

    async def start(self, categories):
        pass

    async def stop(self):
        pass


def collector(fail=False):
    return ControllerCollector("main", "10.0.0.1", client=FakeClient(fail),
                               event_stream=FakeStream())


def test_render_format_and_escaping():
    text = render([("m", "gauge", "Help\nline", [({"b": 'x"y', "a": "1"}, 2.5), ({}, 3)])])
    assert "# HELP m Help\\nline" in text
    assert "# TYPE m gauge" in text
    assert 'm{a="1",b="x\\"y"} 2.5' in text
    assert text.endswith("m 3\n")


def test_poll_success_reports_health():
    c = collector()
    asyncio.run(c.poll())
    text = render(c.families())
    assert 'edidio_up{controller="main"} 1' in text
    assert 'firmware="1.5.7"' in text and 'hardware="S10"' in text
    assert 'edidio_config_count{controller="main",kind="sequences"} 144' in text
    assert 'edidio_active_profile{controller="main"} 1' in text
    assert 'edidio_event_stream_reconnects_total{controller="main"} 2' in text


def test_poll_failure_marks_down():
    c = collector(fail=True)
    asyncio.run(c.poll())
    text = render(c.families())
    assert 'edidio_up{controller="main"} 0' in text
    assert 'edidio_poll_failures_total{controller="main"} 1' in text
    assert "edidio_info" not in text


def test_events_feed_levels_and_counters():
    c = collector()

    async def feed():
        await c._on_event({"kind": "dali", "line": 0, "frame_type": 1, "frame": 0x0AC8})
        await c._on_event({"kind": "dali", "line": 1, "frame_type": 1, "frame": 0x8680})
        await c._on_event({"kind": "input", "index": 2})

    asyncio.run(feed())
    text = render(c.families())
    assert 'edidio_dali_level{address="5",controller="main",line="1",target="address"} 200' in text
    assert 'edidio_dali_level{address="3",controller="main",line="2",target="group"} 128' in text
    assert 'edidio_events_total{controller="main",kind="dali"} 2' in text
    assert 'edidio_events_total{controller="main",kind="input"} 1' in text
    assert "edidio_last_event_timestamp_seconds" in text


def test_config_validation():
    ok = ExporterConfig({"controllers": [{"host": "10.0.0.1"}]})
    assert ok.port == 9464 and ok.controllers[0].name == "10.0.0.1"
    with pytest.raises(ConfigError):
        ExporterConfig({"controllers": []})
    with pytest.raises(ConfigError):
        ExporterConfig({"controllers": [{"host": "a", "name": "x"}, {"host": "b", "name": "x"}]})


def test_http_scrape_and_poll_caching():
    exporter = Exporter([collector()], min_poll_interval=60)
    polls = []
    original = exporter.collectors[0].poll

    async def counting_poll():
        polls.append(1)
        await original()

    exporter.collectors[0].poll = counting_poll

    async def scenario():
        server = await asyncio.start_server(exporter.handle, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        responses = []
        for path in ("/metrics", "/metrics", "/nope"):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            await writer.drain()
            responses.append((await reader.read()).decode())
            writer.close()
        server.close()
        await server.wait_closed()
        return responses

    first, second, missing = asyncio.run(scenario())
    assert first.startswith("HTTP/1.1 200 OK")
    assert "text/plain; version=0.0.4" in first
    assert 'edidio_up{controller="main"} 1' in first
    assert "edidio_exporter_scrapes_total 2" in second
    assert missing.startswith("HTTP/1.1 404")
    assert len(polls) == 1                      # second scrape used the cached poll
