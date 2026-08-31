import { apiFetch } from "./client";
import type { Player } from "../types";

export type PlayerDraft = Omit<Player, "id">;

export function listPlayers(): Promise<Player[]> {
  return apiFetch<Player[]>("/api/players");
}

export function getPlayer(id: number): Promise<Player> {
  return apiFetch<Player>(`/api/players/${id}`);
}

export function createPlayer(player: PlayerDraft): Promise<Player> {
  return apiFetch<Player>("/api/players", { method: "POST", body: JSON.stringify(player) });
}

export function updatePlayer(id: number, player: PlayerDraft): Promise<Player> {
  return apiFetch<Player>(`/api/players/${id}`, { method: "PUT", body: JSON.stringify(player) });
}

export function deletePlayer(id: number): Promise<void> {
  return apiFetch(`/api/players/${id}`, { method: "DELETE" });
}

export function updatePlayerPosition(id: number, canvas_x: number, canvas_y: number): Promise<void> {
  return apiFetch(`/api/players/${id}/position`, {
    method: "PUT",
    body: JSON.stringify({ canvas_x, canvas_y }),
  });
}

export function previewPlayer(id: number, player: PlayerDraft): Promise<void> {
  return apiFetch(`/api/players/${id}/preview`, { method: "POST", body: JSON.stringify(player) });
}
