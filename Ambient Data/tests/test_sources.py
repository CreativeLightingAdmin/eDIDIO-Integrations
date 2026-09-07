"""Source tests: JSON extraction + http_poll with an injected fetch (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_ambient.sources.http_poll import HttpPollSource, extract  # noqa: E402


def test_extract_nested_dict():
    data = {"bitcoin": {"usd": 65000.5}}
    assert extract(data, "bitcoin.usd") == 65000.5


def test_extract_list_index():
    data = {"chart": {"result": [{"meta": {"regularMarketPrice": 189.25}}]}}
    assert extract(data, "chart.result.0.meta.regularMarketPrice") == 189.25


def test_extract_missing_returns_none():
    assert extract({"a": 1}, "a.b.c") is None
    assert extract({"a": 1}, "missing") is None


def test_http_poll_read_once():
    src = HttpPollSource(
        {"type": "http_poll", "url": "http://x", "json_path": "bitcoin.usd"},
        fetch_fn=lambda: {"bitcoin": {"usd": 65000}},
    )
    assert src.read_once() == 65000.0


def test_http_poll_scale_offset():
    # e.g. convert a 0-9 Kp index to a 0-100 scale, or apply a % change.
    src = HttpPollSource(
        {"type": "http_poll", "url": "http://x", "json_path": "kp", "scale": 10, "offset": 5},
        fetch_fn=lambda: {"kp": 4},
    )
    assert src.read_once() == 45.0  # 4*10 + 5


def test_http_poll_fetch_error_returns_none():
    def boom():
        raise RuntimeError("network down")

    src = HttpPollSource({"type": "http_poll", "url": "http://x", "json_path": "a"}, fetch_fn=boom)
    assert src.read_once() is None


def test_http_poll_bad_path_returns_none():
    src = HttpPollSource(
        {"type": "http_poll", "url": "http://x", "json_path": "nope"},
        fetch_fn=lambda: {"a": 1},
    )
    assert src.read_once() is None
