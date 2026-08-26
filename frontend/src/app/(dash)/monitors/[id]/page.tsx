"use client";

import { use, useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Pause, Play, Trash } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useMonitorEvents } from "@/lib/useMonitorEvents";
import { ResponseTimeChart } from "@/components/response-time-chart";
import { HeartbeatBar, type Beat } from "@/components/heartbeat-bar";
import { TimingBar } from "@/components/timing-bar";
import { EditMonitorDialog } from "@/components/edit-monitor-dialog";
import { DataTable, type Column, type FilterDef } from "@/components/data-table";
import { MONITOR_TYPE_LABELS, type ApiLog, type Monitor, type UptimeWindow } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

const RANGES = [
  { key: "1h", label: "1h", ms: 3_600_000 },
  { key: "6h", label: "6h", ms: 21_600_000 },
  { key: "24h", label: "24h", ms: 86_400_000 },
  { key: "all", label: "All", ms: Infinity },
];

/**
 * The hero: the one thing you look at during an incident. Big state word,
 * heartbeat strip, and the interval — mirroring how every uptime product
 * leads its detail view, because it answers "is it up right now" before
 * anything else on the page.
 */
function StatusHero({
  monitor,
  beats,
}: {
  monitor: Monitor;
  beats: Beat[];
}) {
  const paused = monitor.status === "paused";
  const state = paused ? "paused" : monitor.last_status;

  const tone = {
    up: "bg-up text-white",
    down: "bg-down text-white",
    degraded: "bg-degraded text-white",
    paused: "bg-paused text-white",
  }[state as "up" | "down" | "degraded" | "paused"];

  const label = { up: "Up", down: "Down", degraded: "Degraded", paused: "Paused" }[
    state as "up" | "down" | "degraded" | "paused"
  ];

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 pt-6 sm:flex-row sm:items-center">
        <div className="min-w-0 flex-1">
          <HeartbeatBar beats={beats} slots={40} showScale />
          <p className="mt-2 text-xs text-muted-foreground">
            {monitor.type === "heartbeat"
              ? `Expects a ping every ${monitor.interval}s`
              : `Checks every ${monitor.interval} seconds`}
          </p>
        </div>
        <div
          className={cn(
            "flex h-16 w-full items-center justify-center rounded-xl text-lg font-semibold sm:w-28",
            tone,
          )}
        >
          {label}
        </div>
      </CardContent>
    </Card>
  );
}

