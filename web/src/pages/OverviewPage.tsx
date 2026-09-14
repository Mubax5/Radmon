import { useEffect, useMemo, useState } from "react";
import { Badge, LayerCard } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { useWebRefresh } from "../live";
import { navigate } from "../navigation";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  ResponsiveStationView,
  formatTimestamp,
  freshnessLabel,
} from "../ui";

type Overview = {
  counts: Record<string, number>;
  stations: Station[];
};

const SEVERITY: Record<string, number> = { alarm: 0, warning: 1, offline: 2, normal: 3 };

export function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Overview>("/api/v1/web/overview")
    .then((value) => { setData(value); setError(""); })
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load monitoring overview"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); });

  const derived = useMemo(() => {
    if (!data) return { attention: [] as Station[], latest: null as string | null };
    const attention = data.stations
      .filter((station) => station.status !== "normal")
      .sort((a, b) => (SEVERITY[a.status ?? "offline"] ?? 9) - (SEVERITY[b.status ?? "offline"] ?? 9));
    const timestamps = data.stations
      .map((station) => station.dtom ? Date.parse(station.dtom) : Number.NaN)
      .filter(Number.isFinite);
    const latest = timestamps.length ? new Date(Math.max(...timestamps)).toISOString() : null;
    return { attention, latest };
  }, [data]);

  if (!data && !error) return <LoadingCard />;

  const cards = data ? [
    ["Normal", data.counts.normal || 0, "success"],
    ["Warning", data.counts.warning || 0, "warning"],
    ["Alarm", data.counts.alarm || 0, "error"],
    ["Offline", data.counts.offline || 0, "secondary"],
  ] as const : [];

  return (
    <div className="page-stack">
      <PageHeading
        title="Radiation monitoring"
        description="Live operating state, attention queue, freshness, and dose context across all configured stations."
      />
      {error ? <ErrorCard message={error} /> : null}
      {data ? (
        <>
          <div className="metric-grid">
            {cards.map(([label, value, variant]) => (
              <MetricCard key={label} label={label} value={value} badge={<Badge variant={variant}>{label}</Badge>} />
            ))}
          </div>

          <PageSection
            title="Attention"
            description="Alarm, warning, and offline stations are kept ahead of healthy detail."
            className="attention-panel"
          >
            {derived.attention.length ? (
              <ResponsiveStationView
                stations={derived.attention}
                onHistory={(station) => navigate("history", { station: station.serid })}
              />
            ) : (
              <LayerCard className="empty-card">No stations currently need operator attention.</LayerCard>
            )}
          </PageSection>

          <PageSection title="Data freshness" description="Latest measurement received by the central RadMon read model.">
            <div className="metric-grid freshness-grid">
              <MetricCard
                label="Latest live measurement"
                value={derived.latest ? freshnessLabel(derived.latest) : "No data"}
                badge={<span className="cell-subtle">{formatTimestamp(derived.latest)}</span>}
              />
              <MetricCard
                label="Configured stations"
                value={data.stations.length}
                badge={<span className="cell-subtle">Central overview</span>}
              />
            </div>
          </PageSection>

          <PageSection title="Station health" description="Current dose, status, and last-update context for every station.">
            <ResponsiveStationView
              stations={data.stations}
              onHistory={(station) => navigate("history", { station: station.serid })}
            />
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
