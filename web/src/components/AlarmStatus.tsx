import { useEffect, useState } from "react";
import type { Station } from "../api";
import { formatDoseValue } from "../format";

export type AlarmPresentation = "alarm" | "warning" | "historical" | null;

const notifiedAlarmEvents = new Set<string>();

export function alarmPresentation(station: Station): AlarmPresentation {
  if (
    station.status === "alarm" && station.policy_state === "ALARM" &&
    station.underlying_dose_status === "ALARM" && station.active_event_id &&
    station.active_event_lifecycle === "ACTIVE"
  ) return "alarm";
  if (station.status === "warning" || (
    station.status === "alarm" && station.policy_state !== "ALARM" &&
    (station.policy_state === "SUPPRESSED" || station.policy_state === "RETRIGGER_LOCKED")
  )) return "warning";
  if (station.status === "offline" && (station.active_event_id || station.last_event_id)) return "historical";
  return null;
}

export function hasActiveThresholdEvent(station: Station): boolean {
  return (station.status === "warning" || station.status === "alarm") &&
    station.policy_state === "ALARM" && Boolean(station.active_event_id) &&
    station.active_event_lifecycle === "ACTIVE";
}

export function AlarmStatus({ station, onAction }: { station: Station; onAction?: (station: Station) => void }) {
  const presentation = alarmPresentation(station);
  if (!presentation) return null;
  const label = presentation === "alarm"
    ? "ALARM aktif — perlu tindakan"
    : presentation === "warning"
      ? hasActiveThresholdEvent(station) ? "Ambang rendah aktif — perlu tindakan" : station.status === "alarm" ? `Ambang alarm — aturan ${station.policy_state === "SUPPRESSED" ? "diredam" : "terkunci"}` : "Peringatan ambang"
      : "Alarm terakhir — data offline, tidak sedang berbunyi";
  const isActive = hasActiveThresholdEvent(station);
  return (
    <span className={`alarm-status alarm-status-${presentation}`}>
      <span className={`alarm-status-dot${isActive ? " is-blinking" : ""}`} aria-hidden="true" />
      <span>{label}</span>
      {isActive && onAction ? (
        <button type="button" className="alarm-action-link" onClick={() => onAction(station)}>
          Tindak lanjuti alarm
        </button>
      ) : null}
    </span>
  );
}

export function AlarmNotification({ station, onAction }: { station: Station; onAction?: (station: Station) => void }) {
  if (!hasActiveThresholdEvent(station)) return null;
  return <DeduplicatedAlarmNotification station={station} onAction={onAction} />;
}

function DeduplicatedAlarmNotification({ station, onAction }: { station: Station; onAction?: (station: Station) => void }) {
  const [visible, setVisible] = useState(false);
  const eventId = station.active_event_id!;
  useEffect(() => {
    if (notifiedAlarmEvents.has(eventId)) return;
    notifiedAlarmEvents.add(eventId);
    setVisible(true);
  }, [eventId]);
  if (!visible) return null;
  return (
    <div className={`alarm-notification ${station.status === "warning" ? "is-warning" : "is-alarm"}`} role="alert" aria-live="assertive" aria-atomic="true">
      <span className="alarm-status-dot is-blinking" aria-hidden="true" />
      <span><strong>{station.status === "alarm" ? "Ambang tinggi aktif:" : "Ambang rendah aktif:"}</strong> {station.name} ({formatDoseValue(station.doserate)} {station.unit})</span>
      {onAction ? <button type="button" className="alarm-action-link" onClick={() => onAction(station)}>Buka tindakan alarm</button> : null}
      <button type="button" className="alarm-notification-dismiss" onClick={() => setVisible(false)} aria-label="Tutup notifikasi alarm">Tutup</button>
    </div>
  );
}
