import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import type { Station } from "../api";
import { ResponsiveDataView } from "./ResponsiveDataView";

function statusVariant(status?: string): "success" | "warning" | "error" | "secondary" {
  if (status === "normal") return "success";
  if (status === "warning") return "warning";
  if (status === "alarm") return "error";
  return "secondary";
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function freshnessLabel(value?: string | null): string {
  if (!value) return "No live measurement";
  const parsed = new Date(value);
  const delta = Date.now() - parsed.getTime();
  if (!Number.isFinite(delta)) return "Unknown age";
  const minutes = Math.max(0, Math.floor(delta / 60000));
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.floor(hours / 24)} d ago`;
}

export function StationTable({
  stations,
  onOpen,
  onHistory,
}: {
  stations: Station[];
  onOpen?: (station: Station) => void;
  onHistory?: (station: Station) => void;
}) {
  return (
    <LayerCard className="table-card responsive-table">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Station</Table.Head>
            <Table.Head>Location</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Dose rate</Table.Head>
            <Table.Head>Updated</Table.Head>
            {(onOpen || onHistory) ? <Table.Head>Action</Table.Head> : null}
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {stations.map((station) => (
            <Table.Row key={station.serid}>
              <Table.Cell>
                <strong>{station.name}</strong>
                <div className="cell-subtle">SERID {station.serid}</div>
              </Table.Cell>
              <Table.Cell>{station.location}</Table.Cell>
              <Table.Cell>
                <Badge variant={statusVariant(station.status)}>{station.status || "configured"}</Badge>
              </Table.Cell>
              <Table.Cell>
                {station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}
              </Table.Cell>
              <Table.Cell>
                {formatTimestamp(station.dtom)}
                <div className="cell-subtle">{freshnessLabel(station.dtom)}</div>
              </Table.Cell>
              {(onOpen || onHistory) ? (
                <Table.Cell>
                  <div className="card-actions">
                    {onOpen ? <Button variant="secondary" onClick={() => onOpen(station)}>Details</Button> : null}
                    {onHistory ? <Button variant="secondary" onClick={() => onHistory(station)}>History</Button> : null}
                  </div>
                </Table.Cell>
              ) : null}
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function StationCards({
  stations,
  onOpen,
  onHistory,
}: {
  stations: Station[];
  onOpen?: (station: Station) => void;
  onHistory?: (station: Station) => void;
}) {
  if (!stations.length) return <LayerCard className="empty-card">No stations match the current view.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {stations.map((station) => (
        <LayerCard className="station-card" key={station.serid}>
          <div className="station-card-header">
            <div>
              <h3>{station.name}</h3>
              <div className="cell-subtle">SERID {station.serid} · {station.location}</div>
            </div>
            <Badge variant={statusVariant(station.status)}>{station.status || "configured"}</Badge>
          </div>
          <div className="card-meta">
            <span>Dose rate: <strong>{station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}</strong></span>
            <span>Updated: {formatTimestamp(station.dtom)}</span>
            <span>{freshnessLabel(station.dtom)}</span>
          </div>
          {(onOpen || onHistory) ? (
            <div className="card-actions">
              {onOpen ? <Button variant="secondary" onClick={() => onOpen(station)}>Details</Button> : null}
              {onHistory ? <Button variant="secondary" onClick={() => onHistory(station)}>History</Button> : null}
            </div>
          ) : null}
        </LayerCard>
      ))}
    </div>
  );
}

export function ResponsiveStationView(props: {
  stations: Station[];
  onOpen?: (station: Station) => void;
  onHistory?: (station: Station) => void;
}) {
  return (
    <ResponsiveDataView
      desktop={<StationTable {...props} />}
      mobile={<StationCards {...props} />}
    />
  );
}

export function StationDetail({ station, onHistory }: { station: Station | null; onHistory?: (station: Station) => void }) {
  if (!station) return <LayerCard className="empty-card">Select a station to inspect its current state.</LayerCard>;
  return (
    <LayerCard className="station-card station-detail">
      <div className="station-card-header">
        <div>
          <h3>{station.name}</h3>
          <div className="cell-subtle">SERID {station.serid} · {station.location}</div>
        </div>
        <Badge variant={statusVariant(station.status)}>{station.status || "configured"}</Badge>
      </div>
      <div className="station-detail-grid">
        <div className="station-detail-item"><span>Dose rate</span><strong>{station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}</strong></div>
        <div className="station-detail-item"><span>Freshness</span><strong>{freshnessLabel(station.dtom)}</strong></div>
        <div className="station-detail-item"><span>Warning</span><strong>{station.warnlevel} {station.unit}</strong></div>
        <div className="station-detail-item"><span>Alarm</span><strong>{station.alarmlevel} {station.unit}</strong></div>
      </div>
      <div className="card-meta"><span>Last measurement: {formatTimestamp(station.dtom)}</span></div>
      {onHistory ? <div className="card-actions"><Button variant="primary" onClick={() => onHistory(station)}>View history</Button></div> : null}
    </LayerCard>
  );
}
