"""Preview tokens are confirmed only on the connection they were made on, and only
for TOKEN_TTL_S. Before this, confirm wrote to whatever controller was connected at
the time, however old the preview was."""
import asyncio

from edidio_spektra_ai import server as srv
from tests.test_server import fresh_controller

SPEC = {"index": 5, "type": "rotate", "colours": [[255, 0, 0], [0, 255, 0]], "title": "T",
        "time_per_step_ms": 500}


def run(coro):
    return asyncio.run(coro)


def token_of(out):
    return out.split('token="')[1].split('"')[0]


def sent_frames():
    return [x for x in srv._controller._client.sent if isinstance(x, bytes)]


def test_same_connection_confirms():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    assert "Done" in run(srv.confirm(token_of(run(srv.preview_sequence(SPEC)))))


def test_preview_from_another_controller_is_refused():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    token = token_of(run(srv.preview_sequence(SPEC)))
    note = run(srv.connect_controller("10.0.0.2"))
    assert "1 unconfirmed preview(s)" in note
    out = run(srv.confirm(token))
    assert "made on 10.0.0.1" in out and "connected now: 10.0.0.2" in out
    assert sent_frames() == []                       # nothing reached 10.0.0.2


def test_reconnect_to_the_same_controller_also_refuses():
    """Its frames carry the old connection's message ids, and the slot may have changed."""
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    token = token_of(run(srv.preview_sequence(SPEC)))
    run(srv.connect_controller("10.0.0.1"))
    assert "earlier connection" in run(srv.confirm(token))


def test_disconnected_confirm_is_refused():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    token = token_of(run(srv.preview_sequence(SPEC)))
    run(srv._controller.disconnect())
    assert "connected now: no controller" in run(srv.confirm(token))


def test_offline_preview_confirms_on_a_later_connection():
    """A sequence spec needs no controller to preview; it is not tied to one."""
    fresh_controller()
    token = token_of(run(srv.preview_sequence(SPEC)))
    run(srv.connect_controller("10.0.0.1"))
    assert "Done" in run(srv.confirm(token))


def test_expired_preview_is_refused():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    token = token_of(run(srv.preview_sequence(SPEC)))
    srv._pending[token]["made"] -= srv.TOKEN_TTL_S + 60
    before = len(sent_frames())            # the preview itself may read (dry run)
    out = run(srv.confirm(token))
    assert "minutes old" in out and len(sent_frames()) == before   # confirm sent nothing


def test_expired_previews_are_forgotten():
    fresh_controller()
    run(srv.connect_controller("10.0.0.1"))
    old = token_of(run(srv.preview_sequence(SPEC)))
    srv._pending[old]["made"] -= srv.TOKEN_TTL_S + 60
    token_of(run(srv.preview_sequence(SPEC)))
    assert old not in srv._pending
