import { useEffect, useMemo, useState } from "react";
import { Input, LayerCard, Select } from "@cloudflare/kumo";
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
  StationDetail,
} from "../ui";

type Overview = {
  counts: Record<string, number>;
  stations: Station[];
};

const STATUS_ITEMS = {
  all: "All statuses",
  normal: "Normal",
  warning: "Warning",
  alarm: "Alarm",
  offline: "Offline",
};

export function StationsPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");

  const load = () => api<Overview>("/api/v1/web/overview")
    .then((value) => {
      setOverview(value);
      setSelected((current) => current && value.stations.some((item) => item.serid === current)
        ? current
        : value.stations[0]?.serid ?? null);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load stations"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); });

  const filtered = useMemo(() => {
    if (!overview) return [];
    const needle = query.trim().toLowerCase();
    return overview.stations.filter((station) => {
      const matchesStatus = status === "all" || station.status === status;
      const haystack = `${station.name} ${station.location} ${station.serid}`.toLowerCase();
      return matchesStatus && (!needle || haystack.includes(needle));
    });
  }, [overview, query, status]);

  const selectedStation = overview?.stations.find((station) => station.serid === selected) ?? null;
  const abnormal = overview ? overview.stations.filter((station) => station.status !== "normal").length : 0;

  if (!overview && !error) return <LoadingCard />;

  return (
    <div className="page-stack">
      <PageHeading
        title="Stations"
        description="Search, filter, inspect thresholds, and continue directly into measurement history."
      />
      {error ? <ErrorCard message={error} /> : null}
      {overview ? (
        <>
          <div className="metric-grid station-summary">
            <MetricCard label="Configured" value={overview.stations.length} badge={<span className="cell-subtle">All detectors</span>} />
            <MetricCard label="Normal" value={overview.counts.normal || 0} badge={<span className="cell-subtle">Current</span>} />
            <MetricCard label="Needs attention" value={abnormal} badge={<span className="cell-subtle">Warning, alarm, offline</span>} />
            <MetricCard label="Offline" value={overview.counts.offline || 0} badge={<span className="cell-subtle">Stale or missing live data</span>} />
          </div>

          <LayerCard className="filter-card station-search">
            <div className="station-filter-grid">
              <Input
                label="Search stations"
                placeholder="Name, location, or SERID"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
              <Select
                label="Status"
                items={STATUS_ITEMS}
                value={status}
                onValueChange={(value) => setStatus(String(value ?? "all"))}
              />
            </div>
          </LayerCard>

          <PageSection
            title="Station workspace"
            description={`${filtered.length} of ${overview.stations.length} stations shown.`}
          >
            <div className="station-workspace">
              <ResponsiveStationView
                stations={filtered}
                onOpen={(station) => setSelected(station.serid)}
                onHistory={(station) => navigate("history", { station: station.serid })}
              />
              <StationDetail
                station={selectedStation}
                onHistory={(station) => navigate("history", { station: station.serid })}
              />
            </div>
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
