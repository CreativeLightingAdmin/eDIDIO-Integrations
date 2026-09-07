"""eDIDIO KNX Gateway.

Bridges a KNX installation (via KNXnet/IP) to the eDIDIO lighting controller:
listens for KNX group-address telegrams and translates them into eDIDIO commands
through the shared ``edidio_control_py`` engine.
"""

__version__ = "1.0.0"
