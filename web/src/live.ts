import { useEffect, useRef } from "react";
import { subscribeWebEvents, type WebEvent } from "./api";

type RefreshCallback = () => void | Promise<unknown>;

export function useWebRefresh(
  refresh: RefreshCallback,
  acceptedTypes: readonly string[] = ["live_update"],
  debounceMs = 500,
) {
  const refreshRef = useRef<RefreshCallback>(refresh);
  const typesRef = useRef(acceptedTypes);

  refreshRef.current = refresh;
  typesRef.current = acceptedTypes;

  useEffect(() => {
    let timer: number | undefined;
    let inFlight = false;
    let pending = false;
    let disposed = false;

    const runRefresh = async () => {
      timer = undefined;
      if (inFlight) {
        pending = true;
        return;
      }

      inFlight = true;
      try {
        await refreshRef.current();
      } catch {
        // Page loaders own visible error state; refresh hints must never create
        // an unhandled rejection or break the SSE subscription.
      } finally {
        inFlight = false;
        if (disposed || !pending) return;
        pending = false;
        timer = window.setTimeout(() => { void runRefresh(); }, debounceMs);
      }
    };

    const close = subscribeWebEvents((event: WebEvent) => {
      if (!typesRef.current.includes(event.type)) return;
      if (inFlight) {
        pending = true;
        return;
      }
      if (timer !== undefined) window.clearTimeout(timer);
      timer = window.setTimeout(() => { void runRefresh(); }, debounceMs);
    });

    return () => {
      disposed = true;
      close();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [debounceMs]);
}
