import { useState, type FormEvent } from "react";
import { Button } from "@cloudflare/kumo";
import { api, type Role } from "../api";
import { ActionFeedback, type FeedbackState } from "./ActionFeedback";
import { NativeSelect } from "./NativeSelect";

type CreateUserFormProps = {
  onCreated: () => void;
  onDone?: () => void;
  administratorExists?: boolean;
};

export function CreateUserForm({ onCreated, onDone, administratorExists = false }: CreateUserFormProps) {
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("Viewer");
  const [password, setPassword] = useState("");
  const [userPin, setUserPin] = useState("");
  const [adminPin, setAdminPin] = useState("");
  const [pending, setPending] = useState(false);
  const [feedback, setFeedback] = useState<FeedbackState | null>(null);

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

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    setFeedback(null);
    setPending(true);
    try {
      await api("/api/v1/control/users", {
        method: "POST",
        body: JSON.stringify({ pin: adminPin, username, display_name: displayName, role, password, user_pin: userPin }),
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
      <label className="native-input-field"><span>Username</span><input value={username} onChange={(event) => setUsername(event.target.value)} disabled={pending} required autoComplete="username" /></label>
      <label className="native-input-field"><span>Nama tampilan</span><input value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={pending} required autoComplete="name" /></label>
      <NativeSelect id="user-role-select" name="role" testId="user-role-select" label="Peran" value={role} onChange={(event) => setRole(event.target.value as Role)} disabled={pending} required>
        <option value="Viewer">Viewer</option>
        <option value="Operator">Operator</option>
        <option value="Administrator" disabled={administratorExists}>Administrator</option>
      </NativeSelect>
      {administratorExists ? <p className="cell-subtle" role="status">Administrator aktif sudah ada. Nonaktifkan atau ubah peran administrator tersebut sebelum membuat administrator lain.</p> : null}
      <label className="native-input-field"><span>Password awal</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} required minLength={8} autoComplete="new-password" /></label>
      <label className="native-input-field"><span>PIN pengguna</span><input type="password" inputMode="numeric" value={userPin} onChange={(event) => setUserPin(event.target.value)} disabled={pending} required minLength={4} maxLength={8} autoComplete="new-password" /></label>
      <label className="native-input-field"><span>PIN Administrator</span><input type="password" inputMode="numeric" value={adminPin} onChange={(event) => setAdminPin(event.target.value)} disabled={pending} required minLength={4} maxLength={8} autoComplete="current-password" /></label>
      <div className="form-actions">
        <Button type="submit" variant="primary" disabled={pending || !username || !displayName || !password || !userPin || !adminPin || (administratorExists && role === "Administrator")}>
          {pending ? "Membuat…" : "Buat pengguna"}
        </Button>
        <Button type="button" variant="secondary" onClick={reset} disabled={pending}>Bersihkan</Button>
      </div>
      <ActionFeedback state={feedback} />
    </form>
  );
}
