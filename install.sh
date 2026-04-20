#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PLIST_NAME="com.ollama-tracker"
PLIST_SRC="$PROJECT_DIR/$PLIST_NAME.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"
ENV_FILE="$PROJECT_DIR/.env"

echo "=== Ollama Token Usage Tracker - Install ==="
echo ""

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Please install Python 3.11+."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found Python $PY_VERSION"

# Configuration prompts
echo ""
read -rp "Mode — proxy (alongside Ollama) or tracker (central aggregator) [proxy]: " MODE
MODE="${MODE:-proxy}"

read -rp "Device name [$(hostname)]: " DEVICE_NAME
DEVICE_NAME="${DEVICE_NAME:-$(hostname)}"

TRACKER_URL=""
if [ "$MODE" = "proxy" ]; then
    read -rp "Central tracker URL (leave empty for standalone): " TRACKER_URL
fi

# Create virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip -q
"$VENV_DIR/bin/pip" install -r "$PROJECT_DIR/requirements.txt" -q

# Create default DB directory
mkdir -p "$HOME/.ollama-tracker"
echo "Database directory: ~/.ollama-tracker/"

# Generate .env file
echo ""
echo "Writing .env configuration..."
cat > "$ENV_FILE" <<EOF
MODE=$MODE
DEVICE_NAME=$DEVICE_NAME
EOF

if [ -n "$TRACKER_URL" ]; then
    echo "TRACKER_URL=$TRACKER_URL" >> "$ENV_FILE"
fi

if [ "$MODE" = "proxy" ]; then
    cat >> "$ENV_FILE" <<EOF
OLLAMA_HOST=http://localhost:11435
PROXY_PORT=11434
EOF
else
    cat >> "$ENV_FILE" <<EOF
PROXY_PORT=11434
EOF
fi

echo "DB_PATH=~/.ollama-tracker/usage.db" >> "$ENV_FILE"

# Install launchd plist
echo ""
echo "Setting up auto-start with launchd..."

# Unload existing plist if present
if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# Template the plist with actual paths
sed -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DST"

launchctl load "$PLIST_DST"
echo "Loaded $PLIST_NAME into launchd"

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Mode: $MODE | Device: $DEVICE_NAME"
echo ""

if [ "$MODE" = "proxy" ]; then
    echo "IMPORTANT: Move Ollama to port 11435 so the proxy can take over 11434:"
    echo "  launchctl setenv OLLAMA_HOST '127.0.0.1:11435'"
    echo "  Then restart Ollama."
    echo ""
    echo "  Proxy:     http://localhost:11434  (drop-in, no app changes needed)"
    if [ -n "$TRACKER_URL" ]; then
        echo "  Reporting: metrics sent to $TRACKER_URL"
    fi
else
    echo "  Tracker is ready to receive metrics from device proxies."
fi

echo "  Dashboard: http://localhost:11434/dashboard"
echo "  Stats API: http://localhost:11434/stats"
echo ""
echo "Logs: /tmp/ollama-tracker.log"
echo "      /tmp/ollama-tracker.err"
