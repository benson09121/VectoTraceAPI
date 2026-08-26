"use client";

import { useEffect, useRef, useState } from "react";
import { eventStreamUrl } from "./api";
import type { MonitorEvent } from "./types";

type Handler = (event: MonitorEvent) => void;

/**
 * Subscribe to the org's live monitor events.
 *
 * EventSource reconnects on its own, so there is no retry logic here — the
 * backend caps a stream at an hour and the browser simply dials back. The
 * handler is held in a ref so a re-render doesn't tear down the connection.
 */
export function useMonitorEvents(orgId: number | string | null, onEvent: Handler) {
  const [connected, setConnected] = useState(false);
  const handlerRef = useRef<Handler>(onEvent);

  // Assigning during render would be a ref write in render; do it here.
  useEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!orgId) return;

    const source = new EventSource(eventStreamUrl(orgId));

    const dispatch = (e: MessageEvent) => {
      try {
        handlerRef.current(JSON.parse(e.data) as MonitorEvent);
      } catch {
        // A malformed frame is not worth killing the stream over.
      }
    };

    source.addEventListener("connected", () => setConnected(true));
    source.addEventListener("check", dispatch);
    source.addEventListener("incident_opened", dispatch);
    source.addEventListener("incident_resolved", dispatch);
    source.onerror = () => setConnected(false);

    return () => {
      source.close();
      setConnected(false);
    };
  }, [orgId]);

  return { connected };
}
