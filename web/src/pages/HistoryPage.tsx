import { useEffect, useMemo, useState } from "react";
import { LayerCard, Select, Table } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { TrendChart, type TrendPoint } from "../components/TrendChart";
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

type HistoryRow = Record<string, unknown> & {
  dtom?: string;
  doserate?: number | string | null;
  dose?: number | string | null;
  stat?: number | string | null;
};

function numericDoseRate(row: HistoryRow): number | null {
  const value = Number(row.doserate);
  return Number.isFinite(value) ? value : null;
}

export function HistoryPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [rows, setRows] = useState<HistoryRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const stationItems = useMemo(
    () => Object.fromEntries(stations.map((station) => [String(station.serid), `${station.name} — ${station.location}`])),
    [stations],
  );

  const selectedStation = stations.find((station) => station.serid === selected) ?? null;

  useEffect(() => {
    api<Station[]>("/api/v1/web/stations")
      .then((items) => {
        setStations(items);
        const requested = Number(new URLSearchParams(window.location.search).get("station"));
        const initial = items.some((item) => item.serid === requested)
          ? requested
          : items[0]?.serid ?? null;
        setSelected(initial);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat stasiun"));
  }, []);

  function changeStation(value: string | number | null | undefined) {
    const next = value == null ? null : Number(value);
    setSelected(next);
    if (next) {
      window.history.replaceState({}, "", `/app/history?station=${encodeURIComponent(String(next))}`);
    } else {
      window.history.replaceState({}, "", "/app/history");
    }
  }

  const loadHistory = () => {
    if (!selected) {
      setRows([]);
      setLoading(false);
      return Promise.resolve();
    }
    setLoading(true);
    return api<HistoryRow[]>(`/api/v1/web/stations/${selected}/history?limit=240`)
      .then((items) => {
        setRows(items);
        setError("");
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat riwayat"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { void loadHistory(); }, [selected]);
  useWebRefresh(() => { void loadHistory(); });

  const history = useMemo(() => {
    const points: TrendPoint[] = rows
      .flatMap((row) => {
        const value = numericDoseRate(row);
        return value == null || !row.dtom ? [] : [{ at: String(row.dtom), value }];
      })
      .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
    const values = points.map((point) => point.value);
    const latestPoint = points.length ? points[points.length - 1] : null;
    const latest = latestPoint?.value ?? null;
    const min = values.length ? Math.min(...values) : null;
    const max = values.length ? Math.max(...values) : null;
    const average = values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    return { points, latest, min, max, average };
  }, [rows]);

  const unit = selectedStation?.unit ?? "uSv/h";
  const fmt = (value: number | null) => value == null ? "—" : `${value.toFixed(3)} ${unit}`;
  const chronological = [...rows].sort((a, b) => Date.parse(String(b.dtom ?? "")) - Date.parse(String(a.dtom ?? "")));

  return (
    <div className="page-stack">
      <PageHeading title="Riwayat" description="Measurement terbaru, tren, dan statistik rentang untuk stasiun yang dipilih." />
      <LayerCard className="filter-card history-filter">
        <Select
          label="Stasiun"
          placeholder="Pilih stasiun…"
          items={stationItems}
          value={selected == null ? undefined : String(selected)}
          onValueChange={changeStation}
          disabled={stations.length === 0}
        />
      </LayerCard>
      {error ? <ErrorCard message={error} /> : null}
      {loading ? <LoadingCard /> : (
        <>
          <div className="metric-grid history-summary">
            <MetricCard label="Terbaru" value={fmt(history.latest)} />
            <MetricCard label="Minimum" value={fmt(history.min)} />
            <MetricCard label="Maksimum" value={fmt(history.max)} />
            <MetricCard label="Rata-rata" value={fmt(history.average)} />
          </div>

          <PageSection
            title="Tren dose rate"
            description={`${history.points.length} measurement dimuat dari database central.`}
          >
            <LayerCard className="action-card">
              <TrendChart points={history.points} unit={unit} />
            </LayerCard>
          </PageSection>

          <PageSection title="Rekaman measurement terbaru" description="Rekaman terbaru ditampilkan lebih dulu.">
            <ResponsiveDataView
              desktop={(
                <LayerCard className="table-card">
                  <Table>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>Waktu</Table.Head>
                        <Table.Head>Dose rate</Table.Head>
                        <Table.Head>Dose</Table.Head>
                        <Table.Head>Status</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {chronological.map((row, index) => (
                        <Table.Row key={`${row.dtom}-${index}`}>
                          <Table.Cell>{formatTimestamp(String(row.dtom ?? ""))}</Table.Cell>
                          <Table.Cell>{String(row.doserate ?? "—")}</Table.Cell>
                          <Table.Cell>{String(row.dose ?? "—")}</Table.Cell>
                          <Table.Cell>{String(row.stat ?? "—")}</Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                </LayerCard>
              )}
              mobile={chronological.length ? (
                <div className="mobile-card-list">
                  {chronological.map((row, index) => (
                    <LayerCard className="record-card" key={`${row.dtom}-${index}`}>
                      <div className="record-card-header">
                        <div><h3>{formatTimestamp(String(row.dtom ?? ""))}</h3></div>
                        <strong>{String(row.doserate ?? "—")} {unit}</strong>
                      </div>
                      <div className="card-meta">
                        <span>Dose: {String(row.dose ?? "—")}</span>
                        <span>Status: {String(row.stat ?? "—")}</span>
                      </div>
                    </LayerCard>
                  ))}
                </div>
              ) : <LayerCard className="empty-card">Belum ada measurement untuk stasiun ini.</LayerCard>}
            />
          </PageSection>
        </>
      )}
    </div>
  );
}
