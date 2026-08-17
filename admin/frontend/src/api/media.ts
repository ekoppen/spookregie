import { apiFetch } from "./client";
import type { MediaItem } from "../types";

export function listMedia(category?: string): Promise<MediaItem[]> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  return apiFetch<MediaItem[]>(`/api/media${query}`);
}

export async function uploadMedia(file: File, category: string): Promise<MediaItem> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("category", category);
  const response = await fetch("/api/media", {
    method: "POST",
    credentials: "include",
    body: formData, // geen Content-Type header zetten: de browser zet zelf de multipart-boundary
  });
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(text || `Upload mislukt (${response.status})`);
  }
  return response.json();
}

export function deleteMedia(hash: string): Promise<void> {
  return apiFetch(`/api/media/${hash}`, { method: "DELETE" });
}
