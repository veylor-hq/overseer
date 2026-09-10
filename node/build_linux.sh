#!/bin/bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Building static Linux x86_64 binary using Docker..."
docker build --platform linux/amd64 -f Dockerfile.build -t overseer-node-builder .

echo "Extracting binary..."
CONTAINER_ID=$(docker create overseer-node-builder /overseer-node)
mkdir -p "$DIR/dist"
docker cp "$CONTAINER_ID:/overseer-node" "$DIR/dist/overseer-node-linux-x86_64"
docker rm -v "$CONTAINER_ID" >/dev/null

chmod +x "$DIR/dist/overseer-node-linux-x86_64"
echo "Done! Linux binary saved to: $DIR/dist/overseer-node-linux-x86_64"
