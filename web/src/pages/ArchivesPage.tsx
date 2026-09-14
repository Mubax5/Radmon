import { useEffect, useMemo, useState } from "react";
import { LayerCard, Select, Table } from "@cloudflare/kumo";
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
} from "../ui";

type ArchiveRecord = Record<string, unknown> & {
  quarter_id?: string;
  state?: string;
  start_at?: string | null;
  end_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

function quarterYear(value: unknown): string | null {
  const match = /^([0-9]{4})-Q[1-4]$/.exec(String(value ?? ""));
  return match?.[1] ?? null;
}

export function ArchivesPage() {
  const [items, setItems] = useState<ArchiveRecord[] | null>(null);
  const [year, setYear] = useState("all");
  const [error, setError] = useState("");

  const load = () => api<ArchiveRecord[]>("/api/v1/control/archives")
    .then((rows) => { setItems(rows); setError(""); })
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load archives"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); }, ["archive_update"]);

  const derived = useMemo(() => {
    const records = items ?? [];
    const years = [...new Set(records.map((item) => quarterYear(item.quarter_id)).filter((value): value is string => Boolean(value)))].sort().reverse();
    const filtered = year === "all" ? records : records.filter((item) => quarterYear(item.quarter_id) === year);
    const complete = records.filter((item) => String(item.state ?? "").toUpperCase() === "COMPLETE").length;
    const latestQuarter = records
      .map((item) => String(item.quarter_id ?? ""))
      .filter(Boolean)
      .sort()
      .at(-1) ?? "—";
    return { years, filtered, complete, latestQuarter };
  }, [items, year]);

  const yearItems = useMemo(
    () => Object.fromEntries([["all", "All years"], ...derived.years.map((value) => [value, value])]),
    [derived.years],
  );

  return (
    <div className="page-stack">
      <PageHeading
        title="Archives"
        description="Quarterly archive inventory, verification state, and retention context from the central catalog."
      />
      {error ? <ErrorCard message={error} /> : null}
      {!items ? <LoadingCard /> : (
        <>
          <div className="metric-grid archive-summary">
            <MetricCard label="Archive bundles" value={items.length} badge={<span className="cell-subtle">Catalog total</span>} />
            <MetricCard label="Complete" value={derived.complete} badge={<span className="cell-subtle">Finished bundles</span>} />
            <MetricCard label="Latest period" value={derived.latestQuarter} badge={<span className="cell-subtle">Quarter ID</span>} />
            <MetricCard label="Years" value={derived.years.length} badge={<span className="cell-subtle">Available periods</span>} />
          </div>

          <LayerCard className="filter-card archive-filter">
            <Select
              label="Archive year"
              items={yearItems}
              value={year}
              onValueChange={(value) => setYear(String(value ?? "all"))}
            />
          </LayerCard>

          <PageSection
            title="Archive inventory"
            description={`${derived.filtered.length} archive bundle${derived.filtered.length === 1 ? "" : "s"} in the selected period.`}
          >
            <ResponsiveDataView
              desktop={derived.filtered.length ? (
                <LayerCard className="table-card">
                  <Table>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>Quarter</Table.Head>
                        <Table.Head>State</Table.Head>
                        <Table.Head>Start</Table.Head>
                        <Table.Head>End</Table.Head>
                        <Table.Head>Updated</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {derived.filtered.map((item, index) => (
                        <Table.Row key={`${item.quarter_id ?? "archive"}-${index}`}>
                          <Table.Cell><strong>{String(item.quarter_id ?? "—")}</strong></Table.Cell>
                          <Table.Cell>{String(item.state ?? "—")}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.start_at)}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.end_at)}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.updated_at ?? item.created_at)}</Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                </LayerCard>
              ) : <LayerCard className="empty-card">No archive bundles match this year.</LayerCard>}
              mobile={derived.filtered.length ? (
                <div className="mobile-card-list">
                  {derived.filtered.map((item, index) => (
                    <LayerCard className="archive-card" key={`${item.quarter_id ?? "archive"}-${index}`}>
                      <div className="archive-card-header">
                        <div>
                          <h3>{String(item.quarter_id ?? "Archive")}</h3>
                          <div className="cell-subtle">{String(item.state ?? "Unknown state")}</div>
                        </div>
                      </div>
                      <div className="card-meta">
                        {item.start_at ? <span>Start: {formatTimestamp(item.start_at)}</span> : null}
                        {item.end_at ? <span>End: {formatTimestamp(item.end_at)}</span> : null}
                        {(item.updated_at || item.created_at) ? <span>Updated: {formatTimestamp(item.updated_at ?? item.created_at)}</span> : null}
                      </div>
                    </LayerCard>
                  ))}
                </div>
              ) : <LayerCard className="empty-card">No archive bundles match this year.</LayerCard>}
            />
          </PageSection>
        </>
      )}
    </div>
  );
}
