import { useEffect, useMemo, useState } from "react";
import { LayerCard, Select, Table } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { useWebRefresh } from "../live";
import { ErrorCard, LoadingCard, PageHeading } from "../ui";

export function HistoryPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const stationItems = useMemo(
    () => Object.fromEntries(stations.map((station) => [String(station.serid), `${station.name} — ${station.location}`])),
    [stations],
  );

  useEffect(() => {
    api<Station[]>("/api/v1/web/stations")
      .then((items) => {
        setStations(items);
        setSelected(items[0]?.serid ?? null);
      })
      .catch((e) => setError(e.message));
  }, []);

  const loadHistory = () => {
    if (!selected) {
      setLoading(false);
      return Promise.resolve();
    }
    setLoading(true);
    return api<Array<Record<string, unknown>>>(`/api/v1/web/stations/${selected}/history?limit=240`)
      .then((items) => {
        setRows(items);
        setError("");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { void loadHistory(); }, [selected]);
  useWebRefresh(() => { void loadHistory(); });

  return (
    <>
      <PageHeading title="History" description="Recent measurements retained by the central database." />
      <LayerCard className="filter-card">
        <Select
          label="Station"
          placeholder="Select station…"
          items={stationItems}
          value={selected == null ? undefined : String(selected)}
          onValueChange={(value) => setSelected(value == null ? null : Number(value))}
          disabled={stations.length === 0}
        />
      </LayerCard>
      {error ? <ErrorCard message={error} /> : loading ? <LoadingCard /> : (
        <LayerCard className="table-card">
          <Table>
            <Table.Header>
              <Table.Row>
                <Table.Head>Time</Table.Head>
                <Table.Head>Dose rate</Table.Head>
                <Table.Head>Dose</Table.Head>
                <Table.Head>Status</Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {rows.map((row, index) => (
                <Table.Row key={`${row.dtom}-${index}`}>
                  <Table.Cell>{String(row.dtom ?? "")}</Table.Cell>
                  <Table.Cell>{String(row.doserate ?? "")}</Table.Cell>
                  <Table.Cell>{String(row.dose ?? "")}</Table.Cell>
                  <Table.Cell>{String(row.stat ?? "")}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </LayerCard>
      )}
    </>
  );
}
