export type ActiveAlarm = {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  event_type?: string;
  is_active?: boolean;
  source_i_flag?: number;
  source_actionable?: boolean;
  source_id?: string;
  remote_serid?: number;
  event_time?: string;
  surfaced_at?: string;
  reason?: string | null;
  measured_value?: number | null;
  threshold?: number | null;
};

export function isSourceAlarmActionable(event: ActiveAlarm | undefined): boolean {
  if (!event) return false;
  if (event.event_type !== "source_alarm" || event.status !== "ACTIVE") return false;
  if (event.source_actionable === false || event.is_active === false || event.source_i_flag === 1) return false;
  return Boolean(event.source_id && event.event_time);
}

export function alarmResponseRequest(event: ActiveAlarm, fields: { pin: string; action: string; pic: string; reason: string }) {
  if (event.status !== "ACTIVE") throw new Error("Alarm tidak lagi aktif");
  if (event.event_type === "source_alarm") {
    if (!isSourceAlarmActionable(event)) throw new Error("Alarm sumber tidak lagi berbunyi; muat ulang status.");
    if (!event.source_id || !event.event_time) throw new Error("Identitas alarm sumber tidak lengkap");
    return {
      route: `/api/v1/control/alarms/${encodeURIComponent(event.source_id)}/${event.serid}/ack`,
      body: { pin: fields.pin, action: fields.action, pic: fields.pic, note: fields.reason, event_time: event.event_time },
    };
  }
  return { route: `/api/v1/control/alarm-events/${encodeURIComponent(event.event_id)}/response`, body: fields };
}

export function confirmAlarmResponse(event: ActiveAlarm, result: { status?: string; is_active?: boolean; source_i_flag?: number; acknowledged_at?: string }) {
  if (event.event_type === "source_alarm") {
    const alreadyHandled = result.status === "ALREADY_HANDLED";
    if (result.is_active !== false || result.source_i_flag !== 1 || (!result.acknowledged_at && !alreadyHandled)) throw new Error("Sumber belum mengonfirmasi alarm tidak aktif; muat ulang status.");
  } else if (result.status !== "RESPONDED") throw new Error("Respons policy belum terkonfirmasi; muat ulang status.");
}
