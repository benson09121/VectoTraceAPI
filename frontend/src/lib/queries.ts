"use client";

/**
 * TanStack Query layer.
 *
 * Replaces the hand-rolled `useEffect` + `useState` + `cancelled` flag that
 * every page repeated. That pattern re-fetched on every mount, showed a
 * skeleton each time, had no cache, and made "refresh without flashing" a
 * per-page decision. Query gives all of it once:
 *
 *  - **Cached across navigation.** Going Monitors → detail → back shows the
 *    list instantly from cache instead of a fresh skeleton.
 *  - **`keepPreviousData` on refetch**, so polling and refreshes keep the
 *    current render rather than blanking the table (DESIGN.md §6).
 *  - **Invalidation instead of manual `load()` calls**, so a mutation updates
 *    every view that shows that data, not just the one that fired it.
 *
 * Keys are centralised here so an invalidation can never silently miss a view
 * because two files spelled the same key differently.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  AlertChannel,
  ApiToken,
  Incident,
  MaintenanceWindow,
  Monitor,
  StatusPage,
  UptimeWindow,
} from "@/lib/types";

type OrgId = number | string;

export const keys = {
  orgs: ["orgs"] as const,
  monitors: (o: OrgId) => ["monitors", String(o)] as const,
  monitor: (o: OrgId, id: number) => ["monitor", String(o), id] as const,
  monitorChecks: (o: OrgId, id: number) => ["monitor-checks", String(o), id] as const,
  monitorUptime: (o: OrgId, id: number) => ["monitor-uptime", String(o), id] as const,
  incidents: (o: OrgId) => ["incidents", String(o)] as const,
  incident: (o: OrgId, id: number) => ["incident", String(o), id] as const,
  statusPages: (o: OrgId) => ["status-pages", String(o)] as const,
  maintenance: (o: OrgId) => ["maintenance", String(o)] as const,
  channels: (o: OrgId) => ["channels", String(o)] as const,
  tokens: (o: OrgId) => ["tokens", String(o)] as const,
  members: (o: OrgId) => ["members", String(o)] as const,
  subscribers: (o: OrgId, pageId: number) => ["subscribers", String(o), pageId] as const,
  channelSchemas: ["channel-schemas"] as const,
};

/** `enabled` guard shared by every org-scoped query: no org, no request. */
function useOrgQuery<T>(
  org: { id: OrgId } | null | undefined,
  key: readonly unknown[],
  fn: () => Promise<T>,
  extra?: Partial<UseQueryOptions<T>>,
) {
  return useQuery<T>({
    queryKey: key,
    queryFn: fn,
    enabled: !!org,
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------

export function useMonitors(org: { id: OrgId } | null) {
  return useOrgQuery<Monitor[]>(org, keys.monitors(org?.id ?? 0), () =>
    api.listMonitors(org!.id),
  );
}

export function useMonitor(org: { id: OrgId } | null, id: number) {
  return useOrgQuery<Monitor>(org, keys.monitor(org?.id ?? 0, id), () =>
    api.getMonitor(org!.id, id),
  );
}

export function useMonitorChecks(org: { id: OrgId } | null, id: number) {
  return useOrgQuery(org, keys.monitorChecks(org?.id ?? 0, id), () =>
    api.monitorChecks(org!.id, id),
  );
}

export function useMonitorUptime(org: { id: OrgId } | null, id: number) {
  return useOrgQuery<UptimeWindow[]>(org, keys.monitorUptime(org?.id ?? 0, id), () =>
    api.monitorUptime(org!.id, id),
  );
}

export function useIncidents(org: { id: OrgId } | null, params = "?resolved=true") {
  return useOrgQuery<Incident[]>(org, keys.incidents(org?.id ?? 0), () =>
    api.listIncidents(org!.id, params),
  );
}

export function useIncident(org: { id: OrgId } | null, id: number) {
  return useOrgQuery<Incident>(org, keys.incident(org?.id ?? 0, id), () =>
    api.getIncident(org!.id, id),
  );
}

export function useStatusPages(org: { id: OrgId } | null) {
  return useOrgQuery<StatusPage[]>(org, keys.statusPages(org?.id ?? 0), () =>
    api.listStatusPages(org!.id),
  );
}

export function useMaintenance(org: { id: OrgId } | null) {
  return useOrgQuery<MaintenanceWindow[]>(org, keys.maintenance(org?.id ?? 0), () =>
    api.listMaintenance(org!.id),
  );
}

export function useChannels(org: { id: OrgId } | null) {
  return useOrgQuery<AlertChannel[]>(org, keys.channels(org?.id ?? 0), () =>
    api.listChannels(org!.id),
  );
}

export function useTokens(org: { id: OrgId } | null) {
  return useOrgQuery<ApiToken[]>(org, keys.tokens(org?.id ?? 0), () =>
    api.listTokens(org!.id),
  );
}

export function useMembers(org: { id: OrgId } | null) {
  return useOrgQuery(org, keys.members(org?.id ?? 0), () => api.listMembers(org!.id));
}

/**
 * The 210 Apprise schemas. Effectively static for the life of the deployment,
 * so it is cached for the session rather than refetched per dialog open.
 */
export function useChannelSchemas() {
  return useQuery({
    queryKey: keys.channelSchemas,
    queryFn: () => api.channelSchemas(),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

// ---------------------------------------------------------------------------
// Writes
// ---------------------------------------------------------------------------

/**
 * Mutation helper that invalidates the keys a write affects.
 *
 * Passing the affected keys explicitly beats blanket-invalidating everything:
 * pausing a monitor should not blank the incidents table.
 */
export function useInvalidatingMutation<TArgs, TResult>(
  fn: (args: TArgs) => Promise<TResult>,
  affects: () => readonly (readonly unknown[])[],
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      for (const key of affects()) qc.invalidateQueries({ queryKey: key });
    },
  });
}
