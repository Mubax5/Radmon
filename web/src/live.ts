import { useEffect, useRef } from "react";
import { subscribeWebEvents, type WebEvent } from "./api";

export function useWebRefresh(
  refresh: () => void,
  acceptedTypes: readonly string[] = ["live_update"],
  debounceMs = 500,
) {
  const refreshRef = useRef(refresh);
  const typesRef = useRef(acceptedTypes);

  refreshRef.current = refresh;
  typesRef.current = acceptedTypes;

  useEffect(() => {
    let timer: number | undefined;
    const close = subscribeWebEvents((event: WebEvent) => {
      if (!typesRef.current.includes(event.type)) return;
      if (timer !== undefined) window.clearTimeout(timer);
      timer = window.setTimeout(() => refreshRef.current(), debounceMs);
    });

    return () => {
      close();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [debounceMs]);
}
