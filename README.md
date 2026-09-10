# Veylor Overseer

**Veylor Overseer** is an internal defence/military command-centre styled infrastructure monitoring and operations console for the Veylor ecosystem (**SSO**, **Relay**, **Warden**, **Pager**, and **eGarage**).

---

## Architectural Principles

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

## Getting Started

### Master (Python / FastAPI)

```bash
cd /Users/ihorsavenko/Hub/veylor/overseer
uvicorn master.overseer.main:app --port 8080 --reload
```

### Node Agent (Rust)

1. Register a Node in the Overseer UI (`http://localhost:8080/nodes`) to obtain a single-use activation token.
2. Run the agent:

```bash
cd node
cargo build --release
./target/release/overseer-node --activate --url http://localhost:8080 --token <ACTIVATION_TOKEN>
./target/release/overseer-node --url http://localhost:8080
```

---

## Running Automated Tests

```bash
source /Users/ihorsavenko/Hub/veylor/sso/.venv/bin/activate
PYTHONPATH=master pytest -v master/tests/test_master.py
```
