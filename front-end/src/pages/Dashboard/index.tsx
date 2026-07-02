import { useDashboardContext } from "@Shore/contexts/DashboardContext";
import type {
  ServiceRow, DatabaseRow, Hardware, WorkersState, RemoteHardware, GpuInfo,
  AiComponentStatus,
} from "@Shore/services/dashboard.service";
import { ServiceLogo } from "./serviceLogos";
import ServiceControlButton from "./ServiceControlButton";
import "./dashboard-mobile.css";

// ── Helpers ───────────────────────────────────────────────────────────

function statusIsUp(s: string) {
  return s === "up" || s === "loaded" || s === "ok";
}

function fmtUptime(s: number | null): string {
  if (s == null) return "—";
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtTime(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function fmtRelative(ts: number | null): string {
  if (!ts) return "—";
  const diff = Date.now() / 1000 - ts;
  if (diff < 60) return `${Math.round(diff)}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
  return `${Math.round(diff / 86400)}d ago`;
}

// ── Primitives ────────────────────────────────────────────────────────

function Card({ children, accent = false, minHeight, style, className }: { children: React.ReactNode; accent?: boolean; minHeight?: number; style?: React.CSSProperties; className?: string }) {
  return (
    <div className={className} style={{
      background: "var(--md-surface)",
      border: "1px solid var(--md-outline-variant)",
      borderLeft: accent ? "3px solid var(--md-secondary)" : "1px solid var(--md-outline-variant)",
      borderRadius: 12,
      boxShadow: "0 1px 3px rgba(0,0,0,0.07)",
      padding: 20,
      minHeight,
      ...style,
    }}>
      {children}
    </div>
  );
}

function Bar({ pct, color }: { pct: number; color?: string }) {
  const c = color ?? (pct >= 90 ? "var(--md-error)" : pct >= 70 ? "#e67700" : "var(--md-secondary)");
  return (
    <div style={{ height: 4, background: "var(--md-outline-variant)", borderRadius: 2, overflow: "hidden", marginTop: 6 }}>
      <div style={{ height: "100%", width: `${Math.min(100, Math.max(0, pct))}%`, background: c, borderRadius: 2, transition: "width 300ms ease" }} />
    </div>
  );
}

const CPU_BARS = 28;

function CpuBarChart({ history, height = 48 }: { history: number[]; height?: number }) {
  const bars = history.slice(-CPU_BARS);
  const padded = [...Array(CPU_BARS - bars.length).fill(null), ...bars];
  return (
    <div style={{
      height, marginTop: 8,
      background: "rgba(0,90,193,0.06)",
      borderRadius: 6,
      display: "flex", alignItems: "flex-end", gap: 2,
      padding: "4px 4px 0",
      overflow: "hidden",
    }}>
      {padded.map((v, i) => (
        <div key={i} style={{
          flex: 1,
          height: v == null ? "2px" : `${Math.max(3, v)}%`,
          background: v == null ? "var(--md-outline-variant)" : "var(--md-primary)",
          borderRadius: "2px 2px 0 0",
          opacity: v == null ? 0.3 : 1,
          transition: "height 400ms ease",
        }} />
      ))}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; dot: string; label: string }> = {
    up:       { bg: "rgba(0,109,75,0.12)",  dot: "#006d4b", label: "UP" },
    loaded:   { bg: "rgba(0,109,75,0.12)",  dot: "#006d4b", label: "UP" },
    ok:       { bg: "rgba(0,109,75,0.12)",  dot: "#006d4b", label: "UP" },
    down:     { bg: "rgba(186,26,26,0.12)", dot: "#ba1a1a", label: "DOWN" },
    disabled: { bg: "rgba(68,71,78,0.10)",  dot: "#44474e", label: "DISABLED" },
    degraded: { bg: "rgba(230,140,0,0.12)", dot: "#9a6700", label: "DEGRADED" },
  };
  const c = map[status] ?? map.down;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 9999,
      background: c.bg, color: c.dot,
      fontSize: 11, fontWeight: 700, fontFamily: "Inter, sans-serif",
      letterSpacing: 0.3, whiteSpace: "nowrap",
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: c.dot, flexShrink: 0 }} />
      {c.label}
    </span>
  );
}

function SectionLabel({
  title, badge, badgeVariant = "primary",
}: { title: string; badge?: string; badgeVariant?: "primary" | "secondary" | "error" | "gray" }) {
  const v = {
    primary:   { bg: "var(--md-primary-container)",   color: "var(--md-primary)" },
    secondary: { bg: "var(--md-secondary-container)", color: "var(--md-secondary)" },
    error:     { bg: "var(--md-error-container)",     color: "var(--md-error)" },
    gray:      { bg: "rgba(68,71,78,0.08)",           color: "var(--md-on-surface-variant)" },
  }[badgeVariant];
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
      <span style={{
        fontFamily: "Hanken Grotesk, sans-serif",
        fontSize: 11, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: 1.2,
        color: "var(--md-on-surface-variant)",
      }}>
        {title}
      </span>
      {badge && (
        <span style={{
          padding: "2px 8px", borderRadius: 9999,
          background: v.bg, color: v.color,
          fontSize: 11, fontWeight: 600, fontFamily: "Inter, sans-serif",
        }}>
          {badge}
        </span>
      )}
    </div>
  );
}

const GRID3: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 24 };
const GRID6: React.CSSProperties = { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(0, 200px))", gap: 16 };

// ── Service cards ─────────────────────────────────────────────────────

function ServiceCard({ s, expedite }: { s: ServiceRow; expedite: () => void }) {
  const lines = [
    s.latency_ms != null && `${s.latency_ms} ms`,
    s.model,
    s.workflows_count != null && `${s.workflows_count} workflows`,
    s.sessions_count != null && `${s.sessions_count} session${s.sessions_count === 1 ? "" : "s"}`,
  ].filter(Boolean) as string[];

  return (
    <Card className="service-card" style={{ aspectRatio: "1", position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 8, padding: 16, paddingTop: 36 }}>
      {s.control && (
        <div style={{ position: "absolute", top: 10, left: 10 }}>
          <ServiceControlButton control={s.control} expedite={expedite} displayName={s.name} />
        </div>
      )}
      <div style={{ position: "absolute", top: 10, right: 10 }}>
        <StatusBadge status={s.status} />
      </div>
      <ServiceLogo name={s.name} />
      <div className="service-card-info" style={{ display: "flex", flexDirection: "column", gap: 2, width: "100%", overflow: "hidden" }}>
        <span style={{ fontFamily: "Inter, sans-serif", fontSize: 13, fontWeight: 600, color: "var(--md-on-surface)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {s.name}
        </span>
        {lines.map((l, i) => (
          <span key={i} style={{ fontFamily: "Inter, sans-serif", fontSize: 11, color: "var(--md-on-surface-variant)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {l}
          </span>
        ))}
      </div>
    </Card>
  );
}

// ── Database cards ────────────────────────────────────────────────────

function DbCard({ d, expedite }: { d: DatabaseRow; expedite: () => void }) {
  const metric =
    d.short_term_turns != null ? `${d.short_term_turns} turns`
    : d.profile_size_bytes != null ? `${fmtBytes(d.profile_size_bytes)} profile`
    : d.episodic_count != null ? `${d.episodic_count} facts`
    : null;
  const pct = d.status === "up" ? 55 : d.status === "degraded" ? 70 : 15;

  return (
    <Card accent minHeight={120}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 14, fontWeight: 600, color: "var(--md-on-surface)", marginBottom: 2, display: "flex", alignItems: "center", gap: 8 }}>
            {d.name}
            {d.control && (
              <ServiceControlButton control={d.control} expedite={expedite} displayName={d.name} />
            )}
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
            {d.latency_ms != null ? `Latency: ${d.latency_ms} ms` : "—"}
            {metric && ` · ${metric}`}
          </div>
        </div>
        <ServiceLogo name={d.name} />
      </div>
      <Bar pct={pct} color="var(--md-secondary)" />
    </Card>
  );
}

// ── Hardware tiles ────────────────────────────────────────────────────

const LABEL_STYLE: React.CSSProperties = {
  fontFamily: "Hanken Grotesk, sans-serif",
  fontSize: 10, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: 1,
  color: "var(--md-on-surface-variant)",
  marginBottom: 8,
};

const MONO_LG: React.CSSProperties = {
  fontFamily: "JetBrains Mono, monospace",
  fontSize: 20, fontWeight: 500,
  color: "var(--md-on-surface)",
};

function AiComponentsSection({ components }: { components: AiComponentStatus[] }) {
  if (!components.length) return null;
  return (
    <div style={{ marginBottom: 24 }}>
      <SectionLabel title="AI Components" />
      <div className="dash-grid3" style={GRID3}>
        {components.map(c => (
          <Card key={c.name}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <span style={{
                fontFamily: "Inter, sans-serif",
                fontSize: 14,
                fontWeight: 700,
                color: "var(--md-on-surface)",
                textTransform: "uppercase",
              }}>
                {c.name}
              </span>
              <StatusBadge status={c.loaded ? "loaded" : "down"} />
            </div>
            <div style={{
              fontFamily: "Inter, sans-serif",
              fontSize: 12,
              color: "var(--md-on-surface-variant)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {c.detail || "—"}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function HardwareTiles({ h, cpuHistory }: { h: Hardware; cpuHistory?: number[] }) {
  return (
    <>
      <div className="hw-tile" style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Card style={{ flex: 1 }}>
          <div style={LABEL_STYLE}>CPU</div>
          <div style={MONO_LG}>{h.cpu_pct != null ? `${h.cpu_pct.toFixed(0)}%` : "—"}</div>
          {cpuHistory && cpuHistory.length > 0
            ? <CpuBarChart history={cpuHistory} />
            : h.cpu_pct != null && <Bar pct={h.cpu_pct} color="var(--md-primary)" />}
        </Card>
      </div>
      <div className="hw-tile" style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Card style={{ flex: 1 }}>
          <div style={LABEL_STYLE}>RAM</div>
          <div>
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 18, fontWeight: 500, color: "var(--md-primary)" }}>
              {h.ram_used_gb ?? "—"}
            </span>
            <span style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
              {" "}/ {h.ram_total_gb ?? "—"} GB
            </span>
          </div>
          {h.ram_pct != null && <Bar pct={h.ram_pct} color="var(--md-primary)" />}
        </Card>
      </div>
      <div className="hw-tile" style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Card style={{ flex: 1 }}>
          <div style={LABEL_STYLE}>Disk</div>
          <div style={MONO_LG}>{h.disk_free_gb != null ? `${h.disk_free_gb} GB` : "—"}</div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 11, color: "var(--md-on-surface-variant)", marginTop: 2 }}>free</div>
          {h.disk_pct != null && <Bar pct={h.disk_pct} />}
        </Card>
      </div>
      <div className="hw-tile" style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column" }}>
        <Card style={{ flex: 1 }}>
          <div style={LABEL_STYLE}>Uptime</div>
          <div style={MONO_LG}>{fmtUptime(h.uptime_seconds)}</div>
        </Card>
      </div>
    </>
  );
}

function GpuCard({ g, utilHistory, style }: { g: GpuInfo; utilHistory?: number[]; style?: React.CSSProperties }) {
  const vramPct = g.vram_total_mb > 0 ? (g.vram_used_mb / g.vram_total_mb) * 100 : 0;
  const vramColor = vramPct >= 90 ? "var(--md-error)" : "var(--md-primary)";

  return (
    <Card style={style}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
        <div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 15, fontWeight: 700, color: "var(--md-on-surface)" }}>{g.name}</div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 11, color: "var(--md-on-surface-variant)", marginTop: 2 }}>NVIDIA GPU</div>
        </div>
        {g.temp_c > 0 && (
          <span style={{
            padding: "3px 9px", borderRadius: 9999,
            background: g.temp_c >= 80 ? "var(--md-error-container)" : "rgba(230,140,0,0.12)",
            color: g.temp_c >= 80 ? "var(--md-error)" : "#9a6700",
            fontFamily: "Inter, sans-serif", fontSize: 12, fontWeight: 600,
          }}>
            {g.temp_c}°C
          </span>
        )}
      </div>

      <div style={{ marginBottom: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={LABEL_STYLE}>VRAM Allocation</span>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 500, color: vramColor }}>
            {vramPct.toFixed(0)}%
          </span>
        </div>
        <Bar pct={vramPct} color={vramColor} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4 }}>
          <span style={{ fontFamily: "Inter, sans-serif", fontSize: 11, color: "var(--md-on-surface-variant)" }}>
            {(g.vram_used_mb / 1024).toFixed(1)} GB
          </span>
          <span style={{ fontFamily: "Inter, sans-serif", fontSize: 11, color: "var(--md-on-surface-variant)" }}>
            {(g.vram_total_mb / 1024).toFixed(1)} GB
          </span>
        </div>
      </div>

      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 2 }}>
          <div style={LABEL_STYLE}>Compute Util</div>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 500, color: "var(--md-on-surface)" }}>
            {g.util_pct.toFixed(0)}%
          </span>
        </div>
        {utilHistory && utilHistory.length > 0
          ? <CpuBarChart history={utilHistory} height={80} />
          : <Bar pct={g.util_pct} color="var(--md-primary)" />}
      </div>
    </Card>
  );
}

// ── Hardware sections ─────────────────────────────────────────────────


const MACHINE_LABEL_STYLE: React.CSSProperties = {
  fontFamily: "Hanken Grotesk, sans-serif",
  fontSize: 11, fontWeight: 700,
  textTransform: "uppercase", letterSpacing: 1.2,
  color: "var(--md-on-surface-variant)",
};

function HardwareSection({ local, remote, localCpuHistory, gpuUtilHistory }: { local: Hardware; remote: RemoteHardware | null; localCpuHistory: number[]; gpuUtilHistory: number[] }) {
  const hasLocalGpu = local.gpu.length > 0;
  const remoteGpus = remote?.hardware?.gpu ?? [];
  const hasGpu = hasLocalGpu || remoteGpus.length > 0;
  const hasRemote = remote != null;
  // GPU spans: row 2 (local tiles) through row 4 (remote tiles) when remote exists, else just row 2
  const gpuRowSpan = hasRemote ? "2 / 5" : "2 / 3";

  return (
    <div className="hw-section-grid" style={{
      display: "grid",
      gridTemplateColumns: hasGpu ? "1fr 260px" : "1fr",
      columnGap: 16,
      marginBottom: 24,
    }}>
      {/* Row 1 — Local Luna label */}
      <div style={{ gridColumn: 1, gridRow: 1, display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <span style={MACHINE_LABEL_STYLE}>Local Luna</span>
      </div>
      {hasGpu && (
        <div className="hw-gpu-label" style={{ gridColumn: 2, gridRow: 1, display: "flex", alignItems: "center", marginBottom: 14 }}>
          <span style={MACHINE_LABEL_STYLE}>GPU Performance</span>
        </div>
      )}

      {/* Row 2 — Local Luna tiles */}
      <div className="hw-tiles-row" style={{ gridColumn: 1, gridRow: 2, display: "flex", gap: 24, alignItems: "stretch" }}>
        <HardwareTiles h={local} cpuHistory={localCpuHistory} />
      </div>

      {/* GPU card — spans rows 2→4 (or just row 2 if no remote) */}
      {hasGpu && (
        <div className="hw-gpu-col" style={{ gridColumn: 2, gridRow: gpuRowSpan, display: "flex", flexDirection: "column", gap: 16 }}>
          {hasLocalGpu && <GpuCard g={local.gpu[0]} utilHistory={gpuUtilHistory} style={{ flex: 1 }} />}
          {remoteGpus.map((gpu, index) => (
            <div key={`${remote?.name ?? "Remote"}-${gpu.name}-${index}`} style={{ display: "flex", flexDirection: "column", gap: 6, flex: hasLocalGpu ? "0 1 auto" : 1, minHeight: 0 }}>
              <span style={{ ...MACHINE_LABEL_STYLE, fontSize: 10 }}>{remote?.name ?? "Remote"}</span>
              <GpuCard g={gpu} utilHistory={index === 0 ? gpuUtilHistory : undefined} style={{ flex: 1 }} />
            </div>
          ))}
        </div>
      )}

      {/* Row 3 — Remote label */}
      {hasRemote && (
        <div style={{ gridColumn: 1, gridRow: 3, display: "flex", alignItems: "center", gap: 8, marginTop: 16, marginBottom: 14 }}>
          <span style={MACHINE_LABEL_STYLE}>{remote!.name}</span>
          <StatusBadge status={remote!.status} />
        </div>
      )}

      {/* Row 4 — Remote tiles */}
      {hasRemote && (
        <div className="hw-tiles-row" style={{ gridColumn: 1, gridRow: 4, display: "flex", gap: 24, alignItems: "stretch" }}>
          {remote!.status === "down" || !remote!.hardware ? (
            <Card>
              <span style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)", fontStyle: "italic" }}>
                {remote!.last_error || "Remote unreachable. Check the hardware probe configuration."}
              </span>
            </Card>
          ) : (
            <HardwareTiles h={remote!.hardware} />
          )}
        </div>
      )}
    </div>
  );
}

// ── Workers section ───────────────────────────────────────────────────

function WorkersSection({ w, expedite }: { w: WorkersState; expedite: () => void }) {
  const locomoStatus = !w.locomo.enabled ? "disabled" : w.locomo.locked ? "degraded" : "up";
  return (
    <div style={{ marginBottom: 24 }}>
      <SectionLabel title="Workers" />
      <div className="dash-grid3" style={GRID3}>
        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontFamily: "Inter, sans-serif", fontSize: 14, fontWeight: 600, color: "var(--md-on-surface)" }}>LOCOMO worker</span>
              {w.locomo.control && (
                <ServiceControlButton control={w.locomo.control} expedite={expedite} displayName="LOCOMO worker" />
              )}
            </div>
            <StatusBadge status={locomoStatus} />
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
            {!w.locomo.enabled ? "disabled" : w.locomo.locked ? "extracting…" : "idle"}
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)", marginTop: 4 }}>
            last: {fmtRelative(w.locomo.last_extracted_ts)}
            {w.locomo.unprocessed_count != null && ` · queue ${w.locomo.unprocessed_count}`}
          </div>
        </Card>

        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <span style={{ fontFamily: "Inter, sans-serif", fontSize: 14, fontWeight: 600, color: "var(--md-on-surface)" }}>Scheduler</span>
            <span style={{
              padding: "2px 8px", borderRadius: 9999,
              background: "var(--md-primary-container)", color: "var(--md-primary)",
              fontSize: 11, fontWeight: 600, fontFamily: "Inter, sans-serif",
            }}>
              {w.scheduler.active_tasks} active
            </span>
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
            next: {w.scheduler.next_fire_at ? fmtTime(w.scheduler.next_fire_at) : "—"}
          </div>
          {w.scheduler.next_fire_label && (
            <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)", marginTop: 4, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {w.scheduler.next_fire_label}
            </div>
          )}
        </Card>

        <Card>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontFamily: "Inter, sans-serif", fontSize: 14, fontWeight: 600, color: "var(--md-on-surface)" }}>Canonicalizer</span>
              {w.canonicalizer.control && (
                <ServiceControlButton control={w.canonicalizer.control} expedite={expedite} displayName="Canonicalizer" />
              )}
            </div>
            <StatusBadge status={w.canonicalizer.enabled ? "up" : "disabled"} />
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
            {w.canonicalizer.enabled ? "enabled" : "disabled"} · cron <code style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11 }}>{w.canonicalizer.cron}</code>
          </div>
          <div style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)", marginTop: 4 }}>
            threshold {w.canonicalizer.similarity_threshold}
          </div>
        </Card>
      </div>
    </div>
  );
}

// ── Skeleton ──────────────────────────────────────────────────────────

function SkeletonBlock({ width, height, style }: {
  width?: string | number;
  height?: string | number;
  style?: React.CSSProperties;
}) {
  return (
    <div className="skeleton-shimmer" style={{ width: width ?? "100%", height: height ?? 14, ...style }} />
  );
}

function SkeletonHardwareSection() {
  return (
    <div className="hw-section-grid" style={{ display: "grid", gridTemplateColumns: "1fr 260px", columnGap: 16, marginBottom: 24 }}>
      <div style={{ gridColumn: 1, gridRow: 1, display: "flex", alignItems: "center", marginBottom: 14 }}>
        <SkeletonBlock width={80} height={11} />
      </div>
      <div className="hw-gpu-label" style={{ gridColumn: 2, gridRow: 1, display: "flex", alignItems: "center", marginBottom: 14 }}>
        <SkeletonBlock width={120} height={11} />
      </div>

      <div className="hw-tiles-row" style={{ gridColumn: 1, gridRow: 2, display: "flex", gap: 24, alignItems: "stretch" }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="hw-tile" style={{ flex: "1 1 0", minWidth: 0, display: "flex", flexDirection: "column" }}>
            <Card style={{ flex: 1 }}>
              <SkeletonBlock width={36} height={10} style={{ marginBottom: 10 }} />
              <SkeletonBlock width="55%" height={22} style={{ marginBottom: 6 }} />
              <SkeletonBlock height={4} style={{ borderRadius: 2, marginTop: 8 }} />
            </Card>
          </div>
        ))}
      </div>

      <div className="hw-gpu-col" style={{ gridColumn: 2, gridRow: "2 / 3", display: "flex", flexDirection: "column" }}>
        <Card style={{ flex: 1 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 14 }}>
            <div style={{ flex: 1 }}>
              <SkeletonBlock width="70%" height={15} style={{ marginBottom: 6 }} />
              <SkeletonBlock width={40} height={10} />
            </div>
            <SkeletonBlock width={40} height={22} style={{ borderRadius: 9999, marginLeft: 12 }} />
          </div>
          <SkeletonBlock width="60%" height={10} style={{ marginBottom: 8 }} />
          <SkeletonBlock height={4} style={{ borderRadius: 2, marginBottom: 12 }} />
          <SkeletonBlock width="60%" height={10} style={{ marginBottom: 8 }} />
          <SkeletonBlock height={80} style={{ borderRadius: 6, marginTop: 4 }} />
        </Card>
      </div>
    </div>
  );
}

function SkeletonServiceCard() {
  return (
    <Card className="service-card" style={{ aspectRatio: "1", position: "relative", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", gap: 8, padding: 16, paddingTop: 36 }}>
      <SkeletonBlock width={44} height={18} style={{ position: "absolute", top: 10, right: 10, borderRadius: 9999 }} />
      <SkeletonBlock width={32} height={32} style={{ borderRadius: "50%" }} />
      <div className="service-card-info" style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%" }}>
        <SkeletonBlock height={13} />
        <SkeletonBlock width="65%" height={11} style={{ margin: "0 auto" }} />
      </div>
    </Card>
  );
}

function SkeletonDbCard() {
  return (
    <Card accent minHeight={120}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
        <div style={{ flex: 1 }}>
          <SkeletonBlock width="55%" height={14} style={{ marginBottom: 6 }} />
          <SkeletonBlock width="80%" height={12} />
        </div>
        <SkeletonBlock width={28} height={28} style={{ borderRadius: "50%", marginLeft: 12, flexShrink: 0 }} />
      </div>
      <SkeletonBlock height={4} style={{ borderRadius: 2, marginTop: 10 }} />
    </Card>
  );
}

function SkeletonWorkerCard() {
  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <SkeletonBlock width="50%" height={14} />
        <SkeletonBlock width={52} height={18} style={{ borderRadius: 9999 }} />
      </div>
      <SkeletonBlock height={12} style={{ marginBottom: 6 }} />
      <SkeletonBlock width="70%" height={12} />
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <SkeletonHardwareSection />

      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <SkeletonBlock width={64} height={11} />
        </div>
        <div className="dash-grid6" style={GRID6}>
          {[0, 1, 2, 3, 4, 5].map(i => <SkeletonServiceCard key={i} />)}
        </div>
      </div>

      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <SkeletonBlock width={72} height={11} />
        </div>
        <div className="dash-grid3" style={GRID3}>
          {[0, 1, 2].map(i => <SkeletonDbCard key={i} />)}
        </div>
      </div>

      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <SkeletonBlock width={56} height={11} />
        </div>
        <div className="dash-grid3" style={GRID3}>
          {[0, 1, 2].map(i => <SkeletonWorkerCard key={i} />)}
        </div>
      </div>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────

function RefreshIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3 12C3 7.03 7.03 3 12 3C14.5 3 16.77 4.02 18.41 5.66M21 12C21 16.97 16.97 21 12 21C9.5 21 7.23 19.98 5.59 18.34M19 3V8H14M5 21V16H10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function PageDashboard() {
  const { data, error, loading, paused, refresh, expedite, localCpuHistory, gpuUtilHistory } = useDashboardContext();

  const activeServices = data?.services.filter(s => statusIsUp(s.status)).length ?? 0;
  const downDbs = data?.databases.filter(d => !statusIsUp(d.status)).length ?? 0;
  const dbBadge = downDbs > 0 ? `${downDbs} DOWN` : "UP";
  const dbBadgeVariant: "error" | "secondary" = downDbs > 0 ? "error" : "secondary";

  return (
    <div style={{ height: "100%", width: "100%", overflow: "hidden", display: "flex", flexDirection: "column" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "12px 20px",
        borderBottom: "1px solid var(--md-outline-variant)",
        background: "var(--md-surface)",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontFamily: "Hanken Grotesk, sans-serif", fontSize: 18, fontWeight: 700, color: "var(--md-on-surface)" }}>
            Dashboard
          </span>
          {paused && (
            <span style={{ padding: "2px 8px", borderRadius: 9999, background: "rgba(68,71,78,0.1)", color: "var(--md-on-surface-variant)", fontSize: 11, fontWeight: 600, fontFamily: "Inter, sans-serif" }}>
              paused
            </span>
          )}
          {data && (
            <span style={{ fontFamily: "Inter, sans-serif", fontSize: 12, color: "var(--md-on-surface-variant)" }}>
              updated {fmtRelative(data.generated_at)}
            </span>
          )}
        </div>
        <button
          onClick={refresh}
          aria-label="Refresh"
          style={{
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            width: 32, height: 32, borderRadius: 8,
            border: "1px solid var(--md-outline-variant)",
            background: "transparent", cursor: "pointer",
            color: "var(--md-on-surface-variant)",
            transition: "background 150ms",
          }}
          onMouseEnter={e => (e.currentTarget.style.background = "rgba(0,0,0,0.05)")}
          onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
        >
          <RefreshIcon />
        </button>
      </div>

      {/* Body */}
      <div className="dash-body" style={{ flex: 1, overflowY: "auto", padding: 20 }}>
        {error && (
          <div style={{
            padding: "10px 14px", borderRadius: 8, marginBottom: 16,
            background: "var(--md-error-container)", color: "var(--md-error)",
            fontFamily: "Inter, sans-serif", fontSize: 13,
            border: "1px solid rgba(186,26,26,0.2)",
          }}>
            Dashboard fetch failed: {error}
          </div>
        )}

        {loading && !data ? (
          <DashboardSkeleton />
        ) : data ? (
          <>
            {/* Hardware: local + remote tiles + GPU */}
            <HardwareSection local={data.hardware} remote={data.remote_hardware} localCpuHistory={localCpuHistory} gpuUtilHistory={gpuUtilHistory} />

            {/* Services */}
            <div style={{ marginBottom: 24 }}>
              <SectionLabel title="Services" badge={`${activeServices} active`} badgeVariant="primary" />
              <div className="dash-grid6" style={GRID6}>
                {data.services.map(s => <ServiceCard key={s.name} s={s} expedite={expedite} />)}
              </div>
            </div>

            <AiComponentsSection components={data.ai_components} />

            {/* Databases */}
            <div style={{ marginBottom: 24 }}>
              <SectionLabel title="Databases" badge={dbBadge} badgeVariant={dbBadgeVariant} />
              <div className="dash-grid3" style={GRID3}>
                {data.databases.map(d => <DbCard key={d.name} d={d} expedite={expedite} />)}
              </div>
            </div>

            {/* Workers */}
            <WorkersSection w={data.workers} expedite={expedite} />
          </>
        ) : null}
      </div>
    </div>
  );
}
