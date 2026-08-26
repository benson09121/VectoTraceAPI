"use client";

/**
 * Incident detail: what broke, for how long, and what has been said about it.
 *
 * Reads through TanStack Query so posting an update refreshes the incidents
 * list and the overview timeline too, rather than leaving them stale.
 */

import { use, useState } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle, Warning } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { keys, useIncident } from "@/lib/queries";
import type { Incident, IncidentStatus } from "@/lib/types";
import { SeverityBadge } from "@/components/status-pill";
import { PageHeader, StatTile } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

const STATUSES: IncidentStatus[] = [
  "investigating",
  "identified",
  "monitoring",
  "resolved",
];

/** Between two known timestamps only — reading the clock in render is impure. */
function duration(from: string, to: string): string {
  const mins = Math.max(0, Math.round((+new Date(to) - +new Date(from)) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  return `${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h`;
}

export default function IncidentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const incidentId = Number(id);
  const { org } = useAuth();
  const qc = useQueryClient();
  const { data: incident, isLoading } = useIncident(org, incidentId);

  const [status, setStatus] = useState<IncidentStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  function store(updated: Incident) {
    if (!org) return;
    qc.setQueryData(keys.incident(org.id, incidentId), updated);
    qc.invalidateQueries({ queryKey: keys.incidents(org.id) });
  }

  async function postUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!org || !incident) return;
    setBusy(true);
    try {
      store(
        await api.postIncidentUpdate(org.id, incidentId, {
          status: status ?? incident.status,
          message,
        }),
      );
      setMessage("");
      toast.success("Update posted");
    } catch {
      toast.error("Could not post update");
    } finally {
      setBusy(false);
    }
  }

  async function resolve() {
    if (!org) return;
    try {
      store(await api.resolveIncident(org.id, incidentId));
      toast.success("Incident resolved");
    } catch {
      toast.error("Could not resolve incident");
    }
  }

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (!incident)
    return <p className="text-sm text-muted-foreground">Incident not found.</p>;

  const closed = incident.resolved_at !== null;
  const updates = [...incident.updates].sort(
    (a, b) => +new Date(b.posted_at) - +new Date(a.posted_at),
  );

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <Link
        href="/incidents"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" aria-hidden /> Incidents
      </Link>

      <PageHeader
        title={incident.title}
        description={incident.monitor_name}
        actions={
          <div className="flex items-center gap-2">
            <SeverityBadge severity={incident.severity} />
            {!closed && (
              <Button size="sm" onClick={resolve} className="cursor-pointer">
                <CheckCircle className="size-4" aria-hidden /> Resolve
              </Button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatTile
          label="State"
          value={closed ? "Resolved" : "Open"}
          tone={closed ? "up" : "down"}
        />
        <StatTile label="Status" value={<span className="capitalize">{incident.status}</span>} />
        <StatTile
          label="Duration"
          value={closed ? duration(incident.started_at, incident.resolved_at!) : "Ongoing"}
          hint={closed ? undefined : "Still open"}
        />
        <StatTile label="Updates" value={incident.updates.length} />
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="flex flex-col">
            {updates.map((u, idx) => (
              <li key={u.id} className="flex gap-3">
                {/* Rail drawn per row so it stops at the last marker rather
                    than dangling past it. */}
                <div className="flex flex-col items-center">
                  <span
                    className={
                      u.status === "resolved"
                        ? "mt-1 size-2.5 shrink-0 rounded-full bg-up"
                        : "mt-1 size-2.5 shrink-0 rounded-full bg-degraded"
                    }
                    aria-hidden
                  />
                  {idx !== updates.length - 1 && (
                    <span className="w-px flex-1 bg-border" />
                  )}
                </div>
                <div className="min-w-0 flex-1 pb-4">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-sm font-medium capitalize">{u.status}</span>
                    <span className="text-xs text-muted-foreground">
                      {new Date(u.posted_at).toLocaleString()} · {u.posted_by_email}
                    </span>
                  </div>
                  <p className="mt-1 text-sm">{u.message}</p>
                </div>
              </li>
            ))}

            <li className="flex gap-3">
              <div className="flex flex-col items-center">
                <Warning className="size-4 shrink-0 text-down" weight="fill" aria-hidden />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">Incident opened</p>
                <p className="text-xs text-muted-foreground">
                  {new Date(incident.started_at).toLocaleString()}
                </p>
              </div>
            </li>
          </ol>
        </CardContent>
      </Card>

      {!closed && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Post an update</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={postUpdate} className="flex flex-col gap-4">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="status">Status</Label>
                <Select
                  value={status ?? incident.status}
                  onValueChange={(v) => setStatus(v as IncidentStatus)}
                >
                  <SelectTrigger id="status" className="w-56">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {STATUSES.map((s) => (
                      <SelectItem key={s} value={s} className="capitalize">
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="message">Message</Label>
                <Textarea
                  id="message"
                  required
                  rows={3}
                  placeholder="We're rolling back the deploy."
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Subscribers to any status page carrying this monitor are notified.
                </p>
              </div>

              <Button
                type="submit"
                disabled={busy || !message.trim()}
                className="w-fit cursor-pointer"
              >
                {busy ? "Posting…" : "Post update"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
