"""paho-mqtt wiring: connect the Bridge and dispatcher to a broker."""

from __future__ import annotations

import asyncio
import logging

import paho.mqtt.client as mqtt

from .bridge import Bridge
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


async def run(config) -> None:
    """Start the dispatcher and MQTT client; block until cancelled."""
    ctrl = config.controller
    dispatcher = EdidioDispatcher(ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout)
    await dispatcher.start()

    bridge = Bridge(config, dispatcher)
    ctx = config.context
    m = config.mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=m.client_id)
    if m.username:
        client.username_pw_set(m.username, m.password)
    # Last-will: broker marks us offline if we drop unexpectedly.
    client.will_set(ctx.availability_topic, "offline", retain=True)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    # Publish from the bridge via the client (thread-safe in paho).
    bridge.set_publisher(lambda topic, payload, retain: client.publish(topic, payload, retain=retain))

    def on_connect(cli, userdata, flags, reason_code, properties):
        if reason_code != 0:
            _LOGGER.error("MQTT connect failed: %s", reason_code)
            return
        _LOGGER.info("Connected to MQTT broker %s:%s", m.host, m.port)
        for topic in bridge.subscriptions():
            cli.subscribe(topic)
        if m.discovery:
            for topic, payload, retain in bridge.discovery_messages():
                cli.publish(topic, payload, retain=retain)
            _LOGGER.info("Published Home Assistant discovery for %d entities", len(config.entities))
        cli.publish(ctx.availability_topic, "online", retain=True)

    def on_message(cli, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            payload = ""
        bridge.handle_message(msg.topic, payload)

    client.on_connect = on_connect
    client.on_message = on_message

    _LOGGER.info("Connecting to MQTT broker %s:%s ...", m.host, m.port)
    client.connect_async(m.host, m.port)
    client.loop_start()

    try:
        await asyncio.Event().wait()  # run until cancelled
    finally:
        try:
            client.publish(ctx.availability_topic, "offline", retain=True)
            client.loop_stop()
            client.disconnect()
        finally:
            await dispatcher.stop()
