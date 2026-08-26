"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

/**
 * Query client for the dashboard.
 *
 * Defaults are tuned for an ops tool: data that is seconds old is fine to show
 * instantly, but anything the user comes back to should quietly refresh.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  // Created in state, not at module scope: a module-level client would be
  // shared across all users on the server and leak one tenant's cache into
  // another's render.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Monitors change on their check interval (20s+), so a few seconds
            // of staleness is invisible and saves a request on every
            // navigation.
            staleTime: 10_000,
            // Keep results for five minutes so back-navigation is instant.
            gcTime: 5 * 60_000,
            // Coming back to the tab during an incident should show current
            // data without a manual refresh.
            refetchOnWindowFocus: true,
            refetchOnReconnect: true,
            // 401s are handled by the API client (refresh then redirect);
            // retrying them just delays the redirect.
            retry: (count, err) => {
              const status = (err as { status?: number })?.status;
              if (status === 401 || status === 403 || status === 404) return false;
              return count < 2;
            },
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
