import type { ReactNode } from "react";
import { Badge, LayerCard, Table } from "@cloudflare/kumo";
import type { Station } from "./api";

export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function statusVariant(status?: string): "success" | "warning" | "error" | "secondary" {
  if (status === "normal") return "success";
  if (status === "warning") return "warning";
  if (status === "alarm") return "error";
  return "secondary";
}

export function StationTable({ stations }: { stations: Station[] }) {
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Station</Table.Head>
            <Table.Head>Location</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Dose rate</Table.Head>
            <Table.Head>Updated</Table.Head>
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
              <Table.Cell>{station.dtom ? new Date(station.dtom).toLocaleString() : "—"}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function JsonTable({ rows, empty }: { rows: Array<Record<string, unknown>>; empty: string }) {
  if (!rows.length) return <LayerCard className="empty-card">{empty}</LayerCard>;
  const keys = Object.keys(rows[0]).slice(0, 6);
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>{keys.map((key) => <Table.Head key={key}>{key.replaceAll("_", " ")}</Table.Head>)}</Table.Row>
        </Table.Header>
        <Table.Body>
          {rows.map((row, index) => (
            <Table.Row key={index}>
              {keys.map((key) => (
                <Table.Cell key={key}>
                  {typeof row[key] === "object" ? JSON.stringify(row[key]) : String(row[key] ?? "—")}
                </Table.Cell>
              ))}
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function LoadingCard() {
  return <LayerCard className="empty-card">Loading…</LayerCard>;
}

export function ErrorCard({ message }: { message: string }) {
  return <LayerCard className="error-card">{message}</LayerCard>;
}
