"""Minimal stand-in for Extron's `extronlib`, for OFF-DEVICE testing only.

On a real Extron control processor (or in ControlScript Studio's virtual
runtime) the genuine `extronlib` is provided by the platform. This stub mimics
just enough of the API for `edidio_extron.py` to run and be unit-tested on a PC.

Do NOT ship this stub to the device.
"""


def event(interface, eventName):
    """Decorator stand-in matching extronlib's @event(interface, 'Connected')."""
    def decorator(func):
        return func
    return decorator
