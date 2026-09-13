import { useEffect, useState } from "react";
import { Badge, LayerCard } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { ErrorCard, LoadingCard, PageHeading, StationTable } from "../ui";

type Overview = {
  counts: Record<string, number>;
  stations: Station[];
};

export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Overview>("/api/v1/web/overview").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorCard message={error} />;
  if (!data) return <LoadingCard />;

  const cards = [
    ["Normal", data.counts.normal || 0, "success"],
    ["Warning", data.counts.warning || 0, "warning"],
    ["Alarm", data.counts.alarm || 0, "error"],
    ["Offline", data.counts.offline || 0, "secondary"],
  ] as const;

  return (
    <>
      <PageHeading
        title="Radiation monitoring"
        description="Current health and dose state across all connected stations."
      />
      <div className="metric-grid">
        {cards.map(([label, value, variant]) => (
          <LayerCard className="metric-card" key={label}>
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
            <Badge variant={variant}>{label}</Badge>
          </LayerCard>
        ))}
      </div>
      <StationTable stations={data.stations} />
    </>
  );
}
