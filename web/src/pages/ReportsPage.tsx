import { useEffect, useState } from "react";
import { Button, LayerCard } from "@cloudflare/kumo";
import { api, listReportJobs, reportDownloadUrl, reportPreviewUrl, requestReport, type ReportJob, type Station } from "../api";
import { ErrorCard, LoadingCard, PageHeading, PageSection, formatTimestamp } from "../ui";

const now = new Date();
const MAX_REPORT_RANGE_MS = 24 * 60 * 60 * 1000;
const localDateTime = (date: Date) => {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
};
const reportRange = (startAt: string, endAt: string) => {
  const start = new Date(startAt);
  const end = new Date(endAt);
  const duration = end.getTime() - start.getTime();
  return Number.isFinite(start.getTime()) && Number.isFinite(end.getTime()) && duration > 0 && duration <= MAX_REPORT_RANGE_MS
    ? { start_at: start.toISOString(), end_at: end.toISOString() }
    : null;
};
const reportRangeError = (startAt: string, endAt: string) => {
  const start = new Date(startAt);
  const end = new Date(endAt);
  const duration = end.getTime() - start.getTime();
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) return "Waktu mulai dan selesai tidak valid.";
  if (duration <= 0) return "Waktu selesai harus setelah waktu mulai.";
  if (duration > MAX_REPORT_RANGE_MS) return "Rentang laporan maksimal 24 jam (tepat 24 jam diperbolehkan).";
  return "";
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
  const [draftPreview, setDraftPreview] = useState<{ key: string; url: string } | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [draftPaused, setDraftPaused] = useState(false);
  const selectedRange = reportRange(startAt, endAt);
  const selectedRangeError = reportRangeError(startAt, endAt);
  const selectedKey = selectedRange ? JSON.stringify({ serid, ...selectedRange }) : "";
  const currentDraftUrl = draftPreview?.key === selectedKey ? draftPreview.url : null;
  const displayedPreviewUrl = currentDraftUrl ?? (draftPaused ? previewUrl : null);
  const previewReady = Boolean(previewJobId && jobs?.some((job) => job.job_id === previewJobId && job.status === "completed"));
  const currentPreviewReady = Boolean(currentDraftUrl && !draftLoading && !draftError);

  useEffect(() => () => {
    if (draftPreview) URL.revokeObjectURL(draftPreview.url);
  }, [draftPreview]);

  const load = () => void Promise.all([listReportJobs(), api<Station[]>("/api/v1/web/stations")]).then(([reportRows, stationRows]) => {
    setJobs(reportRows);
    setPreviewJobId((current) => current && reportRows.some((job) => job.job_id === current)
      ? current
      : reportRows.find((job) => job.status === "completed")?.job_id ?? null);
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
    if (!previewJobId) {
      setPreviewUrl(null);
      setPreviewLoading(false);
      setPreviewError("");
      return;
    }
    if (!previewReady) {
      setPreviewLoading(false);
      return;
    }
    let objectUrl: string | null = null;
    let committed = false;
    const controller = new AbortController();
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
        committed = true;
        setPreviewUrl((previous) => {
          if (previous) URL.revokeObjectURL(previous);
          return objectUrl;
        });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setPreviewError(reason instanceof Error ? reason.message : "Pratinjau PDF gagal dimuat");
      })
      .finally(() => {
        if (!controller.signal.aborted) setPreviewLoading(false);
      });
    return () => {
      controller.abort();
      if (objectUrl && !committed) URL.revokeObjectURL(objectUrl);
    };
  }, [previewJobId, previewReady]);

  useEffect(() => {
    if (draftPaused) {
      setDraftLoading(false);
      return;
    }
    if (!serid || !selectedRange) {
      setDraftLoading(false);
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    let committed = false;
    const timer = window.setTimeout(() => {
      setDraftLoading(true);
      setDraftError("");
      const query = new URLSearchParams({ serid, ...selectedRange });
      fetch(`/api/v1/control/reports/draft-preview?${query}`, { credentials: "same-origin", signal: controller.signal })
        .then(async (response) => {
          if (!response.ok) {
            let detail = `${response.status} ${response.statusText}`;
            try {
              const payload = await response.json();
              const backendDetail = payload.detail;
              if (typeof backendDetail === "string") detail = backendDetail;
              else if (Array.isArray(backendDetail)) detail = backendDetail.map((item) => item.msg).filter(Boolean).join("; ") || detail;
            } catch {
              // Keep the HTTP status if a proxy returns a non-JSON error page.
            }
            throw new Error(detail);
          }
          if (!response.headers.get("content-type")?.toLowerCase().includes("application/pdf")) throw new Error("Pratinjau bukan file PDF");
          return response.blob();
        })
        .then((blob) => {
          if (!controller.signal.aborted) {
             objectUrl = URL.createObjectURL(blob);
             committed = true;
              setDraftPreview((previous) => {
                return { key: selectedKey, url: objectUrl! };
              });
           }
         })
        .catch((reason: unknown) => { if (!controller.signal.aborted) setDraftError(reason instanceof Error ? reason.message : "Pratinjau gagal dimuat"); })
        .finally(() => { if (!controller.signal.aborted) setDraftLoading(false); });
    }, 350);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
      if (objectUrl && !committed) URL.revokeObjectURL(objectUrl);
    };
   }, [serid, startAt, endAt, draftPaused]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    try {
      if (!selectedRange) throw new Error(selectedRangeError || "Pilih rentang waktu maksimal 24 jam dengan waktu selesai setelah mulai");
      const created = await requestReport({ serid: Number(serid), ...selectedRange });
      setPreviewJobId(created.job_id);
      load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Pembuatan laporan gagal");
    } finally {
      setCreating(false);
    }
  }

  return <div className="page-stack">
    <PageHeading title="Laporan" description="Buat dan pratinjau laporan PDF untuk stasiun dan rentang waktu pilihan." />
    {error ? <ErrorCard message={error} /> : null}
    <p className="report-range-hint">Waktu pada PDF ditampilkan sebagai WIB. Rentang laporan maksimal 24 jam; tepat 24 jam diperbolehkan.</p>
    {selectedRangeError ? <p className="report-range-error" role="alert">{selectedRangeError}</p> : null}
    {!jobs ? <LoadingCard /> : <>
       <div className="report-workspace">
       <section className="report-preview-pane" aria-label="Pratinjau PDF laporan">
          <div className="report-preview-heading"><h2>Pratinjau PDF</h2>{draftError && currentDraftUrl ? <span>PDF sebelumnya — pratinjau terbaru gagal</span> : draftPaused && previewUrl ? <span>PDF sebelumnya — bukan pilihan saat ini</span> : null}</div>
            <p role={draftError ? "alert" : undefined}>{draftError ? `Pratinjau pilihan gagal: ${draftError}` : draftLoading ? "Memperbarui pratinjau untuk stasiun dan rentang terpilih…" : "Pratinjau mengikuti stasiun dan rentang yang dipilih."}</p>
            <p className="report-preview-limit">Pratinjau: maksimal 250 baris. PDF penuh yang dibuat dan diunduh memuat seluruh data dalam rentang terpilih.</p>
         {previewLoading && !displayedPreviewUrl ? <p role="status">Memuat PDF laporan…</p> : null}
         {previewError && !displayedPreviewUrl ? <p role="alert">Pratinjau PDF gagal dimuat: {previewError}</p> : null}
          {displayedPreviewUrl ? <iframe title="Pratinjau PDF laporan" src={displayedPreviewUrl} /> : !previewLoading && !draftLoading ? <div className="report-preview-empty">{draftPaused && previewUrl ? "PDF sebelumnya — bukan pilihan saat ini." : "Pilih rentang untuk membuat pratinjau, atau buat laporan untuk melihat PDF di sini."}</div> : null}
       </section>
       <LayerCard className="action-card report-form-card"><form className="action-form" onSubmit={create}>
         <label className="native-select-field" htmlFor="report-station"><span>Stasiun</span><select id="report-station" className="native-select" value={serid} onChange={(event) => { setDraftPaused(false); setSerid(event.target.value); }} required>{stations.map((station) => <option key={station.serid} value={station.serid}>{station.name} (SERID {station.serid})</option>)}</select></label>
          <label className="native-input-field" htmlFor="report-start"><span>Mulai</span><input id="report-start" type="datetime-local" value={startAt} onChange={(event) => { setDraftPaused(false); setStartAt(event.target.value); }} required /></label>
          <label className="native-input-field" htmlFor="report-end"><span>Selesai</span><input id="report-end" type="datetime-local" value={endAt} onChange={(event) => { setDraftPaused(false); setEndAt(event.target.value); }} required /></label>
          <div className="form-actions"><Button type="submit" variant="primary" disabled={creating || !serid || !selectedRange || !currentPreviewReady}>{creating ? "Meminta laporan…" : "Buat laporan"}</Button></div>
       </form></LayerCard>
       </div>
       <PageSection title="Laporan yang diminta" description="Progres dan hasil laporan diperbarui otomatis.">
        <div className="mobile-card-list">
          {jobs.map((job) => <LayerCard className="user-card" key={job.job_id}>
            <strong>SERID {job.serid} · {job.status}</strong>
            <div className="card-meta"><span>{formatTimestamp(job.start_at)} sampai {formatTimestamp(job.end_at)}</span><span>Diminta {formatTimestamp(job.created_at)}</span>{job.error ? <span role="alert">{job.error}</span> : null}</div>
            {job.status === "completed" ? <div className="report-actions">
                <Button type="button" variant="secondary" onClick={() => { setPreviewJobId(job.job_id); setDraftPaused(true); setDraftPreview(null); }}>{previewJobId === job.job_id ? "Ditampilkan" : "Tampilkan PDF"}</Button>
              <a className="report-download-link" href={reportDownloadUrl(job.job_id)} download>Unduh PDF</a>
            </div> : null}
          </LayerCard>)}
          {jobs.length === 0 ? <LayerCard className="empty-card">Belum ada laporan.</LayerCard> : null}
        </div>
      </PageSection>
    </>}
  </div>;
}
