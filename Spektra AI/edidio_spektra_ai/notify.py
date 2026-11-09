"""Out-of-band notifications: "let me know when ...".

Registers conditions against the live event stream and, when one matches, dispatches
a notification through a delivery channel that fires **independently of the chat** — so
the user is told even when they aren't actively talking to the assistant. This is what
turns passive watching ("recent_events") into the scenarios that motivated it:
  - "let me know when the Foyer sensor goes out of occupancy"
  - "tell me if the sequence doesn't run tonight" (deadline conditions)

Channels: ``log`` (default; recorded in-process, safe, nothing leaves the machine),
``webhook`` (HTTP POST of the event JSON), and ``email`` (SMTP). Webhook/email publish
data to an external service, so they must be explicitly configured by the user.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

_LOGGER = logging.getLogger(__name__)


# --- delivery channels ------------------------------------------------------

class LogChannel:
    """Default, safe channel: records deliveries in-process (retrievable via a tool).
    Nothing leaves the machine."""

    name = "log"

    def __init__(self):
        self.delivered: list[dict] = []

    async def send(self, subject: str, payload: dict):
        self.delivered.append({"at": datetime.now().isoformat(timespec="seconds"),
                               "subject": subject, "payload": payload})
        _LOGGER.info("notify(log): %s", subject)


class WebhookChannel:
    """POSTs the notification as JSON to a user-supplied URL (external send)."""

    name = "webhook"

    def __init__(self, url: str):
        if not url:
            raise ValueError("webhook channel requires a url")
        self.url = url

    async def send(self, subject: str, payload: dict):
        body = json.dumps({"subject": subject, **payload}).encode("utf-8")

        def _post():
            req = urllib.request.Request(
                self.url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status

        # Don't block the event loop on network I/O.
        await asyncio.get_event_loop().run_in_executor(None, _post)


class EmailChannel:
    """Sends the notification via SMTP (external send). Config is user-supplied."""

    name = "email"

    def __init__(self, host: str, port: int, sender: str, to: str,
                 username: str = "", password: str = "", use_tls: bool = True):
        if not (host and sender and to):
            raise ValueError("email channel requires host, sender and to")
        self.host, self.port = host, port
        self.sender, self.to = sender, to
        self.username, self.password, self.use_tls = username, password, use_tls

    async def send(self, subject: str, payload: dict):
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, self.to, subject
        msg.set_content(json.dumps(payload, indent=2))

        def _send():
            with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                if self.use_tls:
                    smtp.starttls()
                if self.username:
                    smtp.login(self.username, self.password)
                smtp.send_message(msg)

        await asyncio.get_event_loop().run_in_executor(None, _send)


# --- conditions + manager ---------------------------------------------------

@dataclass
class Notification:
    id: int
    condition: dict           # field -> required value (all must match an event)
    channel: object           # a channel with async send(subject, payload)
    label: str = ""
    one_shot: bool = True
    armed: bool = True
    fired_count: int = 0
    last_fired: str | None = None
    deadline: datetime | None = None   # for "did NOT happen by" conditions
    satisfied: bool = False            # a matching event seen (for deadline logic)


def matches(condition: dict, event: dict) -> bool:
    """True if every key in ``condition`` equals the event's value (case-insensitive
    for strings). A list value means "any of"; {"not": v} means "anything but v".
    Unknown keys simply won't match, so a bad condition never fires."""
    for key, want in condition.items():
        got = event.get(key)
        if isinstance(want, dict) and "not" in want:      # {"not": value}
            if matches({key: want["not"]}, event):
                return False
            continue
        if isinstance(want, list):                         # any of these values
            if not any(matches({key: w}, event) for w in want):
                return False
            continue
        if isinstance(want, str) and isinstance(got, str):
            if want.lower() != got.lower():
                return False
        elif got != want:
            return False
    return True


