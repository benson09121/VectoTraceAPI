"use client";

/**
 * Notification channel picker.
 *
 * The backend speaks ~210 Apprise schemas, but the UI used to offer three
 * hardcoded options, so every other provider was unreachable from the product.
 * This exposes the full set.
 *
 * A 210-item `<select>` is unusable, so this is a searchable command palette
 * grouped by category, with the popular providers surfaced first. The schema
 * list is fetched from the API rather than duplicated here — hardcoding it
 * would drift the moment Apprise is upgraded.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, CaretUpDown, MagnifyingGlass } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Curated metadata for the providers people actually reach for. Anything not
 * listed still works — it just appears under "All providers" with a generic
 * hint instead of a tailored one.
 */
export const POPULAR: Record<
  string,
  { label: string; category: string; example: string; native?: boolean }
> = {
  // `native: true` means the provider uses our own tested handler instead of
  // Apprise, and therefore takes an **https webhook URL** — not an
  // apprise-style `scheme://` URL. The picker must not advertise "slack://"
  // for these, or the hint contradicts what the field actually accepts and the
  // save fails with "config.url must be an https:// URL".
  slack: {
    label: "Slack",
    category: "Chat",
    native: true,
    example: "https://hooks.slack.com/services/T000/B000/XXXXXXXX",
  },
  discord: {
    label: "Discord",
    category: "Chat",
    native: true,
    example: "https://discord.com/api/webhooks/123456/abcdef",
  },
  webhook: {
    label: "Generic webhook",
    category: "Webhook",
    native: true,
    example: "https://example.com/hooks/vectotrace",
  },
  tgram: { label: "Telegram", category: "Chat", example: "tgram://bot_token/chat_id" },
  msteams: { label: "Microsoft Teams", category: "Chat", example: "msteams://TokenA/TokenB/TokenC" },
  matrix: { label: "Matrix", category: "Chat", example: "matrix://user:pass@hostname/#room" },
  rocket: { label: "Rocket.Chat", category: "Chat", example: "rocket://user:pass@host/#channel" },
  gchat: { label: "Google Chat", category: "Chat", example: "gchat://workspace/key/token" },
  mailto: { label: "Email (SMTP)", category: "Email", example: "mailto://user:pass@gmail.com" },
  mailtos: { label: "Email (SMTP over TLS)", category: "Email", example: "mailtos://user:pass@smtp.host.com" },
  ntfy: { label: "ntfy", category: "Push", example: "ntfy://topic" },
  gotify: { label: "Gotify", category: "Push", example: "gotify://hostname/token" },
  pover: { label: "Pushover", category: "Push", example: "pover://user_key@token" },
  pushbullet: { label: "Pushbullet", category: "Push", example: "pbul://accesstoken" },
  twilio: { label: "Twilio SMS", category: "SMS", example: "twilio://sid:token@from/to" },
  pagerduty: { label: "PagerDuty", category: "On-call", example: "pagerduty://key@integration" },
  opsgenie: { label: "Opsgenie", category: "On-call", example: "opsgenie://apikey" },
  json: { label: "Generic JSON webhook", category: "Webhook", example: "json://hostname/path" },
  form: { label: "Generic form POST", category: "Webhook", example: "form://hostname/path" },
};

const CATEGORY_ORDER = ["Chat", "Email", "Push", "SMS", "On-call", "Webhook"];

export function ChannelPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (schema: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { data: schemas = [], isLoading: loading } = useQuery({
    queryKey: ["channel-schemas"],
    queryFn: async () => {
      try {
        const d = await api.channelSchemas();
        return d.schemas;
      } catch {
        return Object.keys(POPULAR);
      }
    }
  });

  const groups = useMemo(() => {
    const known = new Set(Object.keys(POPULAR));
    const byCategory: Record<string, string[]> = {};

    for (const s of Object.keys(POPULAR)) {
      if (!schemas.length || schemas.includes(s)) {
        (byCategory[POPULAR[s].category] ??= []).push(s);
      }
    }
    const rest = schemas.filter((s) => !known.has(s)).sort();
    if (rest.length) byCategory["All providers"] = rest;

    return [...CATEGORY_ORDER, "All providers"]
      .filter((c) => byCategory[c]?.length)
      .map((c) => ({ category: c, items: byCategory[c] }));
  }, [schemas]);

  const selected = POPULAR[value];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          aria-label="Notification provider"
          className="w-full cursor-pointer justify-between font-normal"
        >
          <span className="truncate">
            {selected ? selected.label : value || "Choose a provider…"}
            {!selected && value && (
              <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                {value}://
              </span>
            )}
          </span>
          <CaretUpDown className="size-4 shrink-0 opacity-50" aria-hidden />
        </Button>
      </PopoverTrigger>

      <PopoverContent align="start" side="bottom" className="w-[--radix-popover-trigger-width] p-0">
        <Command>
          <div className="flex items-center border-b border-border px-3">
            <MagnifyingGlass className="mr-2 size-4 shrink-0 opacity-50" aria-hidden />
            <CommandInput
              placeholder={
                loading ? "Loading providers…" : `Search ${schemas.length || ""} providers…`
              }
              className="border-0 focus:ring-0"
            />
          </div>
          <CommandList className="max-h-72">
            <CommandEmpty>
              No provider matches. Try the scheme name, e.g. &ldquo;tgram&rdquo;.
            </CommandEmpty>
            {groups.map((g) => (
              <CommandGroup key={g.category} heading={g.category}>
                {g.items.map((s) => (
                  <CommandItem
                    key={s}
                    // Search both the human label and the raw scheme, so
                    // "telegram" and "tgram" both find Telegram.
                    value={`${s} ${POPULAR[s]?.label ?? ""}`}
                    onSelect={() => {
                      onChange(s);
                      setOpen(false);
                    }}
                    className="cursor-pointer"
                  >
                    <Check
                      className={cn(
                        "mr-2 size-4",
                        value === s ? "opacity-100" : "opacity-0",
                      )}
                      aria-hidden
                    />
                    <span className="flex-1">{POPULAR[s]?.label ?? s}</span>
                    {/* Show the scheme the FIELD wants, not the provider's
                        Apprise name — otherwise Slack reads "slack://" while
                        the input requires https. */}
                    <span className="font-mono text-xs text-muted-foreground">
                      {POPULAR[s]?.native ? "https://" : `${s}://`}
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}

/** The URL shape for the chosen provider, shown as a hint under the input. */
export function schemaExample(schema: string): string {
  return POPULAR[schema]?.example ?? `${schema}://…`;
}

/**
 * True when the provider uses our own handler rather than Apprise, and so
 * takes an https webhook URL. Exported so the form derives the right label and
 * placeholder from one place instead of each caller hardcoding a list that can
 * drift out of sync with this table.
 */
export function isNativeProvider(schema: string): boolean {
  return POPULAR[schema]?.native === true;
}
