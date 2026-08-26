"use client";

import { useCallback } from "react";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowsClockwise, Broadcast } from "@phosphor-icons/react";
import { PageHeader } from "@/components/shell";
import { StatusPill } from "@/components/status-pill";
import { HeartbeatBar, UptimeBadge } from "@/components/heartbeat-bar";
import { NewMonitorDialog } from "@/components/new-monitor-dialog";
import { DataTable, type Column, type FilterDef } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { keys, useMonitors } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import { useMonitorEvents } from "@/lib/useMonitorEvents";
import { MONITOR_TYPE_LABELS, type Monitor, type MonitorType } from "@/lib/types";
import { cn } from "@/lib/utils";

function relative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export default function MonitorsPage() {
  const { org } = useAuth();
  const qc = useQueryClient();
  // One line replaces the fetch/loading/cancelled dance every page repeated,
  // and the list now comes back from cache instantly on back-navigation.
  const { data: monitors = [], isLoading: loading, refetch } = useMonitors(org);

  const load = useCallback(() => {
    refetch();
  }, [refetch]);

  // Live updates patch the row in place rather than refetching the list.
  const { connected } = useMonitorEvents(
    org?.id ?? null,
    useCallback((event) => {
      if (event.event === "incident_opened") {
        toast.error(event.title ?? `${event.monitor_name} is down`);
      } else if (event.event === "incident_resolved") {
        toast.success(`${event.monitor_name} recovered`);
      }
      // Patch the cache in place — a refetch on every check would hammer the
      // API at the monitor interval and blank nothing useful.
      if (!org) return;
      qc.setQueryData<Monitor[]>(keys.monitors(org.id), (prev) =>
        (prev ?? []).map((m) =>
          m.id === event.monitor_id
            ? {
                ...m,
                last_status: event.last_status,
                last_checked_at: new Date().toISOString(),
              }
            : m,
        ),
      );
    }, [org, qc]),
  );

  async function setPaused(rows: Monitor[], paused: boolean) {
    if (!org) return;
    try {
      await Promise.all(
        rows.map((m) =>
          paused ? api.pauseMonitor(org.id, m.id) : api.resumeMonitor(org.id, m.id),
        ),
      );
      toast.success(`${rows.length} monitor(s) ${paused ? "paused" : "resumed"}`);
    } catch {
      toast.error("Some monitors could not be updated");
    }
    load();
  }

  /**
   * Bulk archive. Confirmed because it is the one bulk action that stops
   * collection — the monitors keep their history but no longer get checked,
   * and there is no undo in the UI.
   */
  async function archiveMany(rows: Monitor[]) {
    if (!org) return;
    const names = rows.length === 1 ? `"${rows[0].name}"` : `${rows.length} monitors`;
    if (!confirm(`Archive ${names}? They stop being checked. History is kept.`)) return;

    // Settled, not all: one failure (e.g. a non-admin hitting an admin-only
    // endpoint) shouldn't discard the successes.
    const results = await Promise.allSettled(
      rows.map((m) => api.archiveMonitor(org.id, m.id)),
    );
    const ok = results.filter((r) => r.status === "fulfilled").length;
    const failed = results.length - ok;

    if (ok) toast.success(`${ok} monitor(s) archived`);
    if (failed) {
      toast.error(
        `${failed} could not be archived — archiving requires the admin role.`,
      );
    }
    load();
  }

  const columns: Column<Monitor>[] = [
    {
      key: "name",
      header: "Monitor",
      sortable: true,
      value: (m) => m.name,
      cell: (m) => (
        <div className="flex min-w-0 items-center gap-2">
          <UptimeBadge value={m.uptime_24h} />
          <div className="min-w-0">
            <Link
              href={`/monitors/${m.id}`}
              className="font-medium hover:underline"
              onClick={(e) => e.stopPropagation()}
            >
              {m.name}
            </Link>
            <p className="truncate font-mono text-xs text-muted-foreground">{m.url}</p>
          </div>
        </div>
      ),
    },
    {
      // The signature element: recent history at a glance, without leaving
      // the list. Sorting it would be meaningless, so it is display-only.
      key: "heartbeat",
      header: "Last 40 checks",
      width: "220px",
      cell: (m) => <HeartbeatBar beats={m.heartbeat ?? []} slots={40} size="sm" />,
    },
    {
      key: "type",
      header: "Type",
      sortable: true,
      secondary: true,
      value: (m) => MONITOR_TYPE_LABELS[m.type] ?? m.type,
      cell: (m) => (
        <span className="text-muted-foreground">
          {MONITOR_TYPE_LABELS[m.type] ?? m.type}
        </span>
      ),
    },
    {
      key: "last_status",
      header: "Health",
      sortable: true,
      value: (m) => m.last_status,
      cell: (m) =>
        m.status === "paused" ? (
          <span className="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground">
            Paused
          </span>
        ) : (
          <StatusPill status={m.last_status} />
        ),
    },
    {
      key: "interval",
      header: "Interval",
      sortable: true,
      secondary: true,
      align: "right",
      value: (m) => m.interval,
      cell: (m) => <span className="tabular text-muted-foreground">{m.interval}s</span>,
    },
    {
      key: "last_checked_at",
      header: "Last check",
      sortable: true,
      align: "right",
      value: (m) => m.last_checked_at ?? "",
      cell: (m) => (
        <span className="tabular text-muted-foreground">
          {relative(m.last_checked_at)}
        </span>
      ),
    },
  ];

  const filters: FilterDef<Monitor>[] = [
    {
      key: "health",
      label: "Health",
      options: [
        { value: "up", label: "Up" },
        { value: "degraded", label: "Degraded" },
        { value: "down", label: "Down" },
      ],
      predicate: (m, v) => m.last_status === v,
    },
    {
      key: "state",
      label: "State",
      options: [
        { value: "active", label: "Active" },
        { value: "paused", label: "Paused" },
      ],
      predicate: (m, v) => m.status === v,
    },
    {
      key: "type",
      label: "Type",
      options: Object.entries(MONITOR_TYPE_LABELS).map(([value, label]) => ({
        value,
        label,
      })),
      predicate: (m, v) => m.type === (v as MonitorType),
    },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        title="Monitors"
        description={`${monitors.length} configured`}
        actions={
          <>
            <span
              className={cn(
                "hidden items-center gap-1.5 self-center text-xs sm:flex",
                connected ? "text-up" : "text-muted-foreground",
              )}
              title={connected ? "Receiving live updates" : "Live updates offline"}
            >
              <Broadcast className="size-3.5" aria-hidden />
              {connected ? "Live" : "Offline"}
            </span>
            <Button
              variant="outline"
              size="icon"
              onClick={load}
              aria-label="Refresh"
              className="cursor-pointer"
            >
              <ArrowsClockwise className="size-4" aria-hidden />
            </Button>
            {org && <NewMonitorDialog orgId={org.id} onCreated={load} />}
          </>
        }
      />

      <DataTable
        rows={monitors}
        columns={columns}
        rowKey={(m) => m.id}
        loading={loading}
        searchPlaceholder="Search name or URL…"
        filters={filters}
        bulkActions={[
          { label: "Pause", onRun: (rows) => setPaused(rows, true) },
          { label: "Resume", onRun: (rows) => setPaused(rows, false) },
          { label: "Archive", destructive: true, onRun: archiveMany },
        ]}
        empty={{
          title: "No monitors yet",
          description:
            "Add your first endpoint and VectoTrace will start checking it on your chosen interval.",
          action: org ? <NewMonitorDialog orgId={org.id} onCreated={load} /> : undefined,
        }}
      />
    </div>
  );
}
