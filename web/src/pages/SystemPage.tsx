import { useEffect, useMemo, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api } from "../api";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import { useWebRefresh } from "../live";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  formatTimestamp,
  freshnessLabel,
} from "../ui";

type SourceHealth = {
  source_id: string;
  host: string;
  state: string;
  last_success?: string | null;
  last_failure?: string | null;
  last_live_poll?: string | null;
  last_alarm_poll?: string | null;
  last_history_import?: string | null;
  last_error?: string | null;
  consecutive_failures: number;
  updated_at?: string | null;
};

type SystemState = {
  service: string;
  role: string;
  sources: SourceHealth[];
  grafana_admin_url: string;
};

function sourceVariant(state: string): "success" | "warning" | "error" | "secondary" {
  if (state === "CONNECTED" || state === "RECOVERED") return "success";
  if (state === "DEGRADED") return "warning";
  if (state === "OFFLINE") return "error";
  return "secondary";
}

function SourceCards({ sources }: { sources: SourceHealth[] }) {
  if (!sources.length) return <LayerCard className="empty-card">Belum ada rekaman kesehatan source LAN.</LayerCard>;
  return (
    <div className="mobile-card-list source-health-list">
      {sources.map((source) => (
        <LayerCard className="source-card" key={source.source_id}>
          <div className="source-card-header">
            <div>
              <h3>{source.source_id}</h3>
              <div className="cell-subtle">{source.host}</div>
            </div>
            <Badge variant={sourceVariant(source.state)}>{source.state}</Badge>
          </div>
          <div className="card-meta">
            <span>Terakhir berhasil: {formatTimestamp(source.last_success)} · {freshnessLabel(source.last_success)}</span>
            <span>Live poll terakhir: {formatTimestamp(source.last_live_poll)}</span>
            {source.last_failure ? <span>Kegagalan terakhir: {formatTimestamp(source.last_failure)}</span> : null}
            {source.last_history_import ? <span>Import history: {formatTimestamp(source.last_history_import)}</span> : null}
            {source.consecutive_failures ? <span>Kegagalan beruntun: {source.consecutive_failures}</span> : null}
            {source.last_error ? <span>Error: {source.last_error}</span> : null}
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function SourceTable({ sources }: { sources: SourceHealth[] }) {
  if (!sources.length) return <LayerCard className="empty-card">Belum ada rekaman kesehatan source LAN.</LayerCard>;
  return (
    <LayerCard className="table-card source-health-table">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Source</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Terakhir berhasil</Table.Head>
            <Table.Head>Live poll</Table.Head>
            <Table.Head>Kegagalan</Table.Head>
            <Table.Head>Error terakhir</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {sources.map((source) => (
            <Table.Row key={source.source_id}>
              <Table.Cell><strong>{source.source_id}</strong><div className="cell-subtle">{source.host}</div></Table.Cell>
              <Table.Cell><Badge variant={sourceVariant(source.state)}>{source.state}</Badge></Table.Cell>
              <Table.Cell>{formatTimestamp(source.last_success)}<div className="cell-subtle">{freshnessLabel(source.last_success)}</div></Table.Cell>
              <Table.Cell>{formatTimestamp(source.last_live_poll)}</Table.Cell>
              <Table.Cell>{source.consecutive_failures}</Table.Cell>
              <Table.Cell>{source.last_error || "—"}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

export function SystemPage() {
  const [data, setData] = useState<SystemState | null>(null);
  const [error, setError] = useState("");

  const load = () => api<SystemState>("/api/v1/web/system")
    .then((value) => {
      setData(value);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat status sistem"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); });

  const summary = useMemo(() => {
    const sources = data?.sources ?? [];
    return {
      healthy: sources.filter((source) => source.state === "CONNECTED" || source.state === "RECOVERED").length,
      degraded: sources.filter((source) => source.state === "DEGRADED").length,
      offline: sources.filter((source) => source.state === "OFFLINE").length,
    };
  }, [data]);

  return (
    <div className="page-stack">
      <PageHeading
        title="Sistem"
        description="Diagnostik runtime central, kesehatan source LAN, dan administrasi Grafana lokal."
        action={data?.grafana_admin_url ? (
          <Button
            variant="secondary"
            onClick={() => window.open(data.grafana_admin_url, "_blank", "noopener,noreferrer")}
          >
            Buka admin Grafana
          </Button>
        ) : undefined}
      />
      {error ? <ErrorCard message={error} /> : null}
      {!data ? <LoadingCard /> : (
        <>
          <div className="metric-grid system-metrics source-health-summary">
            <MetricCard label="Service central" value={data.service} badge={<Badge variant="success">Berjalan</Badge>} className="system-value-card" />
            <MetricCard label="Source sehat" value={summary.healthy} badge={<Badge variant="success">Terhubung</Badge>} />
            <MetricCard label="Degraded" value={summary.degraded} badge={<Badge variant={summary.degraded ? "warning" : "secondary"}>Source</Badge>} />
            <MetricCard label="Offline" value={summary.offline} badge={<Badge variant={summary.offline ? "error" : "secondary"}>Source</Badge>} />
          </div>

          <PageSection
            title="Kesehatan source LAN"
            description="Konektivitas, kesegaran poll, jumlah kegagalan, dan error terbaru dari central security sidecar."
            className="source-health-section"
          >
            <ResponsiveDataView
              desktop={<SourceTable sources={data.sources} />}
              mobile={<SourceCards sources={data.sources} />}
            />
          </PageSection>

          <PageSection title="Administrasi" description={`Terautentikasi sebagai ${data.role}. Editor Grafana tetap lokal di server Dell.`}>
            <LayerCard className="action-card system-admin-card">
              <h2>Administrasi Grafana</h2>
              <p>Editing dashboard tetap pada listener loopback Dell; client BRIN tetap memakai gateway RadMon untuk monitoring read-only.</p>
              <div className="form-actions">
                <Button variant="secondary" onClick={() => window.open(data.grafana_admin_url, "_blank", "noopener,noreferrer")}>Buka admin Grafana lokal</Button>
              </div>
            </LayerCard>
          </PageSection>
        </>
      )}
    </div>
  );
}
