"""eDIDIO Ambient Data engine.

A reusable framework that turns any real-time data source (a polled API, a
WebSocket feed, a webhook) into eDIDIO lighting — gradients, threshold scenes,
brightness levels. Each concept (stock ticker, aurora alert, ISS overhead, F1
telemetry, server health…) is just a small *source* + a *mapping* in config.

  source (produces values) → mapping (value → lighting intent) → dispatcher → eDIDIO
"""

__version__ = "1.0.0"
