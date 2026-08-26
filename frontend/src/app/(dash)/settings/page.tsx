"use client";

/**
 * Organization settings: members, alert channels, API tokens.
 *
 * All three lists were hand-rolled `<ul>`s with no search, sort or empty-state
 * discipline. They are `DataTable` now, so they behave identically to every
 * other list in the product (DESIGN.md §6), and reads go through TanStack
 * Query so a mutation in one tab refreshes the others.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Copy, PaperPlaneTilt, Plus, Trash } from "@phosphor-icons/react";
import { toast } from "sonner";
import { api, ApiError } from "@/lib/api";
import {
  ChannelPicker,
  isNativeProvider,
  schemaExample,
} from "@/components/channel-picker";
import { PageHeader } from "@/components/shell";
import { DataTable, type Column } from "@/components/data-table";
import { keys, useChannels, useMembers, useTokens } from "@/lib/queries";
import { useAuth } from "@/lib/auth";
import type { AlertChannel, ApiToken, Member } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

export default function SettingsPage() {
  const { org } = useAuth();
  const qc = useQueryClient();

  const members = useMembers(org);
  const channels = useChannels(org);
  const tokens = useTokens(org);

  if (!org) return null;

  const invalidate = (key: readonly unknown[]) =>
    qc.invalidateQueries({ queryKey: key });

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <PageHeader title="Settings" description={org.name} />

      <Tabs defaultValue="members">
        <TabsList>
          <TabsTrigger value="members" className="cursor-pointer">
            Members
          </TabsTrigger>
          <TabsTrigger value="alerts" className="cursor-pointer">
            Alert channels
          </TabsTrigger>
          <TabsTrigger value="tokens" className="cursor-pointer">
            API tokens
          </TabsTrigger>
        </TabsList>

        <TabsContent value="members" className="mt-4">
          <MembersCard
            orgId={org.id}
            members={members.data?.members ?? []}
            loading={members.isLoading}
            onChange={() => invalidate(keys.members(org.id))}
          />
        </TabsContent>
        <TabsContent value="alerts" className="mt-4">
          <ChannelsCard
            orgId={org.id}
            channels={channels.data ?? []}
            loading={channels.isLoading}
            onChange={() => invalidate(keys.channels(org.id))}
          />
        </TabsContent>
        <TabsContent value="tokens" className="mt-4">
          <TokensCard
            orgId={org.id}
            tokens={tokens.data ?? []}
            loading={tokens.isLoading}
            onChange={() => invalidate(keys.tokens(org.id))}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

// --- Members ---------------------------------------------------------------

function MembersCard({
  orgId,
  members,
  loading,
  onChange,
}: {
  orgId: number;
  members: Member[];
  loading: boolean;
  onChange: () => void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("member");

  async function invite(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.inviteMember(orgId, email, role);
      toast.success(`${email} added`);
      setEmail("");
      onChange();
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.status === 409
          ? "Already a member of this organization."
          : "That user must register before being invited.",
      );
    }
  }

  async function remove(userId: number, memberEmail: string) {
    if (!confirm(`Remove ${memberEmail}?`)) return;
    try {
      await api.removeMember(orgId, userId);
      toast.success("Member removed");
      onChange();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not remove member");
    }
  }

  const columns: Column<Member>[] = [
    {
      key: "name",
      header: "Member",
      sortable: true,
      value: (m) => `${m.users.first_name} ${m.users.last_name} ${m.users.email}`,
      cell: (m) => (
        <div className="min-w-0">
          <p className="truncate font-medium">
            {m.users.first_name || m.users.last_name
              ? `${m.users.first_name} ${m.users.last_name}`.trim()
              : m.users.email}
          </p>
          <p className="truncate text-xs text-muted-foreground">{m.users.email}</p>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      sortable: true,
      value: (m) => m.role,
      cell: (m) => (
        <span
          className={
            m.role === "admin"
              ? "rounded-full border border-primary/40 bg-primary/10 px-2 py-0.5 text-xs capitalize text-primary"
              : "rounded-full border border-border px-2 py-0.5 text-xs capitalize text-muted-foreground"
          }
        >
          {m.role}
        </span>
      ),
    },
    {
      key: "created_at",
      header: "Joined",
      sortable: true,
      secondary: true,
      align: "right",
      value: (m) => m.created_at,
      cell: (m) => (
        <span className="tabular text-muted-foreground">
          {new Date(m.created_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (m) => (
        <Button
          variant="ghost"
          size="icon"
          className="cursor-pointer hover:text-destructive"
          onClick={() => remove(m.user_id, m.users.email)}
          aria-label={`Remove ${m.users.email}`}
        >
          <Trash className="size-4" aria-hidden />
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <DataTable
        rows={members}
        columns={columns}
        rowKey={(m) => m.id}
        loading={loading}
        searchPlaceholder="Search members…"
        pageSize={10}
        empty={{
          title: "No members listed",
          description: "Invite a teammate below. They must have registered first.",
        }}
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Invite a member</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={invite} className="flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <Label htmlFor="invite-email">Email</Label>
              <Input
                id="invite-email"
                type="email"
                required
                placeholder="teammate@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor="invite-role">Role</Label>
              <Select value={role} onValueChange={setRole}>
                <SelectTrigger id="invite-role" className="mt-1.5 w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="member">Member</SelectItem>
                  <SelectItem value="admin">Admin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <Button type="submit" className="cursor-pointer">
              Invite
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// --- Alert channels --------------------------------------------------------

function ChannelsCard({
  orgId,
  channels,
  loading,
  onChange,
}: {
  orgId: number;
  channels: AlertChannel[];
  loading: boolean;
  onChange: () => void;
}) {
  // Slack, Discord and generic webhooks use our own tested handlers; every
  // other provider routes through Apprise. Derived from the picker's table so
  // the two can't drift apart.
  const [schema, setSchema] = useState("slack");
  const [url, setUrl] = useState("");
  const [customMessage, setCustomMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const native = isNativeProvider(schema);
  const channelType = native ? schema : "apprise";

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const config: { url: string; custom_message?: string } = { url };
      if (customMessage.trim()) {
        config.custom_message = customMessage.trim();
      }
      await api.createChannel(orgId, { type: channelType, config });
      toast.success("Channel added");
      setUrl("");
      setCustomMessage("");
      onChange();
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.status === 403
          ? "Only org admins can add channels."
          : err instanceof ApiError
            ? err.message
            : "Could not add the channel",
      );
    } finally {
      setBusy(false);
    }
  }

  async function test(id: number) {
    try {
      const res = await api.testChannel(orgId, id);
      toast.success(res.detail);
    } catch (err) {
      toast.error(
        err instanceof ApiError ? `Delivery failed: ${err.message}` : "Test message failed",
      );
    }
  }

  async function toggle(channel: AlertChannel, enabled: boolean) {
    try {
      await api.updateChannel(orgId, channel.id, { is_enabled: enabled });
      onChange();
    } catch {
      toast.error("Only org admins can change channels");
    }
  }

  async function remove(id: number) {
    if (!confirm("Remove this alert channel?")) return;
    try {
      await api.deleteChannel(orgId, id);
      toast.success("Channel removed");
      onChange();
    } catch {
      toast.error("Only org admins can remove channels");
    }
  }

  const columns: Column<AlertChannel>[] = [
    {
      key: "type",
      header: "Provider",
      sortable: true,
      value: (c) => c.type,
      cell: (c) => (
        <div className="min-w-0">
          <p className="font-medium capitalize">{c.type}</p>
          {/* Masked by the backend — for Slack and Discord the URL IS the
              credential, so it is never returned in full. */}
          <p className="truncate font-mono text-xs text-muted-foreground">
            {c.config.url}
          </p>
        </div>
      ),
    },
    {
      key: "is_enabled",
      header: "Enabled",
      sortable: true,
      value: (c) => (c.is_enabled ? "yes" : "no"),
      cell: (c) => (
        <Switch
          checked={c.is_enabled}
          onCheckedChange={(on) => toggle(c, on)}
          aria-label={`${c.type} enabled`}
        />
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (c) => (
        <div className="flex justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="cursor-pointer"
            onClick={() => test(c.id)}
            aria-label="Send test message"
            title="Send test message"
          >
            <PaperPlaneTilt className="size-4" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="cursor-pointer hover:text-destructive"
            onClick={() => remove(c.id)}
            aria-label="Remove channel"
          >
            <Trash className="size-4" aria-hidden />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      <DataTable
        rows={channels}
        columns={columns}
        rowKey={(c) => c.id}
        loading={loading}
        searchPlaceholder="Search channels…"
        pageSize={10}
        empty={{
          title: "No alert channels yet",
          description: "Incidents will open silently until you connect one.",
        }}
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Add a channel</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={create} className="flex flex-col gap-3">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,16rem)_1fr]">
              <div className="flex flex-col gap-1.5">
                <Label>Provider</Label>
                <ChannelPicker value={schema} onChange={setSchema} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="channel-url">
                  {native ? "Webhook URL" : "Apprise URL"}
                </Label>
                <Input
                  id="channel-url"
                  required
                  placeholder={schemaExample(schema)}
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  className="font-mono text-sm"
                />
                <p className="text-xs text-muted-foreground">
                  {native ? (
                    <>
                      Paste the webhook URL from your provider — it must be{" "}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono">
                        https://
                      </code>
                    </>
                  ) : (
                    <>
                      Format:{" "}
                      <code className="rounded bg-muted px-1 py-0.5 font-mono">
                        {schemaExample(schema)}
                      </code>
                    </>
                  )}
                </p>
                
                <Label htmlFor="channel-custom-msg" className="mt-2">
                  Custom Message Template (Optional)
                </Label>
                <Textarea
                  id="channel-custom-msg"
                  placeholder="e.g. [#service_name#] is currently [#status#]! URL: [#url#]"
                  value={customMessage}
                  onChange={(e) => setCustomMessage(e.target.value)}
                  className="font-mono text-sm resize-none h-24"
                />
                <p className="text-xs text-muted-foreground">
                  Variables: <code className="rounded bg-muted px-1 py-0.5">{"[#service_name#]"}</code>, <code className="rounded bg-muted px-1 py-0.5">{"[#url#]"}</code>, <code className="rounded bg-muted px-1 py-0.5">{"[#type#]"}</code>, <code className="rounded bg-muted px-1 py-0.5">{"[#status#]"}</code>, <code className="rounded bg-muted px-1 py-0.5">{"[#severity#]"}</code>, <code className="rounded bg-muted px-1 py-0.5">{"[#event#]"}</code>
                </p>
              </div>
            </div>
            <Button type="submit" disabled={busy} className="w-fit cursor-pointer">
              <Plus className="size-4" aria-hidden /> Add channel
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

// --- API tokens ------------------------------------------------------------

function TokensCard({
  orgId,
  tokens,
  loading,
  onChange,
}: {
  orgId: number;
  tokens: ApiToken[];
  loading: boolean;
  onChange: () => void;
}) {
  const [name, setName] = useState("");
  const [minted, setMinted] = useState<string | null>(null);

  async function mint(e: React.FormEvent) {
    e.preventDefault();
    try {
      const token = await api.mintToken(orgId, name);
      // Shown once — the backend keeps only a hash.
      setMinted(token.token);
      setName("");
      onChange();
    } catch {
      toast.error("Only org admins can mint tokens");
    }
  }

  async function revoke(id: number) {
    if (!confirm("Revoke this token? Anything using it will stop working.")) return;
    try {
      await api.revokeToken(orgId, id);
      toast.success("Token revoked");
      onChange();
    } catch {
      toast.error("Only org admins can revoke tokens");
    }
  }

  const columns: Column<ApiToken>[] = [
    {
      key: "name",
      header: "Token",
      sortable: true,
      value: (t) => t.name,
      cell: (t) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{t.name}</p>
          <code className="font-mono text-xs text-muted-foreground">{t.prefix}…</code>
        </div>
      ),
    },
    {
      key: "last_used_at",
      header: "Last used",
      sortable: true,
      value: (t) => t.last_used_at ?? "",
      cell: (t) => (
        <span className="tabular text-muted-foreground">
          {t.last_used_at ? new Date(t.last_used_at).toLocaleDateString() : "Never"}
        </span>
      ),
    },
    {
      key: "expires_at",
      header: "Expires",
      sortable: true,
      secondary: true,
      align: "right",
      value: (t) => t.expires_at ?? "",
      cell: (t) => (
        <span className="tabular text-muted-foreground">
          {t.expires_at ? new Date(t.expires_at).toLocaleDateString() : "Never"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (t) => (
        <Button
          variant="ghost"
          size="icon"
          className="cursor-pointer hover:text-destructive"
          onClick={() => revoke(t.id)}
          aria-label={`Revoke ${t.name}`}
        >
          <Trash className="size-4" aria-hidden />
        </Button>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {minted && (
        // Uses the degraded (amber) tone rather than destructive: this is a
        // one-time warning to act, not an error.
        <div className="rounded-md border border-degraded/40 bg-degraded/10 p-3">
          <p className="text-sm font-medium">
            Copy this now — it will never be shown again.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-background px-2 py-1 font-mono text-xs">
              {minted}
            </code>
            <Button
              size="sm"
              variant="outline"
              className="cursor-pointer"
              onClick={() => {
                navigator.clipboard.writeText(minted);
                toast.success("Copied");
              }}
            >
              <Copy className="size-4" aria-hidden /> Copy
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="cursor-pointer"
              onClick={() => setMinted(null)}
            >
              Done
            </Button>
          </div>
        </div>
      )}

      <DataTable
        rows={tokens}
        columns={columns}
        rowKey={(t) => t.id}
        loading={loading}
        searchPlaceholder="Search tokens…"
        pageSize={10}
        empty={{
          title: "No API tokens yet",
          description:
            "Mint one to drive the API from CI, a script, or a Grafana dashboard.",
        }}
      />

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Mint a token</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={mint} className="flex flex-wrap items-end gap-3">
            <div className="min-w-56 flex-1">
              <Label htmlFor="token-name">Name</Label>
              <Input
                id="token-name"
                required
                placeholder="CI/CD pipeline"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mt-1.5"
              />
            </div>
            <Button type="submit" className="cursor-pointer">
              <Plus className="size-4" aria-hidden /> Mint token
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
