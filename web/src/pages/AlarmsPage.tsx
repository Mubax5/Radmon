import { useEffect, useMemo, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { AlarmOperations } from "../Actions";
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
};

function eventVariant(event: PolicyEvent): "success" | "warning" | "error" | "secondary" {
  if (event.kind === "ALARM" && event.status === "ACTIVE") return "error";
  if (event.kind === "RETRIGGER_LOCKED") return "warning";
  if (event.kind === "SUPPRESSED") return "warning";
  if (event.status === "RESOLVED" || event.status === "NORMAL") return "success";
  return "secondary";
}

function EventCards({ events }: { events: PolicyEvent[] }) {
  if (!events.length) return <LayerCard className="empty-card">No alarm events.</LayerCard>;
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
            <span>Measured: {event.measured_value ?? "—"}</span>
            <span>Threshold: {event.threshold ?? "—"}</span>
            <span>Surfaced: {formatTimestamp(event.surfaced_at)}</span>
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function EventTable({ events }: { events: PolicyEvent[] }) {
  if (!events.length) return <LayerCard className="empty-card">No alarm events.</LayerCard>;
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Station</Table.Head>
            <Table.Head>Kind</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Measured</Table.Head>
            <Table.Head>Threshold</Table.Head>
            <Table.Head>Surfaced</Table.Head>
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
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function AlarmsPage() {
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<PolicyEvent[]>("/api/v1/control/alarm-events")
    .then((rows) => {
      setItems(rows);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load alarms"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); }, ["live_update"]);

  const summary = useMemo(() => {
    const events = items ?? [];
    const active = events.filter((event) => event.kind === "ALARM" && event.status === "ACTIVE");
    const retriggerLocked = events.filter((event) => event.kind === "RETRIGGER_LOCKED").length;
    const suppressed = events.filter((event) => event.kind === "SUPPRESSED").length;
    return { active, retriggerLocked, suppressed, total: events.length };
  }, [items]);

  return (
    <div className="page-stack">
      <PageHeading
        title="Alarms"
        description="Active alarm response comes first; suppression and event history remain protected by role and operator PIN policy."
        action={<Button variant="secondary" onClick={() => void load()}>Refresh</Button>}
      />
      {error ? <ErrorCard message={error} /> : null}
      {!items ? <LoadingCard /> : (
        <>
          <PageSection
            title="Active alarms"
            description="Events requiring immediate operator attention."
            className="active-alarm-section"
          >
            <div className="active-alarm-list">
              <EventCards events={summary.active} />
            </div>
          </PageSection>

          <div className="metric-grid alarm-summary">
            <MetricCard label="Active" value={summary.active.length} badge={<Badge variant={summary.active.length ? "error" : "success"}>{summary.active.length ? "Action required" : "Clear"}</Badge>} />
            <MetricCard label="Retrigger locked" value={summary.retriggerLocked} badge={<span className="cell-subtle">Burst policy</span>} />
            <MetricCard label="Suppressed events" value={summary.suppressed} badge={<span className="cell-subtle">Policy history</span>} />
            <MetricCard label="Recent events" value={summary.total} badge={<span className="cell-subtle">Loaded records</span>} />
          </div>

          <PageSection title="Operator actions" description="Response and timed suppression require authorized PIN confirmation.">
            <AlarmOperations events={items} onChanged={() => void load()} />
          </PageSection>

          <PageSection title="Event history" description="Central persisted alarm-policy events, newest order as returned by the backend.">
            <ResponsiveDataView
              desktop={<EventTable events={items} />}
              mobile={<EventCards events={items} />}
            />
          </PageSection>
        </>
      )}
    </div>
  );
}
