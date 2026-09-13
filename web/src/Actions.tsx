import { useMemo, useState } from "react";
import { Button, Input, LayerCard } from "@cloudflare/kumo";
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
  const [eventId, setEventId] = useState("");
  const [action, setAction] = useState("Confirm");
  const [pic, setPic] = useState("");
  const [reason, setReason] = useState("");
  const [pin, setPin] = useState("");
  const [serid, setSerid] = useState("");
  const [minutes, setMinutes] = useState("15");
  const [suppressPic, setSuppressPic] = useState("");
  const [suppressReason, setSuppressReason] = useState("");
  const [suppressPin, setSuppressPin] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  function resetResponse() {
    setEventId("");
    setAction("Confirm");
    setPic("");
    setReason("");
    setPin("");
    setFeedback(null);
  }

  function resetSuppression() {
    setSerid("");
    setMinutes("15");
    setSuppressPic("");
    setSuppressReason("");
    setSuppressPin("");
    setFeedback(null);
  }

  async function respond(event: React.FormEvent) {
    event.preventDefault();
    setFeedback(null);
    try {
      if (!eventId) throw new Error("Select an active alarm event");
      await api(`/api/v1/control/alarm-events/${encodeURIComponent(eventId)}/response`, {
        method: "POST",
        body: JSON.stringify({ pin, action, pic, reason }),
      });
      setFeedback({ kind: "ok", text: "Alarm response saved." });
      setEventId("");
      setReason("");
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Response failed" });
    } finally {
      setPin("");
    }
  }

  async function suppress(event: React.FormEvent) {
    event.preventDefault();
    setFeedback(null);
    try {
      const station = Number(serid);
      const duration = Number(minutes) * 60;
      if (!Number.isInteger(station) || station <= 0) throw new Error("SERID must be a positive number");
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
      setFeedback({ kind: "ok", text: `Station ${station} suppressed for ${minutes} minutes.` });
      setSerid("");
      setSuppressReason("");
      onChanged();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "Suppression failed" });
    } finally {
      setSuppressPin("");
    }
  }

  return (
    <div className="action-grid">
      <LayerCard className="action-card">
        <h2>Respond to alarm</h2>
        <p>Operator PIN is verified by the RadMon backend before source write-through.</p>
        <form className="action-form" onSubmit={respond}>
          <label>Active event</label>
          <select value={eventId} onChange={(e) => setEventId(e.target.value)}>
            <option value="">Select event…</option>
            {active.map((item) => <option key={item.event_id} value={item.event_id}>SERID {item.serid} · {item.measured_value ?? "—"}</option>)}
          </select>
          <Input label="Action" value={action} onChange={(e) => setAction(e.target.value)} />
          <Input label="PIC" value={pic} onChange={(e) => setPic(e.target.value)} />
          <Input label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Input label="PIN" type="password" value={pin} onChange={(e) => setPin(e.target.value)} />
          <div className="form-actions">
            <Button type="submit" variant="primary">Submit response</Button>
            <Button type="button" variant="secondary" onClick={resetResponse}>Cancel</Button>
          </div>
        </form>
      </LayerCard>

      <LayerCard className="action-card">
        <h2>Timed suppression</h2>
        <p>Suppress alarm surfacing while dose measurements continue uninterrupted.</p>
        <form className="action-form" onSubmit={suppress}>
          <Input label="Station SERID" inputMode="numeric" value={serid} onChange={(e) => setSerid(e.target.value)} />
          <Input label="Duration (minutes)" inputMode="numeric" value={minutes} onChange={(e) => setMinutes(e.target.value)} />
          <Input label="PIC" value={suppressPic} onChange={(e) => setSuppressPic(e.target.value)} />
          <Input label="Reason" value={suppressReason} onChange={(e) => setSuppressReason(e.target.value)} />
          <Input label="PIN" type="password" value={suppressPin} onChange={(e) => setSuppressPin(e.target.value)} />
          <div className="form-actions">
            <Button type="submit" variant="primary">Start suppression</Button>
            <Button type="button" variant="secondary" onClick={resetSuppression}>Cancel</Button>
          </div>
        </form>
      </LayerCard>
      <Feedback state={feedback} />
    </div>
  );
}

export function CreateUserPanel({ onCreated }: { onCreated: () => void }) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("Viewer");
  const [password, setPassword] = useState("");
  const [userPin, setUserPin] = useState("");
  const [adminPin, setAdminPin] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  function reset() {
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
    setFeedback(null);
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
      setFeedback({ kind: "ok", text: `User ${username} created.` });
      setUsername("");
      setDisplayName("");
      setRole("Viewer");
      onCreated();
    } catch (error) {
      setFeedback({ kind: "error", text: error instanceof Error ? error.message : "User creation failed" });
    } finally {
      setPassword("");
      setUserPin("");
      setAdminPin("");
    }
  }

  return (
    <LayerCard className="action-card user-create-card">
      <h2>Create user</h2>
      <p>Viewer is an authenticated read-only role; anonymous access is never a RadMon user.</p>
      <form className="action-form" onSubmit={submit}>
        <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <Input label="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
        <label>Role</label>
        <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
          <option value="Viewer">Viewer</option>
          <option value="Operator">Operator</option>
          <option value="Administrator">Administrator</option>
        </select>
        <Input label="Initial password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <Input label="User PIN" type="password" value={userPin} onChange={(e) => setUserPin(e.target.value)} />
        <Input label="Administrator PIN" type="password" value={adminPin} onChange={(e) => setAdminPin(e.target.value)} />
        <div className="form-actions">
          <Button type="submit" variant="primary">Create user</Button>
          <Button type="button" variant="secondary" onClick={reset}>Cancel</Button>
        </div>
        <Feedback state={feedback} />
      </form>
    </LayerCard>
  );
}
