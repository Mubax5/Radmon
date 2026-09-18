import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import type { Station } from "../api";
import { ResponsiveDataView } from "./ResponsiveDataView";

function statusVariant(status?: string): "success" | "warning" | "error" | "secondary" {
  if (status === "normal") return "success";
  if (status === "warning") return "warning";
  if (status === "alarm") return "error";
  return "secondary";
}

function statusLabel(status?: string): string {
  if (status === "normal") return "normal";
  if (status === "warning") return "peringatan";
  if (status === "alarm") return "alarm";
  if (status === "offline") return "offline";
  return "terkonfigurasi";
}

function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

function freshnessLabel(value?: string | null): string {
  if (!value) return "Belum ada measurement live";
  const parsed = new Date(value);
  const delta = Date.now() - parsed.getTime();
  if (!Number.isFinite(delta)) return "Umur data tidak diketahui";
  const minutes = Math.max(0, Math.floor(delta / 60000));
  if (minutes < 1) return "Baru saja";
  if (minutes < 60) return `${minutes} mnt lalu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
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
            <Table.Head>Stasiun</Table.Head>
            <Table.Head>Lokasi</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Dose rate</Table.Head>
            <Table.Head>Diperbarui</Table.Head>
            {(onOpen || onHistory) ? <Table.Head>Aksi</Table.Head> : null}
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
                <Badge variant={statusVariant(station.status)}>{statusLabel(station.status)}</Badge>
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
                    {onOpen ? <Button variant="secondary" onClick={() => onOpen(station)}>Detail</Button> : null}
                    {onHistory ? <Button variant="secondary" onClick={() => onHistory(station)}>Riwayat</Button> : null}
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
  if (!stations.length) return <LayerCard className="empty-card">Tidak ada stasiun yang cocok dengan tampilan saat ini.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {stations.map((station) => (
        <LayerCard className="station-card" key={station.serid}>
          <div className="station-card-header">
            <div>
              <h3>{station.name}</h3>
              <div className="cell-subtle">SERID {station.serid} · {station.location}</div>
            </div>
            <Badge variant={statusVariant(station.status)}>{statusLabel(station.status)}</Badge>
          </div>
           <div className="card-meta">
            <span>Dose rate: <strong>{station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}</strong></span>
            <span>Diperbarui: {formatTimestamp(station.dtom)}</span>
            <span>{freshnessLabel(station.dtom)}</span>
            {station.status === "offline" && station.offline_reason ? <span>Alasan offline: {station.offline_reason}</span> : null}
          </div>
          {(onOpen || onHistory) ? (
            <div className="card-actions">
              {onOpen ? <Button variant="secondary" onClick={() => onOpen(station)}>Detail</Button> : null}
              {onHistory ? <Button variant="secondary" onClick={() => onHistory(station)}>Riwayat</Button> : null}
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
  if (!station) return <LayerCard className="empty-card">Pilih stasiun untuk melihat status saat ini.</LayerCard>;
  return (
    <LayerCard className="station-card station-detail">
      <div className="station-card-header">
        <div>
          <h3>{station.name}</h3>
          <div className="cell-subtle">SERID {station.serid} · {station.location}</div>
        </div>
        <Badge variant={statusVariant(station.status)}>{statusLabel(station.status)}</Badge>
      </div>
      <div className="station-detail-grid">
        <div className="station-detail-item"><span>Dose rate</span><strong>{station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}</strong></div>
        <div className="station-detail-item"><span>Kesegaran data</span><strong>{freshnessLabel(station.dtom)}</strong></div>
        <div className="station-detail-item"><span>Peringatan</span><strong>{station.warnlevel} {station.unit}</strong></div>
        <div className="station-detail-item"><span>Alarm</span><strong>{station.alarmlevel} {station.unit}</strong></div>
      </div>
      <div className="card-meta">
        <span>Deskripsi: {station.description || "—"}</span>
        {station.status === "offline" && station.offline_reason ? <span>Alasan offline: {station.offline_reason}</span> : null}
        {station.status === "offline" && station.offline_context ? <span>Konteks offline: {station.offline_context}</span> : null}
        <span>Dikelola: {station.ownership === "source" ? `sumber LAN ${station.source_id}` : "pusat"}</span>
      </div>
      <div className="card-meta"><span>Measurement terakhir: {formatTimestamp(station.dtom)}</span></div>
      {onHistory ? <div className="card-actions"><Button variant="primary" onClick={() => onHistory(station)}>Lihat riwayat</Button></div> : null}
    </LayerCard>
  );
}
