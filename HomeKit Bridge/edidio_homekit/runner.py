"""HAP-python AccessoryDriver wiring."""

from __future__ import annotations

import logging
import signal

from pyhap.accessory_driver import AccessoryDriver

from .bridge import EdidioHomeKitBridge

_LOGGER = logging.getLogger(__name__)


def run(config) -> None:
    """Start the HomeKit bridge (blocks until interrupted)."""
    hk = config.homekit
    driver = AccessoryDriver(
        port=hk.port,
        persist_file=hk.persist_file,
        pincode=hk.pincode.encode("ascii"),
    )
    driver.add_accessory(accessory=EdidioHomeKitBridge(driver, config))

    # Graceful shutdown on SIGINT/SIGTERM (stops the dispatcher via Bridge.stop).
    signal.signal(signal.SIGTERM, driver.signal_handler)
    signal.signal(signal.SIGINT, driver.signal_handler)

    _LOGGER.info(
        "Starting HomeKit bridge '%s' on port %s -> eDIDIO %s:%s. Pair with code %s",
        hk.name, hk.port, config.controller.host, config.controller.port, hk.pincode,
    )
    driver.start()
