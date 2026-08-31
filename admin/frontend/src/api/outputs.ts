import { apiFetch } from "./client";
import type { Output } from "../types";

export type OutputDraft = Omit<Output, "id">;

export function listOutputs(): Promise<Output[]> {
  return apiFetch<Output[]>("/api/outputs");
}

export function getOutput(id: number): Promise<Output> {
  return apiFetch<Output>(`/api/outputs/${id}`);
}

export function createOutput(output: OutputDraft): Promise<Output> {
  return apiFetch<Output>("/api/outputs", { method: "POST", body: JSON.stringify(output) });
}

export function updateOutput(id: number, output: OutputDraft): Promise<Output> {
  return apiFetch<Output>(`/api/outputs/${id}`, { method: "PUT", body: JSON.stringify(output) });
}

export function deleteOutput(id: number): Promise<void> {
  return apiFetch(`/api/outputs/${id}`, { method: "DELETE" });
}
