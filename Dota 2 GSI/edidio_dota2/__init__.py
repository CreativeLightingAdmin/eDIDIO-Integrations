"""eDIDIO Dota 2 Game State Integration (GSI) bridge.

Dota 2 posts JSON game-state to a local HTTP endpoint (Valve's native GSI, no
mods). This bridge maps it to eDIDIO lighting: room colour tracks your hero's
health, a red alert on death, green on respawn, and optional day/night ambience.
Second member of the game-state family (see CS2 GSI). Backed by edidio_control_py.
"""

__version__ = "1.0.0"
