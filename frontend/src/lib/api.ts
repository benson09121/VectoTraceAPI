/**
 * Thin client for the VectoTrace REST API.
 *
 * Tokens live in localStorage: the dashboard is a client-rendered SPA, so
 * there is no server session to hang them off. A 401 triggers one silent
 * refresh attempt before the caller ever sees an error — access tokens expire
 * after 15 minutes and users should not be logged out mid-session for it.
 */

import type {
  AlertChannel,
  ApiLog,
  ApiToken,
  Incident,
  Member,
  MaintenanceWindow,
  PageSubscriber,
  MintedToken,
  Monitor,
  Organization,
  Paginated,
  PublicStatus,
  StatusPage,
  UptimeWindow,
  User,
} from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const ACCESS_KEY = "vt_access";
const REFRESH_KEY = "vt_refresh";
const ORG_KEY = "vt_org";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(
      typeof detail === "string"
        ? detail
        : ((detail as { detail?: string })?.detail ?? `Request failed (${status})`),
    );
    this.status = status;
    this.detail = detail;
  }

  /** Field-level errors from a DRF serializer, if this was a 400. */
  fieldErrors(): Record<string, string[]> {
    if (this.status !== 400 || typeof this.detail !== "object" || !this.detail) {
      return {};
    }
    return this.detail as Record<string, string[]>;
  }
}

/** The browser could not reach the API, so no HTTP response exists. */
export class ApiNetworkError extends Error {
  constructor() {
    super(
      `VectoTrace could not reach the API at ${API_BASE}. Check that the backend is running and that NEXT_PUBLIC_API_URL is correct.`,
    );
    this.name = "ApiNetworkError";
  }
}

// --- Token storage ---------------------------------------------------------

export const tokens = {
  access: () =>
    typeof window === "undefined" ? null : localStorage.getItem(ACCESS_KEY),
  refresh: () =>
    typeof window === "undefined" ? null : localStorage.getItem(REFRESH_KEY),
  set(access: string, refresh?: string) {
    localStorage.setItem(ACCESS_KEY, access);
    if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  },
  clear() {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(ORG_KEY);
  },
};

export const currentOrg = {
  get: () =>
    typeof window === "undefined" ? null : localStorage.getItem(ORG_KEY),
  set: (id: number | string) => localStorage.setItem(ORG_KEY, String(id)),
};

// --- Core request ----------------------------------------------------------

async function parse(res: Response) {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function fetchApi(input: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init);
  } catch (error) {
    // fetch() rejects only when no HTTP response can be obtained (offline API,
    // DNS/TLS failure, or a browser-level CORS block). Give the UI a stable,
    // useful error instead of leaking Firefox's "NetworkError" TypeError.
    if (error instanceof TypeError) throw new ApiNetworkError();
    throw error;
  }
}

