import { apiFetch, ApiError } from "./http.service";

// ── Types ─────────────────────────────────────────────────────────────

export interface EpisodicRow {
  point_id: string;
  score: number;
  created_at: number | null;
  fact: string;
  entity_tags: string[];
  emotion: Record<string, number>;
  valence: number;
  source_turn_ts: number;
  source_role: string;
  confidence: number;
}

export interface AuditRow {
  id: number;
  key_path: string;
  old_value: unknown;
  new_value: unknown;
  source_turn_ts: number | null;
  confidence: number | null;
  reason: string | null;
  created_at: string;
}

export interface ProfileResponse {
  data: Record<string, unknown>;
  size_bytes: number;
}

export interface EpisodicUpsertBody {
  fact: string;
  entity_tags?: string[];
  emotion?: Partial<Record<
    | "joy" | "trust" | "fear" | "surprise"
    | "sadness" | "disgust" | "anger" | "anticipation",
    number
  >>;
  source_turn_ts?: number;
  source_role?: "user" | "assistant" | "manual";
  confidence?: number;
}

/** Backwards-compat alias — existing call sites import MemoryApiError. */
export class MemoryApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`Memory API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await apiFetch<T>(path, init);
  } catch (e) {
    if (e instanceof ApiError) {
      const d = e.detail as { detail?: { error?: string } | string } | string;
      let msg = e.message;
      if (typeof d === "object" && d !== null) {
        const inner = (d as { detail?: unknown }).detail;
        if (typeof inner === "string") msg = inner;
        else if (inner && typeof inner === "object" && "error" in (inner as object)) {
          msg = String((inner as { error: unknown }).error);
        }
      }
      throw new MemoryApiError(e.status, msg);
    }
    throw e;
  }
}

// ── Profile ───────────────────────────────────────────────────────────

export const memoryApi = {
  async getProfile(): Promise<ProfileResponse> {
    return request("/api/memory/profile");
  },

  async changeProfile(
    key_path: string,
    new_value: unknown,
    reason = "manual edit",
  ): Promise<{ ok: true; key_path: string }> {
    return request("/api/memory/profile/change", {
      method: "POST",
      body: JSON.stringify({ key_path, new_value, reason }),
    });
  },

  async deleteProfileKey(
    key_path: string,
    reason = "manual delete",
  ): Promise<{ ok: true; key_path: string }> {
    return request("/api/memory/profile/change", {
      method: "POST",
      body: JSON.stringify({ key_path, new_value: null, reason }),
    });
  },

  async getProfileHistory(
    key: string,
    limit = 50,
  ): Promise<{ key_path: string; rows: AuditRow[] }> {
    return request(`/api/memory/profile/history?key=${encodeURIComponent(key)}&limit=${limit}`);
  },

  async getAudit(limit = 50): Promise<{ rows: AuditRow[] }> {
    return request(`/api/memory/profile/audit?limit=${limit}`);
  },

  async restore(
    audit_id: number,
    reason?: string,
  ): Promise<{ ok: true; new_row: AuditRow }> {
    return request("/api/memory/profile/restore", {
      method: "POST",
      body: JSON.stringify({ audit_id, reason }),
    });
  },

  // ── Episodic ────────────────────────────────────────────────────────

  async getEpisodicRecent(limit = 50): Promise<{ rows: EpisodicRow[] }> {
    return request(`/api/memory/episodic/recent?limit=${limit}`);
  },

  async searchEpisodic(
    q: string,
    top_k = 20,
  ): Promise<{ query: string; hits: EpisodicRow[] }> {
    return request(`/api/memory/episodic/search?q=${encodeURIComponent(q)}&top_k=${top_k}`);
  },

  async upsertEpisodic(
    body: EpisodicUpsertBody,
  ): Promise<{ ok: true; point_id: string }> {
    return request("/api/memory/episodic/upsert", {
      method: "POST",
      body: JSON.stringify(body),
    });
  },

  async deleteEpisodic(point_id: string): Promise<{ ok: true; point_id: string }> {
    return request(`/api/memory/episodic/${encodeURIComponent(point_id)}`, {
      method: "DELETE",
    });
  },
};
