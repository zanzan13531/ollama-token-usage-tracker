# Ollama Token Usage Tracker

A transparent proxy that sits between your apps and Ollama to track token usage. Supports multiple devices reporting to a central tracker node. Includes a web dashboard for viewing daily, weekly, and monthly stats filtered by model and device.

## Features

- **Transparent proxy** — takes over port 11434 so all existing apps work with zero config changes
- **Multi-device** — multiple machines report metrics to a central tracker node
- **Token tracking** — logs input/output tokens for every `/api/chat` and `/api/generate` call
- **Streaming support** — handles both streaming and non-streaming responses
- **Web dashboard** — dark-themed UI with charts, filterable by device and model
- **Stats API** — JSON endpoints for daily, weekly, monthly breakdowns
- **Auto-restart** — launchd plist for macOS auto-start on reboot
- **No prompt storage** — only tracks numeric metrics, never stores prompt or message content

## Architecture

Two deployment modes from the same codebase:

- **Proxy mode** (default) — runs on each device alongside Ollama, proxies traffic, tracks locally, and optionally reports to a central tracker
- **Tracker mode** — runs on a dedicated node (no Ollama needed), receives metrics from all device proxies, serves the unified dashboard

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

## Quick Start (Single Device)

### 1. Move Ollama to a different port

```bash
launchctl setenv OLLAMA_HOST "127.0.0.1:11435"
# Restart Ollama (or reboot)
```

### 2. Install

```bash
git clone <repo-url> && cd ollama-token-usage-tracker
chmod +x install.sh
./install.sh
```

The install script will prompt for mode, device name, and tracker URL.

### 3. Use it

All your apps keep using `http://localhost:11434` — no changes needed.

- **Dashboard**: http://localhost:11434/dashboard
- **Stats API**: http://localhost:11434/stats

## Multi-Device Setup

### On the tracker node (no Ollama):

```bash
MODE=tracker DEVICE_NAME=tracker ./install.sh
# Or set in .env: MODE=tracker
```

### On each device with Ollama:

```bash
# Move Ollama to 11435 first
launchctl setenv OLLAMA_HOST "127.0.0.1:11435"

MODE=proxy DEVICE_NAME=mac-studio TRACKER_URL=http://tracker-node:11434 ./install.sh
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

## Managing the Service

```bash
# Stop the service
launchctl unload ~/Library/LaunchAgents/com.ollama-tracker.plist

# Start the service
launchctl load ~/Library/LaunchAgents/com.ollama-tracker.plist

# View logs
tail -f /tmp/ollama-tracker.log
tail -f /tmp/ollama-tracker.err
```
