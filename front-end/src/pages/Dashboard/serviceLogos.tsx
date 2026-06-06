import { useState } from "react";

/**
 * Service / database logos for the dashboard cards.
 *
 * For brands tracked by simple-icons we fetch the official mark from the
 * cdn.simpleicons.org CDN (offline-safe — we fall back to a colored
 * letter tile on load error). For services without a public brand
 * (Kokoro, Whisper-as-Transformers, shore-pty-service, llama-server) we
 * inline a representative generic icon.
 */

type BrandConfig =
  | { kind: "simple-icon"; slug: string; color: string }
  | { kind: "inline"; render: () => React.ReactNode; bg: string };

const LOGOS: Record<string, BrandConfig> = {
  // Services
  "FastAPI":           { kind: "simple-icon", slug: "fastapi",    color: "009688" },
  "llama-server":      { kind: "inline", bg: "#7C3AED", render: LlamaIcon },
  "Whisper STT":       { kind: "inline", bg: "#0EA5E9", render: MicIcon },
  "Kokoro TTS":        { kind: "inline", bg: "#F472B6", render: SpeakerIcon },
  "n8n":               { kind: "simple-icon", slug: "n8n",        color: "EA4B71" },
  "shore-pty-service": { kind: "inline", bg: "#10B981", render: TerminalIcon },

  "FileBrowser":       { kind: "inline", bg: "#2196F3", render: FolderIcon },

  // Databases
  "Redis":             { kind: "simple-icon", slug: "redis",      color: "DC382D" },
  "Postgres":          { kind: "simple-icon", slug: "postgresql", color: "4169E1" },
  "Qdrant":            { kind: "simple-icon", slug: "qdrant",     color: "DC244C" },
};

const SIZE = 40;
const RADIUS = 10;

export function ServiceLogo({ name }: { name: string }) {
  const cfg = LOGOS[name];
  if (!cfg) return <LetterTile name={name} />;
  if (cfg.kind === "inline") {
    return (
      <Box bg={cfg.bg}>
        <span style={{ color: "white", display: "flex" }}>{cfg.render()}</span>
      </Box>
    );
  }
  return <SimpleIconLogo slug={cfg.slug} color={cfg.color} name={name} />;
}

function SimpleIconLogo({ slug, color, name }: { slug: string; color: string; name: string }) {
  const [failed, setFailed] = useState(false);
  if (failed) return <LetterTile name={name} accent={`#${color}`} />;
  return (
    <Box bg={`#${color}1A`}>
      <img
        src={`https://cdn.simpleicons.org/${slug}/${color}`}
        alt=""
        width={24}
        height={24}
        onError={() => setFailed(true)}
        style={{ display: "block" }}
      />
    </Box>
  );
}

function LetterTile({ name, accent }: { name: string; accent?: string }) {
  const letter = name.replace(/[^a-zA-Z]/g, "").slice(0, 1).toUpperCase() || "?";
  const bg = accent ?? hashColor(name);
  return (
    <Box bg={bg}>
      <span style={{ color: "white", fontWeight: 700, fontSize: 12 }}>{letter}</span>
    </Box>
  );
}

function hashColor(s: string): string {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  const palette = ["#6366F1", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899"];
  return palette[Math.abs(h) % palette.length];
}

// ── Layout primitive ───────────────────────────────────────────────────

function Box({ bg, children }: { bg: string; children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: SIZE,
        height: SIZE,
        borderRadius: RADIUS,
        backgroundColor: bg,
        flexShrink: 0,
      }}
    >
      {children}
    </span>
  );
}

// ── Inline generic icons ───────────────────────────────────────────────

function LlamaIcon() {
  // Generic LLM mark: a chip with a sparkle (no llama.cpp official logo)
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="5" y="6" width="14" height="12" rx="2.5" stroke="currentColor" strokeWidth="1.8" />
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 9.5l.9 1.6 1.6.9-1.6.9-.9 1.6-.9-1.6-1.6-.9 1.6-.9z" fill="currentColor" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5 11c0 3.87 3.13 7 7 7s7-3.13 7-7" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M12 18v3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function SpeakerIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M4 9v6h4l5 4V5L8 9H4z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M16 8c1.2 1 2 2.4 2 4s-.8 3-2 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  );
}

function TerminalIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="2.5" y="3.5" width="19" height="16" rx="2" stroke="currentColor" strokeWidth="1.8" />
      <path d="M6 9l3 3-3 3M12 15h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
