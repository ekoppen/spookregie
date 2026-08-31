import { apiFetch } from "./client";
import type { PlayerBranch } from "../types";

export function listPlayerBranches(playerId: number): Promise<PlayerBranch[]> {
  return apiFetch<PlayerBranch[]>(`/api/players/${playerId}/branches`);
}

export function createPlayerBranch(playerId: number, name: string): Promise<PlayerBranch> {
  return apiFetch<PlayerBranch>(`/api/players/${playerId}/branches`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function updatePlayerBranch(id: number, name: string): Promise<PlayerBranch> {
  return apiFetch<PlayerBranch>(`/api/branches/${id}`, { method: "PUT", body: JSON.stringify({ name }) });
}

export function deletePlayerBranch(id: number): Promise<void> {
  return apiFetch(`/api/branches/${id}`, { method: "DELETE" });
}
