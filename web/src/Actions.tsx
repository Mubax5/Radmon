import { useMemo, useState } from "react";
import { Button, Dialog, Input, LayerCard, Select } from "@cloudflare/kumo";
import { api, type Role } from "./api";

type AlarmEvent = {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
};

function Feedback({ state }: { state: { kind: "ok" | "error"; text: string } | null }) {
  if (!state) return null;
  return <div className={state.kind === "ok" ? "form-success" : "form-error"}>{state.text}</div>;
}

export function AlarmOperations({ events, onChanged }: { events: AlarmEvent[]; onChanged: () => void }) {
  const active = useMemo(() => events.filter((event) => event.kind === "ALARM" && event.status === "ACTIVE"), [events]);
  const eventItems = useMemo(
    () => Object.fromEntries(active.map((item) => [item.event_id, `SERID ${item.serid} · ${item.measured_value ?? "—"}`])),
    [active],
  );
  const [respondOpen, setRespondOpen] = useState(false);
  const [suppressionOpen, setSuppressionOpen] = useState(false);
  const [eventId, setEventId] = useState("");
  const [action, setAction] = useState("Konfirmasi");
  const [pic, setPic] = useState("");
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [serid, setSerid] = useState("");
  const [minutes, setMinutes] = useState("15");
  const [suppressPic, setSuppressPic] = useState("");
  const [suppressReason, setSuppressReason] = useState("");
  const [suppressPin, setSuppressPin] = useState("");
  const [pending, setPending] = useState<"respond" | "suppress" | null>(null);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  function resetResponse() {
    setEventId("");
    setAction("Konfirmasi");
    setPic("");
    setReason("");
    setPin("");
  }

  function resetSuppression() {
    setSerid("");
    setMinutes("15");
    setSuppressPic("");
    setSuppressReason("");
    setSuppressPin("");
  }

  function changeRespondOpen(open: boolean) {
    if (!open && pending === "respond") return;
    setRespondOpen(open);
    if (!open) resetResponse();
  }

  function changeSuppressionOpen(open: boolean) {
    if (!open && pending === "suppress") return;
    setSuppressionOpen(open);
    if (!open) resetSuppression();
  }

  async function respond(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending("respond");
    try {
      if (!eventId) throw new Error("Pilih event alarm aktif");
      await api(`/api/v1/control/alarm-events/${encodeURIComponent(eventId)}/response`, {
        method: "POST",
        body: JSON.stringify({ pin, action, pic, reason }),
      });
      setFeedback({ kind: "ok", text: "Respons alarm tersimpan." });
      resetResponse();
      setRespondOpen(false);
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Respons gagal" });
    } finally {
      setPin("");
      setPending(null);
    }
  }

  async function suppress(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending("suppress");
    try {
      const station = Number(serid);
      const duration = Number(minutes) * 60;
      if (!Number.isInteger(station) || station <= 0) throw new Error("SERID harus berupa angka positif");
      if (!Number.isFinite(duration) || duration < 60 || duration > 86400) throw new Error("Durasi harus 1 sampai 1440 menit");
      await api(`/api/v1/control/suppressions/${station}`, {
        method: "POST",
        body: JSON.stringify({
          pin: suppressPin,
          duration_seconds: duration,
          pic: suppressPic,
          reason: suppressReason,
          auto_resume_on_normal: true,
        }),
      });
      setFeedback({ kind: "ok", text: `Stasiun ${station} disupresi selama ${minutes} menit.` });
      resetSuppression();
      setSuppressionOpen(false);
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Suppression gagal" });
    } finally {
      setSuppressPin("");
      setPending(null);
    }
  }

  return (
    <div className="action-grid">
      <LayerCard className="action-card">
        <h2>Respons alarm</h2>
        <p>Respons alarm aktif setelah memastikan event, PIC, action, alasan, dan PIN operator.</p>
        <Dialog.Root open={respondOpen} onOpenChange={changeRespondOpen}>
          <Dialog.Trigger render={(props) => <Button {...props} variant="primary" disabled={active.length === 0 || pending !== null}>Respons alarm</Button>} />
          <Dialog>
            <Dialog.Title>Respons alarm</Dialog.Title>
            <Dialog.Description>
              PIN operator diverifikasi oleh backend RadMon sebelum respons diterima.
            </Dialog.Description>
            <form className="action-form dialog-form" onSubmit={respond}>
              <Select
                label="Event aktif"
                placeholder="Pilih event…"
                items={eventItems}
                value={eventId || undefined}
                onValueChange={(value) => setEventId(String(value ?? ""))}
                disabled={active.length === 0 || pending === "respond"}
              />
              <Input label="Action" value={action} onChange={(e) => setAction(e.target.value)} disabled={pending === "respond"} />
              <Input label="PIC" value={pic} onChange={(e) => setPic(e.target.value)} disabled={pending === "respond"} />
              <Input label="Alasan" value={reason} onChange={(e) => setReason(e.target.value)} disabled={pending === "respond"} />
              <Input label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} disabled={pending === "respond"} />
              <div className="form-actions">
                <Button type="submit" variant="primary" disabled={pending === "respond" || !eventId || !pic || !reason || !pin}>
                  {pending === "respond" ? "Menyimpan…" : "Kirim respons"}
                </Button>
                <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "respond"}>Batal</Button>} />
              </div>
            </form>
          </Dialog>
        </Dialog.Root>
      </LayerCard>

      <LayerCard className="action-card">
        <h2>Timed suppression</h2>
        <p>Supresi sementara tampilan alarm sementara measurement dose tetap berjalan tanpa gangguan.</p>
        <Dialog.Root open={suppressionOpen} onOpenChange={changeSuppressionOpen}>
          <Dialog.Trigger render={(props) => <Button {...props} variant="primary" disabled={pending !== null}>Mulai suppression</Button>} />
          <Dialog>
            <Dialog.Title>Timed suppression</Dialog.Title>
            <Dialog.Description>
              Suppression berlaku 1 menit sampai 24 jam dan otomatis resume saat detektor kembali NORMAL.
            </Dialog.Description>
            <form className="action-form dialog-form" onSubmit={suppress}>
              <Input label="SERID stasiun" inputMode="numeric" value={serid} onChange={(e) => setSerid(e.target.value)} disabled={pending === "suppress"} />
              <Input label="Durasi (menit)" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} disabled={pending === "suppress"} />
              <Input label="PIC" value={suppressPic} onChange={(e) => setSuppressPic(e.target.value)} disabled={pending === "suppress"} />
              <Input label="Alasan" value={suppressReason} onChange={(e) => setSuppressReason(e.target.value)} disabled={pending === "suppress"} />
              <Input label="PIN" type="password" value={suppressPin} onChange={(e) => setSuppressPin(e.target.value)} disabled={pending === "suppress"} />
              <div className="form-actions">
                <Button type="submit" variant="primary" disabled={pending === "suppress" || !serid || !minutes || !suppressPic || !suppressReason || !suppressPin}>
                  {pending === "suppress" ? "Memulai…" : "Mulai suppression"}
                </Button>
                <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "suppress"}>Batal</Button>} />
              </div>
            </form>
          </Dialog>
        </Dialog.Root>
      </LayerCard>
      <Feedback state={feedback} />
    </div>
  );
}

