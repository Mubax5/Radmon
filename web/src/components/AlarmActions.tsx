import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Button, Dialog, Input, LayerCard } from "@cloudflare/kumo";
import { api, type Suppression } from "../api";
import { formatDoseValue } from "../format";
import { useSession } from "../auth";
import {
  alarmResponseRequest,
  confirmAlarmResponse,
  isSourceAlarmActionable,
  type ActiveAlarm,
} from "../activeAlarms";
import { ActionFeedback, type FeedbackState } from "./ActionFeedback";
import { NativeSelect } from "./NativeSelect";

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

const RESPONSE_ACTION_ITEMS = {
  Konfirmasi: "Konfirmasi",
  Eskalasi: "Eskalasi",
  Selesai: "Selesai",
  "Verifikasi Normal": "Verifikasi Normal",
  "Tindak Lanjut": "Tindak Lanjut",
};

type AlarmOperationsProps = {
  events: ActiveAlarm[];
  sourceEvents?: ActiveAlarm[];
  suppressions: Suppression[];
  onChanged: () => void;
  initialEventId?: string | null;
  activeError?: string;
  sourceStatus?: "loading" | "ready" | "error";
  suppressionsStatus?: "loading" | "ready" | "error";
};

type SourceResponse = {
  status?: string;
  is_active?: boolean;
  source_i_flag?: number;
  acknowledged_at?: string;
};

