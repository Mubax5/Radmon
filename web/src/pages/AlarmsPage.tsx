import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Input, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations, type Suppression } from "../Actions";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { formatDoseValue, formatPolicyMeasurement } from "../format";
import { describeLifecycle, kindLabel, statusLabel } from "./alarmLifecycle";
import { useWebRefresh } from "../live";
import { useSession } from "../auth";
import type { ActiveAlarm } from "../activeAlarms";
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

function SourceAlarmResponse({ event, onChanged }: { event: PolicyEvent; onChanged: () => void }) {
  const { user } = useSession();
  const dialog = useRef<HTMLDialogElement>(null);
  const [action, setAction] = useState("Konfirmasi");
  const [pic, setPic] = useState(user?.display_name ?? "");
  const [note, setNote] = useState("");
  const [pin, setPin] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState("");
  useEffect(() => { setPic(user?.display_name ?? ""); }, [user?.display_name]);
  if (!user || user.role === "Viewer" || event.event_type !== "source_alarm" || event.status !== "ACTIVE" || !event.source_id || !event.event_time) return null;
  async function submit(formEvent: React.FormEvent) {
    formEvent.preventDefault();
    if (pending || !event.source_id || !event.event_time) return;
    setPending(true);
    setFeedback("");
    try {
      const result = await api<{ status?: string; is_active?: boolean; source_i_flag?: number; acknowledged_at?: string }>(`/api/v1/control/alarms/${encodeURIComponent(event.source_id)}/${event.serid}/ack`, {
        method: "POST",
        body: JSON.stringify({ event_time: event.event_time, action, pic, note, pin }),
      });
      if (result.is_active !== false || result.source_i_flag !== 1 || (!result.acknowledged_at && result.status !== "ALREADY_HANDLED")) throw new Error("Sumber belum mengonfirmasi perubahan i_flag; alarm tetap aktif.");
      setFeedback(result.status === "ALREADY_HANDLED"
        ? "Alarm sumber sudah ditangani sebelumnya; i_flag=1 terkonfirmasi."
        : "Sumber mengonfirmasi alarm ditangani (i_flag diperbarui ke 1).");
      dialog.current?.close();
      onChanged();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "Respons sumber gagal");
    } finally {
      setPin("");
      setPending(false);
    }
  }
  return <>
    <Button type="button" variant="secondary" onClick={() => dialog.current?.showModal()}>Tindak lanjuti sumber</Button>
    {feedback ? <span role="status">{feedback}</span> : null}
    <dialog ref={dialog} className="native-user-dialog" aria-label={`Respons alarm sumber SERID ${event.serid}`}>
      <form className="native-user-dialog-content action-form" onSubmit={(e) => void submit(e)}>
        <h2>Matikan alarm di sumber</h2>
        <p>Operasi ini menulis i_op, PIC, catatan, dan i_flag=1 pada baris sumber yang dipilih. Kolom ack legacy tidak diubah; PIN operator diperlukan.</p>
        <Input label="Action" value={action} onChange={(e) => setAction(e.target.value)} disabled={pending} required />
        <Input label="PIC" value={pic} onChange={(e) => setPic(e.target.value)} readOnly={user.role !== "Administrator"} disabled={pending} required />
        <Input label="Catatan" value={note} onChange={(e) => setNote(e.target.value)} disabled={pending} />
        <Input label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} disabled={pending} required />
        {feedback ? <p role="alert">{feedback}</p> : null}
        <div className="form-actions"><Button type="submit" variant="primary" disabled={pending || !pic || !pin}>{pending ? "Memperbarui sumber…" : "Matikan alarm sumber"}</Button><Button type="button" variant="secondary" disabled={pending} onClick={() => dialog.current?.close()}>Batal</Button></div>
      </form>
    </dialog>
  </>;
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

