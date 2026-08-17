import { apiFetch } from "./client";

export async function login(password: string): Promise<void> {
  await apiFetch<{ ok: boolean }>("/api/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export async function logout(): Promise<void> {
  await apiFetch<{ ok: boolean }>("/api/logout", { method: "POST" });
}
