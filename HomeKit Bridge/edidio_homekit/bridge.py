"""The eDIDIO HomeKit bridge accessory: owns the dispatcher and hosts the
light/scene accessories.
"""

from __future__ import annotations

import logging

from pyhap.accessory import Bridge

from . import __version__
from .accessories import build_accessory
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
            ctrl.host, ctrl.port, use_tls=ctrl.use_tls, timeout=ctrl.timeout
        )
        for spec in config.specs:
            self.add_accessory(build_accessory(driver, spec, self.dispatcher))

    async def run(self):
        # Runs on the driver's event loop once the HAP server is up.
        await self.dispatcher.start()
        await super().run()

    async def stop(self):
        await super().stop()
        await self.dispatcher.stop()
