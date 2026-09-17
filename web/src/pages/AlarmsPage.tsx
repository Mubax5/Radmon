import { useEffect, useMemo, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations, type Suppression } from "../Actions";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { useWebRefresh } from "../live";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  formatTimestamp,
} from "../ui";

export type PolicyEvent = Record<string, unknown> & {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
  action?: string | null;
  reason?: string | null;
};

function eventVariant(event: PolicyEvent): "success" | "warning" | "error" | "secondary" {
  if (event.kind === "ALARM" && event.status === "ACTIVE") return "error";
  if (event.kind === "RETRIGGER_LOCKED") return "warning";
  if (event.kind === "SUPPRESSED") return "warning";
  if (event.status === "RESOLVED" || event.status === "NORMAL") return "success";
  return "secondary";
}

function EventCards({ events }: { events: PolicyEvent[] }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada event alarm.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {events.map((event) => (
        <LayerCard className="alarm-card" key={event.event_id}>
          <div className="alarm-card-header">
            <div>
              <h3>SERID {event.serid}</h3>
              <div className="cell-subtle">{event.kind}</div>
            </div>
            <Badge variant={eventVariant(event)}>{event.status || event.kind}</Badge>
          </div>
          <div className="card-meta">
            <span>Measurement: {event.measured_value ?? "—"}</span>
            <span>Threshold: {event.threshold ?? "—"}</span>
            <span>Muncul: {formatTimestamp(event.surfaced_at)}</span>
            {event.kind === "SUPPRESSION_END" ? <span>Berakhir: {event.action ?? "—"} · {event.reason ?? "—"}</span> : null}
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function EventTable({ events }: { events: PolicyEvent[] }) {
  if (!events.length) return <LayerCard className="empty-card">Tidak ada event alarm.</LayerCard>;
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Stasiun</Table.Head>
            <Table.Head>Jenis</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Measurement</Table.Head>
            <Table.Head>Threshold</Table.Head>
              <Table.Head>Muncul</Table.Head>
              <Table.Head>Lifecycle</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {events.map((event) => (
            <Table.Row key={event.event_id}>
              <Table.Cell><strong>SERID {event.serid}</strong></Table.Cell>
              <Table.Cell>{event.kind}</Table.Cell>
              <Table.Cell><Badge variant={eventVariant(event)}>{event.status || event.kind}</Badge></Table.Cell>
              <Table.Cell>{event.measured_value ?? "—"}</Table.Cell>
              <Table.Cell>{event.threshold ?? "—"}</Table.Cell>
              <Table.Cell>{formatTimestamp(event.surfaced_at)}</Table.Cell>
              <Table.Cell>{event.kind === "SUPPRESSION_END" ? `${event.action ?? "—"}: ${event.reason ?? "—"}` : "—"}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function AlarmsPage() {
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [suppressions, setSuppressions] = useState<Suppression[]>([]);
  const [error, setError] = useState("");
  const [suppressionError, setSuppressionError] = useState("");
  const loadSuppressions = () => api<Suppression[]>("/api/v1/control/suppressions?active_only=true")
    .then((activeSuppressions) => {
      setSuppressions(activeSuppressions);
      setSuppressionError("");
    })
    .catch((e) => setSuppressionError(e instanceof Error ? e.message : "Tidak dapat memuat suppression"));
  const load = () => Promise.allSettled([
    api<PolicyEvent[]>("/api/v1/control/alarm-events"),
    api<Suppression[]>("/api/v1/control/suppressions?active_only=true"),
  ])
    .then(([events, activeSuppressions]) => {
      if (events.status === "fulfilled") {
        setItems(events.value);
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
    const active = events.filter(
      (event) => String(event.kind).toUpperCase() === "ALARM" && String(event.status).toUpperCase() === "ACTIVE",
    );
    const retriggerLocked = events.filter((event) => event.kind === "RETRIGGER_LOCKED").length;
    const suppressed = events.filter((event) => event.kind === "SUPPRESSED").length;
    return { active, retriggerLocked, suppressed, total: events.length };
  }, [items]);

  const isInitialLoading = items === null && !error;
  const eventsFailedOnFirstLoad = items === null && Boolean(error);

  return (
    <div className="page-stack">
      <PageHeading
        title="Alarm"
        description="Alarm aktif diprioritaskan; suppression dan riwayat event tetap dilindungi oleh role dan policy PIN operator."
        action={<Button variant="secondary" onClick={() => void load()}>Muat ulang</Button>}
      />
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
      {items ? (
        <>
          <PageSection
            title="Alarm aktif"
            description="Event yang memerlukan perhatian operator segera."
            className="active-alarm-section"
          >
            <div className="active-alarm-list" aria-live="polite">
              <EventCards events={summary.active} />
            </div>
          </PageSection>

          <div className="metric-grid alarm-summary">
            <MetricCard label="Aktif" value={summary.active.length} badge={<Badge variant={summary.active.length ? "error" : "success"}>{summary.active.length ? "Perlu tindakan" : "Aman"}</Badge>} />
            <MetricCard label="Retrigger locked" value={summary.retriggerLocked} badge={<span className="cell-subtle">Burst policy</span>} />
            <MetricCard label="Event tersupresi" value={summary.suppressed} badge={<span className="cell-subtle">Riwayat policy</span>} />
            <MetricCard label="Event terbaru" value={summary.total} badge={<span className="cell-subtle">Rekaman dimuat</span>} />
          </div>

          <PageSection title="Tindakan operator" description="Respons alarm dan timed suppression memerlukan konfirmasi PIN yang terotorisasi.">
            {suppressionError ? (
              <div className="alarm-suppression-error">
                <ErrorCard message={`Daftar suppression tidak tersedia: ${suppressionError}`} />
                <Button variant="secondary" onClick={() => void loadSuppressions()}>Muat ulang suppression</Button>
              </div>
            ) : null}
            <AlarmOperations events={items} suppressions={suppressions} onChanged={() => void load()} />
          </PageSection>

          <PageSection title="Riwayat event" description="Event alarm-policy yang tersimpan di central, dengan urutan terbaru sesuai backend.">
            <ResponsiveDataView
              desktop={<EventTable events={items} />}
              mobile={<EventCards events={items} />}
            />
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
