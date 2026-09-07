"""eDIDIO GTA V integration.

Drives eDIDIO lighting from Grand Theft Auto V game state: the **wanted level**
throws a police red/blue siren wash that escalates 1-5 stars, health tints the
room, and busted/wasted moments flash. GTA V has no native game-state export, so
a small ScriptHookV mod (in `mod/`) POSTs state to this local bridge; the bridge
+ mapper are fully tested here (only the mod needs the game).
"""

__version__ = "1.0.0"
