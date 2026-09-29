# Docker gateway configs

Put one YAML per gateway here (mounted read-only into each container at
`/config/config.yaml`):

| File | From |
|------|------|
| `modbus.yaml` | `Modbus TCPRTUGateway/config.example.yaml` |
| `mqtt.yaml` | `MQTT Bridge/config.example.yaml` |
| `knx.yaml` | `KNX Gateway/config.example.yaml` |
| `osc.yaml` | `OSC Bridge/config.example.yaml` |
| `homekit.yaml` | provided here (persist_file → `/data`) |
| `prometheus.yaml` | `Prometheus Exporter/config.example.yaml` |

Copy the example, set your `controller.host`, and adjust the map. The REST
gateway is configured via environment variables in `docker-compose.yml` instead;
its API keys go in `Docker/.env` (gitignored).

> Keep real configs out of version control if they contain secrets.
