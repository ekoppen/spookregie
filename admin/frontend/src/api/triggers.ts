import { apiFetch } from "./client";
import type { Trigger } from "../types";

export type TriggerDraft = Omit<Trigger, "id">;

export function listTriggers(): Promise<Trigger[]> {
  return apiFetch<Trigger[]>("/api/triggers");
}

export function createTrigger(
  trigger: Partial<TriggerDraft> & { from_scene_id: number },
): Promise<Trigger> {
  return apiFetch<Trigger>("/api/triggers", { method: "POST", body: JSON.stringify(trigger) });
}

export function updateTrigger(id: number, trigger: Partial<TriggerDraft>): Promise<Trigger> {
  return apiFetch<Trigger>(`/api/triggers/${id}`, { method: "PUT", body: JSON.stringify(trigger) });
}

export function updateTriggerPosition(id: number, canvas_x: number, canvas_y: number): Promise<void> {
  return apiFetch(`/api/triggers/${id}/position`, {
    method: "PUT",
    body: JSON.stringify({ canvas_x, canvas_y }),
  });
}

export function deleteTrigger(id: number): Promise<void> {
  return apiFetch(`/api/triggers/${id}`, { method: "DELETE" });
}
