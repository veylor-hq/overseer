from pathlib import Path
"""Veylor Overseer Master Application."""

import asyncio
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from overseer.api.v1.alerts import router as alerts_v1_router
from overseer.api.v1.events import router as events_v1_router
from overseer.api.v1.nodes import router as nodes_v1_router
from overseer.api.v1.services import router as services_v1_router
from overseer.api.v1.workspaces import router as workspaces_v1_router
from overseer.config import get_settings
from overseer.database import close_db, init_db
from overseer.services.monitor_service import run_monitoring_tick
from overseer.services.node_service import check_all_nodes_liveness
from overseer.web.auth_routes import router as auth_web_router
from overseer.web.dashboard_routes import router as dashboard_web_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("overseer.master")

monitor_task = None


async def background_monitoring_loop():
    """Continuous background loop for node liveness and HTTP service checks."""
    settings = get_settings()
    logger.info("Starting Overseer background monitoring engine...")
    while True:
        try:
            await check_all_nodes_liveness()
            await run_monitoring_tick()
        except Exception as e:
            logger.error(f"Error in background monitoring tick: {e}")
        await asyncio.sleep(settings.SERVICE_MONITOR_WORKER_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    global monitor_task
    monitor_task = asyncio.create_task(background_monitoring_loop())
    logger.info("Veylor Overseer Master initialized.")
    yield
    # Shutdown
    if monitor_task:
        monitor_task.cancel()
    await close_db()
    logger.info("Veylor Overseer Master shut down.")


settings = get_settings()
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENV == "development" else None,
    redoc_url=None,
)

@app.get("/health", tags=["Health"])
async def health_check():
    """Kamal healthcheck endpoint."""
    return {"status": "ok", "service": "veylor-overseer"}


# CORS
cors_origins = settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Shell installation script endpoint for convenient curl piping
@app.get("/install.sh", response_class=PlainTextResponse)
async def get_install_script(request: Request):
    """
    Returns the dynamic shell script for deploying the Overseer Rust child agent.
    Usage: curl -fsSL https://overseer.veylor.dev/install.sh | sh -s -- --token <TOKEN> --url <URL>
    """
    script = """#!/bin/sh
set -e

OVERSEER_URL=""
ACTIVATION_TOKEN=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url) OVERSEER_URL="$2"; shift 2 ;;
    --token) ACTIVATION_TOKEN="$2"; shift 2 ;;
    *) shift 1 ;;
  esac
done

if [ -z "$ACTIVATION_TOKEN" ]; then
  echo "Error: --token is required"
  exit 1
fi

echo "============================================="
echo "   VEYLOR OVERSEER // CHILD NODE INSTALLER   "
echo "============================================="
echo "Master URL: ${OVERSEER_URL}"
echo "Initiating one-time agent activation..."

# Determine preferred configuration directory
# Try /etc/overseer if root/sudo; otherwise fall back to ~/.overseer
CRED_FILE=""
if [ "$(id -u)" -eq 0 ]; then
  mkdir -p /etc/overseer
  CRED_FILE="/etc/overseer/credentials.json"
else
  mkdir -p "$HOME/.overseer"
  CRED_FILE="$HOME/.overseer/credentials.json"
fi

BINARY=""
if command -v overseer-node >/dev/null 2>&1; then
  BINARY="overseer-node"
elif [ -f "./target/release/overseer-node" ]; then
  BINARY="./target/release/overseer-node"
elif [ -f "./overseer-node" ]; then
  BINARY="./overseer-node"
elif [ -f "/usr/local/bin/overseer-node" ]; then
  BINARY="/usr/local/bin/overseer-node"
fi

if [ -z "$BINARY" ]; then
  echo "Node binary 'overseer-node' not found locally. Detecting machine architecture..."
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64|amd64)
      RELEASE_NAME="overseer-node-linux-x86_64"
      ;;
    aarch64|arm64)
      RELEASE_NAME="overseer-node-linux-aarch64"
      ;;
    *)
      echo "Unsupported architecture: $ARCH"
      exit 1
      ;;
  esac

  echo "Detected architecture: $ARCH (downloading ${RELEASE_NAME})..."
  RELEASE_URL="https://github.com/veylor-hq/overseer/releases/download/v1/${RELEASE_NAME}"
  TARGET_PATH="/usr/local/bin/overseer-node"

  if [ "$(id -u)" -eq 0 ]; then
    curl -fsSL "$RELEASE_URL" -o "$TARGET_PATH"
    chmod +x "$TARGET_PATH"
    BINARY="$TARGET_PATH"
  elif sudo -n true 2>/dev/null; then
    sudo curl -fsSL "$RELEASE_URL" -o "$TARGET_PATH"
    sudo chmod +x "$TARGET_PATH"
    BINARY="$TARGET_PATH"
  else
    # Fallback to local working directory
    curl -fsSL "$RELEASE_URL" -o "./overseer-node"
    chmod +x "./overseer-node"
    BINARY="./overseer-node"
  fi
  echo "Downloaded overseer-node to ${BINARY}"
fi

$BINARY --activate --url "${OVERSEER_URL}" --token "${ACTIVATION_TOKEN}" --cred-file "${CRED_FILE}"
echo "Activation successful. Child node is registered and operational."
"""
    return script


# Register Routers
app.include_router(auth_web_router)
app.include_router(dashboard_web_router)

# Versioned APIs
app.include_router(nodes_v1_router, prefix="/api/v1")
app.include_router(services_v1_router, prefix="/api/v1")
app.include_router(alerts_v1_router, prefix="/api/v1")
app.include_router(events_v1_router, prefix="/api/v1")
app.include_router(workspaces_v1_router, prefix="/api/v1")
