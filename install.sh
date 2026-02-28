#!/usr/bin/env bash
set -euo pipefail

REPO="24R0qu3/Hive"
INSTALL_DIR="$HOME/.local/bin"

case "$(uname -s)" in
    Darwin*) BINARY="hive-macos-latest" ;;
    Linux*)  BINARY="hive-ubuntu-latest" ;;
    *)
        echo "Unsupported platform: $(uname -s)" >&2
        exit 1
        ;;
esac

URL="https://github.com/$REPO/releases/latest/download/$BINARY"

echo "Downloading hive..."
mkdir -p "$INSTALL_DIR"
curl -fsSL "$URL" -o "$INSTALL_DIR/hive"
chmod +x "$INSTALL_DIR/hive"
echo "Installed to $INSTALL_DIR/hive"

if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo ""
    echo "~/.local/bin is not on your PATH. Add this to your shell profile:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi
