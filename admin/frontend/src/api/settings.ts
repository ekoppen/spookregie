import { apiFetch } from "./client";
import type { AppSettings, AppSettingsUpdate } from "../types";

export function getSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>("/api/settings");
}

export function putSettings(update: AppSettingsUpdate): Promise<void> {
  return apiFetch("/api/settings", {
    method: "PUT",
    body: JSON.stringify(update),
  });
}
