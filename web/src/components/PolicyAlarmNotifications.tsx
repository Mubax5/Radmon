import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { freshUndeliveredEvents, notificationStateLabel, playAlarmSignal, type PolicyAlarmEvent } from "../alarmNotifications";
import { navigate } from "../navigation";
import { formatTimestamp } from "../ui";

type EventPage = { events: PolicyAlarmEvent[]; next_cursor: string | null; has_more: boolean };
export function PolicyAlarmNotifications({ enabled }: { enabled: boolean }) {
  const [events, setEvents] = useState<PolicyAlarmEvent[]>([]);
  const [soundOn, setSoundOn] = useState(false);
  const delivered = useRef(new Set<string>());
  const cursor = useRef<string | null>(null);
  const visibleEvents = useRef(events);
  visibleEvents.current = events;

  useEffect(() => {
    const enableSound = () => setSoundOn(true);
    const disableSound = () => setSoundOn(false);
    window.addEventListener("radmon:alarm-sound-enabled", enableSound);
    window.addEventListener("radmon:alarm-sound-disabled", disableSound);
    return () => {
      window.removeEventListener("radmon:alarm-sound-enabled", enableSound);
      window.removeEventListener("radmon:alarm-sound-disabled", disableSound);
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let busy = false;
    const poll = async () => {
      if (busy || disposed) return;
      busy = true;
      try {
        // Drain bounded pages so bursts cannot leap over the client's cursor.
        for (let pageCount = 0; pageCount < 5; pageCount += 1) {
          const suffix = cursor.current ? `?cursor=${encodeURIComponent(cursor.current)}` : "";
          const page = await api<EventPage>(`/api/v1/control/alarm-events/since${suffix}`);
          if (disposed) return;
          const fresh = freshUndeliveredEvents(page.events, delivered.current);
          if (fresh.length) {
            setEvents((current) => [...fresh, ...current].slice(0, 20));
            fresh.forEach((event) => {
              if ("Notification" in window && Notification.permission === "granted") {
                const notification = new Notification(`${event.reason === "LOW_THRESHOLD" ? "LOW" : "HIGH"} threshold · SERID ${event.serid}`, {
                  body: `Measurement ${event.measured_value ?? "—"} · ${formatTimestamp(event.surfaced_at)} · ${notificationStateLabel(event)}.`,
                  tag: event.event_id,
                });
                notification.onclick = () => { window.focus(); navigate("alarms", { event: event.event_id }); notification.close(); };
              }
            });
            playAlarmSignal(soundOn);
          }
          cursor.current = page.next_cursor;
          if (!page.has_more) break;
        }
        if (visibleEvents.current.length) {
          const recent = await api<PolicyAlarmEvent[]>("/api/v1/control/alarm-events");
          if (!disposed) setEvents((current) => current.map((item) => recent.find((row) => row.event_id === item.event_id) ?? item));
        }
      } catch {
        // Offline/stale reads do not advance the cursor or synthesize an alarm.
      } finally {
        busy = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 5000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [enabled, soundOn]);

  if (!enabled) return null;
  if (!events.length) return null;
  return (
    <aside className="policy-alarm-center" aria-live="assertive" aria-label="Notifikasi alarm policy">
      {events.map((event) => (
        <div className="policy-alarm-toast" key={event.event_id} role="alert">
          <strong>{event.reason === "LOW_THRESHOLD" ? "LOW threshold" : "HIGH threshold"} · SERID {event.serid}</strong>
          <span>Measurement {event.measured_value ?? "—"}</span>
          <span>{formatTimestamp(event.surfaced_at)} · {notificationStateLabel(event)}</span>
          <button type="button" onClick={() => navigate("alarms", { event: event.event_id })}>Buka Alarm</button>
          <button type="button" aria-label="Tutup notifikasi" onClick={() => setEvents((current) => current.filter((item) => item.event_id !== event.event_id))}>Tutup</button>
        </div>
      ))}
    </aside>
  );
}
