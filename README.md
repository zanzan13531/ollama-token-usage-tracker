# Ollama Token Usage Tracker

A transparent proxy that sits between your apps and Ollama to track token usage. Supports multiple devices reporting to a central tracker node. Includes a web dashboard for viewing daily, weekly, and monthly stats filtered by model and device.

## Features

- **Transparent proxy** — takes over port 11434 so all existing apps work with zero config changes
- **Multi-device** — multiple machines report metrics to a central tracker node
- **Token tracking** — logs input/output tokens for every `/api/chat` and `/api/generate` call
- **Streaming support** — handles both streaming and non-streaming responses
- **Web dashboard** — dark-themed UI with charts, filterable by device and model
- **Stats API** — JSON endpoints for daily, weekly, monthly breakdowns
- **Auto-restart** — Docker, launchd (macOS), or systemd (Linux) for auto-start on reboot
- **No prompt storage** — only tracks numeric metrics, never stores prompt or message content

## Architecture

Two deployment modes from the same codebase:

- **Proxy mode** (default) — runs alongside Ollama, proxies traffic, tracks locally, and serves its own dashboard. Also accepts `/api/ingest` calls from other devices, so **any proxy machine can double as the central hub** — no dedicated tracker node required.
- **Tracker mode** — for a dedicated aggregator node with no Ollama. Receives metrics from all device proxies and serves the unified dashboard.

```
┌──────────────┐     ┌──────────────┐
│  Mac Studio  │     │  Linux Box   │
│  Ollama:11435│     │  Ollama:11435│
│  Proxy:11434 │     │  Proxy:11434 │
└──────┬───────┘     └──────┬───────┘
       │    POST /api/ingest│
       └────────┬───────────┘
                ▼
        ┌───────────────┐
        │  Tracker Node │
        │  :11434       │
        │  /dashboard   │
        └───────────────┘
```

## Docker

### Prerequisites

Install Docker first:

**macOS:**
```bash
brew install --cask docker
# Then open Docker.app to finish setup
```

**Windows:**
```powershell
winget install Docker.DockerDesktop
# Restart, then open Docker Desktop to finish setup
```

**Linux:**
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER  # log out and back in after this
```

### Run

The `--build` flag builds the image on first run (or after code changes). Pick the profile that matches your setup:

**Proxy mode** — proxy in a container, Ollama running on your host at port 11435:

```bash
# Move Ollama to port 11435 first (see below), then:
docker compose --profile proxy up -d --build
# Dashboard: http://localhost:11434/dashboard
```

**Tracker mode** — central aggregator, no Ollama needed:

```bash
docker compose --profile tracker up -d --build
# Dashboard: http://localhost:11434/dashboard
```

**Full stack** — Ollama + proxy both in containers:

```bash
docker compose --profile full up -d --build
# Pull a model on first run:
docker exec -it ollama-server ollama pull llama3.2
# Dashboard: http://localhost:11434/dashboard
```

### Configuration

Copy `.env.example` to `.env` and edit before starting:

```bash
cp .env.example .env
```

Key variables for Docker:

| Variable | Default | Notes |
|---|---|---|
| `DEVICE_NAME` | `default` | Name shown in the dashboard |
| `TRACKER_URL` | — | Set on proxy machines to report to a central tracker |
| `OLLAMA_HOST` | `http://host.docker.internal:11435` | Change if Ollama is on a different host/port |
| `TIMEZONE` | `America/Los_Angeles` | Used for stats bucketing |

### Auto-restart on reboot

All services use `restart: unless-stopped`, so Docker will restart containers automatically after a crash or reboot — as long as Docker itself starts on boot, which it does by default:

- **Mac/Windows:** Docker Desktop starts on login (Settings → General → "Start Docker Desktop when you sign in")
- **Linux:** the Docker daemon is registered as a systemd service automatically by the installer, so containers come back after reboot with no extra config

To permanently stop a container from restarting, run `docker compose --profile <profile> down` before shutting down.

### Logs & management

Replace `proxy` with `tracker` or `full` depending on your profile:

