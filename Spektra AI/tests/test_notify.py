"""Tests for the out-of-band notifier: condition matching, dispatch, one-shot, deadline."""

import asyncio
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from edidio_spektra_ai import notify  # noqa: E402


class _CaptureChannel:
    name = "capture"

    def __init__(self):
        self.sent = []

    async def send(self, subject, payload):
        self.sent.append((subject, payload))


def test_matches_all_fields_case_insensitive():
    ev = {"kind": "sensor", "motion": "MOTION_IDLE", "index": 2}
    assert notify.matches({"kind": "sensor", "motion": "motion_idle"}, ev)
    assert notify.matches({"index": 2}, ev)
    assert not notify.matches({"kind": "sensor", "index": 3}, ev)
    assert not notify.matches({"motion": "MOTION_OCCUPANCY"}, ev)


def test_fires_on_match_and_is_one_shot():
    async def run():
        mgr = notify.NotificationManager()
        chan = _CaptureChannel()
        mgr.register({"kind": "sensor", "motion": "MOTION_IDLE"}, chan,
                     label="Foyer idle")
        # non-matching event: nothing
        await mgr.handle_event({"kind": "sensor", "motion": "MOTION_OCCUPANCY"})
        assert chan.sent == []
        # matching event: fires once
        await mgr.handle_event({"kind": "sensor", "motion": "MOTION_IDLE", "index": 2})
        assert len(chan.sent) == 1
        subject, payload = chan.sent[0]
        assert subject == "Foyer idle" and payload["reason"] == "matched"
        # one-shot: a second match does not fire again
        await mgr.handle_event({"kind": "sensor", "motion": "MOTION_IDLE"})
        assert len(chan.sent) == 1
        assert mgr.list()[0].armed is False
    asyncio.run(run())


def test_repeating_notification():
    async def run():
        mgr = notify.NotificationManager()
        chan = _CaptureChannel()
        mgr.register({"kind": "input"}, chan, one_shot=False)
        await mgr.handle_event({"kind": "input", "input_mask": 1})
        await mgr.handle_event({"kind": "input", "input_mask": 2})
        assert len(chan.sent) == 2
    asyncio.run(run())


def test_deadline_fires_when_no_match():
    async def run():
        mgr = notify.NotificationManager()
        chan = _CaptureChannel()
        past = datetime.now() - timedelta(seconds=1)
        mgr.register({"kind": "trigger", "type": "SPEKTRA_START_SEQ"}, chan,
                     label="seq didn't run", deadline=past)
        await mgr.check_deadlines()
        assert len(chan.sent) == 1
        assert chan.sent[0][1]["reason"] == "deadline"
    asyncio.run(run())


def test_deadline_cancelled_by_match():
    async def run():
        mgr = notify.NotificationManager()
        chan = _CaptureChannel()
        future = datetime.now() + timedelta(hours=1)
        mgr.register({"kind": "trigger", "type": "SPEKTRA_START_SEQ"}, chan,
                     deadline=future)
        # the awaited event happens -> deadline notification is cancelled, no fire
        await mgr.handle_event({"kind": "trigger", "type": "SPEKTRA_START_SEQ"})
        await mgr.check_deadlines(now=datetime.now() + timedelta(hours=2))
        assert chan.sent == []
        assert mgr.list()[0].armed is False
    asyncio.run(run())


def test_make_channel_and_log_channel():
    async def run():
        log = notify.make_channel("log")
        assert isinstance(log, notify.LogChannel)
        await log.send("hi", {"event": {"kind": "sensor"}})
        assert len(log.delivered) == 1
    asyncio.run(run())


def test_webhook_requires_url():
    try:
        notify.make_channel("webhook")
    except ValueError:
        return
    raise AssertionError("expected ValueError for webhook without url")


def test_clear():
    mgr = notify.NotificationManager()
    mgr.register({"kind": "sensor"}, _CaptureChannel())
    mgr.register({"kind": "input"}, _CaptureChannel())
    assert mgr.clear() == 2 and mgr.list() == []
