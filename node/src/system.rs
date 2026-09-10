use serde::{Deserialize, Serialize};
use sysinfo::{CpuRefreshKind, Disks, MemoryRefreshKind, RefreshKind, System};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SystemMetrics {
    pub hostname: String,
    pub os: String,
    pub arch: String,
    pub cpu_usage: f32,
    pub memory_used: u64,
    pub memory_total: u64,
    pub disk_used: u64,
    pub disk_total: u64,
    pub uptime_seconds: u64,
}

pub fn collect_system_metrics() -> SystemMetrics {
    let mut sys = System::new_with_specifics(
        RefreshKind::new()
            .with_cpu(CpuRefreshKind::everything())
            .with_memory(MemoryRefreshKind::everything()),
    );

    // Initial sleep to get accurate differential CPU load
    std::thread::sleep(std::time::Duration::from_millis(200));
    sys.refresh_cpu();
    sys.refresh_memory();

    let cpu_usage = sys.global_cpu_info().cpu_usage();
    let memory_used = sys.used_memory();
    let memory_total = sys.total_memory();

    let disks = Disks::new_with_refreshed_list();
    let mut disk_used = 0u64;
    let mut disk_total = 0u64;
    for disk in &disks {
        disk_total += disk.total_space();
        disk_used += disk.total_space().saturating_sub(disk.available_space());
    }

    let hostname = System::host_name().unwrap_or_else(|| "unknown-host".into());
    let os = System::name().unwrap_or_else(|| "Linux".into());
    let arch = std::env::consts::ARCH.to_string();
    let uptime_seconds = System::uptime();

    SystemMetrics {
        hostname,
        os,
        arch,
        cpu_usage,
        memory_used,
        memory_total,
        disk_used,
        disk_total,
        uptime_seconds,
    }
}

pub fn get_primary_ip() -> Option<String> {
    local_ip_address::local_ip().ok().map(|ip| ip.to_string())
}
