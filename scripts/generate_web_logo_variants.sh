#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-$ROOT_DIR/apps/web/src/asset/logo-prompt2-pr.png}"
OUT_DIR="${2:-$ROOT_DIR/apps/web/public/brand}"

if ! command -v sips >/dev/null 2>&1; then
  echo "sips is required on macOS to generate image variants."
  echo "Install ImageMagick and adapt this script if you need Linux support."
  exit 1
fi

if [[ ! -f "$SRC" ]]; then
  echo "Source image not found: $SRC"
  exit 1
fi

mkdir -p "$OUT_DIR"

echo "Generating logo variants from: $SRC"

# Square icon sizes.
for size in 16 32 64 128 192 256 512; do
  sips -z "$size" "$size" "$SRC" --out "$OUT_DIR/logo-${size}.png" >/dev/null
done

# Apple touch icon.
sips -z 180 180 "$SRC" --out "$OUT_DIR/apple-touch-icon.png" >/dev/null

# Wide variants for social/hero usage.
sips -z 630 1200 "$SRC" --out "$OUT_DIR/og-image-1200x630.png" >/dev/null
sips -z 675 1200 "$SRC" --out "$OUT_DIR/hero-1200x675.png" >/dev/null

echo "Done. Files written to: $OUT_DIR"
