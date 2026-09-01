export interface Player {
  id: number;
  name: string;
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
  is_root: boolean;
  canvas_x: number;
  canvas_y: number;
  color: string | null;
  source_id: number | null;
  audio_source_id: number | null;
  playback_mode: "once" | "repeat_once" | "repeat_while";
  repeat_while_ha_entity_id: string | null;
}

export interface PlayerBranch {
  id: number;
  player_id: number;
  name: string;
}

export interface Source {
  id: number;
  name: string;
  kind: "camera_stream" | "static_image" | "video_loop" | "audio";
  value: string;
  canvas_x: number;
  canvas_y: number;
}

export interface Trigger {
  id: number;
  from_branch_id: number;
  to_player_id: number | null;
  kind: "always" | "motion" | "schedule" | "ha_sensor" | null;
  schedule_from: string | null;
  schedule_until: string | null;
  ha_entity_id: string | null;
  priority: number;
  canvas_x: number;
  canvas_y: number;
  name: string | null;
  color: string | null;
}

export interface Output {
  id: number;
  name: string;
  camera_source: string;
  canvas_x: number;
  canvas_y: number;
}

export interface OutputConnection {
  id: number;
  output_id: number;
  from_branch_id: number;
}

export interface Device {
  id: number;
  device_uuid: string;
  name: string;
  platform: string;
  git_sha: string | null;
  last_seen_at: string | null;
  output_id: number | null;
  is_mirror: boolean;
  is_camera: boolean;
  camera_stream_url: string | null;
}

export interface ScareConfig {
  enabled_hashes: string[];
}

export interface MediaItem {
  hash: string;
  filename: string;
  kind: "image" | "audio" | "video";
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
}
