import { BACKEND_URL } from "@Shore/constants/backend.constant";

export interface ChronicleMeta {
  slug: string;
  version: string | null;
  title: string;
  date: string | null;
  summary: string | null;
}

export interface ChronicleEntry extends ChronicleMeta {
  content: string;
  prev_slug: string | null;
  next_slug: string | null;
}

export async function listChronicles(): Promise<ChronicleMeta[]> {
  const res = await fetch(`${BACKEND_URL}/api/chronicles`);
  if (!res.ok) throw new Error(`Chronicles list ${res.status}`);
  const body = await res.json();
  return body.entries as ChronicleMeta[];
}

export async function getChronicle(slug: string): Promise<ChronicleEntry> {
  const res = await fetch(`${BACKEND_URL}/api/chronicles/${encodeURIComponent(slug)}`);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(`Chronicle ${slug}: ${detail}`);
  }
  return res.json();
}
