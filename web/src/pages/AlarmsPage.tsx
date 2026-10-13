import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations, type Suppression } from "../Actions";
import { useSession } from "../auth";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { formatDoseValue, formatPolicyMeasurement } from "../format";
import { describeLifecycle, kindLabel, lifecycleReasonLabel, statusLabel } from "./alarmLifecycle";
import { normalizeHistory, type PolicyEvent } from "./alarmHistory";
import { useWebRefresh } from "../live";
import { isSourceAlarmActionable, type ActiveAlarm } from "../activeAlarms";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  Modal,
  PageHeading,
  PageSection,
} from "../ui";

type AlarmHistoryResponse = { items: PolicyEvent[]; total: number; limit: number; offset: number; has_more: boolean };

function PolicyOutcome({ event }: { event: PolicyEvent }) {
  if (event.event_type !== "source_alarm" || !event.policy_event) return null;
  return <span className="cell-subtle">Aturan pusat: {statusLabel(event.policy_event.status, event.policy_event.kind)}</span>;
}

function EventOrigin({ event }: { event: PolicyEvent }) {
  const sourceOwned = event.event_type === "source_alarm" || Boolean(event.source_alarm) || Boolean(event.source_reconciliation) || event.status === "SOURCE_HANDLED";
  const sourceLabel = textValue(event.source_id);
  return <Badge variant={sourceOwned ? "secondary" : "success"}>{sourceOwned ? (sourceLabel === "Tidak tersedia" ? "Alat sumber" : sourceLabel) : "Pusat"}</Badge>;
}

function eventVariant(event: PolicyEvent): "success" | "warning" | "error" | "secondary" {
  if (["ALARM", "SOURCE_ALARM"].includes(event.kind) && event.status === "ACTIVE") return event.reason === "LOW_THRESHOLD" ? "warning" : "error";
  if (["RESPONDED", "AUTO_RESOLVED_NORMAL", "SOURCE_HANDLED", "RESOLVED", "NORMAL", "ENDED"].includes(event.status)) return "success";
  if (event.kind === "RETRIGGER_LOCKED") return "warning";
  if (event.kind === "SUPPRESSED") return "warning";
  return "secondary";
}

function eventLabel(event: PolicyEvent): string {
  if (event.kind === "SOURCE_ALARM") return event.level === "ALERT" ? "Peringatan" : "Alarm";
  if (event.kind === "ALARM" && event.reason === "LOW_THRESHOLD") return "Peringatan";
  if (event.kind === "ALARM" && event.reason === "HIGH_THRESHOLD") return "Alarm";
  return kindLabel(event.kind);
}

function textValue(value: unknown): string {
  if (value == null) return "Tidak tersedia";
  if (typeof value === "string") {
    const cleaned = value.replace(/[\u0000-\u001f\u007f]/g, " ").trim().slice(0, 512);
    return cleaned || "Tidak tersedia";
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "Tidak tersedia";
}

function firstValue(event: PolicyEvent, keys: string[]): unknown {
  for (const key of keys) {
    const value = event[key];
    if (value !== null && value !== undefined && value !== "") return value;
  }
  return null;
}

function formatAlarmTime(value: unknown): string {
  if (value == null || value === "") return "Tidak tersedia";
  const raw = String(value).trim();
  if (!raw) return "Tidak tersedia";
  // Source timestamps without an offset are already emitted in WIB. Keep
  // that original clock value instead of silently applying the browser zone.
  if (!/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)) return `${raw.replace("T", " ")} WIB`;
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return `${raw} WIB`;
  return `${new Intl.DateTimeFormat("id-ID", {
    timeZone: "Asia/Jakarta",
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(parsed)} WIB`;
}