```bash
# View logs (live)
docker compose --profile proxy logs -f

# Stop (containers can be restarted later with `up`)
docker compose --profile proxy down

# Stop and delete the database volume (destructive — data is gone)
docker compose --profile proxy down -v
```

> **Linux note:** `host.docker.internal` resolves to your host automatically via `extra_hosts`. No manual IP config needed.

## Native Install (non-Docker)

> Use this if Docker isn't available. Otherwise the Docker section above is simpler.

### 1. Move Ollama to a different port

The proxy takes over port 11434, so Ollama needs to listen elsewhere. Skip this step if using the Docker `full` profile (Ollama runs in its own container).

**macOS:**
```bash
launchctl setenv OLLAMA_HOST "127.0.0.1:11435"
# Restart Ollama (or reboot)
```

**Linux (systemd):**
```bash
sudo systemctl edit ollama
# Add under [Service]:
#   Environment="OLLAMA_HOST=127.0.0.1:11435"
sudo systemctl restart ollama
```

### 2. Install

```bash
git clone <repo-url> && cd ollama-token-usage-tracker
chmod +x install.sh
./install.sh
```

The install script detects your OS (macOS/Linux) and prompts for mode, device name, and tracker URL.

### 3. Use it

All your apps keep using `http://localhost:11434` — no changes needed.

- **Dashboard**: http://localhost:11434/dashboard
- **Stats API**: http://localhost:11434/stats

## Multi-Device Setup

You have two options:

### Option A: One machine hosts Ollama and acts as the hub

The main machine runs in proxy mode — it handles its own Ollama traffic AND receives metrics from other devices:

```bash
# On the main machine (e.g. 192.168.1.10):
./install.sh
# Mode = proxy, device name = main, leave tracker URL blank
```

Other devices point their `TRACKER_URL` at this machine:

```bash
# On each other device:
./install.sh
# Mode = proxy, device name = <name>, tracker URL = http://192.168.1.10:11434
```

All stats appear on the main machine's dashboard at `http://192.168.1.10:11434/dashboard`.

### Option B: Dedicated tracker node (no Ollama)

```bash
# On the tracker node:
./install.sh
# Mode = tracker
```

```bash
# On each device with Ollama:
./install.sh
# Mode = proxy, enter device name and tracker URL
```

Each proxy saves metrics locally AND reports them to the central tracker.

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /stats` | Overall totals and per-model breakdown |
| `GET /stats/daily` | Last 30 days, grouped by date |
| `GET /stats/weekly` | Last 12 weeks, grouped by week |
| `GET /stats/monthly` | Last 12 months, grouped by month |
| `GET /stats/devices` | List of all known device names |
| `GET /dashboard` | Web dashboard UI |
| `POST /api/ingest` | Receive metrics from device proxies (tracker mode) |
| `*` | All other requests proxied to Ollama (proxy mode) |

All stats endpoints accept optional `?model=<name>` and `?device=<name>` query parameters.

## Configuration

Set via environment variables or `.env` file:

| Variable | Default | Description |
|---|---|---|
| `MODE` | `proxy` | `proxy` (alongside Ollama) or `tracker` (central aggregator) |
| `DEVICE_NAME` | `default` | Human-readable name for this machine |
| `TRACKER_URL` | — | Central tracker URL (proxy mode only) |
| `OLLAMA_HOST` | `http://localhost:11435` | Ollama's actual URL (proxy mode only) |
| `PROXY_PORT` | `11434` | Port for the proxy/tracker |
| `DB_PATH` | `~/.ollama-tracker/usage.db` | SQLite database path |

## Managing the Service (non-Docker install)

If you installed via `install.sh` instead of Docker, use the OS service manager:

**macOS:**
```bash
# Stop / Start
launchctl unload ~/Library/LaunchAgents/com.ollama-tracker.plist
launchctl load ~/Library/LaunchAgents/com.ollama-tracker.plist

# View logs
tail -f /tmp/ollama-tracker.log
tail -f /tmp/ollama-tracker.err
```

**Linux:**
```bash
# Stop / Start / Restart
sudo systemctl stop ollama-tracker
sudo systemctl start ollama-tracker
sudo systemctl restart ollama-tracker

# View logs
journalctl -u ollama-tracker -f
```
