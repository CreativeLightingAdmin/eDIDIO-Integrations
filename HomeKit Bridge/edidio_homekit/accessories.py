"""HAP accessories: turn HomeKit characteristic changes into eDIDIO intents.

Each accessory holds a spec (pure mapping) and a dispatcher. Setter callbacks run
in the driver's event-loop thread; they submit intents to the dispatcher (whose
``submit`` is thread-safe).
"""

from __future__ import annotations

import logging

from pyhap.accessory import Accessory
from pyhap.const import CATEGORY_LIGHTBULB, CATEGORY_SWITCH

from .specs import LightSpec, SceneSpec, pct_to_arc

_LOGGER = logging.getLogger(__name__)


class LightAccessory(Accessory):
    """A DALI address/group as a HomeKit lightbulb (On + Brightness)."""

    category = CATEGORY_LIGHTBULB

    def __init__(self, driver, spec: LightSpec, dispatcher):
        super().__init__(driver, spec.name)
        self.spec = spec
        self.dispatcher = dispatcher
        self._brightness = 100  # last known %, so "On" restores it

        serv = self.add_preload_service("Lightbulb", chars=["On", "Brightness"])
        self.char_on = serv.configure_char("On", setter_callback=self._set_on)
        self.char_brightness = serv.configure_char(
            "Brightness", value=100, setter_callback=self._set_brightness
        )

    def _set_on(self, value):
        if value:
            level = pct_to_arc(self._brightness) or 254
            self.dispatcher.submit(self.spec.level_intent(level))
        else:
            self.dispatcher.submit(self.spec.level_intent(0))

    def _set_brightness(self, value):
        self._brightness = value
        self.dispatcher.submit(self.spec.level_intent(pct_to_arc(value)))


class SceneAccessory(Accessory):
    """A stored DALI scene as a momentary HomeKit switch (recall on 'on')."""

    category = CATEGORY_SWITCH

    def __init__(self, driver, spec: SceneSpec, dispatcher):
        super().__init__(driver, spec.name)
        self.spec = spec
        self.dispatcher = dispatcher

        serv = self.add_preload_service("Switch")
        self.char_on = serv.configure_char("On", setter_callback=self._set_on)

    def _set_on(self, value):
        if not value:
            return
        self.dispatcher.submit(self.spec.intent())
        # Momentary: flip back to off shortly after so it acts as a "recall" button.
        loop = getattr(self.driver, "loop", None)
        if loop is not None:
            loop.call_later(1.0, self.char_on.set_value, False)


def build_accessory(driver, spec, dispatcher) -> Accessory:
    if isinstance(spec, LightSpec):
        return LightAccessory(driver, spec, dispatcher)
    if isinstance(spec, SceneSpec):
        return SceneAccessory(driver, spec, dispatcher)
    raise TypeError(f"unsupported spec type: {type(spec).__name__}")
