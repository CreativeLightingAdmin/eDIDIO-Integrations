"""eDIDIO MQTT Bridge.

Subscribes to MQTT command topics and translates them into eDIDIO lighting
commands via the shared ``edidio_control_py`` engine, with optional Home
Assistant MQTT auto-discovery.
"""

__version__ = "1.0.0"
