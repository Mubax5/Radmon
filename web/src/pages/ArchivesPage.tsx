import { useEffect, useMemo, useState } from "react";
import { Button, LayerCard, Select, Table } from "@cloudflare/kumo";
import { api, archiveExportDownloadUrl, requestArchiveExport, type ArchiveExportJob } from "../api";
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

function exportStatus(job: ArchiveExportJob) {
  const status = job.status === "queued" ? "Menunggu" : job.status === "running"
    ? (job.phase?.startsWith("verifying:") ? `Memverifikasi ${job.phase.slice("verifying:".length)}` : job.phase?.startsWith("merging:") ? `Menggabungkan ${job.phase.slice("merging:".length)}` : "Menggabungkan")
    : job.status === "completed" ? "Selesai" : "Gagal";
  return (
    <span className="archive-export-inline" role="status">
      <span>{status}</span>
      {job.status === "queued" || job.status === "running" ? <progress max={Math.max(job.partitions_total, 1)} value={job.partitions_read} aria-label="Progres bundle" /> : null}
      <small>{job.partitions_read}/{job.partitions_total} bundle · {job.rows_read.toLocaleString()} baris · {job.bytes_written.toLocaleString()} byte</small>
      {job.error ? <span role="alert">{job.error}</span> : null}
      {job.status === "completed" ? <a href={archiveExportDownloadUrl(job.job_id)}>Unduh file database SQL</a> : null}
    </span>
  );
}

function archiveStateLabel(state: unknown): string {
  switch (String(state ?? "").toUpperCase()) {
    case "COMPLETE": return "Selesai";
    case "RUNNING": return "Berjalan";
    case "FAILED": return "Gagal";
    case "QUEUED": return "Menunggu";
    default: return state ? String(state) : "Status tidak diketahui";
  }
}

