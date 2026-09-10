use clap::Parser;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Parser, Debug, Clone)]
#[command(
    name = "overseer-node",
    about = "Veylor Overseer Child Agent - Read-Only Monitoring Daemon"
)]
pub struct CliArgs {
    #[arg(long, env = "OVERSEER_URL", default_value = "http://localhost:8080")]
    pub url: String,

    #[arg(long, env = "OVERSEER_ACTIVATION_TOKEN")]
    pub token: Option<String>,

    #[arg(long, env = "OVERSEER_INTERVAL", default_value = "300")]
    pub interval: u64,

    #[arg(long, default_value = "/etc/overseer/credentials.json")]
    pub cred_file: PathBuf,

    #[arg(long)]
    pub activate: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PersistedCredentials {
    pub node_id: String,
    pub node_secret: String,
    pub master_url: String,
}

impl PersistedCredentials {
    pub fn load(path: &Path) -> Option<Self> {
        if !path.exists() {
            // Check fallback in user home
            if let Some(home) = dirs_home() {
                let home_path = home.join(".overseer/credentials.json");
                if home_path.exists() {
                    return Self::load_file(&home_path);
                }
            }
            return None;
        }
        Self::load_file(path)
    }

    fn load_file(path: &Path) -> Option<Self> {
        let content = fs::read_to_string(path).ok()?;
        serde_json::from_str(&content).ok()
    }

    pub fn save(&self, preferred_path: &Path) -> Result<PathBuf, String> {
        let target_path = if fs::create_dir_all(preferred_path.parent().unwrap_or(Path::new(".")))
            .is_ok()
        {
            preferred_path.to_path_buf()
        } else if let Some(home) = dirs_home() {
            let user_dir = home.join(".overseer");
            fs::create_dir_all(&user_dir)
                .map_err(|e| format!("Failed to create ~/.overseer: {}", e))?;
            user_dir.join("credentials.json")
        } else {
            return Err("Unable to find writable path for node credentials".into());
        };

        let json = serde_json::to_string_pretty(self)
            .map_err(|e| format!("Serialization error: {}", e))?;
        fs::write(&target_path, json).map_err(|e| format!("Write error: {}", e))?;

        // On Unix, enforce 0600 permissions
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let _ = fs::set_permissions(&target_path, fs::Permissions::from_mode(0o600));
        }

        Ok(target_path)
    }
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME").map(PathBuf::from)
}