function Metric({
  label,
  sub,
  value,
}: {
  label: string;
  sub?: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-3 text-center">
      <p className="text-sm font-medium">{label}</p>
      {sub && <p className="text-xs text-muted-foreground">({sub})</p>}
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}

export default function MonitorDetailPage({
  params,
}: {
  // Next 16: route params arrive as a promise.
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const monitorId = Number(id);
  const router = useRouter();
  const { org } = useAuth();

  const queryClient = useQueryClient();
  const queryKey = ["monitor-detail", org?.id, monitorId];
  const [range, setRange] = useState(RANGES[1]);

  const { data, isLoading: loading, refetch: load } = useQuery({
    queryKey,
    queryFn: async () => {
      if (!org) throw new Error("No org");
      const [m, u, c] = await Promise.all([
        api.getMonitor(org.id, monitorId),
        api.monitorUptime(org.id, monitorId),
        api.monitorChecks(org.id, monitorId),
      ]);
      return { monitor: m, uptime: u, checks: c.results };
    },
    enabled: !!org,
  });

  const monitor = data?.monitor ?? null;
  const uptime = data?.uptime ?? [];
  const checks = data?.checks ?? [];

  // Prepend live checks for this monitor instead of polling.
  useMonitorEvents(
    org?.id ?? null,
    useCallback(
      (event) => {
        if (event.monitor_id !== monitorId) return;
        queryClient.setQueryData(queryKey, (prev: any) => {
          if (!prev) return prev;
          const next = { ...prev };
          if (next.monitor) {
            next.monitor = { ...next.monitor, last_status: event.last_status };
          }
          if (event.event === "check") {
            const newCheck = {
              id: -Date.now(),
              region: event.region ?? "default",
              status_code: event.status_code ?? null,
              response_time_ms: event.response_time_ms ?? null,
              result: event.result ?? "success",
              error_message: null,
              ssl_valid: null,
              ssl_expires_at: null,
              checked_at: new Date(event.ts * 1000).toISOString(),
            } as ApiLog;
            next.checks = [newCheck, ...next.checks].slice(0, 200);
          }
          return next;
        });
      },
      [monitorId, queryClient, queryKey],
    ),
  );

  // Newest-first from the API; the heartbeat wants oldest-first.
  const beats: Beat[] = useMemo(
    () =>
      [...checks]
        .reverse()
        .slice(-40)
        .map((c) => ({
          result: c.result,
          response_time_ms: c.response_time_ms,
          checked_at: c.checked_at,
        })),
    [checks],
  );

  const windowed = useMemo(() => {
    if (range.ms === Infinity || checks.length === 0) return checks;
    // Anchor the window to the newest check rather than the wall clock. It
    // keeps the memo pure (Date.now() during render is non-deterministic and
    // never invalidates), and "the last 6h of data" is what you actually want
    // when a monitor has been paused — an absolute cutoff would show nothing.
    const newest = Math.max(...checks.map((c) => new Date(c.checked_at).getTime()));
    const cutoff = newest - range.ms;
    return checks.filter((c) => new Date(c.checked_at).getTime() >= cutoff);
  }, [checks, range]);

  const latest = checks[0];
  const uptime24 = uptime.find((u) => u.window === "24h");
  const uptime30 = uptime.find((u) => u.window === "30d");

  async function archive() {
    if (!org || !confirm("Archive this monitor? It will stop being checked.")) return;
    try {
      await api.archiveMonitor(org.id, monitorId);
      toast.success("Monitor archived");
      router.push("/monitors");
    } catch {
      toast.error("Only org admins can archive monitors");
    }
  }

  async function togglePause() {
    if (!org || !monitor) return;
    try {
      if (monitor.status === "paused") await api.resumeMonitor(org.id, monitorId);
      else await api.pauseMonitor(org.id, monitorId);
      await load();
      toast.success(monitor.status === "paused" ? "Monitor resumed" : "Monitor paused");
    } catch {
      toast.error("Could not change monitor state");
    }
  }

  if (loading) {
    return (
      <div className="mx-auto flex max-w-7xl flex-col gap-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }
  if (!monitor) return <p className="text-sm text-muted-foreground">Monitor not found.</p>;

  const checkColumns: Column<ApiLog>[] = [
    {
      key: "checked_at",
      header: "Time",
      sortable: true,
      value: (c) => c.checked_at,
      cell: (c) => (
        <span className="whitespace-nowrap tabular text-muted-foreground">
          {new Date(c.checked_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "result",
      header: "Result",
      sortable: true,
      value: (c) => c.result,
      cell: (c) => (
        <span
          className={cn(
            "rounded-full border px-2 py-0.5 text-xs capitalize",
            c.result === "success"
              ? "border-up/40 bg-up/10 text-up"
              : "border-down/40 bg-down/10 text-down",
          )}
        >
          {c.result}
        </span>
      ),
    },
    {
      key: "status_code",
      header: "Code",
      sortable: true,
      align: "right",
      value: (c) => c.status_code ?? "",
      cell: (c) => <span className="tabular">{c.status_code ?? "—"}</span>,
    },
    {
      key: "response_time_ms",
      header: "Response",
      sortable: true,
      align: "right",
      value: (c) => c.response_time_ms ?? 0,
      cell: (c) => (
        <span className="tabular">
          {c.response_time_ms != null ? `${c.response_time_ms}ms` : "—"}
        </span>
      ),
    },
    {
      key: "ttfb_ms",
      header: "TTFB",
      sortable: true,
      secondary: true,
      align: "right",
      value: (c) => c.ttfb_ms ?? 0,
      cell: (c) => (
        <span className="tabular text-muted-foreground">
          {c.ttfb_ms != null ? `${c.ttfb_ms}ms` : "—"}
        </span>
      ),
    },
    {
      key: "error_message",
      header: "Error",
      secondary: true,
      value: (c) => c.error_message ?? "",
      cell: (c) => (
        <span className="line-clamp-1 text-xs text-muted-foreground" title={c.error_message ?? ""}>
          {c.error_message ?? "—"}
        </span>
      ),
    },
  ];

  const checkFilters: FilterDef<ApiLog>[] = [
    {
      key: "result",
      label: "Result",
      options: [
        { value: "success", label: "Success" },
        { value: "failure", label: "Failure" },
      ],
      predicate: (c, v) => c.result === v,
    },
  ];

  return (
    <div className="mx-auto flex max-w-7xl flex-col gap-5">
      <Link
        href="/monitors"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Monitors
      </Link>

      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">{monitor.name}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
              {MONITOR_TYPE_LABELS[monitor.type] ?? monitor.type}
            </span>
            <span className="truncate font-mono text-xs text-muted-foreground">
              {monitor.url}
            </span>
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {org && <EditMonitorDialog orgId={org.id} monitor={monitor} onSaved={load} />}
          <Button
            variant="outline"
            size="sm"
            onClick={togglePause}
            className="cursor-pointer"
          >
            {monitor.status === "paused" ? (
              <>
                <Play className="size-4" aria-hidden /> Resume
              </>
            ) : (
              <>
                <Pause className="size-4" aria-hidden /> Pause
              </>
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={archive}
            className="cursor-pointer text-destructive hover:text-destructive"
          >
            <Trash className="size-4" aria-hidden /> Archive
          </Button>
        </div>
      </header>

      <StatusHero monitor={monitor} beats={beats} />

      {/* The four numbers an operator actually reads, in one row. */}
      <Card>
        <CardContent className="grid grid-cols-2 divide-x divide-y divide-border p-0 sm:grid-cols-4 sm:divide-y-0">
          <Metric
            label="Response"
            sub="current"
            value={
              latest?.response_time_ms != null ? (
                <span className="tabular">{latest.response_time_ms} ms</span>
              ) : (
                "—"
              )
            }
          />
          <Metric
            label="Avg response"
            sub="24 hours"
            value={
              uptime24?.avg_response_time_ms != null ? (
                <span className="tabular">{Math.round(uptime24.avg_response_time_ms)} ms</span>
              ) : (
                "—"
              )
            }
          />
          <Metric
            label="Uptime"
            sub="24 hours"
            value={<span className="tabular">{uptime24?.uptime_pct ?? "—"}%</span>}
          />
          <Metric
            label="Uptime"
            sub="30 days"
            value={<span className="tabular">{uptime30?.uptime_pct ?? "—"}%</span>}
          />
        </CardContent>
      </Card>

      {/* A heartbeat monitor has nothing to reach out to — it waits for the
          job to call us. Without showing this URL the whole type is unusable. */}
      {monitor.type === "heartbeat" && monitor.heartbeat_url && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Heartbeat URL</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              Call this from the end of your job. If it stops arriving for longer
              than the grace period, an incident opens.
            </p>
            <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2">
              <code className="min-w-0 flex-1 overflow-x-auto font-mono text-xs">
                {monitor.heartbeat_url}
              </code>
              <Button
                variant="ghost"
                size="sm"
                className="cursor-pointer"
                onClick={() => {
                  navigator.clipboard.writeText(monitor.heartbeat_url!);
                  toast.success("Heartbeat URL copied");
                }}
              >
                Copy
              </Button>
            </div>
            <code className="overflow-x-auto rounded-md bg-muted px-3 py-2 font-mono text-xs text-muted-foreground">
              curl -fsS {monitor.heartbeat_url} &gt; /dev/null
            </code>
            {monitor.last_heartbeat_at && (
              <p className="text-xs text-muted-foreground">
                Last ping {new Date(monitor.last_heartbeat_at).toLocaleString()}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Percentiles: averages hide the tail, which is where users live. */}
      {uptime24 && uptime24.p95_response_time_ms != null && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Response time distribution (24h)</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-3 divide-x divide-border">
            {[
              { label: "p50", hint: "typical", v: uptime24.p50_response_time_ms },
              { label: "p95", hint: "slow tail", v: uptime24.p95_response_time_ms },
              { label: "p99", hint: "worst", v: uptime24.p99_response_time_ms },
            ].map((p) => (
              <div key={p.label} className="px-4 py-1 text-center">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">
                  {p.label} <span className="normal-case">({p.hint})</span>
                </p>
                <p className="mt-1 text-lg font-semibold tabular">
                  {p.v != null ? `${p.v} ms` : "—"}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {latest && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Where the time went</CardTitle>
          </CardHeader>
          <CardContent>
            <TimingBar timings={latest} />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-2 pb-3">
          <CardTitle className="text-base">Response time</CardTitle>
          {/* Range selector sits with the chart it scopes. */}
          <div
            role="radiogroup"
            aria-label="Chart time range"
            className="flex gap-0.5 rounded-md border border-border p-0.5"
          >
            {RANGES.map((r) => (
              <button
                key={r.key}
                role="radio"
                aria-checked={range.key === r.key}
                onClick={() => setRange(r)}
                className={cn(
                  "cursor-pointer rounded px-2.5 py-1 text-xs transition-colors",
                  range.key === r.key
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted",
                )}
              >
                {r.label}
              </button>
            ))}
          </div>
        </CardHeader>
        <CardContent>
          <ResponseTimeChart checks={windowed} />
        </CardContent>
      </Card>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          Recent checks
        </h2>
        <DataTable
          rows={checks}
          columns={checkColumns}
          rowKey={(c) => c.id}
          filters={checkFilters}
          searchPlaceholder="Search checks…"
          pageSize={15}
          empty={{
            title: "No checks recorded yet",
            description:
              "The worker runs on the monitor's interval — the first result appears shortly after it is due.",
          }}
        />
      </section>
    </div>
  );
}
