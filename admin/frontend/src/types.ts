export interface Scene {
  id: number;
  name: string;
  order_index: number;
  enabled: boolean;
  source_mode: "camera" | "scare_video";
  effect: "xray" | "thermal" | "contour" | "posterize";
  params: Record<string, number>;
  overlay_hash: string | null;
  scale: number;
  position: [number, number];
  canvas_size: [number, number] | null;
  source_scale: number;
  source_position: [number, number];
  trigger_type: "always" | "motion" | "schedule";
  trigger_from: string | null;
  trigger_until: string | null;
}

export interface ScareConfig {
  enabled_hashes: string[];
}

export interface MediaItem {
  hash: string;
  filename: string;
  category: "mirror_overlay" | "scare_audio" | "mirror_scare_video";
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

export interface AppSettings {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  ha_url: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mirror_camera_source: string;
  mqtt_pass_set: boolean;
  ha_token_set: boolean;
}

export interface AppSettingsUpdate {
  mqtt_host: string;
  mqtt_port: number;
  mqtt_user: string;
  mqtt_pass?: string;
  ha_url: string;
  ha_token?: string;
  mirror_stream_url: string;
  mqtt_topic_prefix: string;
  mirror_camera_source: string;
}
