#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

mkdir -p "$DIR/dist"

TARGET_ARCH="${1:-all}"

build_arch() {
  local arch="$1"
  local platform=""
  local output_name=""

  if [ "$arch" = "x86_64" ] || [ "$arch" = "amd64" ]; then
    platform="linux/amd64"
    output_name="overseer-node-linux-x86_64"
  elif [ "$arch" = "aarch64" ] || [ "$arch" = "arm64" ]; then
    platform="linux/arm64"
    output_name="overseer-node-linux-aarch64"
  else
    echo "Unsupported arch: $arch"
    exit 1
  fi

  echo "=================================================="
  echo "Building static Linux binary for ${platform}..."
  echo "=================================================="

  docker build --platform "$platform" -f Dockerfile.build -t "overseer-node-builder-${arch}" .

  echo "Extracting binary to dist/${output_name}..."
  CONTAINER_ID=$(docker create "overseer-node-builder-${arch}" /overseer-node)
  docker cp "$CONTAINER_ID:/overseer-node" "$DIR/dist/${output_name}"
  docker rm -v "$CONTAINER_ID" >/dev/null

  chmod +x "$DIR/dist/${output_name}"
  echo "Success: $DIR/dist/${output_name}"
}

if [ "$TARGET_ARCH" = "all" ]; then
  build_arch "x86_64"
  build_arch "aarch64"
else
  build_arch "$TARGET_ARCH"
fi

echo "All requested builds completed successfully in $DIR/dist/"
