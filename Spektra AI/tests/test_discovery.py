"""UDP discovery replies (port 30303) and the line summary; and the DALI name tables."""
from edidio_spektra_ai import dali_names as N
from edidio_spektra_ai import discovery as D


def test_parse_json_reply_adds_the_sender_ip():
    got = D._parse('{"NAME": "Lobby", "MAC": "00:04:A3:01:02:03", "FW": "1.6.3"}', "10.0.0.9")
    assert got == {"NAME": "Lobby", "MAC": "00:04:A3:01:02:03", "FW": "1.6.3", "IP": "10.0.0.9"}


def test_parse_legacy_crlf_reply():
    assert D._parse("Lobby\r\n00:04:A3:01:02:03\r\n", "10.0.0.9") == {
        "NAME": "Lobby", "MAC": "00:04:A3:01:02:03", "IP": "10.0.0.9"}


def test_parse_ignores_our_own_probe_and_junk():
    assert D._parse("D", "10.0.0.1") is None
    assert D._parse("{not json}", "10.0.0.1") is None
    assert D._parse("hello", "10.0.0.1") is None


def test_summarize_lines():
    assert D.summarize_lines([1, 2, 2, 2]) == "Line 1: DALI · Lines 2-4: DMX"
    assert D.summarize_lines([1, 0, 3, 9]) == ("Line 1: DALI · Line 2: Empty · Line 3: DMX-In"
                                               " · Line 4: Type 9")
    assert D.summarize_lines([]) == "Unknown" and D.summarize_lines(None) == "Unknown"


def test_broadcast_targets_always_include_the_limited_broadcast():
    assert "255.255.255.255" in D._broadcast_targets()


def test_dali_names_match_iec_62386():
    """Spot checks against IEC 62386-102 command numbers."""
    assert N.DALI_COMMANDS[0x00] == "OFF" and N.DALI_COMMANDS[0x05] == "RECALL_MAX"
    assert N.DALI_COMMANDS[0x20] == "RESET" and N.DALI_COMMANDS[0x90] == "QUERY_STATUS"
    assert N.DALI_COMMANDS[0xA0] == "QUERY_ACTUAL_LEVEL"
    assert N.DALI_SPECIAL_COMMANDS[0xA1] == "TERMINATE" and N.DALI_SPECIAL_COMMANDS[0xA5] == "INITIALISE"
    assert N.DALI_SPECIAL_COMMANDS[0xB7] == "PROGRAM_ADDRESS"


def test_dali_name_tables_are_well_formed():
    for table in (N.DALI_COMMANDS, N.DALI_SPECIAL_COMMANDS, N.DALI_INSTANCE_TYPES):
        assert all(isinstance(k, int) and 0 <= k <= 0xFF for k in table)
        assert all(isinstance(v, str) and v and v == v.upper() for v in table.values())
    # special commands are odd first bytes (the selector bit), as the standard lays out
    assert all(k & 1 for k in N.DALI_SPECIAL_COMMANDS)
