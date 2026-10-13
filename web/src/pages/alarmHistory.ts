export type PolicyEvent = Record<string, unknown> & {
  event_id?: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
  action?: string | null;
  response_action?: string | null;
  reason?: string | null;
  resolution_code?: string | null;
  resolution_reason?: string | null;
  source_reconciliation?: { status?: string; reason?: string } | null;
  event_type?: "source_alarm" | "policy_lifecycle";
  event_time?: string;
  source_id?: string;
  remote_serid?: number;
  name?: string | null;
  station_name?: string | null;
  location?: string | null;
  unit?: string | null;
  level?: string | null;
  acknowledged_at?: string | null;
  source_observed_at?: string | null;
  response_actor?: string | null;
  response_pic?: string | null;
  acknowledged_by?: string | null;
  operator_name?: string | null;
  note?: string | null;
  response_note?: string | null;
  acknowledged_note?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  resolved_at?: string | null;
  duration_seconds?: number | null;
  suppression_started_at?: string | null;
  expires_at?: string | null;
  suppression_expires_at?: string | null;
  suppression_ended_at?: string | null;
  suppression_pic?: string | null;
  policy_event?: PolicyEvent;
  is_active?: boolean;
  source_i_flag?: number;
  source_actionable?: boolean;
};

function looksLikeSourceAlarm(item: PolicyEvent): boolean {
  return item.event_type === "source_alarm"
    || (item.source_id != null && item.event_time != null && item.remote_serid != null);
}

function sourceFlag(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return parsed === 0 || parsed === 1 ? parsed : null;
}

/** Keep the physical source row canonical when a policy event is correlated. */
export function normalizeHistory(items: PolicyEvent[]): PolicyEvent[] {
  return items.map((item) => {
    if (item.event_type === "policy_lifecycle") return item;
    if (looksLikeSourceAlarm(item)) {
      // The physical latch is authoritative.  A policy event may already be
      // normal after a reading, while source_i_flag=0 still means that the
      // detector alarm is sounding.
      const source_i_flag = sourceFlag(item.source_i_flag);
      const sourceStatus = source_i_flag === 0
        ? "ACTIVE"
        : source_i_flag === 1
          ? "ACKNOWLEDGED"
          : item.status;
      return {
        ...item,
        event_id: item.event_id ?? `source:${item.source_id}:${item.serid}:${item.event_time}`,
        kind: "SOURCE_ALARM",
        status: sourceStatus,
        reason: item.reason ?? (item.level === "ALARM" ? "HIGH_THRESHOLD" : "LOW_THRESHOLD"),
        surfaced_at: item.event_time ?? item.surfaced_at,
        measured_value: item.measured_value,
        threshold: item.threshold,
        source_i_flag: source_i_flag ?? item.source_i_flag,
        is_active: source_i_flag == null ? item.is_active : source_i_flag === 0,
        event_type: "source_alarm",
      };
    }
    if (item.policy_event) {
      return { ...item.policy_event, source_alarm: item, event_type: "policy_lifecycle" };
    }
    return item;
  });
}
