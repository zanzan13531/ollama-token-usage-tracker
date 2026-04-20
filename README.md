# Ollama Token Usage Tracker

A transparent proxy that sits between your apps and Ollama to track token usage. Supports multiple devices reporting to a central tracker node. Includes a web dashboard for viewing daily, weekly, and monthly stats filtered by model and device.

## Features

- **Transparent proxy** — takes over port 11434 so all existing apps work with zero config changes
- **Multi-device** — multiple machines report metrics to a central tracker node
- **Token tracking** — logs input/output tokens for every `/api/chat` and `/api/generate` call
- **Streaming support** — handles both streaming and non-streaming responses
- **Web dashboard** — dark-themed UI with charts, filterable by device and model
- **Stats API** — JSON endpoints for daily, weekly, monthly breakdowns
- **Auto-restart** — launchd (macOS) or systemd (Linux) for auto-start on reboot
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

The proxy takes over port 11434, so Ollama needs to listen elsewhere.

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

### On the tracker node (no Ollama needed):

```bash
./install.sh
# When prompted: Mode = tracker
```

### On each device with Ollama:

First move Ollama to port 11435 (see step 1 above), then:

```bash
./install.sh
# When prompted: Mode = proxy, then enter your device name and tracker URL
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
