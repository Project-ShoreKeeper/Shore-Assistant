/**
 * REST client for /api/services — start/stop registered services.
 *
 * Reads via /api/dashboard's per-row `control` field; this client is only
 * needed for the POST actions.
 */
import { apiFetch, ApiError } from "./http.service";

export class ServicesApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(`Services API ${status}: ${detail}`);
    this.status = status;
    this.detail = detail;
  }
}

interface ActionResponse {
  name: string;
  transitioning: boolean;
  action: "start" | "stop";
}

async function _post(path: string): Promise<ActionResponse> {
  try {
    return await apiFetch<ActionResponse>(path, { method: "POST" });
  } catch (e) {
    if (e instanceof ApiError) {
      const d = e.detail as { detail?: { error?: string; message?: string } } | undefined;
      let msg = e.message;
      const inner = d && typeof d === "object" ? d.detail : undefined;
      if (inner && typeof inner === "object") {
        msg = String(inner.message ?? inner.error ?? msg);
      }
      throw new ServicesApiError(e.status, msg);
    }
    throw e;
  }
}

export const servicesApi = {
  start(name: string): Promise<ActionResponse> {
    return _post(`/api/services/${encodeURIComponent(name)}/start`);
  },
  stop(name: string): Promise<ActionResponse> {
    return _post(`/api/services/${encodeURIComponent(name)}/stop`);
  },
};
