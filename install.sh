#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
ENV_FILE="$PROJECT_DIR/.env"

# Detect OS
OS="$(uname -s)"

echo "=== Ollama Token Usage Tracker - Install ==="
echo "Detected OS: $OS"
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

# ── Auto-start setup (OS-specific) ──────────────────────────────────

echo ""
echo "Setting up auto-start..."

if [ "$OS" = "Darwin" ]; then
    # macOS: launchd
    mkdir -p "$HOME/Library/LaunchAgents"

    # -- Proxy/Tracker service --
    PLIST_NAME="com.ollama-tracker"
    PLIST_SRC="$PROJECT_DIR/$PLIST_NAME.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

    if launchctl list | grep -q "$PLIST_NAME" 2>/dev/null; then
        launchctl unload "$PLIST_DST" 2>/dev/null || true
    fi

    sed -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    launchctl load "$PLIST_DST"
    echo "Loaded $PLIST_NAME into launchd"

    # -- Move Ollama to port 11435 (proxy mode only) --
    if [ "$MODE" = "proxy" ]; then
        OLLAMA_PLIST_NAME="com.ollama.serve.custom"
        OLLAMA_PLIST_SRC="$PROJECT_DIR/com.ollama.serve.plist"
        OLLAMA_PLIST_DST="$HOME/Library/LaunchAgents/$OLLAMA_PLIST_NAME.plist"
        OLLAMA_BIN="$(which ollama 2>/dev/null || echo "/usr/local/bin/ollama")"

        echo ""
        echo "Setting up Ollama to run on port 11435..."

        # Disable the Ollama desktop app's auto-start services
        launchctl remove com.ollama.serve 2>/dev/null || true
        launchctl remove com.ollama.server 2>/dev/null || true
        launchctl remove com.ollama.ollama 2>/dev/null || true

        # Warn user to disable Ollama's background agent in System Settings
        OLLAMA_APP="/Applications/Ollama.app"
        if [ -d "$OLLAMA_APP" ]; then
            echo ""
            echo "*** IMPORTANT: Disable Ollama background agent ***"
            echo "  System Settings → General → Login Items → Allow in the Background"
            echo "  Toggle OFF 'Ollama' to prevent it from grabbing port 11434 on reboot."
            echo ""
            read -rp "Press Enter once you've disabled it (or 's' to skip): " SKIP_OLLAMA
        fi

        # Remove any plist files the desktop app drops into LaunchAgents
        rm -f "$HOME/Library/LaunchAgents/com.ollama.serve.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/com.ollama.server.plist" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/com.ollama.ollama.plist" 2>/dev/null || true

        if launchctl list | grep -q "$OLLAMA_PLIST_NAME" 2>/dev/null; then
            launchctl unload "$OLLAMA_PLIST_DST" 2>/dev/null || true
        fi

        # Kill any existing ollama processes (careful not to kill the proxy)
        killall ollama 2>/dev/null || true
        sleep 2

        sed -e "s|__OLLAMA_BIN__|$OLLAMA_BIN|g" \
            "$OLLAMA_PLIST_SRC" > "$OLLAMA_PLIST_DST"

        launchctl load "$OLLAMA_PLIST_DST"
        echo "Loaded Ollama on port 11435 via launchd"
    fi

elif [ "$OS" = "Linux" ]; then
    # Linux: systemd
    SERVICE_NAME="ollama-tracker"
    SERVICE_SRC="$PROJECT_DIR/$SERVICE_NAME.service"
    SERVICE_DST="/etc/systemd/system/$SERVICE_NAME.service"

    sed -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__USER__|$(whoami)|g" \
        "$SERVICE_SRC" > "/tmp/$SERVICE_NAME.service"

    if command -v sudo &>/dev/null; then
        sudo cp "/tmp/$SERVICE_NAME.service" "$SERVICE_DST"
        sudo systemctl daemon-reload
        sudo systemctl enable "$SERVICE_NAME"
        sudo systemctl restart "$SERVICE_NAME"
        echo "Enabled and started $SERVICE_NAME.service via systemd"
    else
        echo "sudo not available. Install the service manually:"
        echo "  cp /tmp/$SERVICE_NAME.service $SERVICE_DST"
        echo "  systemctl daemon-reload && systemctl enable --now $SERVICE_NAME"
    fi
else
    echo "Unsupported OS: $OS. Skipping auto-start setup."
    echo "Run manually: $VENV_DIR/bin/uvicorn app.main:app --host 0.0.0.0 --port 11434"
fi

# ── Summary ──────────────────────────────────────────────────────────

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Mode: $MODE | Device: $DEVICE_NAME"
echo ""

if [ "$MODE" = "proxy" ]; then
    if [ "$OS" = "Darwin" ]; then
        echo "Ollama has been moved to port 11435 automatically."
        echo "NOTE: Ollama is now managed via launchd (com.ollama.serve.custom)."
        echo "      Make sure Ollama is toggled OFF under:"
        echo "      System Settings → General → Login Items → Allow in the Background"
        echo ""
        echo "If after reboot Ollama grabs port 11434 again, run:"
        echo "  kill -9 \$(lsof -ti :11434)"
        echo "  launchctl load ~/Library/LaunchAgents/com.ollama-tracker.plist"
    else
        echo "IMPORTANT: Move Ollama to port 11435:"
        echo "  sudo systemctl edit ollama"
        echo "  Add: Environment=\"OLLAMA_HOST=127.0.0.1:11435\""
        echo "  Then: sudo systemctl daemon-reload && sudo systemctl restart ollama"
    fi
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

if [ "$OS" = "Darwin" ]; then
    echo "Logs: /tmp/ollama-tracker.log"
    echo "      /tmp/ollama-tracker.err"
elif [ "$OS" = "Linux" ]; then
    echo "Logs: journalctl -u ollama-tracker -f"
fi
