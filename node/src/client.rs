use crate::config::PersistedCredentials;
use crate::docker::ContainerInfo;
use crate::system::SystemMetrics;
use chrono::Utc;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{error, info};

#[derive(Serialize)]
struct ActivationPayload {
    activation_token: String,
    hostname: Option<String>,
    os: Option<String>,
    arch: Option<String>,
    ip_address: Option<String>,
}

#[derive(Deserialize)]
struct ActivationResponse {
    status: String,
    node_id: String,
    node_secret: String,
}

#[derive(Serialize)]
struct HeartbeatPayload {
    node_id: String,
    reported_at: String,
    ip_address: Option<String>,
    system: SystemMetrics,
    docker: Vec<ContainerInfo>,
}

pub struct MasterClient {
    client: Client,
}

impl MasterClient {
    pub fn new() -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(15))
            .build()
            .unwrap_or_default();
        Self { client }
    }

    pub async fn activate(
        &self,
        master_url: &str,
        token: &str,
        metrics: &SystemMetrics,
        ip: Option<&str>,
    ) -> Result<PersistedCredentials, String> {
        let url = format!("{}/api/v1/nodes/activate", master_url.trim_end_matches('/'));
        let payload = ActivationPayload {
            activation_token: token.to_string(),
            hostname: Some(metrics.hostname.clone()),
            os: Some(metrics.os.clone()),
            arch: Some(metrics.arch.clone()),
            ip_address: ip.map(|s| s.to_string()),
        };

        info!("Sending activation request to {}", url);
        let res = self
            .client
            .post(&url)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("Network error: {}", e))?;

        if !res.status().is_success() {
            let status = res.status();
            let body = res.text().await.unwrap_or_default();
            return Err(format!("Master rejected activation (HTTP {}): {}", status, body));
        }

        let resp: ActivationResponse = res
            .json()
            .await
            .map_err(|e| format!("Invalid JSON response: {}", e))?;

        info!("Node successfully activated! ID: {}", resp.node_id);
        Ok(PersistedCredentials {
            node_id: resp.node_id,
            node_secret: resp.node_secret,
            master_url: master_url.to_string(),
        })
    }

    pub async fn send_heartbeat(
        &self,
        creds: &PersistedCredentials,
        metrics: SystemMetrics,
        docker: Vec<ContainerInfo>,
        ip: Option<String>,
    ) -> Result<(), String> {
        let url = format!("{}/api/v1/nodes/heartbeat", creds.master_url.trim_end_matches('/'));
        let payload = HeartbeatPayload {
            node_id: creds.node_id.clone(),
            reported_at: Utc::now().to_rfc3339(),
            ip_address: ip,
            system: metrics,
            docker,
        };

        let res = self
            .client
            .post(&url)
            .header("X-Node-ID", &creds.node_id)
            .header("X-Node-Secret", &creds.node_secret)
            .json(&payload)
            .send()
            .await
            .map_err(|e| format!("Heartbeat failed to send: {}", e))?;

        if !res.status().is_success() {
            let status = res.status();
            return Err(format!("Master returned HTTP {}", status));
        }

        Ok(())
    }
}
