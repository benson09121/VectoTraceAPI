"use client";

/**
 * Status page management drawer: subscribers, sharing assets, and access.
 *
 * These endpoints all existed on the backend and nothing in the dashboard
 * reached them — subscribers could sign up and be verified, but nobody could
 * see or remove them, and the RSS feed and status badge were undiscoverable.
 */

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Check, Copy, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DataTable, type Column } from "@/components/data-table";
import { api, API_BASE } from "@/lib/api";
import type { Monitor, PageSubscriber, StatusPage } from "@/lib/types";
import { Switch } from "@/components/ui/switch";

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <div className="flex items-center gap-2 rounded-md border border-border bg-muted px-3 py-2">
        <code className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs">
          {value}
        </code>
        <Button
          variant="ghost"
          size="sm"
          className="cursor-pointer"
          onClick={() => {
            navigator.clipboard.writeText(value);
            setCopied(true);
            toast.success(`${label} copied`);
            setTimeout(() => setCopied(false), 2000);
          }}
        >
          {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
        </Button>
      </div>
    </div>
  );
}

export function StatusPageDetail({
  orgId,
  page,
  monitors,
  onChange,
}: {
  orgId: number;
  page: StatusPage;
  /** Every monitor in the org, so they can be attached from here. */
  monitors: Monitor[];
  onChange: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const { data: subs = [], isLoading: loading } = useQuery({
    queryKey: ["subscribers", orgId, page.id],
    queryFn: () => api.listSubscribers(orgId, page.id),
    enabled: open,
  });

  const queryClient = useQueryClient();

  async function removeSub(s: PageSubscriber) {
    try {
      await api.removeSubscriber(orgId, page.id, s.id);
      queryClient.setQueryData(["subscribers", orgId, page.id], (cur: PageSubscriber[] | undefined) => 
        cur ? cur.filter((x) => x.id !== s.id) : []
      );
      toast.success("Subscriber removed");
      onChange();
    } catch {
      toast.error("Could not remove subscriber");
    }
  }

  async function toggleMonitor(monitorId: number, on: boolean) {
    const ids = page.monitors.map((m) => m.id);
    const next = on ? [...ids, monitorId] : ids.filter((i) => i !== monitorId);
    try {
      await api.updateStatusPage(orgId, page.id, { monitors: next });
      onChange();
    } catch {
      toast.error("Could not update the monitors on this page");
    }
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      // An empty string clears the password; the API treats an omitted field
      // as "leave unchanged", so this must be sent explicitly.
      await api.updateStatusPage(orgId, page.id, { password } as never);
      toast.success(password ? "Page password set" : "Page password removed");
      setPassword("");
      onChange();
    } catch {
      toast.error("Could not update the page password");
    } finally {
      setSaving(false);
    }
  }

  const publicUrl = `${API_BASE}/api/v1/public/status-pages/${page.slug}/`;
  const feedUrl = `${publicUrl}feed/`;
  const badgeUrl = `${publicUrl}badge.svg`;

  const columns: Column<PageSubscriber>[] = [
    {
      key: "email",
      header: "Subscriber",
      sortable: true,
      value: (s) => s.email,
      cell: (s) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{s.email}</p>
          {s.webhook_url && (
            <p className="truncate font-mono text-xs text-muted-foreground">
              {s.webhook_url}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "verified",
      header: "Status",
      sortable: true,
      value: (s) => (s.verified ? "verified" : "pending"),
      cell: (s) => (
        <span
          className={
            s.verified
              ? "rounded-full border border-up/40 bg-up/10 px-2 py-0.5 text-xs text-up"
              : "rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground"
          }
        >
          {s.verified ? "Verified" : "Pending"}
        </span>
      ),
    },
    {
      key: "subscribed_at",
      header: "Subscribed",
      sortable: true,
      secondary: true,
      align: "right",
      value: (s) => s.subscribed_at,
      cell: (s) => (
        <span className="tabular text-muted-foreground">
          {new Date(s.subscribed_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (s) => (
        <Button
          variant="ghost"
          size="icon"
          className="cursor-pointer"
          aria-label={`Remove ${s.email}`}
          onClick={() => removeSub(s)}
        >
          <Trash className="size-4" aria-hidden />
        </Button>
      ),
    },
  ];

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="cursor-pointer">
          Manage
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{page.title}</DialogTitle>
        </DialogHeader>

        <Tabs defaultValue="monitors">
          <TabsList>
            <TabsTrigger value="monitors" className="cursor-pointer">
              Monitors ({page.monitors.length})
            </TabsTrigger>
            <TabsTrigger value="subscribers" className="cursor-pointer">
              Subscribers ({page.subscriber_count})
            </TabsTrigger>
            <TabsTrigger value="share" className="cursor-pointer">
              Share
            </TabsTrigger>
            <TabsTrigger value="access" className="cursor-pointer">
              Access
            </TabsTrigger>
          </TabsList>

          <TabsContent value="monitors" className="mt-4">
            {monitors.length === 0 ? (
              <p className="rounded-md border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
                No monitors in this organization yet.
              </p>
            ) : (
              <ul className="divide-y divide-border rounded-md border border-border">
                {monitors.map((m) => {
                  const on = page.monitors.some((pm) => pm.id === m.id);
                  return (
                    <li key={m.id} className="flex items-center gap-3 px-3 py-2.5">
                      <Switch
                        id={`p${page.id}m${m.id}`}
                        checked={on}
                        onCheckedChange={(v) => toggleMonitor(m.id, v)}
                      />
                      <Label
                        htmlFor={`p${page.id}m${m.id}`}
                        className="min-w-0 flex-1 cursor-pointer truncate font-normal"
                      >
                        {m.name}
                      </Label>
                      <span className="font-mono text-xs uppercase text-muted-foreground">
                        {m.type}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="mt-2 text-xs text-muted-foreground">
              Only the monitors switched on here appear on the public page.
            </p>
          </TabsContent>

          <TabsContent value="subscribers" className="mt-4">
            <DataTable
              rows={subs}
              columns={columns}
              rowKey={(s) => s.id}
              loading={loading}
              searchPlaceholder="Search subscribers…"
              pageSize={10}
              empty={{
                title: "No subscribers yet",
                description:
                  "People who subscribe on the public page appear here once they confirm their address.",
              }}
            />
          </TabsContent>

          <TabsContent value="share" className="mt-4 flex flex-col gap-4">
            <CopyRow label="Public page" value={`/status/${page.slug}`} />
            <CopyRow label="RSS feed" value={feedUrl} />
            <CopyRow label="Status badge" value={badgeUrl} />
            <div className="flex flex-col gap-1.5">
              <Label>Badge preview</Label>
              <div className="rounded-md border border-border bg-muted p-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={badgeUrl} alt={`Current status of ${page.title}`} />
              </div>
              <p className="text-xs text-muted-foreground">
                Drop the badge into a README or docs page — it renders the live
                state and caches for a minute.
              </p>
            </div>
          </TabsContent>

          <TabsContent value="access" className="mt-4">
            <form onSubmit={savePassword} className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="page-password">Page password</Label>
                <Input
                  id="page-password"
                  type="password"
                  placeholder={
                    page.is_password_protected ? "Set — type to replace" : "No password set"
                  }
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Visitors must enter this to view the page. Submit an empty
                  field to remove it. Stored hashed, never in plain text.
                </p>
              </div>
              <Button type="submit" disabled={saving} className="w-fit cursor-pointer">
                {saving ? "Saving…" : password ? "Set password" : "Remove password"}
              </Button>
            </form>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
