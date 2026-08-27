import { apiFetch } from "./client";

export interface MirrorProcessStatus {
  running: boolean;
  pid: number | null;
}

export function startMirrorProcess(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/start", { method: "POST" });
}

export function stopMirrorProcess(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/stop", { method: "POST" });
}

export function getMirrorProcessStatus(): Promise<MirrorProcessStatus> {
  return apiFetch<MirrorProcessStatus>("/api/mirror-node/status");
}
