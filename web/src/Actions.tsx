import { useEffect, useMemo, useState } from "react";
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

export type Suppression = {
  suppression_id: string;
  serid: number;
  expires_at: string;
  pic: string;
  reason: string;
  ended_at?: string | null;
  ended_reason?: string | null;
  source_silence_state?: string;
};

const DURATION_ITEMS = {
  "1": "1 menit",
  "5": "5 menit",
  "15": "15 menit",
  "30": "30 menit",
  "60": "1 jam",
  "120": "2 jam",
  "240": "4 jam",
  "480": "8 jam",
  "1440": "24 jam",
};

// Preset action respons alarm. Backend (PolicyResponseRequest.action: 1-128 char)
// menerima string bebas, jadi preset ini selalu valid dan konsisten dengan
// default historis "Konfirmasi" + dialog desktop (Confirm/Follow-up/dll).
const RESPONSE_ACTION_ITEMS = {
  Konfirmasi: "Konfirmasi",
  Eskalasi: "Eskalasi",
  Selesai: "Selesai",
  "Verifikasi Normal": "Verifikasi Normal",
  "Tindak Lanjut": "Tindak Lanjut",
};

function Feedback({ state }: { state: { kind: "ok" | "error"; text: string } | null }) {
  if (!state) return null;
  return <div className={state.kind === "ok" ? "form-success" : "form-error"}>{state.text}</div>;
}

function NativeSelect({
  id,
  label,
  value,
  onChange,
  children,
  disabled = false,
  required = false,
  name,
  testId,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLSelectElement>) => void;
  children: React.ReactNode;
  disabled?: boolean;
  required?: boolean;
  name?: string;
  testId: string;
}) {
  return (
    <label className="native-select-field" htmlFor={id}>
      <span>{label}</span>
      <select
        id={id}
        name={name}
        className="native-select"
        data-testid={testId}
        aria-label={label}
        value={value}
        onChange={onChange}
        disabled={disabled}
        required={required}
      >
        {children}
      </select>
    </label>
  );
}

