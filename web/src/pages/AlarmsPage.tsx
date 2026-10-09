import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations, type Suppression } from "../Actions";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { formatDoseValue, formatPolicyMeasurement } from "../format";
import { describeLifecycle, kindLabel, statusLabel } from "./alarmLifecycle";
import { useWebRefresh } from "../live";
import { isSourceAlarmActionable, type ActiveAlarm } from "../activeAlarms";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  formatTimestamp,
} from "../ui";

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
  policy_event?: PolicyEvent;
  is_active?: boolean;
  source_i_flag?: number;
  source_actionable?: boolean;
};

type AlarmHistoryResponse = { items: PolicyEvent[]; total: number; limit: number; offset: number; has_more: boolean };

function normalizeHistory(items: PolicyEvent[]): PolicyEvent[] {
  return items.map((item) => {
    if (item.event_type === "policy_lifecycle") return item;
    if (item.policy_event && (!item.is_active || item.policy_event.status === "ACTIVE")) return { ...item.policy_event, source_alarm: item, event_type: "policy_lifecycle" };
    return {
      ...item,
      event_id: `source:${item.source_id}:${item.serid}:${item.event_time}`,
      kind: "SOURCE_ALARM",
      reason: item.level === "ALARM" ? "HIGH_THRESHOLD" : "LOW_THRESHOLD",
      surfaced_at: item.event_time,
      measured_value: item.measured_value,
      threshold: item.threshold,
      event_type: "source_alarm",
    };
  });
}

function LifecycleDescription({ event }: { event: PolicyEvent }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const lifecycle = describeLifecycle(event);
  if (!lifecycle) return <>—</>;
  return (
    <span className="alarm-lifecycle">
      <span>{lifecycle.label}</span>
      <Button type="button" variant="secondary" onClick={() => dialog.current?.showModal()}>Rincian</Button>
      <dialog ref={dialog} className="native-user-dialog" aria-label={`Rincian SERID ${event.serid}`} data-testid="alarm-lifecycle-dialog">
        <div className="native-user-dialog-content"><h2>Rincian</h2><p>SERID {event.serid} · {eventLabel(event)} · {statusLabel(event.status, event.kind)}</p>
          <ul>{lifecycle.raw.map((detail) => <li key={detail}><code>{detail}</code></li>)}</ul>
          <div className="form-actions"><Button type="button" variant="secondary" onClick={() => dialog.current?.close()}>Tutup</Button></div>
        </div>
      </dialog>
    </span>
  );
}

