import { useEffect, useState } from "react";
import { Button, LayerCard } from "@cloudflare/kumo";
import { api, listReportJobs, reportDownloadUrl, reportPreviewUrl, requestReport, type ReportJob, type Station } from "../api";
import { ErrorCard, LoadingCard, PageHeading, PageSection, formatTimestamp } from "../ui";

const now = new Date();
const localDateTime = (date: Date) => {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};

export function ReportsPage() {
  const [jobs, setJobs] = useState<ReportJob[] | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [serid, setSerid] = useState("");
  const [startAt, setStartAt] = useState(localDateTime(new Date(now.getTime() - 24 * 60 * 60 * 1000)));
  const [endAt, setEndAt] = useState(localDateTime(now));
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [draftUrl, setDraftUrl] = useState<string | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState("");
  const previewReady = Boolean(previewJobId && jobs?.some((job) => job.job_id === previewJobId && job.status === "completed"));

  const load = () => void Promise.all([listReportJobs(), api<Station[]>("/api/v1/web/stations")]).then(([reportRows, stationRows]) => {
    setJobs(reportRows);
    setStations(stationRows);
    setSerid((current) => current || String(stationRows[0]?.serid ?? ""));
    setError("");
  }).catch((reason) => setError(reason instanceof Error ? reason.message : "Laporan tidak tersedia"));

  useEffect(() => {
    load();
    const timer = window.setInterval(load, 3000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!previewJobId || !previewReady) {
      setPreviewUrl(null);
      setPreviewLoading(false);
      setPreviewError("");
      return;
    }
    let objectUrl: string | null = null;
    const controller = new AbortController();
    setPreviewUrl(null);
    setPreviewLoading(true);
    setPreviewError("");
    fetch(reportPreviewUrl(previewJobId), { credentials: "same-origin", signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        if (!response.headers.get("content-type")?.toLowerCase().includes("application/pdf")) throw new Error("Pratinjau bukan file PDF");
        return response.blob();
      })
      .then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setPreviewError(reason instanceof Error ? reason.message : "Pratinjau PDF gagal dimuat");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [previewJobId, previewReady]);

  useEffect(() => {
    if (!serid || !startAt || !endAt) {
      setDraftUrl(null);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    const timer = window.setTimeout(() => {
      setDraftUrl(null);
      setDraftLoading(true);
      setDraftError("");
      const query = new URLSearchParams({ serid, start_at: new Date(startAt).toISOString(), end_at: new Date(endAt).toISOString() });
      fetch(`/api/v1/control/reports/draft-preview?${query}`, { credentials: "same-origin", signal: controller.signal })
        .then((response) => {
          if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
          if (!response.headers.get("content-type")?.toLowerCase().includes("application/pdf")) throw new Error("Pratinjau bukan file PDF");
          return response.blob();
        })
        .then((blob) => {
          if (!controller.signal.aborted) {
            objectUrl = URL.createObjectURL(blob);
            setDraftUrl(objectUrl);
          }
        })
        .catch((reason: unknown) => { if (!controller.signal.aborted) setDraftError(reason instanceof Error ? reason.message : "Pratinjau gagal dimuat"); })
        .finally(() => { if (!controller.signal.aborted) setDraftLoading(false); });
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [serid, startAt, endAt]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      await requestReport({ serid: Number(serid), start_at: new Date(startAt).toISOString(), end_at: new Date(endAt).toISOString() });
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Pembuatan laporan gagal");
    } finally {
      setCreating(false);
    }
  }

  return <div className="page-stack">
    <PageHeading title="Laporan" description="PDF dibuat di worker latar belakang dari scope stasiun dan waktu yang eksplisit." />
    {error ? <ErrorCard message={error} /> : null}
    {!jobs ? <LoadingCard /> : <>
      <div className="report-workspace">
      <LayerCard className="action-card report-form-card"><form className="action-form" onSubmit={create}>
        <label className="native-select-field" htmlFor="report-station"><span>Stasiun</span><select id="report-station" className="native-select" value={serid} onChange={(event) => setSerid(event.target.value)} required>{stations.map((station) => <option key={station.serid} value={station.serid}>{station.name} (SERID {station.serid})</option>)}</select></label>
        <label className="native-input-field" htmlFor="report-start"><span>Mulai</span><input id="report-start" type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} required /></label>
        <label className="native-input-field" htmlFor="report-end"><span>Selesai</span><input id="report-end" type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} required /></label>
        <div className="form-actions"><Button type="submit" variant="primary" disabled={creating || !serid || !draftUrl}>{creating ? "Meminta laporan…" : "Buat laporan"}</Button></div>
      </form></LayerCard>
      <section className="report-draft-pane" aria-label="Pratinjau PDF laporan saat ini">
        <h2>Pratinjau PDF</h2>
        <p>Pratinjau menggunakan stasiun dan rentang yang sedang dipilih.</p>
        {draftLoading ? <p role="status">Membuat pratinjau PDF…</p> : null}
        {draftError ? <p role="alert">Pratinjau PDF gagal dimuat: {draftError}</p> : null}
        {draftUrl ? <iframe title="Pratinjau PDF laporan saat ini" src={draftUrl} /> : null}
      </section>
      </div>
      <PageSection title="Job laporan" description="Status diperbarui otomatis setiap 3 detik.">
        <div className="mobile-card-list">
          {jobs.map((job) => <LayerCard className="user-card" key={job.job_id}>
            <strong>SERID {job.serid} · {job.status}</strong>
            <div className="card-meta"><span>{formatTimestamp(job.start_at)} sampai {formatTimestamp(job.end_at)}</span><span>Diminta {formatTimestamp(job.created_at)}</span>{job.error ? <span role="alert">{job.error}</span> : null}</div>
            {job.status === "completed" ? <div className="report-actions">
              <Button type="button" variant="secondary" onClick={() => setPreviewJobId((current) => current === job.job_id ? null : job.job_id)}>{previewJobId === job.job_id ? "Tutup pratinjau" : "Pratinjau PDF"}</Button>
              <a className="report-download-link" href={reportDownloadUrl(job.job_id)} download>Unduh PDF</a>
            </div> : null}
            {previewJobId === job.job_id && job.status === "completed" ? <section className="report-preview" aria-label={`Pratinjau laporan SERID ${job.serid}`}>
              {previewLoading ? <p role="status">Memuat pratinjau PDF…</p> : null}
              {previewError ? <p role="alert">Pratinjau PDF gagal dimuat: {previewError}</p> : null}
              {previewUrl ? <iframe title={`Pratinjau laporan SERID ${job.serid}`} src={previewUrl} /> : null}
            </section> : null}
          </LayerCard>)}
          {jobs.length === 0 ? <LayerCard className="empty-card">Belum ada laporan.</LayerCard> : null}
        </div>
      </PageSection>
    </>}
  </div>;
}
