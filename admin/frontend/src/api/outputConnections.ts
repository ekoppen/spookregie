import { apiFetch } from "./client";
import type { OutputConnection } from "../types";

export function listOutputConnections(): Promise<OutputConnection[]> {
  return apiFetch<OutputConnection[]>("/api/output-connections");
}

export function createOutputConnection(output_id: number, from_branch_id: number): Promise<OutputConnection> {
  return apiFetch<OutputConnection>("/api/output-connections", {
    method: "POST",
    body: JSON.stringify({ output_id, from_branch_id }),
  });
}

export function deleteOutputConnection(id: number): Promise<void> {
  return apiFetch(`/api/output-connections/${id}`, { method: "DELETE" });
}
