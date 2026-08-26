"use client";

/**
 * Profile settings — the signed-in person's own account, kept separate from
 * /settings which is about the organization. Mixing "my password" with "our
 * API tokens" is how people change the wrong thing.
 */

import { useState } from "react";
import { toast } from "sonner";
import { Check, Copy, Moon, Sun, Desktop } from "@phosphor-icons/react";
import { PageHeader } from "@/components/shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { tokens } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTheme, type Theme } from "@/lib/theme";
import { cn } from "@/lib/utils";

export default function ProfilePage() {
  const { user, org, orgs } = useAuth();
  const [theme, applyTheme] = useTheme();
  const [copied, setCopied] = useState(false);

  async function copyAccessToken() {
    const t = tokens.access();
    if (!t) return;
    await navigator.clipboard.writeText(t);
    setCopied(true);
    toast.success("Access token copied");
    setTimeout(() => setCopied(false), 2000);
  }

  const themeOptions: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Desktop },
  ];

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <PageHeader title="Profile" description="Your account and preferences" />

      <Tabs defaultValue="account">
        <TabsList>
          <TabsTrigger value="account" className="cursor-pointer">
            Account
          </TabsTrigger>
          <TabsTrigger value="appearance" className="cursor-pointer">
            Appearance
          </TabsTrigger>
          <TabsTrigger value="orgs" className="cursor-pointer">
            Organizations
          </TabsTrigger>
        </TabsList>

        <TabsContent value="account" className="mt-4 flex flex-col gap-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Account details</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="first">First name</Label>
                  <Input id="first" defaultValue={user?.first_name ?? ""} readOnly />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="last">Last name</Label>
                  <Input id="last" defaultValue={user?.last_name ?? ""} readOnly />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="email">Email</Label>
                <Input id="email" defaultValue={user?.email ?? ""} readOnly />
              </div>
              {/* Honest about the current state rather than showing inputs that
                  silently discard what you type. */}
              <p className="text-sm text-muted-foreground">
                Profile editing is not available yet — the API is read-only for
                account details.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Session</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Copy your short-lived access token for use with{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">curl</code>.
                It expires in 15 minutes. For anything long-lived, mint an API
                token under Organization settings instead.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={copyAccessToken}
                className="w-fit cursor-pointer"
              >
                {copied ? (
                  <Check className="size-4" aria-hidden />
                ) : (
                  <Copy className="size-4" aria-hidden />
                )}
                {copied ? "Copied" : "Copy access token"}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="appearance" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Theme</CardTitle>
            </CardHeader>
            <CardContent>
              <div
                role="radiogroup"
                aria-label="Theme"
                className="grid grid-cols-3 gap-2"
              >
                {themeOptions.map(({ value, label, icon: Icon }) => (
                  <button
                    key={value}
                    role="radio"
                    aria-checked={theme === value}
                    onClick={() => applyTheme(value)}
                    className={cn(
                      "flex cursor-pointer flex-col items-center gap-2 rounded-lg border p-4 text-sm transition-colors",
                      theme === value
                        ? "border-primary bg-primary/10 font-medium text-primary"
                        : "border-border hover:bg-muted",
                    )}
                  >
                    <Icon className="size-5" aria-hidden />
                    {label}
                  </button>
                ))}
              </div>
              <p className="mt-3 text-sm text-muted-foreground">
                System follows your operating system setting.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="orgs" className="mt-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Your organizations</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="divide-y divide-border rounded-md border border-border">
                {orgs.map((o) => (
                  <li
                    key={o.id}
                    className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm"
                  >
                    <span className="truncate">{o.name}</span>
                    {o.id === org?.id && (
                      <span className="shrink-0 rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                        Current
                      </span>
                    )}
                  </li>
                ))}
                {orgs.length === 0 && (
                  <li className="px-3 py-6 text-center text-sm text-muted-foreground">
                    You are not a member of any organization yet.
                  </li>
                )}
              </ul>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