function SourceResponsePanel({
  events,
  sourceEvents,
  onChanged,
  initialEventId,
  activeError,
  sourceStatus = "ready",
}: Pick<AlarmOperationsProps, "events" | "sourceEvents" | "onChanged" | "initialEventId" | "activeError" | "sourceStatus">) {
  const { user } = useSession();
  const canEditPic = user?.role === "Administrator";
  const sourceAlarmEvents = useMemo(
    () => (sourceEvents ?? events).filter(isSourceAlarmActionable),
    [events, sourceEvents],
  );
  const eventItems = useMemo(
    () => Object.fromEntries(sourceAlarmEvents.map((item) => [
      item.event_id,
      `SERID ${item.serid} · ${item.source_id || "Pusat"} · ${item.reason === "LOW_THRESHOLD" ? "Alarm rendah" : "Alarm tinggi"} · ${formatDoseValue(item.measured_value)} · ${item.surfaced_at || item.event_time || ""}`,
    ])),
    [sourceAlarmEvents],
  );
  const [dialogOpen, setDialogOpen] = useState(false);
  const [eventId, setEventId] = useState("");
  const [action, setAction] = useState("Konfirmasi");
  const [pic, setPic] = useState(user?.display_name ?? "");
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

  useEffect(() => {
    setPic(user?.display_name ?? "");
  }, [user?.display_name]);

  useEffect(() => {
    if (!initialEventId || !sourceAlarmEvents.some((item) => item.event_id === initialEventId)) return;
    setEventId(initialEventId);
    setDialogOpen(true);
  }, [initialEventId, sourceAlarmEvents]);

  useEffect(() => {
    if (sourceAlarmEvents.length === 1) {
      if (eventId !== sourceAlarmEvents[0].event_id) setEventId(sourceAlarmEvents[0].event_id);
      return;
    }
    if (eventId && !sourceAlarmEvents.some((item) => item.event_id === eventId)) setEventId("");
  }, [eventId, sourceAlarmEvents]);

  const selectedEventId = sourceAlarmEvents.length === 1
    ? sourceAlarmEvents[0].event_id
    : sourceAlarmEvents.some((item) => item.event_id === eventId) ? eventId : "";
  const selectedEvent = sourceAlarmEvents.find((item) => item.event_id === selectedEventId);
  const responseDisabled = sourceStatus !== "ready" || sourceAlarmEvents.length === 0 || !user || user.role === "Viewer" || pending;
  const responseHelp = sourceStatus === "loading"
    ? "Status alarm sumber sedang dimuat; respons dikunci."
    : sourceStatus === "error"
      ? `Status alarm sumber tidak tersedia${activeError ? `: ${activeError}` : ""}; respons dikunci.`
      : sourceAlarmEvents.length === 0
        ? "Tidak ada alarm yang berbunyi."
        : `${sourceAlarmEvents.length} alarm sumber berbunyi tersedia untuk direspons.`;

  function resetForm() {
    setEventId("");
    setAction("Konfirmasi");
    setPic(user?.display_name ?? "");
    setReason("");
    setPin("");
  }

  function changeDialogOpen(open: boolean) {
    if (!open && pending) return;
    setDialogOpen(open);
    if (open) {
      if (!eventId && sourceAlarmEvents.length === 1) setEventId(sourceAlarmEvents[0].event_id);
    } else {
      resetForm();
    }
  }

  async function respond(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending(true);
    try {
      if (!selectedEventId) throw new Error("Pilih alarm sumber yang aktif");
      const selected = sourceAlarmEvents.find((item) => item.event_id === selectedEventId);
      if (!selected || !isSourceAlarmActionable(selected) || user?.role === "Viewer") {
        throw new Error("Pilih alarm sumber yang masih berbunyi dengan izin operator");
      }
      const request = alarmResponseRequest(selected, { pin, action, pic, reason });
      const result = await api<SourceResponse>(request.route, {
        method: "POST",
        body: JSON.stringify(request.body),
      });
      confirmAlarmResponse(selected, result);
      setFeedback({
        kind: "ok",
        text: result.status === "ALREADY_HANDLED"
          ? "Alarm sumber sudah ditangani sebelumnya."
          : "Alarm sumber berhasil ditangani.",
      });
      resetForm();
      setDialogOpen(false);
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Respons gagal" });
    } finally {
      setPin("");
      setPending(false);
    }
  }

  return (
    <LayerCard className="action-card">
      <h2>Respons alarm sumber</h2>
      <p>Tangani alarm yang masih berbunyi pada alat sumber. PIC operator dan PIN diperlukan.</p>
      <Dialog.Root open={dialogOpen} onOpenChange={changeDialogOpen}>
        <Dialog.Trigger render={(props) => <Button {...props} variant="primary" aria-describedby="alarm-response-help" disabled={responseDisabled}>Respons alarm</Button>} />
        <p id="alarm-response-help" className="cell-subtle alarm-empty-hint" role="status">{responseHelp}</p>
        {sourceStatus === "error" ? <Button type="button" variant="secondary" onClick={() => void onChanged()}>Coba lagi status sumber</Button> : null}
        <Dialog className="radmon-dialog mobile-sheet-dialog" data-testid="alarm-response-dialog">
          <div className="mobile-sheet-content">
            <div className="mobile-sheet-handle" aria-hidden />
            <Dialog.Title>Respons alarm sumber</Dialog.Title>
            <Dialog.Description>PIN operator diperlukan untuk mencatat tindakan pada alarm yang dipilih.</Dialog.Description>
            <form className="action-form dialog-form" onSubmit={respond}>
              <NativeSelect
                id="alarm-event-select"
                name="event_id"
                testId="alarm-event-select"
                label={`Alarm sumber aktif (${activeError ? "?" : sourceAlarmEvents.length})`}
                value={selectedEventId}
                onChange={(event) => setEventId(event.target.value)}
                disabled={sourceAlarmEvents.length === 0 || pending}
                required
              >
                <option value="">Pilih alarm sumber…</option>
                {Object.entries(eventItems).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </NativeSelect>
              {sourceAlarmEvents.length === 0 ? (
                <p className="cell-subtle alarm-empty-hint" role="status">
                  {sourceStatus === "loading" ? "Status alarm sumber sedang dimuat; pilihan dikunci." : sourceStatus === "error" ? `Status alarm sumber tidak tersedia: ${activeError || "muat ulang status"}` : "Tidak ada alarm yang berbunyi."}
                </p>
              ) : <p className="cell-subtle alarm-empty-hint" role="status">{sourceAlarmEvents.length} alarm sumber berbunyi tersedia untuk direspons.</p>}
              <NativeSelect
                id="alarm-action-select"
                name="action"
                testId="alarm-action-select"
                label="Tindakan"
                value={action}
                onChange={(event) => setAction(event.target.value)}
                disabled={pending}
                required
              >
                {Object.entries(RESPONSE_ACTION_ITEMS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </NativeSelect>
              <Input label="PIC" value={pic} onChange={(event) => setPic(event.target.value)} readOnly={!canEditPic} disabled={pending} />
              <Input label="Alasan" value={reason} onChange={(event) => setReason(event.target.value)} disabled={pending} />
              <Input label="PIN" type="password" value={pin} onChange={(event) => setPin(event.target.value)} disabled={pending} />
              <div className="form-actions">
                <Button type="submit" variant="primary" disabled={pending || !selectedEvent || !pic || !reason || !pin || sourceStatus !== "ready"}>
                  {pending ? "Menyimpan…" : "Kirim respons"}
                </Button>
                <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending}>Batal</Button>} />
              </div>
            </form>
          </div>
        </Dialog>
      </Dialog.Root>
      <ActionFeedback state={feedback} />
    </LayerCard>
  );
}

function SuppressionPanel({ suppressions, onChanged, suppressionsStatus = "ready" }: Pick<AlarmOperationsProps, "suppressions" | "onChanged" | "suppressionsStatus">) {
  const { user } = useSession();
  const canEditPic = user?.role === "Administrator";
  const [dialogOpen, setDialogOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState("");
  const [serid, setSerid] = useState("");
  const [minutes, setMinutes] = useState("15");
  const [pic, setPic] = useState(user?.display_name ?? "");
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [cancelReason, setCancelReason] = useState("");
  const [cancelPin, setCancelPin] = useState("");
  const [pending, setPending] = useState<"start" | "cancel" | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

  useEffect(() => {
    setPic(user?.display_name ?? "");
  }, [user?.display_name]);

  function resetForm() {
    setSerid("");
    setMinutes("15");
    setPic(user?.display_name ?? "");
    setReason("");
    setPin("");
  }

  function changeDialogOpen(open: boolean) {
    if (!open && pending === "start") return;
    setDialogOpen(open);
    if (!open) resetForm();
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending("start");
    try {
      const station = Number(serid);
      const duration = Number(minutes) * 60;
      if (!Number.isInteger(station) || station <= 0) throw new Error("SERID harus berupa angka positif");
      if (!Number.isFinite(duration) || duration < 60 || duration > 86400) throw new Error("Durasi harus 1 sampai 1440 menit");
      await api(`/api/v1/control/suppressions/${station}`, {
        method: "POST",
        body: JSON.stringify({ pin, duration_seconds: duration, pic, reason, auto_resume_on_normal: true }),
      });
      setFeedback({ kind: "ok", text: `Alarm stasiun ${station} diredam selama ${minutes} menit.` });
      resetForm();
      setDialogOpen(false);
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Peredaman alarm gagal" });
    } finally {
      setPin("");
      setPending(null);
    }
  }

  async function cancel(event: FormEvent, item: Suppression) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending("cancel");
    try {
      await api(`/api/v1/control/suppressions/${encodeURIComponent(item.suppression_id)}/cancel`, {
        method: "POST",
        body: JSON.stringify({ pin: cancelPin, reason: cancelReason }),
      });
      setFeedback({ kind: "ok", text: `Peredaman stasiun ${item.serid} diakhiri.` });
      setCancelOpen("");
      setCancelReason("");
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Pengakhiran peredaman gagal" });
    } finally {
      setCancelPin("");
      setPending(null);
    }
  }

  return (
    <LayerCard className="action-card">
      <h2>Redam alarm sementara</h2>
      <p>Sembunyikan alarm stasiun untuk sementara; pengukuran tetap berjalan dan alarm kembali dipantau saat kondisi normal.</p>
      <Dialog.Root open={dialogOpen} onOpenChange={changeDialogOpen}>
        <Dialog.Trigger render={(props) => <Button {...props} variant="primary" disabled={pending !== null}>Mulai peredaman</Button>} />
        <Dialog className="radmon-dialog mobile-sheet-dialog">
          <div className="mobile-sheet-content">
            <div className="mobile-sheet-handle" aria-hidden />
            <Dialog.Title>Redam alarm sementara</Dialog.Title>
            <Dialog.Description>Peredaman berlaku 1 menit sampai 24 jam dan berakhir otomatis saat detektor kembali normal.</Dialog.Description>
            <form className="action-form dialog-form" onSubmit={start}>
              <Input label="SERID stasiun" inputMode="numeric" value={serid} onChange={(event) => setSerid(event.target.value)} disabled={pending === "start"} />
              <NativeSelect id="suppression-duration-select" testId="suppression-duration-select" label="Durasi peredaman" value={minutes} onChange={(event) => setMinutes(event.target.value)} disabled={pending === "start"} required>
                {Object.entries(DURATION_ITEMS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </NativeSelect>
              <Input label="PIC" value={pic} onChange={(event) => setPic(event.target.value)} readOnly={!canEditPic} disabled={pending === "start"} />
              <Input label="Alasan" value={reason} onChange={(event) => setReason(event.target.value)} disabled={pending === "start"} />
              <Input label="PIN" type="password" value={pin} onChange={(event) => setPin(event.target.value)} disabled={pending === "start"} />
              <div className="form-actions">
                <Button type="submit" variant="primary" disabled={pending === "start" || !serid || !minutes || !pic || !reason || !pin}>{pending === "start" ? "Memulai…" : "Mulai peredaman"}</Button>
                <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "start"}>Batal</Button>} />
              </div>
            </form>
          </div>
        </Dialog>
      </Dialog.Root>
      <div className="active-suppression-list" aria-live="polite">
        <h3>Peredaman aktif</h3>
        {suppressionsStatus === "loading" ? <p className="cell-subtle" role="status">Memuat peredaman aktif…</p> : suppressionsStatus === "error" ? <p className="cell-subtle" role="status">Daftar peredaman aktif belum tersedia.</p> : suppressions.length === 0 ? <p className="cell-subtle">Tidak ada peredaman aktif.</p> : suppressions.map((item) => (
          <div className="active-suppression-row" key={item.suppression_id}>
            <div>
              <strong>SERID {item.serid}</strong>
              <span>Sampai {new Date(item.expires_at).toLocaleString("id-ID")}</span>
              <span>{item.pic}: {item.reason}</span>
              <span>Status sumber: {item.source_silence_state ?? "BELUM DIKETAHUI"}</span>
            </div>
            <Dialog.Root open={cancelOpen === item.suppression_id} onOpenChange={(open) => {
              if (pending === "cancel") return;
              setCancelOpen(open ? item.suppression_id : "");
              if (!open) { setCancelReason(""); setCancelPin(""); }
            }}>
              <Dialog.Trigger render={(props) => <Button {...props} variant="secondary" disabled={pending !== null}>Akhiri peredaman</Button>} />
              <Dialog className="radmon-dialog mobile-sheet-dialog">
                <div className="mobile-sheet-content">
                  <div className="mobile-sheet-handle" aria-hidden />
                  <Dialog.Title>Akhiri peredaman SERID {item.serid}</Dialog.Title>
                  <Dialog.Description>Pengakhiran dicatat dan tidak menghapus pengukuran atau riwayat alarm.</Dialog.Description>
                  <form className="action-form dialog-form" onSubmit={(event) => void cancel(event, item)}>
                    <Input label="Alasan pengakhiran" value={cancelReason} onChange={(event) => setCancelReason(event.target.value)} disabled={pending === "cancel"} />
                    <Input label="PIN" type="password" value={cancelPin} onChange={(event) => setCancelPin(event.target.value)} disabled={pending === "cancel"} />
                    <div className="form-actions">
                      <Button type="submit" variant="primary" disabled={pending === "cancel" || !cancelReason || !cancelPin}>{pending === "cancel" ? "Mengakhiri…" : "Akhiri peredaman"}</Button>
                      <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary" disabled={pending === "cancel"}>Batal</Button>} />
                    </div>
                  </form>
                </div>
              </Dialog>
            </Dialog.Root>
          </div>
        ))}
      </div>
      <ActionFeedback state={feedback} />
    </LayerCard>
  );
}

export function AlarmOperations(props: AlarmOperationsProps) {
  const sourceStatus = props.sourceStatus ?? "ready";
  const suppressionsStatus = props.suppressionsStatus ?? "ready";
  return (
    <div className="action-grid">
      <SourceResponsePanel {...props} sourceStatus={sourceStatus} />
      <SuppressionPanel suppressions={props.suppressions} onChanged={props.onChanged} suppressionsStatus={suppressionsStatus} />
    </div>
  );
}
