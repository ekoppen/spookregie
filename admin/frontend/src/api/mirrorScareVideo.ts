import { apiFetch } from "./client";
import type { ScareConfig } from "../types";

export function getMirrorScareVideoConfig(): Promise<ScareConfig> {
  return apiFetch<ScareConfig>("/api/mirror/scare-video-config");
}

export function putMirrorScareVideoConfig(config: ScareConfig): Promise<void> {
  return apiFetch("/api/mirror/scare-video-config", {
    method: "PUT",
    body: JSON.stringify(config),
  });
}
