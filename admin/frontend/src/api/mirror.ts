import { apiFetch } from "./client";

export function testMirror(): Promise<void> {
  return apiFetch("/api/mirror/test", { method: "POST" });
}
