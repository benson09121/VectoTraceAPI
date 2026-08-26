"use client";

/**
 * Edit an existing monitor.
 *
 * The API has supported updates all along; the dashboard only offered create
 * and archive, so changing an interval meant deleting and recreating a monitor
 * — losing its whole history.
 *
 * Only fields that apply to the monitor's type are shown, matching the create
 * dialog. Type itself is not editable: changing an HTTP monitor into a DNS
 * monitor would leave its check history describing something that no longer
 * exists.
 */

import { useState } from "react";
import { PencilSimple } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { MONITOR_TYPE_LABELS, type Monitor } from "@/lib/types";

const METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD"];

export function EditMonitorDialog({
  orgId,
  monitor,
  onSaved,
}: {
  orgId: number | string;
  monitor: Monitor;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [form, setForm] = useState({
    name: monitor.name,
    url: monitor.url,
    interval: monitor.interval,
    http_method: monitor.http_method ?? "GET",
    timeout_ms: monitor.timeout_ms ?? 30000,
    expected_status_codes: (monitor.expected_status_codes ?? [200]).join(", "),
    degraded_threshold_ms: monitor.degraded_threshold_ms?.toString() ?? "",
    follow_redirect: monitor.follow_redirect ?? true,
    keyword: monitor.keyword ?? "",
    keyword_inverted: monitor.keyword_inverted ?? false,
    heartbeat_grace_seconds: monitor.heartbeat_grace_seconds ?? 300,
  });

  const isHttpish = ["http", "keyword", "json"].includes(monitor.type);
  const isHeartbeat = monitor.type === "heartbeat";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setBusy(true);

    const payload: Record<string, unknown> = {
      name: form.name,
      interval: Number(form.interval),
      // Empty clears the threshold rather than sending "" and failing
      // validation on a field the user deliberately blanked.
      degraded_threshold_ms: form.degraded_threshold_ms
        ? Number(form.degraded_threshold_ms)
        : null,
    };
    if (!isHeartbeat) {
      payload.url = form.url;
      payload.timeout_ms = Number(form.timeout_ms);
    }
    if (isHttpish) {
      payload.http_method = form.http_method;
      payload.follow_redirect = form.follow_redirect;
      payload.expected_status_codes = form.expected_status_codes
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => !Number.isNaN(n));
    }
    if (monitor.type === "keyword") {
      payload.keyword = form.keyword;
      payload.keyword_inverted = form.keyword_inverted;
    }
    if (isHeartbeat) {
      payload.heartbeat_grace_seconds = Number(form.heartbeat_grace_seconds);
    }

    try {
      await api.updateMonitor(orgId, monitor.id, payload as never);
      toast.success("Monitor updated");
      setOpen(false);
      onSaved();
    } catch (err) {
      if (err instanceof ApiError) {
        const fields = err.fieldErrors();
        setErrors(fields);
        if (!Object.keys(fields).length) toast.error(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  const err = (n: string) => errors[n]?.[0];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="cursor-pointer">
          <PencilSimple className="size-4" aria-hidden /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Edit monitor</DialogTitle>
        </DialogHeader>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            Type is{" "}
            <span className="font-medium text-foreground">
              {MONITOR_TYPE_LABELS[monitor.type] ?? monitor.type}
            </span>{" "}
            and cannot be changed — the recorded history describes this kind of
            check. Create a new monitor to check something different.
          </p>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="e-name">Name</Label>
            <Input
              id="e-name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            {err("name") && <p className="text-sm text-destructive">{err("name")}</p>}
          </div>

          {!isHeartbeat && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="e-url">Target</Label>
              <Input
                id="e-url"
                required
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
                className="font-mono text-sm"
              />
              {err("url") && <p className="text-sm text-destructive">{err("url")}</p>}
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="e-interval">Interval (seconds)</Label>
              <Input
                id="e-interval"
                type="number"
                min={20}
                required
                value={form.interval}
                onChange={(e) => setForm({ ...form, interval: Number(e.target.value) })}
              />
              {err("interval") && (
                <p className="text-sm text-destructive">{err("interval")}</p>
              )}
            </div>

            {isHeartbeat ? (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="e-grace">Grace period (seconds)</Label>
                <Input
                  id="e-grace"
                  type="number"
                  min={30}
                  value={form.heartbeat_grace_seconds}
                  onChange={(e) =>
                    setForm({ ...form, heartbeat_grace_seconds: Number(e.target.value) })
                  }
                />
              </div>
            ) : (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="e-timeout">Timeout (ms)</Label>
                <Input
                  id="e-timeout"
                  type="number"
                  min={1000}
                  value={form.timeout_ms}
                  onChange={(e) => setForm({ ...form, timeout_ms: Number(e.target.value) })}
                />
              </div>
            )}
          </div>

          {isHttpish && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="e-method">Method</Label>
                  <Select
                    value={form.http_method}
                    onValueChange={(v) => setForm({ ...form, http_method: v })}
                  >
                    <SelectTrigger id="e-method">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {METHODS.map((m) => (
                        <SelectItem key={m} value={m}>
                          {m}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="e-codes">Expected status codes</Label>
                  <Input
                    id="e-codes"
                    value={form.expected_status_codes}
                    onChange={(e) =>
                      setForm({ ...form, expected_status_codes: e.target.value })
                    }
                  />
                  {err("expected_status_codes") && (
                    <p className="text-sm text-destructive">
                      {err("expected_status_codes")}
                    </p>
                  )}
                </div>
              </div>

              <div className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
                <Label htmlFor="e-redirect">Follow redirects</Label>
                <Switch
                  id="e-redirect"
                  checked={form.follow_redirect}
                  onCheckedChange={(v) => setForm({ ...form, follow_redirect: v })}
                />
              </div>
            </>
          )}

          {monitor.type === "keyword" && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="e-keyword">Keyword</Label>
                <Input
                  id="e-keyword"
                  required
                  value={form.keyword}
                  onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
                <Label htmlFor="e-inverted">Fail when present</Label>
                <Switch
                  id="e-inverted"
                  checked={form.keyword_inverted}
                  onCheckedChange={(v) => setForm({ ...form, keyword_inverted: v })}
                />
              </div>
            </>
          )}

          {!isHeartbeat && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="e-degraded">Degraded above (ms)</Label>
              <Input
                id="e-degraded"
                type="number"
                min={1}
                placeholder="Leave empty to disable"
                value={form.degraded_threshold_ms}
                onChange={(e) =>
                  setForm({ ...form, degraded_threshold_ms: e.target.value })
                }
              />
              <p className="text-xs text-muted-foreground">
                Responses slower than this mark the monitor degraded rather than up.
              </p>
            </div>
          )}

          <DialogFooter>
            <Button type="submit" disabled={busy} className="cursor-pointer">
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
