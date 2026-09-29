"""eDIDIO Prometheus exporter.

Exposes controller health (reachability, firmware, configuration counts, active
profile) and live DALI levels / event rates from the event stream as Prometheus
metrics, via the shared ``edidio_control_py`` engine.
"""

__version__ = "1.0.0"
