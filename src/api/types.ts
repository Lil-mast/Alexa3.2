/**
 * Wire types. These mirror the Pydantic models in `backend/app/models.py`,
 * the tool manifests in `backend/app/tools/specs.py`, and the console routes in
 * `backend/app/main.py`. If a field is missing on the wire, it is missing here.
 */

export type Decision = "executed" | "previewed" | "refused" | "no_change";
export type Outcome = "ok" | "confirmation_required" | "error";
export type Risk = "low" | "medium" | "high";

export interface Health {
  status: string;
  service: string;
  version: string;
  rules_version: string;
  tools: number;
  audit_rows: number;
  audit_seeded: boolean;
}

export interface WhoAmI {
  subject: string;
  client_id: string;
  scopes: string[];
}

export interface PendingAction {
  tool: string;
  effect: string;
  expires_at: string;
  ttl_seconds: number;
}

export interface AssistantReply {
  understood: boolean;
  status: "ok" | "confirmation_required" | "error" | "clarification" | "cancelled";
  speech: string;
  detail?: string | null;
  detail_available: boolean;
  intent?: { tool: string; params: Record<string, unknown>; rationale: string } | null;
  pending?: PendingAction | null;
  suggestions: string[];
  trace_id?: string | null;
  audit_id?: string | null;
  /** One entry per task in a multi-task turn, in the order the user asked. */
  steps?: { tool: string | null; status: string; speech: string; audit_id?: string | null }[];
}

export interface VoiceConfig {
  enabled: boolean;
  provider: "elevenlabs";
  model: string;
  max_chars: number;
  fallback: "browser_speech_synthesis";
}

export interface HouseTimer {
  id: string;
  label: string | null;
  duration_s: number;
  started_at: string;
  ends_at: string;
  remaining_s: number;
}

export interface HouseLight {
  room: string;
  room_name: string;
  on: boolean;
  brightness: number;
  updated_at: string;
}

export interface HouseClimate {
  zone: string;
  zone_name: string;
  target_c: number;
  updated_at: string;
}

export interface HouseBooking {
  id: string;
  room: string;
  room_name: string;
  date: string;
  start_time: string;
  end_time: string;
  duration_minutes: number;
  guests: number;
  title: string | null;
}

/** The server's view of one household. Read-only; every change goes through the assistant. */
export interface HouseState {
  subject: string;
  server_time: string;
  rules_version: string;
  timers: HouseTimer[];
  lights: HouseLight[];
  climate: HouseClimate[];
  bookings: HouseBooking[];
  pending: PendingAction | null;
}

export interface TraceEvent {
  id: string;
  ts: string;
  subject: string;
  tool: string;
  service: string;
  params_hash: string;
  status: Outcome;
  decision: Decision;
  ok: boolean;
  ms: number;
  speech: string;
}

export interface TraceList {
  entries: TraceEvent[];
}

export interface AuditRow {
  id: string;
  seq: number;
  ts: string;
  subject: string;
  tool: string;
  tool_version: string;
  rules_version: string;
  service: string;
  scopes_used: string[];
  params_hash: string;
  decision: Decision;
  status: Outcome;
  error_code: string | null;
  compensator_of: string | null;
  result_ref: string | null;
  compensation: Record<string, unknown> | null;
  tombstone: boolean;
  prev_hash: string;
  row_hash: string;
}

export interface AuditSeed {
  fixture: string;
  rows: number;
  seeded: boolean;
}

export interface AuditList {
  seeded: AuditSeed | null;
  entries: AuditRow[];
}

export interface AuditVerify {
  ok: boolean;
  rows: number;
  head: string;
  first_bad: string | null;
  reason: string | null;
}

/**
 * Field rules come from the versioned YAML with defaults excluded, so every
 * property except `type` may be absent.
 */
export interface ToolFieldRule {
  type: "integer" | "number" | "string" | "boolean";
  label?: string;
  min?: number;
  max?: number;
  enum?: (string | number)[];
  enum_labels?: Record<string, string>;
  max_length?: number;
  format?: "date" | "time";
  not_past?: boolean;
  display?: string;
  default?: unknown;
}

export interface ToolManifest {
  name: string;
  title: string;
  version: string;
  description: string;
  service: string;
  scopes: string[];
  risk: Risk;
  reversible: boolean;
  read_only: boolean;
  idempotent: boolean;
  compensator: string | null;
  required: string[];
  optional: string[];
  confirmation_template: string | null;
  external: boolean;
  certified: boolean | null;
  rules_version: string;
  fields: Record<string, ToolFieldRule>;
}

export interface ToolList {
  rules_version: string;
  confirmation_ttl_seconds: number;
  tools: ToolManifest[];
}
