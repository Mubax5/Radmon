export type PolicyEvent = Record<string, unknown> & {
  event_id?: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
  action?: string | null;
  reason?: string | null;
  resolution_code?: string | null;
  resolution_reason?: string | null;
  source_reconciliation?: { status?: string; reason?: string } | null;
  event_type?: "source_alarm" | "policy_lifecycle";
  event_time?: string;
  level?: string;
  source_id?: string;
  remote_serid?: number;
  policy_event?: PolicyEvent;
  is_active?: boolean;
  source_i_flag?: number;
  source_actionable?: boolean;
};

function looksLikeSourceAlarm(item: PolicyEvent): boolean {
  return item.event_type === "source_alarm"
    || (item.source_id != null && item.event_time != null && item.remote_serid != null);
}

/** Keep the physical source row canonical when a policy event is correlated. */
export function normalizeHistory(items: PolicyEvent[]): PolicyEvent[] {
  return items.map((item) => {
    if (item.event_type === "policy_lifecycle") return item;
    if (looksLikeSourceAlarm(item)) {
      return {
        ...item,
        event_id: item.event_id ?? `source:${item.source_id}:${item.serid}:${item.event_time}`,
        kind: "SOURCE_ALARM",
        reason: item.reason ?? (item.level === "ALARM" ? "HIGH_THRESHOLD" : "LOW_THRESHOLD"),
        surfaced_at: item.event_time ?? item.surfaced_at,
        measured_value: item.measured_value,
        threshold: item.threshold,
        event_type: "source_alarm",
      };
    }
    if (item.policy_event) {
      return { ...item.policy_event, source_alarm: item, event_type: "policy_lifecycle" };
    }
    return item;
  });
}
