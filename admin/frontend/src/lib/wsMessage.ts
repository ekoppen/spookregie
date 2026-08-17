import type { LogEntry } from "../types";

export function parseLogPayload(payload: string): LogEntry | null {
  try {
    const data = JSON.parse(payload);
    if (typeof data !== "object" || data === null || Array.isArray(data)) {
      return null;
    }
    return {
      node: "", // wordt door de aanroeper ingevuld vanuit het topic, zie useWebSocket
      ts: data.ts,
      level: data.level,
      msg: data.msg,
    };
  } catch {
    return null;
  }
}
