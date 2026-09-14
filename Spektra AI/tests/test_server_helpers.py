"""Tests for small server-side helpers (address spec parsing)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai import server  # noqa: E402


def test_parse_addresses_range():
    assert server._parse_addresses("0-6") == [0, 1, 2, 3, 4, 5, 6]


def test_parse_addresses_list_and_mixed():
    assert server._parse_addresses("7,8,9") == [7, 8, 9]
    assert server._parse_addresses("0-2,5,7-8") == [0, 1, 2, 5, 7, 8]


def test_parse_addresses_single_and_spaces():
    assert server._parse_addresses("7") == [7]
    assert server._parse_addresses(" 0 - 3 , 5 ") == [0, 1, 2, 3, 5]
