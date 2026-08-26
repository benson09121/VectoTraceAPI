"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * The one interactive island on an otherwise server-rendered page.
 *
 * The backend answers identically whether or not the address is already
 * subscribed, so this message is deliberately non-committal too — saying
 * "already subscribed" here would leak who watches the page.
 */
export function SubscribeForm({ slug }: { slug: string }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");

  async function subscribe(e: React.FormEvent) {
    e.preventDefault();
    setState("busy");
    try {
      await api.subscribePublic(slug, email);
      setState("done");
      setEmail("");
    } catch (err: any) {
      if (err.status === 429) {
        setState("error");
        return;
      }
      setState("error");
    }
  }

  if (state === "done") {
    return (
      <section className="mt-8 rounded-lg border p-4">
        <p className="text-sm">
          Check your inbox for a verification link to confirm your subscription.
        </p>
      </section>
    );
  }

  return (
    <section className="mt-8 rounded-lg border p-4">
      <h2 className="font-medium">Get notified</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Subscribe to receive updates when an incident is opened or resolved.
      </p>

      <form onSubmit={subscribe} className="mt-3 flex flex-wrap items-end gap-3">
        <div className="min-w-56 flex-1 space-y-2">
          <Label htmlFor="subscribe-email">Email</Label>
          <Input
            id="subscribe-email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </div>
        <Button type="submit" disabled={state === "busy"}>
          {state === "busy" ? "Subscribing…" : "Subscribe"}
        </Button>
      </form>

      {state === "error" && (
        <p role="alert" className="mt-2 text-sm text-destructive">
          Could not subscribe right now. Please try again shortly.
        </p>
      )}
    </section>
  );
}
