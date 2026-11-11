"""Undo for confirmed writes: confirm reads what it overwrites and returns a token that
re-sends the controller's own copy. (Stub controller: sequences 0-1 and theme 0 exist,
every zone reads as 10 lights x 3 DMX channels, schedule 0 exists.)"""
import asyncio

import edidio_control_py.eDS10_ProtocolBuffer_pb2 as pb

from edidio_spektra_ai import server as srv, undo
from edidio_spektra_ai.controller import _is_live
from tests.test_server import fresh_controller


def run(coro):
    return asyncio.run(coro)


def token_of(out, marker='token="'):
    return out.split(marker)[1].split('"')[0]


def undo_token(out):
    return token_of(out.split("To undo:")[1])


def decode(frame):
    m = pb.EdidioMessage()
    m.ParseFromString(frame[3:])
    return m


def write(spec):
    return run(srv.confirm(token_of(run(srv.preview_sequence(spec)))))


SPEC = {"index": 1, "type": "blend", "colours": [[0, 255, 0]], "title": "New",
        "time_per_step_ms": 800}


def test_confirm_offers_an_undo_that_restores_the_old_sequence():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = write(SPEC)
    assert "To undo:" in out and "puts back sequence 2 (index 1)" in out
    frames = srv._pending[undo_token(out)]["messages"]
    seq = decode(frames[0]).spektra_sequence
    # the stub's own copy of slot 1, not the new one
    assert (seq.index, seq.type, seq.title) == (1, 4, "Seq1")
    assert list(seq.colours[0].channel_value) == [255, 0, 0]
    # the write's DEVICE_SAVE is repeated after the restore
    assert decode(frames[-1]).WhichOneof("payload") == "external_trigger"


def test_undo_confirms_and_offers_a_redo():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.confirm(undo_token(write(SPEC))))
    assert out.startswith("Done.") and "To undo:" in out       # the undo has its own undo


def test_empty_slot_is_restored_as_a_deletion_marker():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    out = write(dict(SPEC, index=9))                           # slot 9 is empty in the stub
    assert "was empty - undo marks it deleted" in out
    seq = decode(srv._pending[undo_token(out)]["messages"][0]).spektra_sequence
    assert (seq.index, seq.title, len(seq.colours)) == (9, undo.DELETION_MARKER_NAME, 0)


def test_undo_last_write_shows_the_latest_undo():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert "No undo available" in run(srv.undo_last_write())
    out = write(SPEC)
    shown = run(srv.undo_last_write())
    assert token_of(shown) == undo_token(out) and "sequence 2 (index 1)" in shown


def test_undo_is_tied_to_the_connection_and_lasts_longer():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    token = undo_token(write(SPEC))
    p = srv._pending[token]
    assert p["ttl"] == srv.UNDO_TTL_S
    p["made"] -= srv.TOKEN_TTL_S + 60                          # older than a preview may be
    assert "Done." in run(srv.confirm(token))                  # ... but an undo still works
    token = undo_token(write(SPEC))
    run(srv.connect_controller("10.0.0.2"))
    assert "earlier connection" in run(srv.undo_last_write())


def test_zone_write_restores_the_zone_settings(monkeypatch):
    from edidio_spektra_ai import tools_live
    from edidio_spektra_ai.live import programming       # defines preview_zone; binds at import
    monkeypatch.setattr(programming, "_controller", fresh_controller())
    run(srv.connect_controller("10.0.0.1"))
    out = run(srv.confirm(token_of(run(tools_live.preview_zone(2, "dmx", 2, 12, "red,green,blue,white", 1)))))
    assert "puts back zone 3" in out
    frames = srv._pending[undo_token(out)]["messages"]
    zs = decode(frames[0]).spektra_settings
    assert (zs.zone, zs.number_of_lights, zs.channels_per_light) == (2, 10, 3)
    assert decode(frames[1]).WhichOneof("payload") == "spektra_control"   # zone SAVE


def test_writes_it_cannot_restore_say_so():
    """A DALI gear write has no read-back to restore from: no undo, and it says so."""
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    frame = undo._frame(pb.EdidioMessage(message_id=1, dali_message=pb.DALIMessage()))
    snap = run(undo.snapshot(srv._controller, [frame]))
    assert snap["frames"] is None and "not undoable" in snap["missing"][0]
    token = srv._new_token([frame], "dali")
    out = run(srv.confirm(token))
    assert "cannot be undone automatically" in out


def test_deletion_markers_read_as_empty():
    """SpektraPlus treats a !DELETED! slot as empty on read; so must every reader."""
    live, marked = pb.EdidioMessage(), pb.EdidioMessage()
    live.spektra_sequence.title = "Real"
    marked.spektra_sequence.title = undo.DELETION_MARKER_NAME
    assert _is_live(live, "spektra_sequence") and not _is_live(marked, "spektra_sequence")
