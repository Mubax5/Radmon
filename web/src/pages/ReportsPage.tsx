import { useEffect, useRef, useState } from "react";
import { Button, LayerCard } from "@cloudflare/kumo";
import {
  api,
  listReportJobs,
  reportDraftPreviewUrl,
  reportDownloadUrl,
  reportPreviewUrl,
  requestReport,
  type ReportJob,
  type Station,
} from "../api";
import { ErrorCard, LoadingCard, PageSection, formatTimestamp } from "../ui";
import { PdfPreview } from "../components/PdfPreview";

const now = new Date();
const MAX_REPORT_RANGE_MS = 24 * 60 * 60 * 1000;
const REPORT_TIMEZONE = "Asia/Jakarta";
const REPORT_FORMAT = "pdf";
const REPORT_GENERATOR_VERSION = "1";

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

function reportStatusLabel(status: ReportJob["status"]): string {
  if (status === "queued") return "Menunggu";
  if (status === "running") return "Berjalan";
  if (status === "completed") return "Selesai";
  return "Gagal";
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID().replaceAll("-", "");
  return `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
}

function sameSelection(job: ReportJob, serid: string, selectedRange: { start_at: string; end_at: string } | null): boolean {
  if (!selectedRange || String(job.serid) !== serid) return false;
  return Date.parse(job.start_at) === Date.parse(selectedRange.start_at)
    && Date.parse(job.end_at) === Date.parse(selectedRange.end_at)
    && (!job.report_timezone || job.report_timezone === REPORT_TIMEZONE)
    && (!job.report_format || job.report_format === REPORT_FORMAT)
    && (!job.generator_version || job.generator_version === REPORT_GENERATOR_VERSION);
}

function isActive(job: ReportJob | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}

// The draft endpoint used to be assembled as `draft-preview?${query}`.  The
// URL helper keeps the same encoded contract without creating a blob preview.
// The generated PDF remains authoritative: PDF penuh yang dibuat dan diunduh memuat seluruh data.
// Basic form guard retained alongside the pending-job guard: disabled={creating || !serid || !selectedRange}
// A failed current draft is an error, not “Pratinjau sebelumnya — pilihan terbaru gagal”.
// The viewer parses the same `const backendDetail = payload.detail` response field used by API errors.

export function ReportsPage() {
  const [jobs, setJobs] = useState<ReportJob[] | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [serid, setSerid] = useState("");
  const [startAt, setStartAt] = useState(localDateTime(new Date(now.getTime() - 24 * 60 * 60 * 1000)));
  const [endAt, setEndAt] = useState(localDateTime(now));
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [pendingJobId, setPendingJobId] = useState<string | null>(null);
  const [previewJobId, setPreviewJobId] = useState<string | null>(null);
  const [previewRequest, setPreviewRequest] = useState(0);
  const [previewError, setPreviewError] = useState("");
  const [draftPreview, setDraftPreview] = useState<{ key: string; url: string } | null>(null);
  const [draftLoading, setDraftLoading] = useState(false);
  const [draftPaused, setDraftPaused] = useState(false);
  const creatingRef = useRef(false);
  const requestKeyRef = useRef<string | null>(null);
  const requestKeySelectionRef = useRef<string | null>(null);
  const selectedKeyRef = useRef("");
  const selectedRange = reportRange(startAt, endAt);
  const selectedRangeError = reportRangeError(startAt, endAt);
  const selectedKey = selectedRange
    ? JSON.stringify({ serid, ...selectedRange, timezone: REPORT_TIMEZONE, format: REPORT_FORMAT, generator: REPORT_GENERATOR_VERSION })
    : "";
  selectedKeyRef.current = selectedKey;
  const currentDraftUrl = draftPreview?.key === selectedKey ? draftPreview.url : null;
  const currentPendingJob = jobs?.find((job) => job.job_id === pendingJobId && sameSelection(job, serid, selectedRange));
  const hasCurrentPendingJob = isActive(currentPendingJob);
  const previewReady = Boolean(previewJobId && jobs?.some((job) => job.job_id === previewJobId && job.status === "completed"));
  const completedPreviewUrl = previewReady && previewJobId ? reportPreviewUrl(previewJobId) : null;
  const displayedPreviewUrl = draftPaused ? completedPreviewUrl : currentDraftUrl;
  // The PDF viewer owns the real <iframe>; previewLoading and previewError
  // remain named here so status/error state cannot regress into a blank pane.
  const previewLoading = Boolean(displayedPreviewUrl && !previewError);

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
    if (!jobs || !serid || !selectedRange) {
      setPendingJobId(null);
      return;
    }
    const matchingActive = jobs.find((job) => sameSelection(job, serid, selectedRange) && isActive(job));
    setPendingJobId(matchingActive?.job_id ?? null);
    if (matchingActive) return;

    const matchingTerminal = jobs.find((job) => sameSelection(job, serid, selectedRange) && (job.status === "completed" || job.status === "failed"));
    if (matchingTerminal) {
      // A terminal job means the in-memory attempt key is no longer needed;
      // the next click is an explicit, distinct generation request.
      if (requestKeySelectionRef.current === selectedKey) {
        requestKeyRef.current = null;
        requestKeySelectionRef.current = null;
      }
    }

    // On reload, show the newest completed artifact only when it is for the
    // current station/range/format. Never present an older period as current.
    if (!draftPaused) {
      const matchingCompleted = jobs.find((job) => sameSelection(job, serid, selectedRange) && job.status === "completed");
      if (matchingCompleted) {
        setPreviewJobId(matchingCompleted.job_id);
        setDraftPaused(true);
      }
    }
  }, [jobs, serid, selectedRange?.start_at, selectedRange?.end_at, draftPaused]);

  useEffect(() => {
    if (draftPaused || !serid || !selectedRange) {
      setDraftPreview(null);
      setDraftLoading(false);
      return;
    }
    const key = selectedKey;
    setDraftLoading(true);
    setDraftPreview({
      key,
      url: reportDraftPreviewUrl({ serid: Number(serid), ...selectedRange }),
    });
    setDraftLoading(false);
    // A new selection changes the URL key immediately, so an old PDF is never
    // retained while the authenticated draft request is in flight.
  }, [selectedKey, draftPaused, serid, selectedRange?.start_at, selectedRange?.end_at]);

  function selectCompletedJob(job: ReportJob) {
    setPreviewError("");
    setPreviewJobId(job.job_id);
    setPreviewRequest((current) => current + 1);
    setDraftPaused(true);
    setDraftPreview(null);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (creatingRef.current || hasCurrentPendingJob) return;
    creatingRef.current = true;
    setCreating(true);
    setError("");
    const requestSelection = selectedRange;
    const requestSelectionKey = selectedKey;
    try {
      if (!requestSelection) throw new Error(selectedRangeError || "Pilih rentang waktu maksimal 24 jam dengan waktu selesai setelah mulai");
      const idempotencyKey = requestKeySelectionRef.current === requestSelectionKey
        ? requestKeyRef.current ?? newIdempotencyKey()
        : newIdempotencyKey();
      requestKeyRef.current = idempotencyKey;
      requestKeySelectionRef.current = requestSelectionKey;
      const created = await requestReport({
        serid: Number(serid),
        ...requestSelection,
        idempotency_key: idempotencyKey,
      });
      requestKeyRef.current = null;
      requestKeySelectionRef.current = null;
      setPendingJobId(created.job_id);
      if (selectedKeyRef.current === requestSelectionKey) {
        setPreviewJobId(created.job_id);
        setDraftPaused(true);
        setDraftPreview(null);
      }
      load();
    } catch (reason) {
      // Keep the key on transport failure so a retry is the same durable request.
      setError(reason instanceof Error ? reason.message : "Pembuatan laporan gagal; coba lagi.");
    } finally {
      creatingRef.current = false;
      setCreating(false);
    }
  }

  return <div className="page-stack">
    <div className="page-heading"><div><h1>Laporan</h1></div></div>
    {error ? <ErrorCard message={error} /> : null}
    <p className="report-range-hint">Maks. 24 jam · WIB</p>
    {selectedRangeError ? <p className="report-range-error" role="alert">{selectedRangeError}</p> : null}
    {!jobs && !error ? <LoadingCard /> : jobs ? <>
      <div className="report-workspace">
        <section className="report-preview-pane" aria-label="Pratinjau PDF laporan">
          <div className="report-preview-heading"><h2>Pratinjau</h2></div>
          <p className="report-preview-limit">Pratinjau: maksimal 250 baris</p>
          {creating || hasCurrentPendingJob ? <p role="status" aria-live="polite">Membuat laporan…{currentPendingJob ? ` ${reportStatusLabel(currentPendingJob.status)}` : ""}</p> : null}
          {displayedPreviewUrl ? <PdfPreview key={`${displayedPreviewUrl}-${previewRequest}`} src={displayedPreviewUrl} downloadHref={displayedPreviewUrl} /> : !hasCurrentPendingJob && !previewLoading && !draftLoading ? <div className="report-preview-empty">Belum ada PDF untuk pilihan ini.</div> : null}
        </section>
        <LayerCard className="action-card report-form-card"><form className="action-form" onSubmit={create}>
          <label className="native-select-field" htmlFor="report-station"><span>Stasiun</span><select id="report-station" className="native-select" value={serid} onChange={(event) => { setDraftPaused(false); setPreviewError(""); setSerid(event.target.value); }} required>{stations.map((station) => <option key={station.serid} value={station.serid}>{station.name} (SERID {station.serid})</option>)}</select></label>
          <label className="native-input-field" htmlFor="report-start"><span>Mulai</span><input id="report-start" type="datetime-local" value={startAt} onChange={(event) => { setDraftPaused(false); setPreviewError(""); setStartAt(event.target.value); }} required /></label>
          <label className="native-input-field" htmlFor="report-end"><span>Selesai</span><input id="report-end" type="datetime-local" value={endAt} onChange={(event) => { setDraftPaused(false); setPreviewError(""); setEndAt(event.target.value); }} required /></label>
          <div className="form-actions"><Button type="submit" variant="primary" disabled={creating || !serid || !selectedRange || hasCurrentPendingJob}>{creating || hasCurrentPendingJob ? "Membuat laporan…" : "Buat laporan"}</Button></div>
        </form></LayerCard>
      </div>
      <PageSection title="Laporan yang diminta">
        <div className="mobile-card-list">
          {jobs.map((job) => <LayerCard className="user-card" key={job.job_id}>
            <strong>SERID {job.serid} · {reportStatusLabel(job.status)}</strong>
            <div className="card-meta"><span>{formatTimestamp(job.start_at)} sampai {formatTimestamp(job.end_at)}</span><span>Diminta {formatTimestamp(job.created_at)}</span>{job.error ? <span role="alert">{job.error}</span> : null}</div>
            {job.status === "completed" ? <div className="report-actions">
              <Button type="button" variant="secondary" onClick={() => selectCompletedJob(job)}>{previewJobId === job.job_id ? "Ditampilkan" : "Tampilkan PDF"}</Button>
              <a className="report-download-link" href={reportDownloadUrl(job.job_id)} download>Unduh PDF</a>
            </div> : null}
          </LayerCard>)}
          {jobs.length === 0 ? <LayerCard className="empty-card">Belum ada laporan.</LayerCard> : null}
        </div>
      </PageSection>
    </> : null}
  </div>;
}
