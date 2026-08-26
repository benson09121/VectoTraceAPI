"use client";

/**
 * Create-monitor dialog.
 *
 * The form is type-driven: picking a monitor type swaps the fields, so a DNS
 * monitor never asks for an HTTP method and a heartbeat never asks for a URL.
 * Showing every field for every type is how config forms become unusable.
 */

import { useState } from "react";
import { Plus } from "@phosphor-icons/react";
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
import { MONITOR_TYPE_LABELS, type MonitorType } from "@/lib/types";

const METHODS = ["GET", "POST", "PUT", "DELETE", "HEAD"];
const DNS_TYPES = ["A", "AAAA", "CNAME", "MX", "TXT", "NS"];

/** What the target field means for each type — the label must not lie. */
const TARGET: Record<MonitorType, { label: string; placeholder: string } | null> = {
  http: { label: "URL", placeholder: "https://api.example.com/health" },
  keyword: { label: "URL", placeholder: "https://example.com" },
  json: { label: "URL", placeholder: "https://api.example.com/status" },
  ping: { label: "Hostname or IP", placeholder: "example.com" },
  port: { label: "Hostname or IP", placeholder: "db.example.com" },
  dns: { label: "Hostname", placeholder: "example.com" },
  ssl: { label: "URL", placeholder: "https://example.com" },
  domain: { label: "Domain", placeholder: "example.com" },
  heartbeat: null, // nothing to reach out to — the job calls us
};

const HINTS: Partial<Record<MonitorType, string>> = {
  keyword: "Fails when the body does not contain your keyword, even on a 200.",
  json: "Checks a value inside the JSON response, e.g. status = ok.",
  heartbeat:
    "Nothing is checked from here. You get a URL to curl from your cron job, and we alert when it stops arriving.",
  domain: "Warns before the domain registration lapses.",
  ssl: "Warns before the TLS certificate expires.",
};

