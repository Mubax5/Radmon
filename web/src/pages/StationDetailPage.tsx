import { useEffect, useState } from "react";
import { Button, Input, LayerCard } from "@cloudflare/kumo";
import { api, type Station } from "../api";
import { useSession } from "../auth";
import { useWebRefresh } from "../live";
import { navigate } from "../navigation";
import { ErrorCard, LoadingCard, PageHeading, StationDetail } from "../ui";

function stationId(): number | null {
  const value = Number(new URLSearchParams(window.location.search).get("serid"));
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function StationDetailPage() {
  const { user } = useSession();
  const serid = stationId();
  const [station, setStation] = useState<Station | null>(null);
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [warnlevel, setWarnlevel] = useState("");
  const [alarmlevel, setAlarmlevel] = useState("");
  const [maxidlemin, setMaxidlemin] = useState("");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const load = () => {
    if (!serid) return;
    void api<Station>(`/api/v1/web/stations/${serid}`).then((value) => {
      setStation(value); setName(value.name); setLocation(value.location); setDescription(value.description ?? "");
      setWarnlevel(String(value.warnlevel)); setAlarmlevel(String(value.alarmlevel)); setMaxidlemin(String(value.maxidlemin ?? 30)); setError("");
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "Stasiun tidak tersedia"));
  };
  useEffect(load, [serid]);
  useWebRefresh(() => { load(); });

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!serid || saving) return;
    setSaving(true); setError("");
    try {
      await api(`/api/v1/control/stations/${serid}`, { method: "POST", body: JSON.stringify({ pin, changes: { name, location, description, warnlevel: Number(warnlevel), alarmlevel: Number(alarmlevel), maxidlemin: Number(maxidlemin) } }) });
      setPin(""); load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Pembaruan stasiun gagal"); } finally { setSaving(false); }
  }

  async function deleteStation() {
    if (!serid || !station || saving || !window.confirm(`Hapus stasiun pusat ${station.name}? Measurement yang masih ada akan mencegah penghapusan.`)) return;
    setSaving(true); setError("");
    try {
      await api(`/api/v1/control/stations/${serid}`, { method: "DELETE", body: JSON.stringify({ pin }) });
      setPin(""); navigate("stations");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Penghapusan stasiun gagal"); } finally { setSaving(false); }
  }

  if (!serid) return <ErrorCard message="SERID stasiun tidak valid." />;
  if (!station && !error) return <LoadingCard />;
  return <div className="page-stack">
    <PageHeading title="Detail stasiun" description="Status terakhir dan konfigurasi yang dapat diedit tanpa mengubah measurement atau identitas detector." action={<Button variant="secondary" onClick={() => navigate("stations")}>Kembali</Button>} />
    {error ? <ErrorCard message={error} /> : null}
    <StationDetail station={station} onHistory={(item) => navigate("history", { station: item.serid })} />
    {station && user && user.role !== "Viewer" && station.ownership === "central" ? <LayerCard className="action-card">
      <h2>Edit konfigurasi pusat</h2><p>Identitas detector dan measurement tidak dapat diubah. Stasiun sumber LAN bersifat hanya-baca di pusat.</p>
      <form className="action-form" onSubmit={save}>
        <Input label="Nama" value={name} onChange={(event) => setName(event.target.value)} disabled={saving} />
        <Input label="Lokasi" value={location} onChange={(event) => setLocation(event.target.value)} disabled={saving} />
        <Input label="Deskripsi perangkat" value={description} onChange={(event) => setDescription(event.target.value)} disabled={saving} />
        <Input label="Threshold peringatan" type="number" value={warnlevel} onChange={(event) => setWarnlevel(event.target.value)} disabled={saving} />
        <Input label="Threshold alarm" type="number" value={alarmlevel} onChange={(event) => setAlarmlevel(event.target.value)} disabled={saving} />
        <Input label="Batas idle (menit)" type="number" min="1" value={maxidlemin} onChange={(event) => setMaxidlemin(event.target.value)} disabled={saving} />
        <Input label="PIN" type="password" value={pin} onChange={(event) => setPin(event.target.value)} disabled={saving} />
        <div className="form-actions"><Button type="submit" variant="primary" disabled={saving || !pin || !name || !location}>Simpan perubahan</Button><Button type="button" variant="secondary" disabled={saving || !pin} onClick={() => void deleteStation()}>Hapus stasiun pusat</Button></div>
      </form>
    </LayerCard> : station ? <LayerCard className="action-card">Stasiun ini dikelola oleh sumber LAN dan tidak dapat diubah atau dihapus dari pusat.</LayerCard> : null}
  </div>;
}