function EventOrigin({ event }: { event: PolicyEvent }) {
  const sourceOwned = event.event_type === "source_alarm" || Boolean(event.source_alarm) || Boolean(event.source_reconciliation) || event.status === "SOURCE_HANDLED";
  return <Badge variant={sourceOwned ? "secondary" : "success"}>{sourceOwned ? (event.source_id || "Sumber") : "Pusat"}</Badge>;
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

function SourceActionButton({ event, onAction }: { event: PolicyEvent; onAction?: (eventId: string) => void }) {
  if (!onAction || !event.event_id || !isSourceAlarmActionable(event as ActiveAlarm)) return null;
  return <Button type="button" variant="secondary" onClick={() => onAction(event.event_id!)}>Tindak lanjuti sumber</Button>;
}

function EventCards({ events, onAction }: { events: PolicyEvent[]; onAction?: (eventId: string) => void }) {
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
            <span>Muncul: {formatTimestamp(event.surfaced_at)}</span>
            {describeLifecycle(event) ? <span>Aksi: <LifecycleDescription event={event} /></span> : null}
            <SourceActionButton event={event} onAction={onAction} />
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function EventTable({ events, onAction }: { events: PolicyEvent[]; onAction?: (eventId: string) => void }) {
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
              <Table.Cell><Badge variant={eventVariant(event)}>{statusLabel(event.status, event.kind)}</Badge></Table.Cell>
              <Table.Cell>{formatPolicyMeasurement(event)}</Table.Cell>
              <Table.Cell>{formatDoseValue(event.threshold)}</Table.Cell>
              <Table.Cell>{formatTimestamp(event.surfaced_at)}</Table.Cell>
              <Table.Cell><LifecycleDescription event={event} /> <SourceActionButton event={event} onAction={onAction} /></Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function AlarmsPage() {
  const requestedEventId = new URLSearchParams(window.location.search).get("event");
  const [actionEventId, setActionEventId] = useState<string | null>(requestedEventId);
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
        description="Tinjau alarm aktif, catat tindak lanjut, dan lihat riwayat perubahan alarm."
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
            description="Alarm yang masih berbunyi pada alat sumber dipisahkan dari peristiwa aturan. Hanya alarm sumber yang dapat ditangani di panel tindakan."
            className="active-alarm-section"
          >
            <div className="active-alarm-list" aria-live="polite">
              {!activeLoaded ? <LoadingCard label="Memuat status alarm sumber…" /> : activeError ? <><ErrorCard message={`Status alarm sumber tidak tersedia: ${activeError}. Status terakhir belum terverifikasi; alarm tidak dianggap sunyi.`} />{summary.sourceActive.length ? <><p className="cell-subtle">Snapshot alarm sumber terakhir (belum terverifikasi):</p><EventCards events={summary.sourceActive as PolicyEvent[]} /></> : null}</> : <EventCards events={summary.sourceActive as PolicyEvent[]} />}
            </div>
            {!activeError && summary.policyActive.length ? <div className="active-alarm-list" aria-label="Aturan aktif informasional"><p className="cell-subtle">Aturan aktif (informasi; tidak membuka respons sumber):</p><EventCards events={summary.policyActive as PolicyEvent[]} /></div> : null}
          </PageSection>

          <div className="metric-grid alarm-summary">
            <MetricCard label="Aktif (sumber)" value={activeError || !activeLoaded ? "—" : summary.sourceActive.length} badge={<Badge variant={activeError || !activeLoaded ? "warning" : summary.sourceActive.length ? "error" : "success"}>{activeError || !activeLoaded ? "Status tidak tersedia" : summary.sourceActive.length ? "Perlu tindakan" : "Tidak ada alarm yang berbunyi"}</Badge>} />
            {summary.policyActive.length ? <MetricCard label="Aturan aktif (informasi)" value={summary.policyActive.length} badge={<span className="cell-subtle">Tidak membuka respons sumber</span>} /> : null}
            <MetricCard label="Alarm ditahan sementara" value={items === null ? "—" : summary.retriggerLocked} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Menunggu pemicu baru"}</span>} />
            <MetricCard label="Alarm diredam" value={items === null ? "—" : summary.suppressed} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Sesuai pengaturan"}</span>} />
            <MetricCard label="Catatan terbaru" value={items === null ? "—" : summary.total} badge={<span className="cell-subtle">{items === null ? "Riwayat tidak tersedia" : "Riwayat alarm"}</span>} />
          </div>

          <PageSection title="Tindakan operator" description="Catat respons dan penanggung jawab alarm, atau redam alarm stasiun untuk waktu tertentu. Perubahan memerlukan PIN operator.">
            {suppressionError ? (
              <div className="alarm-suppression-error">
                <ErrorCard message={`Daftar peredaman tidak tersedia: ${suppressionError}`} />
                <Button variant="secondary" onClick={() => void loadSuppressions()}>Muat ulang peredaman</Button>
              </div>
            ) : null}
            <AlarmOperations events={activeItems} sourceEvents={sourceItems} sourceStatus={!activeLoaded ? "loading" : activeError ? "error" : "ready"} activeError={activeError} suppressions={suppressions} suppressionsStatus={!suppressionLoaded ? "loading" : suppressionError ? "error" : "ready"} onChanged={() => void load()} initialEventId={actionEventId} />
          </PageSection>

          <PageSection title="Riwayat alarm" description="Lihat alarm alat dan perubahan pengaturan alarm berdasarkan waktu.">
            {items === null ? historyLoaded ? <p className="cell-subtle" role="status">Riwayat alarm belum tersedia.</p> : <LoadingCard label="Memuat riwayat alarm…" /> : <>
              <ResponsiveDataView
                desktop={<EventTable events={items} onAction={setActionEventId} />}
                mobile={<EventCards events={items} onAction={setActionEventId} />}
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
    </div>
  );
}
