"""eDIDIO Kerbal Space Program integration.

Drives eDIDIO lighting from KSP vessel telemetry: a countdown/launch ignition
sequence, throttle -> brightness, fuel -> a green->red gauge, and stage/abort
flashes. Telemetry comes from kRPC (or Telemachus); the mapping is pure and
tested, so only the live link needs the game.
"""

__version__ = "1.0.0"
