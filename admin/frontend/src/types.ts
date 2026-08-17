export interface MirrorConfig {
  effect: "xray" | "thermal" | "contour" | "posterize";
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
}

export interface ScareConfig {
  enabled_hashes: string[];
}

export interface MediaItem {
  hash: string;
  filename: string;
  category: "mirror_overlay" | "scare_audio";
  uploaded_at: string;
}

export interface NodeStatusMap {
  [node: string]: { status: "online" | "offline" };
}

export interface LogEntry {
  node: string;
  ts: number;
  level: string;
  msg: string;
}

export interface Schedule {
  on_time: string;
  off_time: string;
  enabled: boolean;
}

export interface HaState {
  entity_id: string;
  state: string;
  [key: string]: unknown;
}

export interface WsMessage {
  type: "status" | "log";
  topic: string;
  payload: string;
}