export function ArchivesPage() {
  const [items, setItems] = useState<ArchiveRecord[] | null>(null);
  const [year, setYear] = useState("all");
  const [error, setError] = useState("");
  const [jobs, setJobs] = useState<ArchiveExportJob[]>([]);
  const [creating, setCreating] = useState(false);

  const load = () => api<ArchiveRecord[] | { archives: ArchiveRecord[] }>("/api/v1/control/archives")
    .then((payload) => { setItems(Array.isArray(payload) ? payload : payload.archives); setError(""); })
    .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat arsip"));

  useEffect(() => {
    void load();
    void api<ArchiveExportJob[]>("/api/v1/control/archive-exports").then(setJobs).catch(() => undefined);
  }, []);
  useWebRefresh(() => { void load(); }, ["archive_update"]);

  useEffect(() => {
    const pending = jobs.filter((job) => job.status === "queued" || job.status === "running");
    if (!pending.length) return;
    const timer = window.setInterval(() => {
      void Promise.all(pending.map((job) => api<ArchiveExportJob>(`/api/v1/control/archive-exports/${encodeURIComponent(job.job_id)}`)))
        .then((updates) => setJobs((current) => current.map((job) => updates.find((update) => update.job_id === job.job_id) ?? job)))
        .catch((reason) => setError(reason instanceof Error ? reason.message : "Status unduhan gagal dimuat"));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const startExport = async (selection: "single" | "year" | "all", value: string | null) => {
    setCreating(true);
    setError("");
    try {
      const job = await requestArchiveExport(selection, value);
      setJobs((current) => [job, ...current]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unduhan arsip gagal dimulai");
    } finally {
      setCreating(false);
    }
  };

  const derived = useMemo(() => {
    const records = items ?? [];
    const years = [...new Set(records.map((item) => quarterYear(item.quarter_id)).filter((value): value is string => Boolean(value)))].sort().reverse();
    const filtered = year === "all" ? records : records.filter((item) => quarterYear(item.quarter_id) === year);
    const complete = records.filter((item) => String(item.state ?? "").toUpperCase() === "COMPLETE").length;
    const quarters = records
      .map((item) => String(item.quarter_id ?? ""))
      .filter(Boolean)
      .sort();
    const latestQuarter = quarters.length ? quarters[quarters.length - 1] : "—";
    return { years, filtered, complete, latestQuarter };
  }, [items, year]);

  const yearItems = useMemo(
    () => Object.fromEntries([["all", `Semua tahun (${(items ?? []).length} arsip)`], ...derived.years.map((value) => [value, `${value} (${(items ?? []).filter((item) => quarterYear(item.quarter_id) === value).length} arsip)`])]),
    [derived.years, derived.filtered.length, items],
  );
  const selectedExport = jobs.find((job) => job.selection === (year === "all" ? "all" : "year") && (year === "all" || job.selection_value === year));

  return (
    <div className="page-stack">
      <PageHeading
        title="Arsip"
        description="Temukan arsip pengukuran per kuartal dan unduh data untuk disimpan atau ditinjau."
      />
      {error ? <ErrorCard message={error} /> : null}
      {!items && !error ? <LoadingCard /> : items ? (
        <>
          <div className="metric-grid archive-summary">
            <MetricCard label="Bundle arsip" value={items.length} badge={<span className="cell-subtle">Total katalog</span>} />
            <MetricCard label="Selesai" value={derived.complete} badge={<span className="cell-subtle">Bundle selesai</span>} />
            <MetricCard label="Periode terbaru" value={derived.latestQuarter} badge={<span className="cell-subtle">Kuartal</span>} />
            <MetricCard label="Tahun" value={derived.years.length} badge={<span className="cell-subtle">Periode tersedia</span>} />
          </div>

          <div className="archive-filter">
            <Select
              label="Tahun arsip"
              items={yearItems}
              value={year}
              onValueChange={(value) => setYear(String(value ?? "all"))}
            />
            <div className="archive-export-control">
              <Button disabled={creating || !derived.filtered.some((item) => String(item.state).toUpperCase() === "COMPLETE")} onClick={() => void startExport(year === "all" ? "all" : "year", year === "all" ? null : year)}>
                {year === "all" ? "Ekspor semua arsip" : `Ekspor tahun ${year}`}
              </Button>
              {selectedExport ? exportStatus(selectedExport) : null}
            </div>
          </div>

          <PageSection
            title="Daftar arsip"
            description={`${derived.filtered.length} bundle arsip pada periode yang dipilih.`}
          >
            <ResponsiveDataView
              desktop={derived.filtered.length ? (
                <LayerCard className="table-card">
                  <Table>
                    <Table.Header>
                      <Table.Row>
                        <Table.Head>Kuartal</Table.Head>
                        <Table.Head>Status</Table.Head>
                        <Table.Head>Mulai</Table.Head>
                        <Table.Head>Selesai</Table.Head>
                        <Table.Head>Diperbarui</Table.Head>
                        <Table.Head>Database</Table.Head>
                      </Table.Row>
                    </Table.Header>
                    <Table.Body>
                      {derived.filtered.map((item, index) => (
                        <Table.Row key={`${item.quarter_id ?? "archive"}-${index}`}>
                          <Table.Cell><strong>{String(item.quarter_id ?? "—")}</strong></Table.Cell>
                          <Table.Cell>{archiveStateLabel(item.state)}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.start_at)}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.end_at)}</Table.Cell>
                          <Table.Cell>{formatTimestamp(item.updated_at ?? item.created_at)}</Table.Cell>
                          <Table.Cell>
                            <div className="archive-export-control">
                              <Button disabled={creating || String(item.state).toUpperCase() !== "COMPLETE"} onClick={() => void startExport("single", String(item.quarter_id))}>Ekspor database</Button>
                              {jobs.find((job) => job.selection === "single" && job.selection_value === item.quarter_id) ? exportStatus(jobs.find((job) => job.selection === "single" && job.selection_value === item.quarter_id)!) : null}
                            </div>
                          </Table.Cell>
                        </Table.Row>
                      ))}
                    </Table.Body>
                  </Table>
                </LayerCard>
              ) : <LayerCard className="empty-card">Tidak ada bundle arsip untuk tahun ini.</LayerCard>}
              mobile={derived.filtered.length ? (
                <div className="mobile-card-list">
                  {derived.filtered.map((item, index) => (
                    <LayerCard className="archive-card" key={`${item.quarter_id ?? "archive"}-${index}`}>
                      <div className="archive-card-header">
                        <div>
                          <h3>{String(item.quarter_id ?? "Arsip")}</h3>
                          <div className="cell-subtle">{archiveStateLabel(item.state)}</div>
                        </div>
                      </div>
                      <div className="card-meta">
                        {item.start_at ? <span>Mulai: {formatTimestamp(item.start_at)}</span> : null}
                        {item.end_at ? <span>Selesai: {formatTimestamp(item.end_at)}</span> : null}
                        {(item.updated_at || item.created_at) ? <span>Diperbarui: {formatTimestamp(item.updated_at ?? item.created_at)}</span> : null}
                      </div>
                      <div className="archive-export-control">
                        <Button disabled={creating || String(item.state).toUpperCase() !== "COMPLETE"} onClick={() => void startExport("single", String(item.quarter_id))}>Ekspor database</Button>
                        {jobs.find((job) => job.selection === "single" && job.selection_value === item.quarter_id) ? exportStatus(jobs.find((job) => job.selection === "single" && job.selection_value === item.quarter_id)!) : null}
                      </div>
                    </LayerCard>
                  ))}
                </div>
              ) : <LayerCard className="empty-card">Tidak ada bundle arsip untuk tahun ini.</LayerCard>}
            />
          </PageSection>
        </>
      ) : null}
    </div>
  );
}
