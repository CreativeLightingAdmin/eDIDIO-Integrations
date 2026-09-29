"""The eDIDIO HomeKit bridge accessory: owns the dispatcher and hosts the
light/scene accessories. With state feedback on, levels seen on the DALI bus
(wall panels, schedules, other apps) are reflected in the Home app.
"""

from __future__ import annotations

import logging

from pyhap.accessory import Bridge

from . import __version__
from .accessories import build_accessory
from .specs import LightSpec
from .dispatcher import EdidioDispatcher

_LOGGER = logging.getLogger(__name__)


class EdidioHomeKitBridge(Bridge):
    def __init__(self, driver, config):
        super().__init__(driver, config.homekit.name)
        self.set_info_service(
            firmware_revision=__version__,
            manufacturer="Control Freak",
            model="eDIDIO",
            serial_number=str(config.controller.host),
        )
        ctrl = config.controller
        self.dispatcher = EdidioDispatcher(
            ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout,
            on_state=self.on_state if ctrl.state_feedback else None,
        )
        self._lights = {}  # (line, eDIDIO address) -> [LightAccessory]
        for spec in config.specs:
            acc = build_accessory(driver, spec, self.dispatcher)
            self.add_accessory(acc)
            if isinstance(spec, LightSpec):
                self._lights.setdefault((spec.line, spec.edidio_address), []).append(acc)

    async def on_state(self, change, touched):
        """Dispatcher state callback (runs on the driver's loop)."""
        if change.level is None and change.command == "scene":
            return
        for line, address, level in touched:
            for acc in self._lights.get((line, address), []):
                acc.apply_level(level)

    async def run(self):
        # Runs on the driver's event loop once the HAP server is up.
        await self.dispatcher.start()
        await super().run()

    async def stop(self):
        await super().stop()
        await self.dispatcher.stop()
