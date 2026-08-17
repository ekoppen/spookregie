import { apiFetch } from "./client";
import type { Schedule } from "../types";

export function getSchedule(): Promise<Schedule> {
  return apiFetch<Schedule>("/api/schedule");
}

export function putSchedule(schedule: Schedule): Promise<void> {
  return apiFetch("/api/schedule", { method: "PUT", body: JSON.stringify(schedule) });
}

export function emergencyStop(): Promise<void> {
  return apiFetch("/api/system/emergency-stop", { method: "POST" });
}

export function wake(): Promise<void> {
  return apiFetch("/api/system/wake", { method: "POST" });
}