class NotificationManager:
    """Holds registered notifications and evaluates them against live events."""

    def __init__(self):
        self._items: dict[int, Notification] = {}
        self._next_id = 1

    def register(self, condition: dict, channel, *, label: str = "",
                 one_shot: bool = True, deadline: datetime | None = None) -> Notification:
        n = Notification(id=self._next_id, condition=dict(condition), channel=channel,
                         label=label, one_shot=one_shot, deadline=deadline)
        self._items[n.id] = n
        self._next_id += 1
        return n

    def list(self) -> list[Notification]:
        return list(self._items.values())

    def clear(self, notif_id: int | None = None) -> int:
        if notif_id is None:
            n = len(self._items)
            self._items.clear()
            return n
        return 1 if self._items.pop(notif_id, None) else 0

    async def handle_event(self, event: dict):
        """Called for each decoded live event; fire any armed matching notifications.
        Errors in a channel never propagate into the read loop (best-effort delivery)."""
        for n in list(self._items.values()):
            if not n.armed or not matches(n.condition, event):
                continue
            n.satisfied = True
            if n.deadline is not None:
                # Deadline = "notify if it did NOT happen"; a match cancels it.
                n.armed = False
                continue
            await self._fire(n, event, reason="matched")

    async def check_deadlines(self, now: datetime | None = None):
        """Fire deadline notifications whose time has passed WITHOUT a matching event
        (the "tell me if it didn't run" case). Call periodically."""
        now = now or datetime.now()
        for n in list(self._items.values()):
            if (n.armed and n.deadline is not None and now >= n.deadline
                    and not n.satisfied):
                n.armed = False
                await self._fire(n, {"reason": "deadline passed without a match"},
                                 reason="deadline")

    async def _fire(self, n: Notification, event: dict, *, reason: str):
        n.fired_count += 1
        n.last_fired = datetime.now().isoformat(timespec="seconds")
        if n.one_shot:
            n.armed = False
        subject = n.label or f"eDIDIO notification #{n.id}"
        payload = {"notification_id": n.id, "label": n.label, "reason": reason,
                   "condition": n.condition, "event": event}
        try:
            await n.channel.send(subject, payload)
        except Exception as err:  # noqa: BLE001 — delivery is best-effort
            _LOGGER.error("notification %s delivery failed: %s", n.id, err)


def make_channel(kind: str, *, log_channel=None, webhook_url: str = "",
                 email: dict | None = None):
    """Build a channel from a friendly kind. ``log`` reuses a shared LogChannel."""
    kind = (kind or "log").lower()
    if kind == "log":
        return log_channel or LogChannel()
    if kind == "webhook":
        return WebhookChannel(webhook_url)
    if kind == "email":
        return EmailChannel(**(email or {}))
    raise ValueError(f"unknown channel '{kind}' (use log, webhook or email)")


# --- friendly presets (Event Stream v2 field values) -----------------------------------

# InputEvent.press_type for physical inputs: 0 short, 1 long, 2 latch low (closed),
# 3 latch high (opened). SensorEvent.motion_state: 0 idle, 1 disabled, 2 warning,
# 3 occupancy.
PRESETS = {
    "input_pressed": ({"kind": "input", "press": [0, 1]}, "input"),
    "input_short_press": ({"kind": "input", "press": 0}, "input"),
    "input_long_press": ({"kind": "input", "press": 1}, "input"),
    "input_closed": ({"kind": "input", "press": 2}, "input"),
    "input_opened": ({"kind": "input", "press": 3}, "input"),
    "sensor_occupied": ({"kind": "sensor", "motion": 3}, "sensor"),
    "sensor_warning": ({"kind": "sensor", "motion": 2}, "sensor"),
    "sensor_idle": ({"kind": "sensor", "motion": 0}, "sensor"),
    "list_started": ({"kind": "list", "step": 0}, "list"),
    "list_step": ({"kind": "list"}, "list"),
    "schedule_fired": ({"kind": "schedule", "is_end": False}, "schedule"),
    "schedule_ended": ({"kind": "schedule", "is_end": True}, "schedule"),
    "config_changed": ({"kind": "config"}, "config"),
    "restart": ({"kind": "boot"}, None),
    "client_connected": ({"kind": "net", "event_name": ["TCP_CONNECT", "TLS_CONNECT"]}, None),
    "client_disconnected": ({"kind": "net",
                             "event_name": ["TCP_DISCONNECT", "TLS_DISCONNECT"]}, None),
    "network_link_down": ({"kind": "net", "event_name": "LINK_DOWN"}, None),
    "spektra_started": ({"kind": "spektra", "action": 1}, "zone"),
    "spektra_stopped": ({"kind": "spektra", "action": 2}, "zone"),
    "dali_error": ({"kind": "dali", "direction": 0, "ok": False,
                    "status_name": {"not": "ATTEMPT"}}, "line"),
}
_INDEX_FIELD = {"input": "index", "sensor": "index", "list": "index", "schedule": "index",
                "config": "read_type", "zone": "zone", "line": "line"}


def preset_condition(event: str, index: int = -1) -> dict:
    """A friendly event name (+ optional 0-based index / 1-based line for dali_error)
    -> a matches() condition over decoded v2 events."""
    key = event.strip().lower()
    if key not in PRESETS:
        raise ValueError(f"event: one of {', '.join(sorted(PRESETS))}")
    cond, kind = PRESETS[key]
    cond = dict(cond)
    if index >= 0 and kind:
        if kind == "line":
            cond["line"] = index - 1 if index >= 1 else 0     # DaliFrame lines are 0-based
        else:
            cond[_INDEX_FIELD[kind]] = index
    return cond
