import { apiFetch } from "./client";
import type { MirrorConfig } from "../types";

export function getMirrorConfig(): Promise<MirrorConfig> {
  return apiFetch<MirrorConfig>("/api/mirror/config");
}

export function putMirrorConfig(config: MirrorConfig): Promise<void> {
  return apiFetch("/api/mirror/config", { method: "PUT", body: JSON.stringify(config) });
}

export function previewMirrorConfig(config: MirrorConfig): Promise<void> {
  return apiFetch("/api/mirror/preview", { method: "POST", body: JSON.stringify(config) });
}

export function testMirror(): Promise<void> {
  return apiFetch("/api/mirror/test", { method: "POST" });
}
