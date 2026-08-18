import { apiFetch } from "./client";
import type { ScareConfig } from "../types";

export function getScareConfig(zone: string): Promise<ScareConfig> {
  return apiFetch<ScareConfig>(`/api/scare/${encodeURIComponent(zone)}/config`);
}

export function putScareConfig(zone: string, config: ScareConfig): Promise<void> {
  return apiFetch(`/api/scare/${encodeURIComponent(zone)}/config`, {
    method: "PUT",
    body: JSON.stringify(config),
  });
}

export function testScare(zone: string): Promise<void> {
  return apiFetch(`/api/scare/${encodeURIComponent(zone)}/test`, { method: "POST" });
}
