import { apiFetch } from "./client";
import type { Source } from "../types";

export type SourceDraft = Omit<Source, "id">;

export function listSources(): Promise<Source[]> {
  return apiFetch<Source[]>("/api/sources");
}

export function getSource(id: number): Promise<Source> {
  return apiFetch<Source>(`/api/sources/${id}`);
}

export function createSource(source: SourceDraft): Promise<Source> {
  return apiFetch<Source>("/api/sources", { method: "POST", body: JSON.stringify(source) });
}

export function updateSource(id: number, source: SourceDraft): Promise<Source> {
  return apiFetch<Source>(`/api/sources/${id}`, { method: "PUT", body: JSON.stringify(source) });
}

export function deleteSource(id: number): Promise<void> {
  return apiFetch(`/api/sources/${id}`, { method: "DELETE" });
}
