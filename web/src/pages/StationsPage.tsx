import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Input, LayerCard, Select } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { useSession } from "../auth";
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
  all: "Semua status",
  normal: "Normal",
  warning: "Peringatan",
  alarm: "Alarm",
  offline: "Offline",
};

export function StationsPage() {
  const createDialog = useRef<HTMLDialogElement>(null);
  const { user } = useSession();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [newSerid, setNewSerid] = useState("");
  const [newName, setNewName] = useState("");
  const [newLocation, setNewLocation] = useState("");
  const [newDescription, setNewDescription] = useState("");
  const [newWarnlevel, setNewWarnlevel] = useState("");
  const [newAlarmlevel, setNewAlarmlevel] = useState("");
  const [newMaxidlemin, setNewMaxidlemin] = useState("30");
  const [newPin, setNewPin] = useState("");
  const [creating, setCreating] = useState(false);

  const load = () => api<Overview>("/api/v1/web/overview")
    .then((value) => {
      setOverview(value);
      setSelected((current) => current && value.stations.some((item) => item.serid === current)
        ? current
        : value.stations[0]?.serid ?? null);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat stasiun"));

  useEffect(() => { void load(); }, []);
  useWebRefresh(() => { void load(); });

  async function createStation(event: React.FormEvent) {
    event.preventDefault();
    const serid = Number(newSerid);
    if (!Number.isInteger(serid) || serid <= 0) { setError("SERID harus berupa angka positif"); return; }
    setError("");
    const warnlevel = Number(newWarnlevel);
    const alarmlevel = Number(newAlarmlevel);
    const maxidlemin = Number(newMaxidlemin);
    if (![warnlevel, alarmlevel, maxidlemin].every(Number.isFinite) || warnlevel < 0 || alarmlevel < warnlevel || maxidlemin < 1 || !Number.isInteger(maxidlemin)) { setError("Threshold dan batas idle tidak valid"); return; }
    setCreating(true);
    try {
      await api("/api/v1/control/stations", { method: "POST", body: JSON.stringify({ pin: newPin, serid, values: { name: newName, location: newLocation, description: newDescription, warnlevel, alarmlevel, maxidlemin } }) });
      setNewSerid(""); setNewName(""); setNewLocation(""); setNewDescription(""); setNewWarnlevel(""); setNewAlarmlevel(""); setNewMaxidlemin("30"); setNewPin(""); createDialog.current?.close(); load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Pembuatan stasiun gagal"); } finally { setCreating(false); }
  }

  function fillExample() {
    setNewSerid("12345"); setNewName("Stasiun Contoh"); setNewLocation("Ruang pemantauan");
    setNewDescription("Detektor RadMon contoh"); setNewWarnlevel("0.5"); setNewAlarmlevel("1");
    setNewMaxidlemin("30"); setNewPin(""); setError("");
  }

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
  const openAlarm = user && user.role !== "Viewer"
    ? (station: Station) => navigate("alarms", { serid: station.serid, event: station.active_event_id ?? undefined })
    : undefined;
  const abnormal = overview ? overview.stations.filter((station) => station.status !== "normal").length : 0;

  if (!overview && !error) return <LoadingCard />;

  return (
    <div className="page-stack">
      <PageHeading
        title="Stasiun"
        description="Cari stasiun, tinjau status dan ambang radiasinya, atau buka riwayat pengukuran."
      />
      {error ? <ErrorCard message={error} /> : null}
      {overview ? (
        <>
          <div className="metric-grid station-summary">
            <MetricCard label="Terkonfigurasi" value={overview.stations.length} badge={<span className="cell-subtle">Semua detektor</span>} />
            <MetricCard label="Normal" value={overview.counts.normal || 0} badge={<span className="cell-subtle">Saat ini</span>} />
            <MetricCard label="Perlu perhatian" value={abnormal} badge={<span className="cell-subtle">Peringatan, alarm, offline</span>} />
            <MetricCard label="Offline" value={overview.counts.offline || 0} badge={<span className="cell-subtle">Data live usang atau tidak ada</span>} />
          </div>

          <LayerCard className="filter-card station-search">
            <div className="station-filter-grid">
              <Input
                label="Cari stasiun"
                placeholder="Nama, lokasi, atau SERID"
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
            title="Detail stasiun"
            description={`${filtered.length} dari ${overview.stations.length} stasiun ditampilkan.`}
            action={user && user.role !== "Viewer" ? <Button type="button" variant="primary" onClick={() => createDialog.current?.showModal()}>Tambah stasiun</Button> : undefined}
          >
            <div className="station-workspace">
              <ResponsiveStationView
                stations={filtered}
                onOpen={(station) => navigate("station", { serid: station.serid })}
                onHistory={(station) => navigate("history", { station: station.serid })}
                onAlarm={openAlarm}
              />
              <StationDetail
                station={selectedStation}
                onHistory={(station) => navigate("history", { station: station.serid })}
                onAlarm={openAlarm}
              />
            </div>
          </PageSection>
          {user && user.role !== "Viewer" ? <>
            <dialog ref={createDialog} className="native-user-dialog" aria-labelledby="station-create-title" data-testid="station-create-dialog">
              <div className="native-user-dialog-content"><h2 id="station-create-title">Tambah stasiun</h2>
                <p>Daftarkan konfigurasi stasiun. Akses perubahan mengikuti role dan izin yang berlaku.</p>
                <div className="form-actions"><Button type="button" variant="secondary" onClick={fillExample}>Contoh</Button><span className="cell-subtle">Mengisi nilai contoh tanpa menyimpan.</span></div>
                <form className="action-form" onSubmit={createStation}>
                  <Input label="SERID" type="number" min="1" value={newSerid} onChange={(event) => setNewSerid(event.target.value)} disabled={creating} />
                  <Input label="Nama" value={newName} onChange={(event) => setNewName(event.target.value)} disabled={creating} />
                  <Input label="Lokasi" value={newLocation} onChange={(event) => setNewLocation(event.target.value)} disabled={creating} />
                  <Input label="Deskripsi perangkat" value={newDescription} onChange={(event) => setNewDescription(event.target.value)} disabled={creating} />
                  <Input label="Threshold peringatan" type="number" min="0" value={newWarnlevel} onChange={(event) => setNewWarnlevel(event.target.value)} disabled={creating} />
                  <Input label="Threshold alarm" type="number" min="0" value={newAlarmlevel} onChange={(event) => setNewAlarmlevel(event.target.value)} disabled={creating} />
                  <Input label="Batas idle (menit)" type="number" min="1" value={newMaxidlemin} onChange={(event) => setNewMaxidlemin(event.target.value)} disabled={creating} />
                  <Input label="PIN" type="password" value={newPin} onChange={(event) => setNewPin(event.target.value)} disabled={creating} />
                  {error ? <div className="form-error" role="alert">{error}</div> : null}
                  <div className="form-actions"><Button type="submit" variant="primary" disabled={creating || !newSerid || !newName || !newLocation || !newWarnlevel || !newAlarmlevel || !newPin}>{creating ? "Membuat…" : "Tambah stasiun"}</Button><Button type="button" variant="secondary" disabled={creating} onClick={() => createDialog.current?.close()}>Batal</Button></div>
                </form>
              </div>
            </dialog>
          </> : null}
        </>
      ) : null}
    </div>
  );
}
