"""Transport-agnostic MQTT routing.

Maps subscribed command topics to entities, builds Home Assistant discovery
messages, and turns an incoming (topic, payload) into an eDIDIO intent plus any
optimistic state publishes. Kept independent of paho/MQTT so it is unit testable
with a fake dispatcher and publisher.
"""

from __future__ import annotations

import json
import logging

_LOGGER = logging.getLogger(__name__)


class Bridge:
    def __init__(self, config, dispatcher, publisher=None):
        self.config = config
        self.ctx = config.context
        self.entities = config.entities
        self.dispatcher = dispatcher
        self._publisher = publisher  # callable(topic, payload, retain)
        self._topic_map = {}
        for entity in self.entities:
            for topic in entity.command_topics(self.ctx):
                self._topic_map[topic] = entity

    def set_publisher(self, publisher):
        self._publisher = publisher

    # --- topics the client must subscribe to ---
    def subscriptions(self) -> list[str]:
        return list(self._topic_map.keys())

    # --- retained Home Assistant discovery messages ---
    def discovery_messages(self):
        """Return [(topic, json_payload, retain), ...] for HA auto-discovery."""
        messages = []
        for entity in self.entities:
            result = entity.discovery(self.ctx)
            if result:
                topic, cfg = result
                messages.append((topic, json.dumps(cfg), True))
        return messages

    # --- handle an inbound command ---
    def handle_message(self, topic: str, payload: str) -> None:
        entity = self._topic_map.get(topic)
        if entity is None:
            _LOGGER.debug("Message on unmapped topic %s ignored", topic)
            return
        try:
            intent, states = entity.handle(topic, payload, self.ctx)
        except Exception as err:  # noqa: BLE001 - a bad payload must not kill the bridge
            _LOGGER.error("Error handling %s = %r: %s", topic, payload, err)
            return
        if intent is not None:
            _LOGGER.info("%s = %r => %s", topic, payload, intent["kind"])
            self.dispatcher.submit(intent)
        for state_topic, state_payload, retain in states:
            self._publish(state_topic, state_payload, retain)

    def _publish(self, topic, payload, retain):
        if self._publisher is not None:
            self._publisher(topic, payload, retain)
