import { apiFetch } from "./client";
import type { HaState } from "../types";

export function getHaStates(): Promise<HaState[]> {
  return apiFetch<HaState[]>("/api/ha/states");
}

export function getHaCameraStreamUrl(entityId: string): Promise<{ url: string }> {
  return apiFetch<{ url: string }>(`/api/ha/camera-stream-url/${entityId}`);
}

export function callHaService(
  domain: string,
  service: string,
  data: Record<string, unknown>,
): Promise<void> {
  return apiFetch("/api/ha/service", {
    method: "POST",
    body: JSON.stringify({ domain, service, data }),
  });
}
