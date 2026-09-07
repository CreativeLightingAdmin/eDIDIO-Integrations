# eDIDIO Gateways in Docker

Run any of the eDIDIO gateways as containers — one `docker compose` command
instead of per-machine Python/Node setup.

| Service | Gateway | Ports |
|---------|---------|-------|
| `rest` | REST API Gateway (Node) | 8080/tcp |
| `modbus` | Modbus TCP/RTU Gateway | 5020/tcp |
| `mqtt` | MQTT Bridge | (broker outbound) |
| `osc` | OSC Bridge | 8000/udp |
| `knx` | KNX Gateway | (KNXnet/IP) |
| `homekit` | HomeKit Bridge | host network (mDNS) |

## Quick start

```bash
# 1. Put your gateway configs in Docker/config/ (see config/README.md).
cp "../MQTT Bridge/config.example.yaml"        config/mqtt.yaml
cp "../Modbus TCPRTUGateway/config.example.yaml" config/modbus.yaml
cp "../OSC Bridge/config.example.yaml"         config/osc.yaml
cp "../KNX Gateway/config.example.yaml"        config/knx.yaml
# homekit.yaml is already provided; edit the controller host.
# Edit each file's controller.host (and the REST env in docker-compose.yml).

# 2. Build + run one (or more) services:
docker compose up -d mqtt
docker compose up -d            # everything
docker compose logs -f mqtt
```

## How the images are built

- **Python gateways** share `Dockerfile.python`, parameterised by a `GATEWAY`
  build arg (the gateway folder name). The build context is the repo root so the
  image can copy the gateway source. The shared engine `edidio_control_py` is
  installed from PyPI via each gateway's `requirements.txt`.
- **REST** uses `Dockerfile.node`.

## Networking notes

- **HomeKit** uses `network_mode: host` — HomeKit relies on mDNS/Bonjour, which
  doesn't traverse Docker's bridge network. (Host networking is Linux-only; on
  Docker Desktop run the HomeKit bridge natively instead.)
- **KNX** in `connection: routing` mode uses multicast — uncomment
  `network_mode: host` for the `knx` service. Tunnelling mode works on the bridge
  network.
- **OSC** publishes UDP `8000`; make sure your OSC source targets the host.

## Building a single image manually

```bash
# from the repo root:
docker build -f Docker/Dockerfile.python --build-arg "GATEWAY=MQTT Bridge" -t edidio-mqtt .
docker run --rm -v "$PWD/Docker/config/mqtt.yaml:/config/config.yaml:ro" edidio-mqtt
```

## Files

```
Docker/
├── docker-compose.yml     # all gateway services
├── Dockerfile.python      # shared image for Python gateways (GATEWAY build arg)
├── Dockerfile.node        # REST gateway image
└── config/                # your per-gateway YAML configs (mounted in)
```
