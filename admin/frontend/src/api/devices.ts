import { apiFetch } from "./client";
import type { Device } from "../types";

export interface DeviceUpdate {
  name: string;
  output_id: number | null;
}

export function listDevices(): Promise<Device[]> {
  return apiFetch<Device[]>("/api/devices");
}

export function updateDevice(id: number, update: DeviceUpdate): Promise<Device> {
  return apiFetch<Device>(`/api/devices/${id}`, { method: "PUT", body: JSON.stringify(update) });
}

export function deleteDevice(id: number): Promise<void> {
  return apiFetch(`/api/devices/${id}`, { method: "DELETE" });
}
