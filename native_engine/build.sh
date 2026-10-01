#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

mkdir -p "$ROOT_DIR/bin"
BUILD_DIR="$(mktemp -d "$ROOT_DIR/bin/.build-XXXXXX")"
trap 'rm -rf "$BUILD_DIR"' EXIT

if [ -x "/usr/bin/swiftc" ]; then
  SWIFTC="/usr/bin/swiftc"
elif command -v xcrun &>/dev/null; then
  SWIFTC="xcrun swiftc"
else
  SWIFTC="$(command -v swiftc || echo "swiftc")"
fi

echo "==> Using swiftc compiler: $SWIFTC"
echo "==> Compiling mac_cua_engine.swift..."
$SWIFTC -O "$SCRIPT_DIR/mac_cua_engine.swift" \
  -o "$BUILD_DIR/mac-cua" \
  -framework ApplicationServices \
  -framework CoreGraphics \
  -framework AppKit \
  -framework ImageIO

$SWIFTC -O "$SCRIPT_DIR/overlay.swift" -o "$BUILD_DIR/mac-cua-overlay" -framework AppKit
chmod +x "$BUILD_DIR/mac-cua" "$BUILD_DIR/mac-cua-overlay"
# Both compilations must succeed before replacing either installed binary.
mv "$BUILD_DIR/mac-cua" "$ROOT_DIR/bin/mac-cua"
mv "$BUILD_DIR/mac-cua-overlay" "$ROOT_DIR/bin/mac-cua-overlay"

echo "==> Build successful! Binary generated at: $ROOT_DIR/bin/mac-cua"