function EventCards({ events, onChanged }: { events: PolicyEvent[]; onChanged: () => void }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada event alarm.</LayerCard>;
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
            <SourceAlarmResponse event={event} onChanged={onChanged} />
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function EventTable({ events, onChanged }: { events: PolicyEvent[]; onChanged: () => void }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada event alarm.</LayerCard>;
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
              <Table.Cell><LifecycleDescription event={event} /> <SourceAlarmResponse event={event} onChanged={onChanged} /></Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function AlarmsPage() {
  const { user } = useSession();
  const requestedEventId = new URLSearchParams(window.location.search).get("event");
  const [soundOn, setSoundOn] = useState(false);
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [activeItems, setActiveItems] = useState<ActiveAlarm[]>([]);
  const [activeLoaded, setActiveLoaded] = useState(false);
  const [activeError, setActiveError] = useState("");
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [suppressions, setSuppressions] = useState<Suppression[]>([]);
  const [error, setError] = useState("");
  const [suppressionError, setSuppressionError] = useState("");
  const loadSuppressions = () => api<Suppression[]>("/api/v1/control/suppressions?active_only=true")
    .then((activeSuppressions) => {
      setSuppressions(activeSuppressions);
      setSuppressionError("");
    })
    .catch((e) => setSuppressionError(e instanceof Error ? e.message : "Tidak dapat memuat suppression"));
  const load = (offset = historyOffset) => Promise.allSettled([
    api<AlarmHistoryResponse>(`/api/v1/web/alarm-history?limit=500&offset=${offset}`),
    api<Suppression[]>("/api/v1/control/suppressions?active_only=true"),
    api<{ items: ActiveAlarm[] }>("/api/v1/web/active-alarms").then((currentAlarms) => {
      setActiveLoaded(true);
      setActiveItems(currentAlarms.items);
      setActiveError("");
    }).catch((reason: unknown) => {
      setActiveLoaded(true);
      setActiveItems([]);
      setActiveError(reason instanceof Error ? reason.message : "Tidak dapat memuat alarm aktif");
    }),
  ])
    .then(([events, activeSuppressions]) => {
      if (events.status === "fulfilled") {
        setItems(normalizeHistory(events.value.items));
        setHistoryOffset(events.value.offset);
        setHistoryTotal(events.value.total);
        setError("");
      } else {
        setError(events.reason instanceof Error ? events.reason.message : "Tidak dapat memuat alarm");
      }
      if (activeSuppressions.status === "fulfilled") {
        setSuppressions(activeSuppressions.value);
        setSuppressionError("");
      } else {
        setSuppressionError(activeSuppressions.reason instanceof Error ? activeSuppressions.reason.message : "Tidak dapat memuat suppression");
      }
    });

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); }, ["live_update"]);

  const summary = useMemo(() => {
    const events = items ?? [];
    const retriggerLocked = events.filter((event) => event.kind === "RETRIGGER_LOCKED").length;
    const suppressed = events.filter((event) => event.kind === "SUPPRESSED").length;
    return { active: activeItems, retriggerLocked, suppressed, total: events.length };
  }, [items, activeItems]);

  const isInitialLoading = items === null && !activeLoaded && !error;
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
            description="Event aktif yang perlu ditinjau. Gunakan notifikasi suara/desktop di bagian atas; respons operator dan suppression tersedia pada kontrol tindakan di bawah."
            className="active-alarm-section"
          >
            <div className="active-alarm-list" aria-live="polite">
              {activeError ? <ErrorCard message={`Status alarm aktif tidak tersedia: ${activeError}`} /> : <EventCards events={summary.active as PolicyEvent[]} onChanged={() => void load()} />}
            </div>
          </PageSection>

          <div className="metric-grid alarm-summary">
            <MetricCard label="Aktif" value={activeError ? "—" : summary.active.length} badge={<Badge variant={activeError ? "warning" : summary.active.length ? "error" : "success"}>{activeError ? "Status tidak tersedia" : summary.active.length ? "Perlu tindakan" : "Tidak ada alarm aktif"}</Badge>} />
            <MetricCard label="Alarm ditahan sementara" value={summary.retriggerLocked} badge={<span className="cell-subtle">Menunggu pemicu baru</span>} />
            <MetricCard label="Alarm diredam" value={summary.suppressed} badge={<span className="cell-subtle">Sesuai pengaturan</span>} />
            <MetricCard label="Catatan terbaru" value={summary.total} badge={<span className="cell-subtle">Riwayat alarm</span>} />
          </div>

          <PageSection title="Tindakan operator" description="Catat respons dan penanggung jawab alarm, atau redam alarm stasiun untuk waktu tertentu. Perubahan memerlukan PIN operator.">
            {suppressionError ? (
              <div className="alarm-suppression-error">
                <ErrorCard message={`Daftar suppression tidak tersedia: ${suppressionError}`} />
                <Button variant="secondary" onClick={() => void loadSuppressions()}>Muat ulang suppression</Button>
              </div>
            ) : null}
            <AlarmOperations events={activeItems} activeError={activeError} suppressions={suppressions} onChanged={() => void load()} initialEventId={requestedEventId} />
          </PageSection>

          <PageSection title="Riwayat alarm" description="Lihat alarm alat dan perubahan pengaturan alarm berdasarkan waktu.">
            <ResponsiveDataView
              desktop={<EventTable events={items ?? []} onChanged={() => void load()} />}
              mobile={<EventCards events={items ?? []} onChanged={() => void load()} />}
            />
            <div className="form-actions" aria-label="Navigasi riwayat event">
              <span className="cell-subtle">{historyTotal === 0 ? "0 event" : `${historyOffset + 1}–${Math.min(historyOffset + (items?.length ?? 0), historyTotal)} dari ${historyTotal}`}</span>
              <Button variant="secondary" disabled={historyOffset === 0} onClick={() => void load(Math.max(0, historyOffset - 500))}>Sebelumnya</Button>
              <Button variant="secondary" disabled={historyOffset + (items?.length ?? 0) >= historyTotal} onClick={() => void load(historyOffset + 500)}>Berikutnya</Button>
            </div>
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
