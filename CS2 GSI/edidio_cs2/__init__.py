"""eDIDIO Counter-Strike 2 Game State Integration (GSI) bridge.

Counter-Strike 2 posts JSON game-state to a local HTTP endpoint on every state
change. This bridge maps that state to eDIDIO lighting: room colour tracks your
health (green→red), a blinding white flash on a flashbang, a red alert when the
bomb is planted. Backed by ``edidio_control_py``.
"""

__version__ = "1.0.0"