export function NewMonitorDialog({
  orgId,
  onCreated,
}: {
  orgId: number | string;
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [type, setType] = useState<MonitorType>("http");
  const [form, setForm] = useState({
    name: "",
    url: "",
    http_method: "GET",
    interval: 60,
    expected_status_codes: "200",
    keyword: "",
    keyword_inverted: false,
    json_path: "",
    json_expected: "",
    port: "",
    dns_record_type: "A",
    dns_expected: "",
    heartbeat_grace_seconds: 300,
    degraded_threshold_ms: "",
  });

  const target = TARGET[type];
  const isHttpish = ["http", "keyword", "json"].includes(type);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErrors({});
    setBusy(true);

    // Only send what this type actually uses; posting empty strings for
    // irrelevant fields makes the backend validate things nobody set.
    const payload: Record<string, unknown> = {
      name: form.name,
      type,
      interval: Number(form.interval),
    };
    if (target) payload.url = form.url;
    if (form.degraded_threshold_ms)
      payload.degraded_threshold_ms = Number(form.degraded_threshold_ms);

    if (isHttpish) {
      payload.http_method = form.http_method;
      payload.expected_status_codes = form.expected_status_codes
        .split(",")
        .map((s) => Number(s.trim()))
        .filter((n) => !Number.isNaN(n));
    }
    if (type === "keyword") {
      payload.keyword = form.keyword;
      payload.keyword_inverted = form.keyword_inverted;
    }
    if (type === "json") {
      payload.json_path = form.json_path;
      payload.json_expected = form.json_expected;
    }
    if (type === "port") payload.port = Number(form.port);
    if (type === "dns") {
      payload.dns_record_type = form.dns_record_type;
      payload.dns_expected = form.dns_expected;
    }
    if (type === "heartbeat")
      payload.heartbeat_grace_seconds = Number(form.heartbeat_grace_seconds);

    try {
      await api.createMonitor(orgId, payload as never);
      toast.success("Monitor created");
      setOpen(false);
      setForm({ ...form, name: "", url: "", keyword: "", json_path: "", port: "" });
      onCreated();
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

  const err = (name: string) => errors[name]?.[0];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button className="cursor-pointer">
          <Plus className="size-4" aria-hidden />
          New monitor
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>New monitor</DialogTitle>
        </DialogHeader>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="type">Type</Label>
            <Select value={type} onValueChange={(v) => setType(v as MonitorType)}>
              <SelectTrigger id="type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(MONITOR_TYPE_LABELS).map(([v, label]) => (
                  <SelectItem key={v} value={v}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {HINTS[type] && (
              <p className="text-xs text-muted-foreground">{HINTS[type]}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              required
              placeholder="Payments API"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
            {err("name") && <p className="text-sm text-destructive">{err("name")}</p>}
          </div>

          {target && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="url">{target.label}</Label>
              <Input
                id="url"
                required
                placeholder={target.placeholder}
                value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })}
              />
              {err("url") && <p className="text-sm text-destructive">{err("url")}</p>}
            </div>
          )}

          {type === "port" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="port">Port</Label>
              <Input
                id="port"
                type="number"
                required
                min={1}
                max={65535}
                placeholder="5432"
                value={form.port}
                onChange={(e) => setForm({ ...form, port: e.target.value })}
              />
              {err("port") && <p className="text-sm text-destructive">{err("port")}</p>}
            </div>
          )}

          {type === "keyword" && (
            <>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="keyword">Keyword</Label>
                <Input
                  id="keyword"
                  required
                  placeholder="operational"
                  value={form.keyword}
                  onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                />
                {err("keyword") && (
                  <p className="text-sm text-destructive">{err("keyword")}</p>
                )}
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
                <div>
                  <Label htmlFor="inverted">Fail when present</Label>
                  <p className="text-xs text-muted-foreground">
                    Invert the check — useful for spotting error text.
                  </p>
                </div>
                <Switch
                  id="inverted"
                  checked={form.keyword_inverted}
                  onCheckedChange={(v) => setForm({ ...form, keyword_inverted: v })}
                />
              </div>
            </>
          )}

          {type === "json" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="jpath">JSON path</Label>
                <Input
                  id="jpath"
                  required
                  placeholder="status"
                  value={form.json_path}
                  onChange={(e) => setForm({ ...form, json_path: e.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="jexp">Expected value</Label>
                <Input
                  id="jexp"
                  required
                  placeholder="ok"
                  value={form.json_expected}
                  onChange={(e) => setForm({ ...form, json_expected: e.target.value })}
                />
              </div>
            </div>
          )}

          {type === "dns" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="rtype">Record type</Label>
                <Select
                  value={form.dns_record_type}
                  onValueChange={(v) => setForm({ ...form, dns_record_type: v })}
                >
                  <SelectTrigger id="rtype">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {DNS_TYPES.map((r) => (
                      <SelectItem key={r} value={r}>
                        {r}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="dexp">Expected value</Label>
                <Input
                  id="dexp"
                  placeholder="93.184.216.34"
                  value={form.dns_expected}
                  onChange={(e) => setForm({ ...form, dns_expected: e.target.value })}
                />
              </div>
            </div>
          )}

          {type === "heartbeat" ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="grace">Grace period (seconds)</Label>
              <Input
                id="grace"
                type="number"
                min={30}
                value={form.heartbeat_grace_seconds}
                onChange={(e) =>
                  setForm({ ...form, heartbeat_grace_seconds: Number(e.target.value) })
                }
              />
              <p className="text-xs text-muted-foreground">
                How long we wait past the expected ping before opening an incident.
              </p>
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {isHttpish && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="method">Method</Label>
                  <Select
                    value={form.http_method}
                    onValueChange={(v) => setForm({ ...form, http_method: v })}
                  >
                    <SelectTrigger id="method">
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
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="interval">Interval (seconds)</Label>
                <Input
                  id="interval"
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
            </div>
          )}

          {isHttpish && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="codes">Expected status codes</Label>
              <Input
                id="codes"
                placeholder="200, 201, 204"
                value={form.expected_status_codes}
                onChange={(e) =>
                  setForm({ ...form, expected_status_codes: e.target.value })
                }
              />
              {err("expected_status_codes") && (
                <p className="text-sm text-destructive">{err("expected_status_codes")}</p>
              )}
            </div>
          )}

          {type !== "heartbeat" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="degraded">Degraded above (ms, optional)</Label>
              <Input
                id="degraded"
                type="number"
                min={1}
                placeholder="1000"
                value={form.degraded_threshold_ms}
                onChange={(e) =>
                  setForm({ ...form, degraded_threshold_ms: e.target.value })
                }
              />
              <p className="text-xs text-muted-foreground">
                Responses slower than this count as degraded rather than up.
              </p>
            </div>
          )}

          <DialogFooter>
            <Button type="submit" disabled={busy} className="cursor-pointer">
              {busy ? "Creating…" : "Create monitor"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
