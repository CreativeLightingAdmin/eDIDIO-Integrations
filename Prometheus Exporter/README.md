# eDIDIO Prometheus Exporter

Exposes Control Freak **eDIDIO** controller health and live lighting state as
**Prometheus** metrics, for Grafana dashboards and alerting across a site or a
fleet of controllers.

> **Target:** facilities / integrators monitoring installed systems.
> **Tech:** Python, wrapping the shared `edidio_control_py` engine (≥ 0.5.0).
> No `prometheus_client` dependency — the exposition format is built in.

## How it works

```
Prometheus ──scrape /metrics──▶ exporter ──DIAGNOSTIC_SYSTEM_INFO (poll)──▶ eDIDIO
                                    ▲
                                    └──── event stream (push, fw ≥ 1.4.0) ◀─┘
```

- **Health** — each scrape polls every controller's system info (cached for
  `min_poll_interval`, so short scrape intervals don't hammer the devices).
- **Live state** — a dedicated event-stream connection per controller tracks every
  DALI level seen on the bus (wall panels, schedules, SpektraPlus, other gateways)
  and counts events by kind. It reconnects and resubscribes on its own.

## Setup

```bash
cd "Prometheus Exporter"
python -m pip install -r requirements.txt
cp config.example.yaml config.yaml   # then edit
python run.py --config config.yaml
curl http://localhost:9464/metrics
```

Prometheus:

```yaml
scrape_configs:
  - job_name: edidio
    scrape_interval: 30s
    static_configs:
      - targets: ["exporter-host:9464"]
```

## Metrics

All controller metrics carry a `controller` label (the configured `name`).

| Metric | Type | Description |
|---|---|---|
| `edidio_up` | gauge | 1 if the last health poll succeeded |
| `edidio_info{firmware,hardware,proto_version,vendor_id}` | gauge | identity (always 1) |
| `edidio_active_profile` | gauge | selected profile index |
| `edidio_config_count{kind}` | gauge | capacity reported by the controller (sequences, themes, lists, schedules, inputs, …) |
| `edidio_poll_duration_seconds` | gauge | last health poll duration |
| `edidio_poll_failures_total` | counter | failed health polls |
| `edidio_event_stream_up` | gauge | 1 while the event stream is connected |
| `edidio_event_stream_reconnects_total` | counter | event stream reconnects |
| `edidio_events_total{kind}` | counter | events received (dali, input, sensor, spektra, …) |
| `edidio_last_event_timestamp_seconds` | gauge | Unix time of the last event |
| `edidio_dali_level{line,target,address}` | gauge | last DALI arc level (0-254); `address` is the group number when `target="group"` |
| `edidio_exporter_build_info{version}` / `edidio_exporter_scrapes_total` | | exporter self-metrics |

`edidio_dali_level` only includes targets that have changed since the exporter
started (the bus is observed, not polled).

### Example alerts

```yaml
- alert: EdidioDown
  expr: edidio_up == 0
  for: 5m
- alert: EdidioEventStreamFlapping
  expr: increase(edidio_event_stream_reconnects_total[1h]) > 5
- alert: EdidioLightsOnAfterHours
  expr: edidio_dali_level{target="broadcast"} > 0 and on() hour() > 20
```

## Tests

```bash
python -m pytest -q
```

Fake controller clients cover polling, event-driven levels, the exposition format
and a real HTTP scrape — no hardware needed.

## License

MIT
