import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, LayerCard, Table } from "@cloudflare/kumo";
import { api, type Role } from "../api";
import { CreateUserForm } from "../Actions";
import { ResponsiveDataView } from "../components/ResponsiveDataView";
import {
  ErrorCard,
  LoadingCard,
  MetricCard,
  PageHeading,
  PageSection,
  formatTimestamp,
} from "../ui";

type UserRecord = {
  username: string;
  display_name: string;
  role: Role;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
};

function NativeInput({ label, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return <label className="native-input-field"><span>{label}</span><input {...props} /></label>;
}

function UserCards({ users }: { users: UserRecord[] }) {
  if (!users.length) return <LayerCard className="empty-card">Tidak ada pengguna.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {users.map((user) => (
        <LayerCard className="user-card" key={user.username}>
          <div className="user-card-header">
            <div>
              <h3>{user.display_name}</h3>
              <div className="cell-subtle">@{user.username}</div>
            </div>
            <Badge variant={user.enabled ? "success" : "secondary"}>{user.enabled ? "Aktif" : "Nonaktif"}</Badge>
          </div>
          <div className="card-meta">
            <span>Peran: {user.role}</span>
            <span>Diperbarui: {formatTimestamp(user.updated_at ?? user.created_at)}</span>
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function UserTable({ users }: { users: UserRecord[] }) {
  if (!users.length) return <LayerCard className="empty-card">Tidak ada pengguna.</LayerCard>;
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Username</Table.Head>
            <Table.Head>Nama tampilan</Table.Head>
            <Table.Head>Peran</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Diperbarui</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {users.map((user) => (
            <Table.Row key={user.username}>
              <Table.Cell><strong>{user.username}</strong></Table.Cell>
              <Table.Cell>{user.display_name}</Table.Cell>
              <Table.Cell>{user.role}</Table.Cell>
              <Table.Cell>
                <Badge variant={user.enabled ? "success" : "secondary"}>
                  {user.enabled ? "Aktif" : "Nonaktif"}
                </Badge>
              </Table.Cell>
              <Table.Cell>{formatTimestamp(user.updated_at ?? user.created_at)}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

function UserManagementForm({ users, onChanged }: { users: UserRecord[]; onChanged: () => void }) {
  const [username, setUsername] = useState(users[0]?.username ?? "");
  const selected = users.find((item) => item.username === username);
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("Viewer");
  const [enabled, setEnabled] = useState(true);
  const [password, setPassword] = useState("");
  const [newPin, setNewPin] = useState("");
  const [adminPin, setAdminPin] = useState("");
  const [feedback, setFeedback] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!selected) return;
    setDisplayName(selected.display_name); setRole(selected.role); setEnabled(selected.enabled); setPassword(""); setNewPin(""); setFeedback(null);
  }, [selected?.username]);

  async function mutate(action: "update" | "enabled" | "password" | "pin" | "delete") {
    if (!username || pending) return;
    setPending(true); setFeedback(null);
    try {
      if (action === "update") await api(`/api/v1/control/users/${encodeURIComponent(username)}`, { method: "PATCH", body: JSON.stringify({ pin: adminPin, display_name: displayName, role }) });
      if (action === "enabled") await api(`/api/v1/control/users/${encodeURIComponent(username)}/enabled`, { method: "POST", body: JSON.stringify({ pin: adminPin, enabled }) });
      if (action === "password") await api(`/api/v1/control/users/${encodeURIComponent(username)}/password`, { method: "POST", body: JSON.stringify({ pin: adminPin, password }) });
      if (action === "pin") await api(`/api/v1/control/users/${encodeURIComponent(username)}/pin`, { method: "POST", body: JSON.stringify({ pin: adminPin, new_pin: newPin }) });
      if (action === "delete") await api(`/api/v1/control/users/${encodeURIComponent(username)}`, { method: "DELETE", body: JSON.stringify({ pin: adminPin }) });
      setFeedback({ kind: "ok", text: "Perubahan pengguna tersimpan." }); setAdminPin(""); setPassword(""); setNewPin(""); onChanged();
    } catch (reason) { setFeedback({ kind: "error", text: reason instanceof Error ? reason.message : "Perubahan pengguna gagal" }); } finally { setPending(false); }
  }

  if (!users.length) return null;
  return <LayerCard className="action-card"><h2>Kelola pengguna</h2><p>Setiap perubahan administratif memerlukan PIN administrator dan akan mencabut sesi serta otorisasi sensitif pengguna target.</p>
    <form className="action-form" onSubmit={(event) => { event.preventDefault(); void mutate("update"); }}>
      <label className="native-select-field"><span>Pengguna</span><select className="native-select" value={username} onChange={(event) => setUsername(event.target.value)}>{users.map((user) => <option key={user.username} value={user.username}>{user.display_name} (@{user.username})</option>)}</select></label>
      <NativeInput label="Nama tampilan" value={displayName} onChange={(event) => setDisplayName(event.target.value)} disabled={pending} required autoComplete="name" />
      <label className="native-select-field"><span>Role</span><select className="native-select" value={role} onChange={(event) => setRole(event.target.value as Role)} disabled={pending}><option value="Viewer">Viewer</option><option value="Operator">Operator</option><option value="Administrator">Administrator</option></select></label>
      <label className="native-select-field"><span>Status</span><select className="native-select" value={enabled ? "enabled" : "disabled"} onChange={(event) => setEnabled(event.target.value === "enabled")} disabled={pending}><option value="enabled">Aktif</option><option value="disabled">Nonaktif</option></select></label>
      <NativeInput label="Password baru" type="password" value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} minLength={8} autoComplete="new-password" />
      <NativeInput label="PIN pengguna baru" type="password" inputMode="numeric" value={newPin} onChange={(event) => setNewPin(event.target.value)} disabled={pending} minLength={4} maxLength={8} autoComplete="new-password" />
      <NativeInput label="PIN Administrator saat ini" type="password" inputMode="numeric" value={adminPin} onChange={(event) => setAdminPin(event.target.value)} disabled={pending} required minLength={4} maxLength={8} autoComplete="current-password" />
      <div className="form-actions"><Button type="submit" variant="primary" disabled={pending || !adminPin}>Simpan profil/role</Button><Button type="button" variant="secondary" disabled={pending || !adminPin} onClick={() => void mutate("enabled")}>Simpan status</Button><Button type="button" variant="secondary" disabled={pending || !adminPin || !password} onClick={() => void mutate("password")}>Reset password</Button><Button type="button" variant="secondary" disabled={pending || !adminPin || !newPin} onClick={() => void mutate("pin")}>Reset PIN</Button><Button type="button" variant="secondary" disabled={pending || !adminPin} onClick={() => void mutate("delete")}>Nonaktifkan pengguna</Button></div>
      {feedback ? <div className={feedback.kind === "ok" ? "form-success" : "form-error"} role={feedback.kind === "ok" ? "status" : "alert"}>{feedback.text}</div> : null}
    </form>
  </LayerCard>;
}

function CreateUserDialog({ onCreated }: { onCreated: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  return <>
    <Button type="button" variant="primary" onClick={() => dialog.current?.showModal()}>Buat pengguna</Button>
    <dialog ref={dialog} className="native-user-dialog" aria-labelledby="user-create-title" data-testid="user-create-dialog">
      <div className="native-user-dialog-content">
        <h2 id="user-create-title">Buat pengguna</h2>
        <p>Buat identitas RadMon terautentikasi. Viewer hanya dapat membaca; izin Operator dan Administrator tetap ditegakkan oleh backend.</p>
        <CreateUserForm onCreated={onCreated} onDone={() => dialog.current?.close()} />
        <form method="dialog" className="form-actions dialog-close-row"><button type="submit" className="native-dialog-close">Tutup</button></form>
      </div>
    </dialog>
  </>;
}

export function UsersPage() {
  const [items, setItems] = useState<UserRecord[] | null>(null);
  const [error, setError] = useState("");

  const load = () => api<UserRecord[]>("/api/v1/control/users")
    .then((rows) => {
      setItems(rows);
      setError("");
    })
    .catch((e) => setError(e instanceof Error ? e.message : "Tidak dapat memuat pengguna"));

  useEffect(() => { void load(); }, []);

  const summary = useMemo(() => {
    const users = items ?? [];
    return {
      total: users.length,
      enabled: users.filter((user) => user.enabled).length,
      operators: users.filter((user) => user.role === "Operator").length,
      administrators: users.filter((user) => user.role === "Administrator").length,
    };
  }, [items]);

  const createUserAction = <CreateUserDialog onCreated={() => void load()} />;

  return (
    <div className="page-stack">
      <PageHeading
        title="Pengguna"
        description="Identitas RadMon terautentikasi, role, dan status akun. Password serta PIN tetap write-only."
        action={createUserAction}
      />
      {error ? <ErrorCard message={error} /> : null}
      {!items ? <LoadingCard /> : (
        <>
          <div className="metric-grid user-summary">
            <MetricCard label="Pengguna" value={summary.total} badge={<span className="cell-subtle">Identitas terautentikasi</span>} />
            <MetricCard label="Aktif" value={summary.enabled} badge={<span className="cell-subtle">Dapat masuk</span>} />
            <MetricCard label="Operator" value={summary.operators} badge={<span className="cell-subtle">Kontrol operasional</span>} />
            <MetricCard label="Administrator" value={summary.administrators} badge={<span className="cell-subtle">Akses administrasi</span>} />
          </div>

          <PageSection title="Direktori pengguna" description="Role dan status akun ditampilkan tanpa material password atau PIN.">
            <ResponsiveDataView
              desktop={<UserTable users={items} />}
              mobile={<UserCards users={items} />}
            />
          </PageSection>
          <PageSection title="Administrasi pengguna" description="Akun administrator aktif terakhir dan akun yang sedang dipakai dilindungi dari lockout.">
            <UserManagementForm users={items} onChanged={() => void load()} />
          </PageSection>
        </>
      )}
    </div>
  );
}
