export type AlarmLifecycleEvent = {
  kind?: string | null;
  status?: string | null;
  action?: string | null;
  reason?: string | null;
  resolution_code?: string | null;
  resolution_reason?: string | null;
  source_reconciliation?: { status?: string | null; reason?: string | null } | null;
};

const STATUS_LABELS: Record<string, string> = {
  ACTIVE: "Aktif — perlu tindakan",
  RESPONDED: "Ditanggapi operator",
  AUTO_RESOLVED_NORMAL: "Pulih otomatis — bacaan kembali normal",
  SOURCE_HANDLED: "Ditangani pada alat sumber",
  RESOLVED: "Selesai",
  NORMAL: "Normal",
  ENDED: "Berakhir",
  SUPPRESSED: "Dalam supresi",
  AUTO_SILENCED: "Diredam otomatis",
  RETRIGGER_LOCKED: "Pengulangan alarm ditahan",
  PENDING: "Menunggu konfirmasi",
  AMBIGUOUS: "Perlu pemeriksaan operator",
  CONFIRMED: "Terkonfirmasi",
};

const REASON_LABELS: Record<string, string> = {
  EXACT_SOURCE_ALARM_NOT_OBSERVED: "Menunggu konfirmasi alarm dari alat",
  AMBIGUOUS_SOURCE_CORRELATION: "Bukti alarm sumber belum cukup",
  SOURCE_EVENT_LINK_CONFLICT: "Tautan alarm sumber perlu diperiksa",
  SOURCE_ID_MISSING: "Identitas alat sumber belum tersedia",
  SOURCE_ALARM_STILL_ACTIVE: "Alarm pada alat sumber masih aktif",
  SOURCE_HANDLED_TIME_MISSING: "Waktu penanganan alat sumber belum tersedia",
  SOURCE_HANDLED_TIME_BEFORE_OCCURRENCE: "Waktu penanganan alat sumber perlu diperiksa",
  EXACT_SOURCE_I_FLAG_CONFIRMED: "Penanganan pada alat sumber terkonfirmasi",
  POLICY_EVENT_NOT_ACTIVE: "Event tidak lagi aktif untuk dikonfirmasi",
  POLICY_STATE_NOT_LINKED: "Menunggu sinkronisasi status alarm",
  SOURCE_EVENT_LINK_NOT_WRITTEN: "Menunggu sinkronisasi tautan alarm sumber",
  AUTO_RESOLVED_NORMAL: "Bacaan kembali normal",
  EXPIRED: "Supresi berakhir: kedaluwarsa",
  AUTO_NORMAL: "Supresi berakhir: bacaan kembali normal",
  CANCELLED: "Supresi berakhir: dihentikan operator",
  LOW_THRESHOLD: "Bacaan melewati ambang peringatan rendah",
  HIGH_THRESHOLD: "Bacaan melewati ambang alarm tinggi",
};

function humanizeCode(code: string): string {
  return code.toLowerCase().split(/[_:\s]+/).filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
}

export function statusLabel(status: string | null | undefined, fallback?: string | null): string {
  const value = status || fallback || "UNKNOWN";
  return STATUS_LABELS[value] ?? humanizeCode(value);
}

export function kindLabel(kind: string | null | undefined): string {
  if (!kind) return "Event alarm";
  if (kind === "ALARM") return "Alarm";
  if (kind === "RETRIGGER_LOCKED") return "Pengulangan alarm ditahan";
  if (kind === "SUPPRESSED") return "Alarm tersupresi";
  if (kind === "SUPPRESSION_END") return "Supresi berakhir";
  return humanizeCode(kind);
}

function reasonLabel(reason: string | null | undefined): string | null {
  if (!reason) return null;
  const code = reason.split(":", 1)[0];
  return REASON_LABELS[code] ?? humanizeCode(reason);
}

export function describeLifecycle(event: AlarmLifecycleEvent): { label: string; raw: string[] } | null {
  const reconciliation = event.source_reconciliation;
  if (reconciliation) {
    const state = (reconciliation.status || "PENDING").toUpperCase();
    const reason = reconciliation.reason;
    let label: string;
    if (state === "AMBIGUOUS") label = "Bukti alarm sumber belum cukup";
    else if (state === "PENDING") label = reasonLabel(reason) ?? "Menunggu konfirmasi alarm dari alat";
    else if (state === "SOURCE_HANDLED" || state === "CONFIRMED") label = "Ditangani pada alat sumber";
    else label = statusLabel(state);
    return {
      label,
      raw: [
        `kind: ${event.kind ?? "(kosong)"}`,
        `status: ${event.status ?? "(kosong)"}`,
        `source_reconciliation.status: ${reconciliation.status ?? "(kosong)"}`,
        `source_reconciliation.reason: ${reason ?? "(kosong)"}`,
      ],
    };
  }

  if (event.kind === "SUPPRESSION_END") {
    const reason = event.reason ?? event.action;
    return {
      label: reasonLabel(reason) ?? "Supresi berakhir",
      raw: [`kind: ${event.kind ?? "(kosong)"}`, `status: ${event.status ?? "(kosong)"}`, `action: ${event.action ?? "(kosong)"}`, `reason: ${event.reason ?? "(kosong)"}`],
    };
  }

  const code = event.resolution_code || (event.status === "AUTO_RESOLVED_NORMAL" || event.status === "SOURCE_HANDLED" ? event.status : null);
  if (code) {
    return {
      label: statusLabel(code),
      raw: [`kind: ${event.kind ?? "(kosong)"}`, `status: ${event.status ?? "(kosong)"}`, `resolution_code: ${event.resolution_code ?? "(kosong)"}`, `resolution_reason: ${event.resolution_reason ?? "(kosong)"}`],
    };
  }
  if (event.status || event.kind || event.reason) {
    return {
      label: statusLabel(event.status, event.kind),
      raw: [`kind: ${event.kind ?? "(kosong)"}`, `status: ${event.status ?? "(kosong)"}`, `reason: ${event.reason ?? "(kosong)"}`],
    };
  }
  return null;
}
