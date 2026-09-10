use serde::{Deserialize, Serialize};
use std::path::Path;

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ContainerInfo {
    pub id: String,
    pub name: String,
    pub image: String,
    pub state: String,
    pub status: String,
}

pub async fn inspect_local_docker() -> Vec<ContainerInfo> {
    let socket_path = Path::new("/var/run/docker.sock");
    if !socket_path.exists() {
        return Vec::new();
    }

    // Try executing `docker ps` directly first
    let output = std::process::Command::new("docker")
        .args(["ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.State}}|{{.Status}}"])
        .output();

    let output_bytes = match output {
        Ok(out) if out.status.success() => out.stdout,
        _ => {
            // Fallback: If current user lacks docker group permissions, try `sudo -n docker ps`
            // (-n = non-interactive, only succeeds if passwordless sudo is permitted for docker)
            match std::process::Command::new("sudo")
                .args(["-n", "docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Image}}|{{.State}}|{{.Status}}"])
                .output()
            {
                Ok(sudo_out) if sudo_out.status.success() => sudo_out.stdout,
                _ => return Vec::new(),
            }
        }
    };

    let text = String::from_utf8_lossy(&output_bytes);
    let mut containers = Vec::new();

    for line in text.lines() {
        let parts: Vec<&str> = line.split('|').collect();
        if parts.len() >= 5 {
            containers.push(ContainerInfo {
                id: parts[0].to_string(),
                name: parts[1].to_string(),
                image: parts[2].to_string(),
                state: parts[3].to_string(),
                status: parts[4].to_string(),
            });
        }
    }

    containers
}
