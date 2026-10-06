import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { alarmSoundEnabled, freshUndeliveredEvents, playAlarmSignal, type PolicyAlarmEvent } from "../alarmNotifications";
import { navigate } from "../navigation";

type EventPage = { events: PolicyAlarmEvent[]; next_cursor: string | null; has_more: boolean };
const CURSOR_KEY = "radmon-policy-alarm-cursor";
const DELIVERED_KEY = "radmon-policy-alarm-delivered";

export function PolicyAlarmNotifications({ enabled }: { enabled: boolean }) {
  const [events, setEvents] = useState<PolicyAlarmEvent[]>([]);
  const [soundOn, setSoundOn] = useState(alarmSoundEnabled);
  const delivered = useRef(new Set<string>());
  const cursor = useRef<string | null>(null);

  useEffect(() => {
    try {
      delivered.current = new Set<string>(JSON.parse(localStorage.getItem(DELIVERED_KEY) ?? "[]"));
      cursor.current = localStorage.getItem(CURSOR_KEY);
    } catch {
      delivered.current = new Set();
      cursor.current = null;
    }
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
                  body: `Measurement ${event.measured_value ?? "—"}. Buka Alarm untuk tindakan operator.`,
                  tag: event.event_id,
                });
                notification.onclick = () => { window.focus(); navigate("alarms", { event: event.event_id }); notification.close(); };
              }
            });
            playAlarmSignal();
            localStorage.setItem(DELIVERED_KEY, JSON.stringify([...delivered.current].slice(-1000)));
          }
          cursor.current = page.next_cursor;
          if (cursor.current) localStorage.setItem(CURSOR_KEY, cursor.current);
          if (!page.has_more) break;
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
  }, [enabled]);

  if (!enabled) return null;
  const enableAlerts = async () => {
    // Construct/resume audio inside the explicit operator gesture for autoplay policy.
    if (window.AudioContext) {
      const context = new window.AudioContext();
      await context.resume();
      await context.close();
    }
    localStorage.setItem("radmon-alarm-sound", "enabled");
    setSoundOn(true);
    if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  };

  return (
    <aside className="policy-alarm-center" aria-live="assertive" aria-label="Notifikasi alarm policy">
      <div className="policy-alarm-controls">
        <button type="button" onClick={() => void enableAlerts()}>
          {soundOn ? "Suara alarm aktif" : "Aktifkan suara & notifikasi desktop"}
        </button>
        {soundOn ? <button type="button" onClick={() => { localStorage.setItem("radmon-alarm-sound", "disabled"); setSoundOn(false); }}>Matikan suara</button> : null}
        <small>
          {"Notification" in window
            ? Notification.permission === "granted" ? "Notifikasi desktop diizinkan" : Notification.permission === "denied" ? "Notifikasi desktop diblokir di pengaturan browser" : "Izinkan notifikasi desktop saat mengaktifkan suara"
            : "Notifikasi dalam aplikasi aktif; browser ini tidak mendukung desktop notification"}
        </small>
      </div>
      {events.map((event) => (
        <div className="policy-alarm-toast" key={event.event_id} role="alert">
          <strong>{event.reason === "LOW_THRESHOLD" ? "LOW threshold" : "HIGH threshold"} · SERID {event.serid}</strong>
          <span>Measurement {event.measured_value ?? "—"}</span>
          <button type="button" onClick={() => navigate("alarms", { event: event.event_id })}>Buka Alarm</button>
          <button type="button" aria-label="Tutup notifikasi" onClick={() => setEvents((current) => current.filter((item) => item.event_id !== event.event_id))}>Tutup</button>
        </div>
      ))}
    </aside>
  );
}
