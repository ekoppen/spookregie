import { apiFetch } from "./client";
import type { NodeStatusMap, LogEntry } from "../types";

export function getNodes(): Promise<NodeStatusMap> {
  return apiFetch<NodeStatusMap>("/api/nodes");
}

export function getLogs(node?: string, limit = 100): Promise<LogEntry[]> {
  const params = new URLSearchParams();
  if (node) params.set("node", node);
  params.set("limit", String(limit));
  return apiFetch<LogEntry[]>(`/api/logs?${params.toString()}`);
}
