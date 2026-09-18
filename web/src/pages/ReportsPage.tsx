import { useEffect, useState } from "react";
import { Button, LayerCard } from "@cloudflare/kumo";
import { api, listReportJobs, reportDownloadUrl, requestReport, type ReportJob, type Station } from "../api";
import { ErrorCard, LoadingCard, PageHeading, PageSection, formatTimestamp } from "../ui";

const now = new Date();
const localDateTime = (date: Date) => date.toISOString().slice(0, 16);

export function ReportsPage() {
  const [jobs, setJobs] = useState<ReportJob[] | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [serid, setSerid] = useState("");
  const [startAt, setStartAt] = useState(localDateTime(new Date(now.getTime() - 24 * 60 * 60 * 1000)));
  const [endAt, setEndAt] = useState(localDateTime(now));
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const load = () => void Promise.all([listReportJobs(), api<Station[]>("/api/v1/web/stations")]).then(([reportRows, stationRows]) => { setJobs(reportRows); setStations(stationRows); setSerid((current) => current || String(stationRows[0]?.serid ?? "")); setError(""); }).catch((reason) => setError(reason instanceof Error ? reason.message : "Laporan tidak tersedia"));
  useEffect(() => { load(); const timer = window.setInterval(load, 3000); return () => window.clearInterval(timer); }, []);
  async function create(event: React.FormEvent) { event.preventDefault(); setCreating(true); try { await requestReport({ serid: Number(serid), start_at: new Date(startAt).toISOString(), end_at: new Date(endAt).toISOString() }); load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Pembuatan laporan gagal"); } finally { setCreating(false); } }
  return <div className="page-stack"><PageHeading title="Laporan" description="PDF dibuat di worker latar belakang dari scope stasiun dan waktu yang eksplisit." />{error ? <ErrorCard message={error} /> : null}{!jobs ? <LoadingCard /> : <><LayerCard className="action-card"><form className="action-form" onSubmit={create}><label className="native-select-field" htmlFor="report-station"><span>Stasiun</span><select id="report-station" className="native-select" value={serid} onChange={(event) => setSerid(event.target.value)} required>{stations.map((station) => <option key={station.serid} value={station.serid}>{station.name} (SERID {station.serid})</option>)}</select></label><label className="native-input-field" htmlFor="report-start"><span>Mulai</span><input id="report-start" type="datetime-local" value={startAt} onChange={(event) => setStartAt(event.target.value)} required /></label><label className="native-input-field" htmlFor="report-end"><span>Selesai</span><input id="report-end" type="datetime-local" value={endAt} onChange={(event) => setEndAt(event.target.value)} required /></label><div className="form-actions"><Button type="submit" variant="primary" disabled={creating || !serid}>{creating ? "Meminta laporan…" : "Buat laporan"}</Button></div></form></LayerCard><PageSection title="Job laporan" description="Status diperbarui otomatis setiap 3 detik."><div className="mobile-card-list">{jobs.map((job) => <LayerCard className="user-card" key={job.job_id}><strong>SERID {job.serid} · {job.status}</strong><div className="card-meta"><span>{formatTimestamp(job.start_at)} sampai {formatTimestamp(job.end_at)}</span><span>Diminta {formatTimestamp(job.created_at)}</span>{job.error ? <span role="alert">{job.error}</span> : null}</div>{job.status === "completed" ? <a className="report-download-link" href={reportDownloadUrl(job.job_id)} download>Unduh PDF</a> : null}</LayerCard>)}{jobs.length === 0 ? <LayerCard className="empty-card">Belum ada laporan.</LayerCard> : null}</div></PageSection></>}</div>;
}