function formatDuration(value: unknown): string {
  const seconds = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return textValue(value);
  if (seconds < 60) return `${Math.round(seconds)} detik`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes} menit${remainder ? ` ${remainder} detik` : ""}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} jam${minutes % 60 ? ` ${minutes % 60} menit` : ""}`;
}

function formatAlarmNumber(value: unknown): string {
  if (value !== null && value !== undefined && typeof value !== "number" && typeof value !== "string") return "Tidak tersedia";
  const formatted = formatDoseValue(value as number | string | null | undefined);
  return formatted === "—" ? "Tidak tersedia" : formatted;
}

function sourceFlag(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return parsed === 0 || parsed === 1 ? parsed : null;
}

function sourceStatusLabel(event: PolicyEvent): string {
  const flag = sourceFlag(event.source_i_flag);
  if (flag === 0 || (flag == null && event.is_active === true)) return "Alarm masih berbunyi";
  if (flag === 1 || event.is_active === false) return "Alarm tidak lagi berbunyi dari alat";
  return statusLabel(event.status, event.kind);
}

function severityLabel(event: PolicyEvent): string {
  if (event.level === "ALERT" || event.reason === "HIGH_THRESHOLD") return "Alarm";
  if (event.level === "WARNING" || event.reason === "LOW_THRESHOLD") return "Peringatan";
  return eventLabel(event);
}

function DetailField({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="alarm-detail-field"><dt>{label}</dt><dd>{value}</dd></div>;
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="alarm-detail-section"><h3>{title}</h3><dl className="alarm-detail-grid">{children}</dl></section>;
}

function AlarmDetailContent({ event, canViewResponse }: { event: PolicyEvent; canViewResponse: boolean }) {
  const policyEvent = event.policy_event;
  const lifecycle = describeLifecycle(event);
  // Lifecycle values are used only to retain the existing domain contract;
  // their internal keys are never rendered as a technical dump.
  const lifecycleDetailCount = lifecycle ? lifecycle.raw.map(() => 1).length : 0;
  const stationName = firstValue(event, ["station_name", "name"]);
  const stationLocation = firstValue(event, ["location"]);
  const unit = firstValue(event, ["unit"]);
  const isSource = event.event_type === "source_alarm";
  const responseActor = firstValue(event, ["response_actor"]);
  const responseNote = firstValue(event, ["response_note"]);
  const responseAction = firstValue(event, ["response_action"]);
  const hasHandling = isSource || responseActor !== null || responseAction !== null || responseNote !== null || event.acknowledged_at != null;
  const isSuppression = event.kind === "SUPPRESSION_START" || event.kind === "SUPPRESSION_END" || event.suppression_id != null
    || firstValue(event, ["suppression_started_at", "suppression_expires_at", "suppression_ended_at"]) !== null;
  const sourceTime = firstValue(event, ["event_time", "surfaced_at"]);
  const centralTime = policyEvent ? firstValue(policyEvent, ["surfaced_at", "event_time"]) : !isSource ? firstValue(event, ["surfaced_at", "event_time"]) : null;
  const endedTime = firstValue(event, ["ended_at", "resolved_at"]);
  const suppressionReason = lifecycleReasonLabel(firstValue(event, ["response_note", "resolution_reason"]) as string | null);
  const reconciliation = event.source_reconciliation;

  return (
    <div className="alarm-detail-body" data-lifecycle-details={lifecycleDetailCount || undefined}>
      <DetailSection title="Alarm">
        <DetailField label="Nama stasiun" value={textValue(stationName)} />
        <DetailField label="Lokasi" value={textValue(stationLocation)} />
        <DetailField label="SERID" value={textValue(event.serid)} />
        <DetailField label="Sumber" value={event.event_type === "source_alarm" ? textValue(event.source_id || "Alat sumber") : "Pusat"} />
        <DetailField label="Jenis" value={eventLabel(event)} />
        <DetailField label="Keparahan" value={severityLabel(event)} />
        <DetailField label="Bacaan" value={formatAlarmNumber(event.measured_value)} />
        <DetailField label="Satuan" value={textValue(unit)} />
        <DetailField label="Ambang" value={formatAlarmNumber(event.threshold)} />
        <DetailField label="Jumlah pemicu" value={textValue(event.hit_count)} />
        {isSource ? <DetailField label="Status alarm sumber" value={sourceStatusLabel(event)} /> : <DetailField label="Status" value={statusLabel(event.status, event.kind)} />}
        {policyEvent ? <DetailField label="Status aturan pusat" value={statusLabel(policyEvent.status, policyEvent.kind)} /> : null}
        {reconciliation ? <DetailField label="Keterangan aturan pusat" value={lifecycleReasonLabel(reconciliation.reason) ?? statusLabel(reconciliation.status, "PENDING")} /> : null}
      </DetailSection>

      {hasHandling ? (
        <DetailSection title="Penanganan">
          {canViewResponse ? <DetailField label="PIC" value={textValue(responseActor)} /> : null}
          <DetailField label="Tindakan operator" value={canViewResponse ? textValue(responseAction) : "Tidak tersedia"} />
          <DetailField label="Waktu ditangani" value={formatAlarmTime(event.acknowledged_at)} />
          <DetailField label="Catatan operator" value={canViewResponse ? textValue(responseNote) : "Tidak tersedia"} />
        </DetailSection>
      ) : null}

      <DetailSection title="Waktu">
        {isSource ? <DetailField label="Waktu alarm sumber" value={formatAlarmTime(sourceTime)} /> : null}
        {policyEvent ? <DetailField label="Waktu aturan pusat" value={formatAlarmTime(centralTime)} /> : null}
        {!isSource && !policyEvent ? <DetailField label="Waktu peristiwa" value={formatAlarmTime(sourceTime)} /> : null}
        <DetailField label="Waktu pemantauan sumber" value={formatAlarmTime(event.source_observed_at)} />
        {event.started_at != null ? <DetailField label="Waktu mulai" value={formatAlarmTime(event.started_at)} /> : null}
        {endedTime != null ? <DetailField label="Waktu berakhir" value={formatAlarmTime(endedTime)} /> : null}
        {event.duration_seconds != null ? <DetailField label="Durasi" value={formatDuration(event.duration_seconds)} /> : null}
      </DetailSection>

      {isSuppression ? (
        <DetailSection title="Supresi">
          <DetailField label="Mulai" value={formatAlarmTime(firstValue(event, ["suppression_started_at", "started_at", "surfaced_at"]))} />
          <DetailField label="Berakhir direncanakan" value={formatAlarmTime(firstValue(event, ["suppression_expires_at", "expires_at"]))} />
          <DetailField label="Berakhir aktual" value={formatAlarmTime(firstValue(event, ["suppression_ended_at", "ended_at"]))} />
          {canViewResponse ? <DetailField label="PIC" value={textValue(event.response_actor)} /> : null}
          <DetailField label="Alasan" value={textValue(suppressionReason)} />
          {event.suppression_id ? <DetailField label="Referensi" value={textValue(event.suppression_id)} /> : null}
        </DetailSection>
      ) : null}
    </div>
  );
}

function AlarmDetailsModal({ event, onClose }: { event: PolicyEvent | null; onClose: () => void }) {
  const { user } = useSession();
  const dialogRef = useRef<HTMLDialogElement>(null);
  return (
    // Modal opens the native dialog with showModal() and restores focus.
    <Modal
      open={event !== null}
      onOpenChange={(open) => { if (!open) onClose(); }}
      title="Rincian"
      dialogRef={dialogRef}
      className="alarm-detail-modal"
      data-testid="alarm-lifecycle-dialog"
    >
      {event ? <AlarmDetailContent event={event} canViewResponse={user?.role !== "Viewer"} /> : null}
      <div className="form-actions"><Button type="button" variant="secondary" onClick={onClose}>Tutup</Button></div>
    </Modal>
  );
}

function DetailButton({ event, onDetails }: { event: PolicyEvent; onDetails: (event: PolicyEvent) => void }) {
  return <Button type="button" variant="secondary" onClick={() => onDetails(event)}>Rincian</Button>;
}

function EventCards({ events, onDetails }: { events: PolicyEvent[]; onDetails: (event: PolicyEvent) => void }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada peristiwa alarm.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {events.map((event) => (
        <LayerCard className="alarm-card" key={event.event_id}>
          <div className="alarm-card-header">
            <div>
              <h3>SERID {event.serid}</h3>
              <div className="cell-subtle">{eventLabel(event)} · <EventOrigin event={event} /></div>
            </div>
            <Badge variant={eventVariant(event)}>{statusLabel(event.status, event.kind)}</Badge>
          </div>
          <div className="card-meta">
            <span>Pengukuran: {formatPolicyMeasurement(event)}</span>
            <span>Ambang: {formatDoseValue(event.threshold)}</span>
            <span>Muncul: {formatAlarmTime(event.surfaced_at)}</span>
            <PolicyOutcome event={event} />
            <DetailButton event={event} onDetails={onDetails} />
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function EventTable({ events, onDetails }: { events: PolicyEvent[]; onDetails: (event: PolicyEvent) => void }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada peristiwa alarm.</LayerCard>;
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Stasiun</Table.Head>
            <Table.Head>Sumber / jenis</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Pengukuran</Table.Head>
              <Table.Head>Ambang</Table.Head>
              <Table.Head>Muncul</Table.Head>
              <Table.Head>Aksi</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {events.map((event) => (
            <Table.Row key={event.event_id ?? `${event.source_id}:${event.serid}:${event.event_time}`}>
              <Table.Cell><strong>SERID {event.serid}</strong></Table.Cell>
              <Table.Cell><div className="alarm-event-origin"><EventOrigin event={event} />{eventLabel(event)}</div></Table.Cell>
              <Table.Cell><Badge variant={eventVariant(event)}>{statusLabel(event.status, event.kind)}</Badge><PolicyOutcome event={event} /></Table.Cell>
              <Table.Cell>{formatPolicyMeasurement(event)}</Table.Cell>
              <Table.Cell>{formatDoseValue(event.threshold)}</Table.Cell>
              <Table.Cell>{formatAlarmTime(event.surfaced_at)}</Table.Cell>
              <Table.Cell><DetailButton event={event} onDetails={onDetails} /></Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function AlarmsPage() {
  const requestedEventId = new URLSearchParams(window.location.search).get("event");
  const [actionEventId] = useState<string | null>(requestedEventId);
  const [detailEvent, setDetailEvent] = useState<PolicyEvent | null>(null);
  const [soundOn, setSoundOn] = useState(false);
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [activeItems, setActiveItems] = useState<ActiveAlarm[]>([]);
  const [sourceItems, setSourceItems] = useState<ActiveAlarm[]>([]);
  const [activeLoaded, setActiveLoaded] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [activeError, setActiveError] = useState("");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [suppressions, setSuppressions] = useState<Suppression[]>([]);
  const [error, setError] = useState("");
  const [suppressionError, setSuppressionError] = useState("");
  const [suppressionLoaded, setSuppressionLoaded] = useState(false);
  const loadSuppressions = () => {
    setSuppressionLoaded(false);
    return api<Suppression[]>("/api/v1/control/suppressions?active_only=true")
    .then((activeSuppressions) => {
      setSuppressions(activeSuppressions);
      setSuppressionError("");
      setSuppressionLoaded(true);
    })
     .catch((e) => { setSuppressionError(e instanceof Error ? e.message : "Tidak dapat memuat peredaman"); setSuppressionLoaded(true); });
  };
  const load = (offset = historyOffset) => Promise.allSettled([
    api<AlarmHistoryResponse>(`/api/v1/web/alarm-history?limit=500&offset=${offset}`),
    api<Suppression[]>("/api/v1/control/suppressions?active_only=true"),
    api<{ items: ActiveAlarm[]; source_items?: ActiveAlarm[] }>("/api/v1/web/active-alarms").then((currentAlarms) => {
      setActiveLoaded(true);
      setActiveItems(currentAlarms.items);
      // Older isolated fixtures may only return items. The production API
      // always returns source_items, which is the authoritative split.
      setSourceItems((currentAlarms.source_items ?? currentAlarms.items.filter(isSourceAlarmActionable)).filter(isSourceAlarmActionable));
      setActiveError("");
    }).catch((reason: unknown) => {
      setActiveLoaded(true);
      // Preserve the last successful snapshot, but mark it unavailable so a
      // read failure can never masquerade as a confirmed zero-source state.
      setActiveError(reason instanceof Error ? reason.message : "Tidak dapat memuat alarm aktif");
    }),
  ])
    .then(([events, activeSuppressions]) => {
      if (events.status === "fulfilled") {
        setItems(normalizeHistory(events.value.items));
        setHistoryOffset(events.value.offset);
        setHistoryTotal(events.value.total);
        setError("");
        setHistoryLoaded(true);
      } else {
        setError(events.reason instanceof Error ? events.reason.message : "Tidak dapat memuat alarm");
        setHistoryLoaded(true);
      }
      if (activeSuppressions.status === "fulfilled") {
        setSuppressions(activeSuppressions.value);
        setSuppressionError("");
        setSuppressionLoaded(true);
      } else {
         setSuppressionError(activeSuppressions.reason instanceof Error ? activeSuppressions.reason.message : "Tidak dapat memuat peredaman");
        setSuppressionLoaded(true);
      }
    });

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); }, ["live_update"]);

  const summary = useMemo(() => {
    const events = items ?? [];
    const retriggerLocked = events.filter((event) => event.kind === "RETRIGGER_LOCKED").length;
    const suppressed = events.filter((event) => event.kind === "SUPPRESSED").length;
    return {
      active: activeItems,
      sourceActive: sourceItems,
      policyActive: activeItems.filter((event) => event.event_type === "policy_lifecycle"),
      retriggerLocked,
      suppressed,
      total: events.length,
    };
  }, [items, activeItems, sourceItems]);

  const isInitialLoading = items === null && !activeLoaded && !historyLoaded && !error;
  const eventsFailedOnFirstLoad = items === null && Boolean(error);
  const openDetails = (event: PolicyEvent) => setDetailEvent(event);
  const enableAlarmAlerts = async () => {
    // Explicit click grants autoplay eligibility before later alarm beeps.
    if (window.AudioContext) {
      const context = new window.AudioContext();
      await context.resume();
      await context.close();
    }
    setSoundOn(true);
    window.dispatchEvent(new Event("radmon:alarm-sound-enabled"));
    if ("Notification" in window && Notification.permission === "default") await Notification.requestPermission();
  };

  return (
    <div className="page-stack">
      <PageHeading
        title="Alarm"
        description="Status dan riwayat alarm."
        action={<div className="form-actions">
          <Button variant="secondary" onClick={() => void load()}>Muat ulang</Button>
          <Button variant={soundOn ? "secondary" : "primary"} onClick={() => {
            if (soundOn) {
              setSoundOn(false);
              window.dispatchEvent(new Event("radmon:alarm-sound-disabled"));
            } else void enableAlarmAlerts();
          }}>{soundOn ? "Suara alarm aktif · Matikan" : "Aktifkan suara alarm"}</Button>
        </div>}
      />
      <p className="cell-subtle alarm-notification-permission">
        {"Notification" in window
          ? Notification.permission === "granted" ? "Notifikasi desktop diizinkan." : Notification.permission === "denied" ? "Notifikasi desktop diblokir di pengaturan browser; notifikasi dalam aplikasi tetap aktif." : "Klik Aktifkan suara alarm untuk suara dan izin notifikasi desktop."
          : "Suara memerlukan aktivasi operator; notifikasi dalam aplikasi tetap aktif."}
      </p>
      {error && items !== null ? <ErrorCard message={`Data alarm mungkin usang: ${error}`} /> : null}
      {isInitialLoading ? <LoadingCard label="Memuat alarm…" /> : null}
      {eventsFailedOnFirstLoad ? (
        <div className="alarm-events-error">
          <ErrorCard message={error} />
          <div className="form-actions">
            <Button variant="secondary" onClick={() => void load()}>Muat ulang alarm</Button>
          </div>
        </div>
      ) : null}
      {items || activeLoaded ? (
        <>
          <PageSection
            title="Alarm aktif"
            description="Alarm yang masih berbunyi."
            className="active-alarm-section"
          >
            <div className="active-alarm-list" aria-live="polite">
              {!activeLoaded ? <LoadingCard label="Memuat status alarm sumber…" /> : activeError ? <><ErrorCard message={`Status alarm sumber tidak tersedia: ${activeError}. Status terakhir belum terverifikasi; alarm tidak dianggap sunyi.`} />{summary.sourceActive.length ? <><p className="cell-subtle">Snapshot alarm sumber terakhir (belum terverifikasi):</p><EventCards events={summary.sourceActive as PolicyEvent[]} onDetails={openDetails} /></> : null}</> : <EventCards events={summary.sourceActive as PolicyEvent[]} onDetails={openDetails} />}
            </div>
            {!activeError && summary.policyActive.length ? <div className="active-alarm-list" aria-label="Aturan aktif informasional"><p className="cell-subtle">Aturan aktif (informasi; tidak membuka respons sumber):</p><EventCards events={summary.policyActive as PolicyEvent[]} onDetails={openDetails} /></div> : null}
          </PageSection>

          <div className="metric-grid alarm-summary">
            <MetricCard label="Aktif (sumber)" value={activeError || !activeLoaded ? "—" : summary.sourceActive.length} badge={<Badge variant={activeError || !activeLoaded ? "warning" : summary.sourceActive.length ? "error" : "success"}>{activeError || !activeLoaded ? "Status tidak tersedia" : summary.sourceActive.length ? "Perlu tindakan" : "Tidak ada alarm yang berbunyi"}</Badge>} />
            {summary.policyActive.length ? <MetricCard label="Aturan aktif (informasi)" value={summary.policyActive.length} badge={<span className="cell-subtle">Tidak membuka respons sumber</span>} /> : null}
            <MetricCard label="Alarm ditahan sementara" value={items === null ? "—" : summary.retriggerLocked} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Menunggu pemicu baru"}</span>} />
            <MetricCard label="Alarm diredam" value={items === null ? "—" : summary.suppressed} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Sesuai pengaturan"}</span>} />
            <MetricCard label="Catatan terbaru" value={items === null ? "—" : summary.total} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Riwayat alarm"}</span>} />
          </div>

          <PageSection title="Tindakan operator" description="Respons alarm dan peredaman. Memerlukan PIN.">
            {suppressionError ? (
              <div className="alarm-suppression-error">
                <ErrorCard message={`Daftar peredaman tidak tersedia: ${suppressionError}`} />
                <Button variant="secondary" onClick={() => void loadSuppressions()}>Muat ulang peredaman</Button>
              </div>
            ) : null}
            <AlarmOperations events={activeItems} sourceEvents={sourceItems} sourceStatus={!activeLoaded ? "loading" : activeError ? "error" : "ready"} activeError={activeError} suppressions={suppressions} suppressionsStatus={!suppressionLoaded ? "loading" : suppressionError ? "error" : "ready"} onChanged={() => void load()} initialEventId={actionEventId} />
          </PageSection>

          <PageSection title="Riwayat alarm" description="Riwayat alarm dan perubahan status.">
            {items === null ? historyLoaded ? <p className="cell-subtle" role="status">Riwayat alarm belum tersedia.</p> : <LoadingCard label="Memuat riwayat alarm…" /> : <>
              <ResponsiveDataView
                desktop={<EventTable events={items} onDetails={openDetails} />}
                mobile={<EventCards events={items} onDetails={openDetails} />}
              />
              <div className="form-actions" aria-label="Navigasi riwayat peristiwa">
                <span className="cell-subtle">{historyTotal === 0 ? "0 peristiwa" : `${historyOffset + 1}–${Math.min(historyOffset + items.length, historyTotal)} dari ${historyTotal}`}</span>
                <Button variant="secondary" disabled={historyOffset === 0} onClick={() => void load(Math.max(0, historyOffset - 500))}>Sebelumnya</Button>
                <Button variant="secondary" disabled={historyOffset + items.length >= historyTotal} onClick={() => void load(historyOffset + 500)}>Berikutnya</Button>
              </div>
            </>}
          </PageSection>
        </>
      ) : null}
      <AlarmDetailsModal event={detailEvent} onClose={() => setDetailEvent(null)} />
    </div>
  );
}
