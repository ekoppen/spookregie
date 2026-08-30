import { apiFetch } from "./client";
import type { Scene } from "../types";

export type SceneDraft = Omit<Scene, "id" | "order_index">;

export function listScenes(): Promise<Scene[]> {
  return apiFetch<Scene[]>("/api/scenes");
}

export function getScene(id: number): Promise<Scene> {
  return apiFetch<Scene>(`/api/scenes/${id}`);
}

export function createScene(scene: SceneDraft): Promise<Scene> {
  return apiFetch<Scene>("/api/scenes", { method: "POST", body: JSON.stringify(scene) });
}

export function updateScene(id: number, scene: SceneDraft): Promise<Scene> {
  return apiFetch<Scene>(`/api/scenes/${id}`, { method: "PUT", body: JSON.stringify(scene) });
}

export function deleteScene(id: number): Promise<void> {
  return apiFetch(`/api/scenes/${id}`, { method: "DELETE" });
}

export function reorderScenes(order: number[]): Promise<void> {
  return apiFetch("/api/scenes/order", { method: "PUT", body: JSON.stringify({ order }) });
}

export function previewScene(id: number, scene: SceneDraft): Promise<void> {
  return apiFetch(`/api/scenes/${id}/preview`, { method: "POST", body: JSON.stringify(scene) });
}
