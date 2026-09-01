import { apiFetch } from "./client";
import type { MediaItem } from "../types";

export function listMedia(kind?: string): Promise<MediaItem[]> {
  const query = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  return apiFetch<MediaItem[]>(`/api/media${query}`);
}

export async function uploadMedia(file: File, kind: string): Promise<MediaItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("kind", kind);
  const response = await fetch("/api/media", {
    method: "POST",
    credentials: "include",
    body: formData, // geen Content-Type header zetten: de browser zet zelf de multipart-boundary
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    // Backend stuurt {"detail": "..."} bij een validatiefout (bijv. verkeerd
    // bestandstype) -- die reden moet de gebruiker zien, niet alleen "mislukt".
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed?.detail === "string") detail = parsed.detail;
    } catch {
      /* geen JSON-body, val terug op de ruwe tekst */
    }
    throw new Error(detail || `Upload mislukt (${response.status})`);
  }
  return response.json();
}

export function deleteMedia(hash: string): Promise<void> {
  return apiFetch(`/api/media/${hash}`, { method: "DELETE" });
}
