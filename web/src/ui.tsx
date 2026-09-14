import type { ReactNode } from "react";
import { LayerCard, Table } from "@cloudflare/kumo";

export { ResponsiveStationView, StationCards, StationDetail, StationTable } from "./components/StationViews";

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

export function PageSection({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`page-section ${className}`.trim()}>
      <div className="page-section-header">
        <div className="page-section-title">
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  badge,
  className = "",
}: {
  label: string;
  value: ReactNode;
  badge?: ReactNode;
  className?: string;
}) {
  return (
    <LayerCard className={`metric-card ${className}`.trim()}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {badge}
    </LayerCard>
  );
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString();
}

export function freshnessLabel(value?: string | null): string {
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
