import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CheckCircle, RssSimple, Warning, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { API_BASE, fetchPublicStatus } from "@/lib/api";
import type { PublicMonitor, PublicStatus } from "@/lib/types";
import { SubscribeForm } from "./subscribe-form";

// Server-rendered on every request. This page is read during outages, so it
// must never be served from cache, and rendering it on the server is what
// gives link unfurls and search engines something to read.
export const dynamic = "force-dynamic";

const BANNER: Record<
  PublicStatus["status"],
  { label: string; className: string; Icon: typeof CheckCircle }
> = {
  operational: {
    label: "All systems operational",
    className: "border-up/30 bg-up/10 text-up",
    Icon: CheckCircle,
  },
  degraded: {
    label: "Degraded performance",
    className: "border-degraded/30 bg-degraded/10 text-degraded",
    Icon: Warning,
  },
  major_outage: {
    label: "Major outage",
    className: "border-down/30 bg-down/10 text-down",
    Icon: WarningCircle,
  },
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}): Promise<Metadata> {
  const { slug } = await params;
  const status = await fetchPublicStatus(slug);
  if (!status) return { title: "Status page not found" };

  const description = BANNER[status.status].label;
  return {
    title: `${status.title} — ${description}`,
    description,
    // The unfurl is the whole point of rendering this server-side.
    openGraph: { title: status.title, description },
  };
}

export default async function PublicStatusPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  const status = await fetchPublicStatus(slug);
  if (!status) notFound();

  const { label, className, Icon } = BANNER[status.status];
  const feedUrl = `${API_BASE}/api/v1/public/status-pages/${status.slug}/feed/`;

  return (
    <div className="min-h-screen bg-background">
      {/* Branded chrome, same as the dashboard: the brand lives in the shell,
          never on the surface carrying the health colours. */}
      <header className="border-b border-sidebar-border bg-sidebar">
        <div className="mx-auto flex max-w-3xl items-center gap-3 px-6 py-4">
          <h1 className="text-lg font-semibold tracking-tight text-white">
            {status.title}
          </h1>
          <a
            href={feedUrl}
            className="ml-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-sm text-sidebar-foreground transition-colors hover:bg-white/10"
          >
            <RssSimple className="size-4" aria-hidden /> RSS
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8">
        {/* Icon + word, never colour alone — red/green is exactly the pair
            most colour-blind readers cannot separate. */}
        <div
          className={`flex items-center gap-2.5 rounded-lg border px-4 py-3 font-medium ${className}`}
        >
          <Icon className="size-5 shrink-0" weight="fill" aria-hidden />
          {label}
        </div>

        {status.active_incidents.length > 0 && (
          <section className="mt-8">
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Active incidents
            </h2>
            <div className="flex flex-col gap-4">
              {status.active_incidents.map((incident) => (
                <article
                  key={incident.id}
                  className="rounded-lg border border-border bg-card p-4"
                >
                  <div className="flex flex-wrap items-baseline gap-2">
                    <h3 className="font-medium">{incident.title}</h3>
                    <span className="rounded-full border border-border px-2 py-0.5 text-xs capitalize text-muted-foreground">
                      {incident.severity} · {incident.status}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {incident.monitor} · since{" "}
                    {new Date(incident.started_at).toLocaleString()}
                  </p>
                  {incident.updates.length > 0 && (
                    <ol className="mt-3 flex flex-col gap-3 border-l-2 border-border pl-4">
                      {incident.updates.map((u) => (
                        <li key={u.id}>
                          <p className="text-xs capitalize text-muted-foreground">
                            {u.status} · {new Date(u.posted_at).toLocaleString()}
                          </p>
                          <p className="text-sm">{u.message}</p>
                        </li>
                      ))}
                    </ol>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}

        <section className="mt-8">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Services
          </h2>
          {status.monitors.length === 0 ? (
            <p className="rounded-lg border border-dashed border-border p-12 text-center text-sm text-muted-foreground">
              No services are listed on this page yet.
            </p>
          ) : (
            <ul className="divide-y divide-border rounded-lg border border-border bg-card">
              {status.monitors.map((monitor) => (
                <li key={monitor.id} className="p-4">
                  <MonitorRow monitor={monitor} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <SubscribeForm slug={status.slug} />

        <p className="mt-10 text-center text-xs text-muted-foreground">
          Last updated {new Date(status.updated_at).toLocaleString()} · powered by
          VectoTrace
        </p>
      </main>
    </div>
  );
}

function MonitorRow({ monitor }: { monitor: PublicMonitor }) {
  const dot =
    monitor.status === "up"
      ? "bg-up"
      : monitor.status === "down"
        ? "bg-down"
        : "bg-degraded";

  // Right-align the strip so the newest day sits at the right edge, which is
  // what people expect from an uptime bar.
  const bars = monitor.daily.slice(-30);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <span className={`size-2.5 shrink-0 rounded-full ${dot}`} aria-hidden />
        <span className="font-medium">{monitor.name}</span>
        <span className="text-xs capitalize text-muted-foreground">
          {monitor.status}
        </span>
        <span className="ml-auto text-sm tabular text-muted-foreground">
          {monitor.uptime_30d}% uptime
        </span>
      </div>

      {bars.length > 0 && (
        <>
          <div className="mt-3 flex items-end justify-end gap-[3px]" aria-hidden>
            {bars.map((day) => (
              <span
                key={day.date}
                title={`${day.date}: ${day.uptime_pct}% over ${day.checks} checks`}
                className={`h-8 w-2 rounded-sm ${
                  day.uptime_pct >= 99.5
                    ? "bg-up"
                    : day.uptime_pct >= 95
                      ? "bg-degraded"
                      : "bg-down"
                }`}
              />
            ))}
          </div>
          {bars.length > 1 && (
            <div
              className="mt-1.5 flex justify-between text-xs text-muted-foreground"
              aria-hidden
            >
              <span>
                {bars.length} day{bars.length === 1 ? "" : "s"} ago
              </span>
              <span>Today</span>
            </div>
          )}
        </>
      )}
      <p className="sr-only">
        {monitor.name} is {monitor.status}, {monitor.uptime_30d}% uptime over 30 days.
      </p>
    </>
  );
}
