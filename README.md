# Veylor Overseer

**Veylor Overseer** is an internal defence/military command-centre styled infrastructure monitoring and operations console for the Veylor ecosystem (**SSO**, **Relay**, **Warden**, **Pager**, and **eGarage**).

---

## Architecture & Core Invariants

1. **Strict Inbound-Only Telemetry**:
   - Master **never** connects outbound to child nodes.
   - Child nodes in Rust are strictly read-only telemetric agents.
   - There is **no command channel**, no remote execution, no SSH, and no remote container manipulation.
2. **Master Time Authority**:
   - Availability and health are determined by Master's authoritative `received_at` clock, not untrusted node timestamps.
3. **Workspace Multi-Tenancy**:
   - Tenancy enforced at every layer: Auth -> Membership -> Service Logic -> Database query scoping.
4. **Veylor SSO Native**:
   - Standard OIDC Authorization Code Flow with PKCE (S256). Uses immutable `sub` claim for identity reference.
5. **Alert Suppression**:
   - Telegram notifications adhere to a maximum 2-failure limit per persistent outage incident, suppressing spam until recovery.
6. **Privacy Mode & IP Visibility**:
   - Nodes report server IP addresses for situational awareness.
   - Built-in navbar "Privacy Mode" instantly obscures sensitive IPs, hostnames, and URLs with `[REDACTED]` for safe screen-sharing and public demos.
7. **Direct Service Navigation**:
   - Monitored HTTP services feature an "Open" action button for immediate direct verification.

---

## 1. Master Server (FastAPI + MongoDB)

### Local Development

```bash
cd overseer
uvicorn master.overseer.main:app --port 8080 --reload
```

### Automated Tests

```bash
source /Users/ihorsavenko/Hub/veylor/sso/.venv/bin/activate
PYTHONPATH=master pytest -v master/tests/test_master.py
```

### Production Deployment (Kamal 2)

Deploying with Kamal to production (`https://overseer.veylor.dev`):

```bash
# Push Kamal secrets to server
kamal secrets push

# Deploy master app & proxy
kamal deploy
```

---

## 2. Child Node Agent (`overseer-node` in Rust)

The node agent compiles to a standalone static binary without dynamic C dependencies (`x86_64-unknown-linux-musl`).

### A. Obtaining the Linux Binary

#### Option 1: Download Pre-built Release (Recommended)
You can directly download the static Linux musl binary:
```bash
sudo curl -fsSL https://github.com/veylor-hq/overseer/releases/download/v1/overseer-node-linux-x86_64 -o /usr/local/bin/overseer-node
sudo chmod +x /usr/local/bin/overseer-node
```

*(Note: The `/install.sh` script will also automatically download this release binary if `overseer-node` is not already installed on the machine).*

#### Option 2: Build from Source Using Docker
On macOS / Linux using Docker:

```bash
cd node
./build_linux.sh
```

This compiles a stripped, static binary and saves it to:
```text
node/dist/overseer-node-linux-x86_64
```

Copy this binary to the target Linux host:
```bash
scp node/dist/overseer-node-linux-x86_64 user@your-server:/tmp/overseer-node
```

On the target server, move it into `PATH`:
```bash
sudo mv /tmp/overseer-node /usr/local/bin/overseer-node
sudo chmod +x /usr/local/bin/overseer-node
```

---

### B. One-Time Activation Handshake

1. Go to your Overseer Web Console: **https://overseer.veylor.dev/nodes**
2. Click **+ Register Node**, name the server, and copy the generated one-time activation token.
3. On the target Linux host, activate using either the installer script or direct binary command:

#### Option 1: Quick Installer Script (Piped curl)
```bash
curl -fsSL https://overseer.veylor.dev/install.sh | sh -s -- \
  --token "<ACTIVATION_TOKEN>" \
  --url "https://overseer.veylor.dev"
```

#### Option 2: Direct Binary Execution
```bash
overseer-node --activate \
  --url "https://overseer.veylor.dev" \
  --token "<ACTIVATION_TOKEN>"
```

> **Note**: Always use `https://` in production. Activation tokens are single-use and burned immediately upon activation. Credentials will be securely saved to `/etc/overseer/credentials.json` (root) or `~/.overseer/credentials.json` (user).

---

### C. Running as a Permanent Systemd Service (Recommended)

To ensure the node automatically starts on boot and streams CPU, RAM, Disk, and Docker metrics:

#### 1. Setup System-Wide Service

If your user activated the node, copy credentials to system path:
```bash
sudo mkdir -p /etc/overseer
[ -f ~/.overseer/credentials.json ] && sudo cp ~/.overseer/credentials.json /etc/overseer/credentials.json
sudo chmod 600 /etc/overseer/credentials.json
```

Create `/etc/systemd/system/overseer-node.service`:
```bash
sudo tee /etc/systemd/system/overseer-node.service << 'EOF'
[Unit]
Description=Veylor Overseer Node Agent
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
ExecStart=/usr/local/bin/overseer-node
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

#### 2. Start & Enable Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now overseer-node
```

#### 3. Inspect Live Heartbeat Logs
```bash
journalctl -u overseer-node -f -n 25
```

---

### D. Docker Monitoring Permissions (If Running as Non-Root)

If running `overseer-node` under a specific non-root user instead of root, grant access to `/var/run/docker.sock`:

```bash
# Add user to docker group
sudo usermod -aG docker $USER

# Apply group changes to existing session / systemd user manager
sudo systemctl restart user@$(id -u).service
```

---

## Configuration Reference

### Node CLI / Environment Variables

| Argument | Environment Variable | Default | Description |
|---|---|---|---|
| `--url` | `OVERSEER_URL` | `http://localhost:8080` | Master public URL |
| `--token` | `OVERSEER_ACTIVATION_TOKEN` | *None* | One-time single-use activation token |
| `--interval` | `OVERSEER_INTERVAL` | `300` | Telemetry heartbeat interval in seconds (minimum 10s) |
| `--cred-file` | - | `/etc/overseer/credentials.json` | Path to load/save authenticated credentials |
| `--activate` | - | `false` | Perform activation handshake and exit immediately |

