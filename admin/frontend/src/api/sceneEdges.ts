import { apiFetch } from "./client";
import type { SceneEdge } from "../types";

export type SceneEdgeDraft = Omit<SceneEdge, "id">;

export function listSceneEdges(): Promise<SceneEdge[]> {
  return apiFetch<SceneEdge[]>("/api/scene-edges");
}

export function createSceneEdge(
  edge: Partial<SceneEdgeDraft> & { from_scene_id: number },
): Promise<SceneEdge> {
  return apiFetch<SceneEdge>("/api/scene-edges", { method: "POST", body: JSON.stringify(edge) });
}

export function updateSceneEdge(id: number, edge: Partial<SceneEdgeDraft>): Promise<SceneEdge> {
  return apiFetch<SceneEdge>(`/api/scene-edges/${id}`, { method: "PUT", body: JSON.stringify(edge) });
}

export function deleteSceneEdge(id: number): Promise<void> {
  return apiFetch(`/api/scene-edges/${id}`, { method: "DELETE" });
}