async function tryRefresh(): Promise<boolean> {
  const refresh = tokens.refresh();
  if (!refresh) return false;

  const res = await fetchApi(`${API_BASE}/api/v1/auth/refresh/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return false;

  const data = await res.json();
  // ROTATE_REFRESH_TOKENS is on, so a new refresh token comes back too.
  tokens.set(data.access, data.refresh);
  return true;
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  auth?: boolean;
  retry?: boolean;
}

export async function request<T>(
  path: string,
  { method = "GET", body, auth = true, retry = true }: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const access = auth ? tokens.access() : null;
  if (access) headers["Authorization"] = `Bearer ${access}`;

  let res: Response;
  try {
    res = await fetchApi(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (
      error instanceof ApiNetworkError &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/system-offline")
    ) {
      window.location.href = "/system-offline";
    }
    throw error;
  }

  if (res.status === 401 && auth && retry) {
    if (await tryRefresh()) {
      return request<T>(path, { method, body, auth, retry: false });
    }
    tokens.clear();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
  }

  if (!res.ok) {
    if (res.status === 503) {
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/system-offline")) {
        window.location.href = "/system-offline";
      }
    }
    throw new ApiError(res.status, await parse(res));
  }
  return (await parse(res)) as T;
}

// --- Endpoints -------------------------------------------------------------

const org = (id: number | string) => `/api/v1/orgs/${id}`;

/**
 * Write payloads differ from read types for the nested collections: the API
 * accepts bare ids, but returns expanded objects.
 */
export type MonitorWrite = Omit<Partial<Monitor>, "regions"> & { regions?: string[] };
export type StatusPageWrite = Omit<Partial<StatusPage>, "monitors"> & {
  monitors?: number[];
};

export const api = {
  // Auth
  register: (data: {
    email: string;
    password: string;
    first_name: string;
    last_name: string;
  }) => request<User>("/api/v1/auth/register/", { method: "POST", body: data, auth: false }),

  login: async (email: string, password: string) => {
    const data = await request<{ access: string; refresh: string }>(
      "/api/v1/auth/login/",
      { method: "POST", body: { email, password }, auth: false },
    );
    tokens.set(data.access, data.refresh);
    return data;
  },

  logout: async () => {
    const refresh = tokens.refresh();
    try {
      if (refresh) {
        await request("/api/v1/auth/logout/", { method: "POST", body: { refresh } });
      }
    } finally {
      tokens.clear();
    }
  },

  me: () => request<User>("/api/v1/auth/me/"),

  // Config
  getSystemConfig: () => request<{ is_showcase_mode: boolean; is_maintenance_mode: boolean; allow_registrations: boolean }>("/api/v1/config/", { auth: false }),
  getSystemHealth: () => request<{ metrics: Record<string, any> }>("/api/v1/health/system/"),

  // Organizations
  listOrgs: () => request<Organization[]>("/api/v1/organizations/"),
  createOrg: (name: string) =>
    request<Organization>("/api/v1/organizations/", { method: "POST", body: { name } }),
  getOrg: (id: number | string) => request<Organization>(`/api/v1/organizations/${id}/`),
  updateOrg: (id: number | string, data: Partial<Organization>) =>
    request<Organization>(`/api/v1/organizations/${id}/`, { method: "PATCH", body: data }),
  listMembers: (id: number | string) =>
    request<{ members: Member[] }>(`/api/v1/organizations/${id}/members/`),
  inviteMember: (id: number | string, email: string, role: string) =>
    request(`/api/v1/organizations/${id}/members/invite/`, {
      method: "POST",
      body: { email, role },
    }),
  removeMember: (id: number | string, userId: number) =>
    request(`/api/v1/organizations/${id}/members/${userId}/`, { method: "DELETE" }),

  // Monitors
  listMonitors: (o: number | string) => request<Monitor[]>(`${org(o)}/monitors/`),
  createMonitor: (o: number | string, data: MonitorWrite) =>
    request<Monitor>(`${org(o)}/monitors/`, { method: "POST", body: data }),
  getMonitor: (o: number | string, id: number) =>
    request<Monitor>(`${org(o)}/monitors/${id}/`),
  updateMonitor: (o: number | string, id: number, data: Partial<Monitor>) =>
    request<Monitor>(`${org(o)}/monitors/${id}/`, { method: "PATCH", body: data }),
  archiveMonitor: (o: number | string, id: number) =>
    request(`${org(o)}/monitors/${id}/`, { method: "DELETE" }),
  pauseMonitor: (o: number | string, id: number) =>
    request(`${org(o)}/monitors/${id}/pause/`, { method: "POST" }),
  resumeMonitor: (o: number | string, id: number) =>
    request(`${org(o)}/monitors/${id}/resume/`, { method: "POST" }),
  monitorChecks: (o: number | string, id: number, page = 1) =>
    request<Paginated<ApiLog>>(`${org(o)}/monitors/${id}/checks/?page=${page}`),
  monitorUptime: (o: number | string, id: number) =>
    request<UptimeWindow[]>(`${org(o)}/monitors/${id}/uptime/`),

  // Incidents
  listIncidents: (o: number | string, params = "") =>
    request<Incident[]>(`${org(o)}/incidents/${params}`),
  getIncident: (o: number | string, id: number) =>
    request<Incident>(`${org(o)}/incidents/${id}/`),
  postIncidentUpdate: (
    o: number | string,
    id: number,
    data: { status: string; message: string },
  ) => request<Incident>(`${org(o)}/incidents/${id}/updates/`, { method: "POST", body: data }),
  resolveIncident: (o: number | string, id: number, message?: string) =>
    request<Incident>(`${org(o)}/incidents/${id}/resolve/`, {
      method: "POST",
      body: { message },
    }),

  // Status pages
  listStatusPages: (o: number | string) => request<StatusPage[]>(`${org(o)}/status-pages/`),
  createStatusPage: (o: number | string, data: StatusPageWrite) =>
    request<StatusPage>(`${org(o)}/status-pages/`, { method: "POST", body: data }),
  getStatusPage: (o: number | string, id: number) =>
    request<StatusPage>(`${org(o)}/status-pages/${id}/`),
  updateStatusPage: (
    o: number | string,
    id: number,
    data: StatusPageWrite,
  ) => request<StatusPage>(`${org(o)}/status-pages/${id}/`, { method: "PATCH", body: data }),
  deleteStatusPage: (org: string | number, id: number) => request(`/api/v1/organizations/${org}/status-pages/${id}/`, { method: "DELETE" }),

  // Public Endpoints
  subscribePublic: (slug: string, email: string) => request(`/api/v1/public/status-pages/${slug}/subscribe/`, {
    method: "POST",
    body: { email },
    auth: false
  }),

  // Alert channels
  listChannels: (o: number | string) => request<AlertChannel[]>(`${org(o)}/alert-channels/`),
  createChannel: (o: number | string, data: { type: string; config: { url: string } }) =>
    request<AlertChannel>(`${org(o)}/alert-channels/`, { method: "POST", body: data }),
  updateChannel: (o: number | string, id: number, data: Partial<AlertChannel>) =>
    request<AlertChannel>(`${org(o)}/alert-channels/${id}/`, { method: "PATCH", body: data }),
  deleteChannel: (o: number | string, id: number) =>
    request(`${org(o)}/alert-channels/${id}/`, { method: "DELETE" }),
  testChannel: (o: number | string, id: number) =>
    request<{ success: boolean; detail: string }>(`${org(o)}/alert-channels/${id}/test/`, {
      method: "POST",
    }),

  // API tokens
  listTokens: (o: number | string) => request<ApiToken[]>(`${org(o)}/tokens/`),
  mintToken: (o: number | string, name: string, expires_in_days?: number) =>
    request<MintedToken>(`${org(o)}/tokens/`, {
      method: "POST",
      body: { name, ...(expires_in_days ? { expires_in_days } : {}) },
    }),
  revokeToken: (o: number | string, id: number) =>
    request(`${org(o)}/tokens/${id}/`, { method: "DELETE" }),

  // --- Maintenance windows ---
  listMaintenance: (o: number | string) =>
    request<MaintenanceWindow[]>(`${org(o)}/maintenance/`),
  createMaintenance: (o: number | string, data: Record<string, unknown>) =>
    request<MaintenanceWindow>(`${org(o)}/maintenance/`, { method: "POST", body: data }),
  updateMaintenance: (o: number | string, id: number, data: Record<string, unknown>) =>
    request<MaintenanceWindow>(`${org(o)}/maintenance/${id}/`, { method: "PATCH", body: data }),
  deleteMaintenance: (o: number | string, id: number) =>
    request<void>(`${org(o)}/maintenance/${id}/`, { method: "DELETE" }),

  // --- Status page subscribers ---
  listSubscribers: (o: number | string, pageId: number) =>
    request<PageSubscriber[]>(`${org(o)}/status-pages/${pageId}/subscribers/`),
  removeSubscriber: (o: number | string, pageId: number, subId: number) =>
    request<void>(`${org(o)}/status-pages/${pageId}/subscribers/${subId}/`, {
      method: "DELETE",
    }),

  // --- Alert channel schemas (Apprise) ---
  channelSchemas: () =>
    request<{ count: number; schemas: string[] }>("/api/v1/alert-channels/schemas/"),
};

/** Server-side fetch for the public status page — no auth, no localStorage. */
export async function fetchPublicStatus(slug: string): Promise<PublicStatus | null> {
  const res = await fetchApi(`${API_BASE}/api/v1/public/status-pages/${slug}/`, {
    // Status pages must not be served stale during an incident.
    cache: "no-store",
  });
  if (!res.ok) return null;
  return res.json();
}

/** SSE stream URL. EventSource cannot set headers, so the token rides along. */
export function eventStreamUrl(orgId: number | string): string {
  return `${API_BASE}${org(orgId)}/events/?token=${encodeURIComponent(tokens.access() ?? "")}`;
}
