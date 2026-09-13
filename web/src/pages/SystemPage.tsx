import { useEffect, useState } from "react";
import { Badge, Button, LayerCard } from "@cloudflare/kumo";
import { api } from "../api";
import { ErrorCard, JsonTable, LoadingCard, PageHeading } from "../ui";

type SystemState = {
  service: string;
  role: string;
  sources: Array<Record<string, unknown>>;
  grafana_admin_url: string;
};

export function SystemPage() {
  const [data, setData] = useState<SystemState | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<SystemState>("/api/v1/web/system")
      .then((value) => {
        setData(value);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Unable to load system state"));
  }, []);

  return (
    <>
      <PageHeading
        title="System"
        description="Central runtime diagnostics, source health, and monitoring administration."
        action={data?.grafana_admin_url ? (
          <Button
            variant="secondary"
            onClick={() => window.open(data.grafana_admin_url, "_blank", "noopener,noreferrer")}
          >
            Open Grafana admin
          </Button>
        ) : undefined}
      />
      {error ? <ErrorCard message={error} /> : null}
      {!data ? <LoadingCard /> : (
        <>
          <div className="metric-grid system-metrics">
            <LayerCard className="metric-card">
              <div className="metric-label">Service</div>
              <div className="system-value">{data.service}</div>
              <Badge variant="success">Running</Badge>
            </LayerCard>
            <LayerCard className="metric-card">
              <div className="metric-label">Access</div>
              <div className="system-value">{data.role}</div>
              <Badge variant="secondary">Authenticated</Badge>
            </LayerCard>
            <LayerCard className="metric-card">
              <div className="metric-label">Sources</div>
              <div className="metric-value">{data.sources.length}</div>
              <Badge variant="secondary">Configured</Badge>
            </LayerCard>
          </div>
          <JsonTable rows={data.sources} empty="No LAN source health records." />
        </>
      )}
    </>
  );
}
