"use client";

import { useCallback } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/shell";
import { SeverityBadge } from "@/components/status-pill";
import { DataTable, type Column, type FilterDef } from "@/components/data-table";
import { useIncidents } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import { useMonitorEvents } from "@/lib/useMonitorEvents";
import type { Incident } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, string> = {
  investigating: "border-down/40 bg-down/10 text-down",
  identified: "border-degraded/40 bg-degraded/10 text-degraded",
  monitoring: "border-primary/40 bg-primary/10 text-primary",
  resolved: "border-up/40 bg-up/10 text-up",
};

function duration(from: string, to: string | null): string {
  const mins = Math.round(
    ((to ? new Date(to).getTime() : Date.now()) - new Date(from).getTime()) / 60000,
  );
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d`;
}

export default function IncidentsPage() {
  const { org } = useAuth();
  const { data: incidents = [], isLoading: loading, refetch } = useIncidents(org);

  const load = useCallback(() => {
    refetch();
  }, [refetch]);


  useMonitorEvents(
    org?.id ?? null,
    useCallback(
      (event) => {
        if (event.event === "incident_opened" || event.event === "incident_resolved") {
          load();
        }
      },
      [load],
    ),
  );

  const columns: Column<Incident>[] = [
    {
      key: "title",
      header: "Incident",
      sortable: true,
      value: (i) => i.title,
      cell: (i) => (
        <div className="min-w-0">
          <Link
            href={`/incidents/${i.id}`}
            className="font-medium hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {i.title}
          </Link>
          <p className="truncate text-xs text-muted-foreground">{i.monitor_name}</p>
        </div>
      ),
    },
    {
      key: "severity",
      header: "Severity",
      sortable: true,
      value: (i) => i.severity,
      cell: (i) => <SeverityBadge severity={i.severity} />,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      value: (i) => i.status,
      cell: (i) => (
        <span
          className={cn(
            "rounded-full border px-2.5 py-0.5 text-xs capitalize",
            STATUS_STYLES[i.status] ?? "border-border text-muted-foreground",
          )}
        >
          {i.status}
        </span>
      ),
    },
    {
      key: "started_at",
      header: "Started",
      sortable: true,
      secondary: true,
      align: "right",
      value: (i) => i.started_at,
      cell: (i) => (
        <span className="tabular text-muted-foreground">
          {new Date(i.started_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      align: "right",
      value: (i) => duration(i.started_at, i.resolved_at),
      cell: (i) => (
        <span className="tabular text-muted-foreground">
          {duration(i.started_at, i.resolved_at)}
        </span>
      ),
    },
  ];

  const filters: FilterDef<Incident>[] = [
    {
      key: "status",
      label: "Status",
      options: [
        { value: "investigating", label: "Investigating" },
        { value: "identified", label: "Identified" },
        { value: "monitoring", label: "Monitoring" },
        { value: "resolved", label: "Resolved" },
      ],
      predicate: (i, v) => i.status === v,
    },
    {
      key: "severity",
      label: "Severity",
      options: [
        { value: "critical", label: "Critical" },
        { value: "major", label: "Major" },
        { value: "minor", label: "Minor" },
      ],
      predicate: (i, v) => i.severity === v,
    },
    {
      key: "open",
      label: "Resolution",
      options: [
        { value: "open", label: "Open" },
        { value: "closed", label: "Resolved" },
      ],
      predicate: (i, v) => (v === "open" ? !i.resolved_at : !!i.resolved_at),
    },
  ];

  const open = incidents.filter((i) => !i.resolved_at).length;

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        title="Incidents"
        description={open > 0 ? `${open} currently open` : "No open incidents"}
      />

      <DataTable
        rows={incidents}
        columns={columns}
        rowKey={(i) => i.id}
        loading={loading}
        searchPlaceholder="Search incidents…"
        filters={filters}
        empty={{
          title: "No incidents recorded",
          description:
            "Incidents open automatically after consecutive failed checks, and resolve when the monitor recovers.",
        }}
      />
    </div>
  );
}
