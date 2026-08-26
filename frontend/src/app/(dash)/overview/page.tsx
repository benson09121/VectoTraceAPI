"use client";

/**
 * Overview: the "is anything on fire" page.
 *
 * Leads with state, not history — during an incident nobody wants to read a
 * chart, they want to know what is broken and for how long. History comes
 * after: an aggregate response-time trend and a timeline of recent incidents.
 */

import { useMemo } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, CheckCircle, Warning } from "@phosphor-icons/react";
import { PageHeader, StatTile } from "@/components/shell";
import { StatusPill } from "@/components/status-pill";
import { HeartbeatBar, UptimeBadge } from "@/components/heartbeat-bar";
import { ResponseTimeChart } from "@/components/response-time-chart";
import { DataTable, type Column } from "@/components/data-table";
import { Button } from "@/components/ui/button";
import { keys, useIncidents, useMonitors } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import { useMonitorEvents } from "@/lib/useMonitorEvents";
import {
  MONITOR_TYPE_LABELS,
  type ApiLog,
  type Incident,
  type Monitor,
} from "@/lib/types";

/** Buckets every monitor's heartbeat into one org-wide response-time series. */
const BUCKETS = 40;

function aggregateTrend(monitors: Monitor[]): ApiLog[] {
  const beats = monitors.flatMap((m) => m.heartbeat ?? []);
  if (beats.length === 0) return [];

  const times = beats.map((b) => +new Date(b.checked_at));
  const t0 = Math.min(...times);
  const t1 = Math.max(...times);
  const span = Math.max(t1 - t0, 1);

  const slots: { sum: number; n: number; failed: boolean }[] = Array.from(
    { length: BUCKETS },
    () => ({ sum: 0, n: 0, failed: false }),
  );

  for (const b of beats) {
    const i = Math.min(
      BUCKETS - 1,
      Math.floor(((+new Date(b.checked_at) - t0) / span) * BUCKETS),
    );
    if (b.result === "failure") slots[i].failed = true;
    if (b.response_time_ms != null) {
      slots[i].sum += b.response_time_ms;
      slots[i].n += 1;
    }
  }

  return slots.flatMap((s, i) =>
    s.n === 0 && !s.failed
      ? []
      : [
          {
            id: i,
            region: "self",
            status_code: null,
            response_time_ms: s.n ? Math.round(s.sum / s.n) : null,
            result: s.failed ? ("failure" as const) : ("success" as const),
            error_message: null,
            ssl_valid: null,
            ssl_expires_at: null,
            checked_at: new Date(t0 + (span * (i + 0.5)) / BUCKETS).toISOString(),
          },
        ],
  );
}

/**
 * Duration between two known timestamps. Deliberately not "time since now":
 * reading the clock during render is impure, breaks hydration and is what the
 * purity lint rule exists to catch. Open incidents say "Ongoing" instead.
 */
