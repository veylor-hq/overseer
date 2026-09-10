mod client;
mod config;
mod docker;
mod system;

use clap::Parser;
use client::MasterClient;
use config::{CliArgs, PersistedCredentials};
use std::path::Path;
use std::time::Duration;
use tokio::time::sleep;
use tracing::{error, info, warn};

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let args = CliArgs::parse();

    info!("Starting Veylor Overseer Node Agent (Strictly Read-Only Monitoring)");

    let http_client = MasterClient::new();

    // Check if node needs one-time activation
    let mut creds = PersistedCredentials::load(&args.cred_file);

    if creds.is_none() {
        if let Some(token) = args.token.as_ref() {
            info!("No saved credentials found. Initiating one-time node activation...");
            let initial_metrics = system::collect_system_metrics();
            let primary_ip = system::get_primary_ip();

            match http_client
                .activate(
                    &args.url,
                    token,
                    &initial_metrics,
                    primary_ip.as_deref(),
                )
                .await
            {
                Ok(new_creds) => {
                    match new_creds.save(&args.cred_file) {
                        Ok(saved_path) => {
                            info!("Credentials secured at {:?}", saved_path);
                        }
                        Err(e) => {
                            warn!("Could not persist credentials to disk: {}", e);
                        }
                    }
                    creds = Some(new_creds);
                }
                Err(e) => {
                    error!("Activation failed: {}", e);
                    std::process::exit(1);
                }
            }
        } else {
            error!(
                "Node is not activated and no --token provided. Run with --token <ACTIVATION_TOKEN>"
            );
            std::process::exit(1);
        }
    }

    let credentials = creds.expect("Credentials must be present to operate");
    info!(
        "Node authenticated [Node ID: {}]. Target Master: {}",
        credentials.node_id, credentials.master_url
    );

    if args.activate {
        info!("Activation mode completed successfully.");
        return;
    }

    // Telemetric Inbound-Only Loop
    // CRITICAL SECURITY INVARIANT:
    // The node NEVER listens on a port, NEVER executes commands received from Master,
    // and ONLY pushes local metrics outbound to Master.
    let interval = Duration::from_secs(args.interval.max(10));
    info!("Entering periodic heartbeat loop (every {}s)...", interval.as_secs());

    loop {
        let metrics = system::collect_system_metrics();
        let docker_state = docker::inspect_local_docker().await;
        let ip_address = system::get_primary_ip();

        match http_client
            .send_heartbeat(&credentials, metrics, docker_state, ip_address)
            .await
        {
            Ok(_) => {
                info!("Heartbeat ACK received from Master.");
            }
            Err(e) => {
                warn!("Heartbeat warning: {}. Will retry next interval.", e);
            }
        }

        sleep(interval).await;
    }
}