export function AlarmOperations({ events, suppressions, onChanged }: { events: AlarmEvent[]; suppressions: Suppression[]; onChanged: () => void }) {
  const active = useMemo(
    () => events.filter((event) => String(event.kind).toUpperCase() === "ALARM" && String(event.status).toUpperCase() === "ACTIVE"),
    [events],
  );
  const eventItems = useMemo(
    () => Object.fromEntries(active.map((item) => [item.event_id, `SERID ${item.serid} · ${item.measured_value ?? "—"}`])),
    [active],
  );
  const [respondOpen, setRespondOpen] = useState(false);
  const [suppressionOpen, setSuppressionOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState("");
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
  const [cancelReason, setCancelReason] = useState("");
  const [cancelPin, setCancelPin] = useState("");
  const [pending, setPending] = useState<"respond" | "suppress" | "cancel" | null>(null);
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Keep the native control bound even when a live refresh changes the active list.
  useEffect(() => {
    if (active.length === 1) {
      if (eventId !== active[0].event_id) setEventId(active[0].event_id);
      return;
    }
    if (eventId && !active.some((item) => item.event_id === eventId)) setEventId("");
  }, [active, eventId]);

  const selectedEventId = active.length === 1
    ? active[0].event_id
    : active.some((item) => item.event_id === eventId) ? eventId : "";

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
    if (open) {
      // Dialog dibuka saat tepat satu alarm aktif: langsung ikat valuenya
      // sehingga trigger tidak tertinggal di placeholder.
      if (!eventId && active.length === 1) setEventId(active[0].event_id);
    } else resetResponse();
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
      if (!selectedEventId) throw new Error("Pilih event alarm aktif");
      await api(`/api/v1/control/alarm-events/${encodeURIComponent(selectedEventId)}/response`, {
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

  async function cancelSuppression(event: React.FormEvent, item: Suppression) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending("cancel");
    try {
      await api(`/api/v1/control/suppressions/${encodeURIComponent(item.suppression_id)}/cancel`, {
        method: "POST",
        body: JSON.stringify({ pin: cancelPin, reason: cancelReason }),
      });
      setFeedback({ kind: "ok", text: `Suppression stasiun ${item.serid} diakhiri.` });
      setCancelOpen("");
      setCancelReason("");
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Pembatalan suppression gagal" });
    } finally {
      setCancelPin("");
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
          <Dialog className="radmon-dialog mobile-sheet-dialog" data-testid="alarm-response-dialog">
            <div className="mobile-sheet-content">
              <div className="mobile-sheet-handle" aria-hidden />
              <Dialog.Title>Respons alarm</Dialog.Title>
              <Dialog.Description>
                PIN operator diverifikasi oleh backend RadMon sebelum respons diterima.
              </Dialog.Description>
              <form className="action-form dialog-form" onSubmit={respond}>
                <NativeSelect
                  id="alarm-event-select"
                  name="event_id"
                  testId="alarm-event-select"
                  label={`Event aktif (${active.length})`}
                  value={selectedEventId}
                  onChange={(event) => setEventId(event.target.value)}
                  disabled={active.length === 0 || pending === "respond"}
                  required
                >
                  <option value="">Pilih event...</option>
                  {Object.entries(eventItems).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </NativeSelect>
                {active.length === 0 ? (
                  <p className="cell-subtle alarm-empty-hint" role="status">
                    Tidak ada alarm aktif saat ini. Respons tersedia setelah ada event ALARM ACTIVE.
                  </p>
                ) : (
                  <p className="cell-subtle alarm-empty-hint" role="status">
                    {active.length} alarm aktif tersedia untuk direspons.
                  </p>
                )}
                <NativeSelect
                  id="alarm-action-select"
                  name="action"
                  testId="alarm-action-select"
                  label="Action"
                  value={action}
                  onChange={(event) => setAction(event.target.value)}
                  disabled={pending === "respond"}
                  required
                >
                  {Object.entries(RESPONSE_ACTION_ITEMS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </NativeSelect>
                <Input label="PIC" value={pic} onChange={(e) => setPic(e.target.value)} disabled={pending === "respond"} />
                <Input label="Alasan" value={reason} onChange={(e) => setReason(e.target.value)} disabled={pending === "respond"} />
                <Input label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} disabled={pending === "respond"} />
                <div className="form-actions">
                  <Button type="submit" variant="primary" disabled={pending === "respond" || !selectedEventId || !pic || !reason || !pin}>
                    {pending === "respond" ? "Menyimpan…" : "Kirim respons"}
                  </Button>
                  <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "respond"}>Batal</Button>} />
                </div>
              </form>
            </div>
          </Dialog>
        </Dialog.Root>
      </LayerCard>

      <LayerCard className="action-card">
        <h2>Timed suppression</h2>
        <p>Supresi sementara tampilan alarm sementara measurement dose tetap berjalan tanpa gangguan.</p>
        <Dialog.Root open={suppressionOpen} onOpenChange={changeSuppressionOpen}>
          <Dialog.Trigger render={(props) => <Button {...props} variant="primary" disabled={pending !== null}>Mulai suppression</Button>} />
          <Dialog className="radmon-dialog mobile-sheet-dialog">
            <div className="mobile-sheet-content">
              <div className="mobile-sheet-handle" aria-hidden />
              <Dialog.Title>Timed suppression</Dialog.Title>
              <Dialog.Description>
                Suppression berlaku 1 menit sampai 24 jam dan otomatis resume saat detektor kembali NORMAL.
              </Dialog.Description>
              <form className="action-form dialog-form" onSubmit={suppress}>
                <Input label="SERID stasiun" inputMode="numeric" value={serid} onChange={(e) => setSerid(e.target.value)} disabled={pending === "suppress"} />
                <Select
                  label="Durasi suppression"
                  items={DURATION_ITEMS}
                  value={minutes}
                  onValueChange={(value) => setMinutes(String(value ?? "15"))}
                  disabled={pending === "suppress"}
                />
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
            </div>
          </Dialog>
        </Dialog.Root>
        <div className="active-suppression-list" aria-live="polite">
          <h3>Suppression aktif</h3>
          {suppressions.length === 0 ? <p className="cell-subtle">Tidak ada suppression aktif.</p> : suppressions.map((item) => (
            <div className="active-suppression-row" key={item.suppression_id}>
              <div>
                <strong>SERID {item.serid}</strong>
                <span>Sampai {new Date(item.expires_at).toLocaleString("id-ID")} · sumber {item.source_silence_state ?? "NONE"}</span>
                <span>{item.pic}: {item.reason}</span>
              </div>
              <Dialog.Root open={cancelOpen === item.suppression_id} onOpenChange={(open) => {
                if (pending === "cancel") return;
                setCancelOpen(open ? item.suppression_id : "");
                if (!open) { setCancelReason(""); setCancelPin(""); }
              }}>
                <Dialog.Trigger render={(props) => <Button {...props} variant="secondary" disabled={pending !== null}>Akhiri suppression</Button>} />
                <Dialog className="radmon-dialog mobile-sheet-dialog">
                  <div className="mobile-sheet-content">
                    <div className="mobile-sheet-handle" aria-hidden />
                    <Dialog.Title>Akhiri suppression SERID {item.serid}</Dialog.Title>
                    <Dialog.Description>Pembatalan dicatat permanen dan tidak menghapus measurement atau riwayat alarm.</Dialog.Description>
                    <form className="action-form dialog-form" onSubmit={(event) => void cancelSuppression(event, item)}>
                      <Input label="Alasan pembatalan" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} disabled={pending === "cancel"} />
                      <Input label="PIN" type="password" value={cancelPin} onChange={(event) => setCancelPin(event.target.value)} disabled={pending === "cancel"} />
                      <div className="form-actions">
                        <Button type="submit" variant="primary" disabled={pending === "cancel" || !cancelReason || !cancelPin}>{pending === "cancel" ? "Mengakhiri…" : "Akhiri suppression"}</Button>
                        <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "cancel"}>Batal</Button>} />
                      </div>
                    </form>
                  </div>
                </Dialog>
              </Dialog.Root>
            </div>
          ))}
        </div>
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
      <label className="native-input-field"><span>Username</span><input value={username} onChange={(e) => setUsername(e.target.value)} disabled={pending} required autoComplete="username" /></label>
      <label className="native-input-field"><span>Nama tampilan</span><input value={displayName} onChange={(e) => setDisplayName(e.target.value)} disabled={pending} required autoComplete="name" /></label>
      <NativeSelect
        id="user-role-select"
        name="role"
        testId="user-role-select"
        label="Role"
        value={role}
        onChange={(event) => setRole(event.target.value as Role)}
        disabled={pending}
        required
      >
        <option value="Viewer">Viewer</option>
        <option value="Operator">Operator</option>
        <option value="Administrator">Administrator</option>
      </NativeSelect>
      <label className="native-input-field"><span>Password awal</span><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={pending} required minLength={8} autoComplete="new-password" /></label>
      <label className="native-input-field"><span>PIN pengguna</span><input type="password" inputMode="numeric" value={userPin} onChange={(e) => setUserPin(e.target.value)} disabled={pending} required minLength={4} maxLength={8} autoComplete="new-password" /></label>
      <label className="native-input-field"><span>PIN Administrator</span><input type="password" inputMode="numeric" value={adminPin} onChange={(e) => setAdminPin(e.target.value)} disabled={pending} required minLength={4} maxLength={8} autoComplete="current-password" /></label>
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