function duration(from: string, to: string): string {
  const mins = Math.max(0, Math.round((+new Date(to) - +new Date(from)) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h`;
}

export default function OverviewPage() {
  const { org } = useAuth();
  const qc = useQueryClient();
  const monitorsQuery = useMonitors(org);
  const incidentsQuery = useIncidents(org);

  const monitors = useMemo(() => monitorsQuery.data ?? [], [monitorsQuery.data]);
  const incidents = useMemo(() => incidentsQuery.data ?? [], [incidentsQuery.data]);
  const loading = monitorsQuery.isLoading || incidentsQuery.isLoading;

  // Live check results patch the cached list in place rather than refetching,
  // so the page stays current without a poll loop.
  useMonitorEvents(org?.id ?? null, (evt) => {
    if (evt.event !== "check" || !org) return;
    qc.setQueryData<Monitor[]>(keys.monitors(org.id), (cur) =>
      cur?.map((m) =>
        m.id === evt.monitor_id ? { ...m, last_status: evt.last_status } : m,
      ),
    );
  });

  const stats = useMemo(() => {
    const active = monitors.filter((m) => m.status === "active");
    const withUptime = active.filter((m) => m.uptime_24h != null);
    return {
      total: active.length,
      down: active.filter((m) => m.last_status === "down").length,
      degraded: active.filter((m) => m.last_status === "degraded").length,
      open: incidents.filter((i) => !i.resolved_at).length,
      uptime: withUptime.length
        ? withUptime.reduce((a, m) => a + (m.uptime_24h ?? 0), 0) / withUptime.length
        : null,
    };
  }, [monitors, incidents]);

  const trend = useMemo(() => aggregateTrend(monitors), [monitors]);
  const attention = monitors.filter(
    (m) => m.status === "active" && m.last_status !== "up",
  );
  const timeline = useMemo(
    () =>
      [...incidents]
        .sort((a, b) => +new Date(b.started_at) - +new Date(a.started_at))
        .slice(0, 8),
    [incidents],
  );

  const columns: Column<Monitor>[] = [
    {
      key: "name",
      header: "Monitor",
      sortable: true,
      value: (m) => m.name,
      cell: (m) => (
        <div className="flex items-center gap-2">
          <UptimeBadge value={m.uptime_24h} />
          <Link
            href={`/monitors/${m.id}`}
            className="font-medium hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {m.name}
          </Link>
        </div>
      ),
    },
    {
      key: "heartbeat",
      header: "Recent",
      width: "180px",
      cell: (m) => <HeartbeatBar beats={m.heartbeat ?? []} slots={30} size="sm" />,
    },
    {
      key: "type",
      header: "Type",
      secondary: true,
      value: (m) => MONITOR_TYPE_LABELS[m.type] ?? m.type,
      cell: (m) => (
        <span className="text-muted-foreground">
          {MONITOR_TYPE_LABELS[m.type] ?? m.type}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      value: (m) => m.last_status,
      cell: (m) => <StatusPill status={m.last_status} />,
    },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-6">
      <PageHeader
        title="Overview"
        description={org?.name}
        actions={
          <Button asChild variant="outline" size="sm" className="cursor-pointer">
            <Link href="/monitors">
              All monitors
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </Button>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Monitors" value={stats.total} loading={loading} />
        <StatTile
          label="Down"
          value={stats.down}
          tone={stats.down > 0 ? "down" : "default"}
          loading={loading}
        />
        <StatTile
          label="Degraded"
          value={stats.degraded}
          tone={stats.degraded > 0 ? "degraded" : "default"}
          loading={loading}
        />
        <StatTile
          label="Open incidents"
          value={stats.open}
          tone={stats.open > 0 ? "down" : "default"}
          loading={loading}
        />
        <StatTile
          label="Uptime 24h"
          value={stats.uptime == null ? "—" : `${stats.uptime.toFixed(2)}%`}
          hint="Mean across active monitors"
          tone={stats.uptime != null && stats.uptime < 99 ? "degraded" : "up"}
          loading={loading}
        />
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Needs attention
        </h2>
        <DataTable
          rows={attention}
          columns={columns}
          rowKey={(m) => m.id}
          loading={loading}
          searchable={false}
          pageSize={8}
          empty={{
            title: "Everything is up",
            description: "No monitor is currently reporting down or degraded.",
          }}
        />
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Response time — all monitors
          </h2>
          <div className="rounded-lg border border-border bg-card p-4">
            {trend.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                No checks recorded yet.
              </p>
            ) : (
              <ResponseTimeChart checks={trend} />
            )}
          </div>
        </section>

        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Recent incidents
          </h2>
          <div className="rounded-lg border border-border bg-card p-4">
            {timeline.length === 0 ? (
              <p className="py-12 text-center text-sm text-muted-foreground">
                No incidents recorded. Long may it last.
              </p>
            ) : (
              <ol className="flex flex-col">
                {timeline.map((i, idx) => (
                  <TimelineRow key={i.id} incident={i} last={idx === timeline.length - 1} />
                ))}
              </ol>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function TimelineRow({ incident, last }: { incident: Incident; last: boolean }) {
  const open = !incident.resolved_at;
  const Icon = open ? Warning : CheckCircle;

  return (
    <li className="flex gap-3">
      {/* The rail is drawn per-row rather than as one absolute element so it
          stops cleanly at the last marker instead of dangling. */}
      <div className="flex flex-col items-center">
        <Icon
          className={open ? "size-4 shrink-0 text-down" : "size-4 shrink-0 text-up"}
          weight="fill"
          aria-hidden
        />
        {!last && <span className="w-px flex-1 bg-border" />}
      </div>
      <Link
        href={`/incidents/${incident.id}`}
        className="min-w-0 flex-1 pb-4 hover:underline"
      >
        <p className="truncate text-sm font-medium">{incident.title}</p>
        <p className="truncate text-xs text-muted-foreground">
          {incident.monitor_name} ·{" "}
          {open
            ? "Ongoing"
            : `resolved in ${duration(incident.started_at, incident.resolved_at!)}`}{" "}
          ·{" "}
          {new Date(incident.started_at).toLocaleString()}
        </p>
      </Link>
    </li>
  );
}