export function CreateUserForm({
  onCreated,
  onDone,
}: {
  onCreated: () => void;
  onDone?: () => void;
}) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("Viewer");
  const [password, setPassword] = useState("");
  const [userPin, setUserPin] = useState("");
  const [adminPin, setAdminPin] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  function reset() {
    if (pending) return;
    setUsername("");
    setDisplayName("");
    setRole("Viewer");
    setPassword("");
    setUserPin("");
    setAdminPin("");
    setFeedback(null);
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending(true);
    try {
      await api("/api/v1/control/users", {
        method: "POST",
        body: JSON.stringify({
          pin: adminPin,
          username,
          display_name: displayName,
          role,
          password,
          user_pin: userPin,
        }),
      });
      setFeedback({ kind: "ok", text: `Pengguna ${username} dibuat.` });
      setUsername("");
      setDisplayName("");
      setRole("Viewer");
      onCreated();
      onDone?.();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Pembuatan pengguna gagal" });
    } finally {
      setPassword("");
      setUserPin("");
      setAdminPin("");
      setPending(false);
    }
  }

  return (
    <form className="action-form user-create-form" onSubmit={submit}>
      <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} disabled={pending} />
      <Input label="Nama tampilan" value={displayName} onChange={(e) => setDisplayName(e.target.value)} disabled={pending} />
      <Select
        label="Role"
        items={{ Viewer: "Viewer", Operator: "Operator", Administrator: "Administrator" }}
        value={role}
        onValueChange={(value) => setRole((value ?? "Viewer") as Role)}
        disabled={pending}
      />
      <Input label="Password awal" type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={pending} />
      <Input label="PIN pengguna" type="password" value={userPin} onChange={(e) => setUserPin(e.target.value)} disabled={pending} />
      <Input label="PIN Administrator" type="password" value={adminPin} onChange={(e) => setAdminPin(e.target.value)} disabled={pending} />
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={pending || !username || !displayName || !password || !userPin || !adminPin}>
          {pending ? "Membuat…" : "Buat pengguna"}
        </Button>
        <Button type="button" variant="secondary" onClick={reset} disabled={pending}>Bersihkan</Button>
      </div>
      <Feedback state={feedback} />
    </form>
  );
}

export function CreateUserPanel({ onCreated }: { onCreated: () => void }) {
  return (
    <LayerCard className="action-card user-create-card">
      <h2>Buat pengguna</h2>
      <p>Viewer adalah role read-only terautentikasi; akses anonim bukan pengguna RadMon.</p>
      <CreateUserForm onCreated={onCreated} />
    </LayerCard>
  );
}
