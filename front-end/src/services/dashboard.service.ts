import { apiFetch } from "./http.service";

export interface ServiceRow {
  name: string;
  status: string;
  latency_ms?: number | null;
  model?: string | null;
  workflows_count?: number;
  sessions_count?: number;
}

export interface DatabaseRow {
  name: string;
  status: "up" | "down";
  latency_ms?: number | null;
  short_term_turns?: number | null;
  profile_size_bytes?: number | null;
  episodic_count?: number | null;
}

export interface GpuInfo {
  name: string;
  util_pct: number;
  vram_used_mb: number;
  vram_total_mb: number;
  temp_c: number;
}

export interface Hardware {
  cpu_pct: number | null;
  ram_pct: number | null;
  ram_used_gb: number | null;
  ram_total_gb: number | null;
  disk_pct: number | null;
  disk_free_gb: number | null;
  uptime_seconds: number | null;
  gpu: GpuInfo[];
}

export interface WorkersState {
  locomo: {
    enabled: boolean;
    last_extracted_ts: number | null;
    locked: boolean;
    unprocessed_count: number | null;
  };
  scheduler: {
    active_tasks: number;
    next_fire_at: number | null;
    next_fire_label: string | null;
  };
  canonicalizer: {
    enabled: boolean;
    cron: string;
    similarity_threshold: number;
  };
}

export interface RemoteHardware {
  name: string;
  status: "up" | "down";
  hardware: Hardware | null;
}

export interface DashboardSnapshot {
  generated_at: number;
  services: ServiceRow[];
  databases: DatabaseRow[];
  hardware: Hardware;
  remote_hardware: RemoteHardware | null;
  workers: WorkersState;
}

export async function fetchDashboard(): Promise<DashboardSnapshot> {
  return apiFetch<DashboardSnapshot>("/api/dashboard");
}
