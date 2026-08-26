// Mirrors the DRF serializers in the Django backend.

export type MonitorStatus = "active" | "paused" | "archived";
export type ServerStatus = "up" | "down" | "degraded";
export type IncidentStatus =
  | "investigating"
  | "identified"
  | "monitoring"
  | "resolved";
export type Severity = "minor" | "major" | "critical";
export type ChannelType = "slack" | "discord" | "webhook";

export interface User {
  first_name: string;
  last_name: string;
  email: string;
}

export interface Organization {
  id: number;
  name: string;
  status?: boolean;
  settings?: Record<string, unknown>;
}

export interface Member {
  /** Membership row id — not the user id. */
  id: number;
  /** The user's id; this is what the remove endpoint is keyed on. */
  user_id: number;
  /** The API nests the profile rather than flattening it. */
  users: {
    first_name: string;
    last_name: string;
    email: string;
  };
  role: string;
  created_at: string;
}

export type MonitorType =
  | "http" | "keyword" | "json" | "ping" | "port"
  | "dns" | "ssl" | "domain" | "heartbeat";

export const MONITOR_TYPE_LABELS: Record<MonitorType, string> = {
  http: "HTTP(S)",
  keyword: "Keyword in body",
  json: "JSON query",
  ping: "Ping (ICMP)",
  port: "TCP port",
  dns: "DNS record",
  ssl: "SSL certificate",
  domain: "Domain expiry",
  heartbeat: "Heartbeat (push)",
};

export interface Beat {
  result: "success" | "failure";
  response_time_ms: number | null;
  checked_at: string;
}

export interface Monitor {
  id: number;
  name: string;
  url: string;
  status: MonitorStatus;
  last_status: ServerStatus;
  interval: number;
  http_method: string;
  type: MonitorType;
  last_checked_at: string | null;
  created_at: string;
  /** Recent checks, oldest first — powers the row heartbeat strip. */
  heartbeat?: Beat[];
  uptime_24h?: number | null;
  // Detail view only
  request_headers?: Record<string, string>;
  request_body?: unknown;
  expected_status_codes?: number[];
  timeout_ms?: number;
  degraded_threshold_ms?: number | null;
  port?: number | null;
  keyword?: string;
  keyword_inverted?: boolean;
  json_path?: string;
  json_expected?: string;
  dns_record_type?: string;
  dns_expected?: string;
  heartbeat_grace_seconds?: number;
  heartbeat_token?: string;
  heartbeat_url?: string | null;
  last_heartbeat_at?: string | null;
  follow_redirect?: boolean;
  consecutive_failures?: number;
  updated_at?: string;
}

export interface ApiLog {
  id: number;
  region: string;
  status_code: number | null;
  response_time_ms: number | null;
  result: "success" | "failure";
  error_message: string | null;
  ssl_valid: boolean | null;
  ssl_expires_at: string | null;
  checked_at: string;
  // Phase breakdown, recorded per check by the engine.
  dns_ms?: number | null;
  connect_ms?: number | null;
  tls_ms?: number | null;
  ttfb_ms?: number | null;
}

export interface UptimeWindow {
  window: string;
  total_checks: number;
  successful_checks: number;
  failed_checks: number;
  uptime_pct: number;
  avg_response_time_ms: number | null;
  p50_response_time_ms?: number | null;
  p95_response_time_ms?: number | null;
  p99_response_time_ms?: number | null;
}

export interface IncidentUpdateEntry {
  id: number;
  status: IncidentStatus;
  message: string;
  posted_at: string;
  posted_by_email: string;
}

export interface Incident {
  id: number;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  monitor_name: string;
  started_at: string;
  resolved_at: string | null;
  updates: IncidentUpdateEntry[];
}

export interface StatusPageMonitorEntry {
  id: number;
  name: string;
  last_status: ServerStatus;
  display_order: number;
}

export interface StatusPage {
  id: number;
  slug: string;
  title: string;
  is_public: boolean;
  theme: "light" | "dark" | "auto";
  custom_domain: string | null;
  monitors: StatusPageMonitorEntry[];
  subscriber_count: number;
  is_password_protected?: boolean;
}

export interface AlertChannel {
  id: number;
  type: ChannelType;
  config: { url?: string; custom_message?: string };
  is_enabled: boolean;
}

export interface ApiToken {
  id: number;
  name: string;
  prefix: string;
  created_by: string;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface MintedToken extends ApiToken {
  token: string;
  warning: string;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// --- Public status page ----------------------------------------------------

export interface PublicDailyUptime {
  date: string;
  uptime_pct: number;
  checks: number;
}

export interface PublicMonitor {
  id: number;
  name: string;
  status: ServerStatus;
  uptime_30d: number;
  daily: PublicDailyUptime[];
}

export interface PublicIncident {
  id: number;
  title: string;
  status: IncidentStatus;
  severity: Severity;
  monitor: string;
  started_at: string;
  resolved_at: string | null;
  updates: IncidentUpdateEntry[];
}

export interface PublicStatus {
  slug: string;
  title: string;
  theme: string;
  status: "operational" | "degraded" | "major_outage";
  monitors: PublicMonitor[];
  active_incidents: PublicIncident[];
  updated_at: string;
}

// --- SSE -------------------------------------------------------------------

export interface MonitorEvent {
  event: "check" | "incident_opened" | "incident_resolved" | "connected" | "error";
  monitor_id: number;
  monitor_name: string;
  organization_id: number;
  last_status: ServerStatus;
  ts: number;
  result?: "success" | "failure";
  status_code?: number | null;
  response_time_ms?: number | null;
  region?: string;
  incident_id?: number;
  title?: string;
  severity?: Severity;
}


export interface MaintenanceWindow {
  id: number;
  title: string;
  description: string;
  starts_at: string;
  ends_at: string;
  suppress_alerts: boolean;
  exclude_from_uptime: boolean;
  state: "scheduled" | "in_progress" | "completed";
  monitor_ids: number[];
  created_at: string;
}

export interface PageSubscriber {
  id: number;
  email: string;
  webhook_url: string | null;
  verified: boolean;
  subscribed_at: string;
}
