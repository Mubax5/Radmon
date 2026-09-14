import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Dialog, LayerCard, Table } from "@cloudflare/kumo";
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

  const createUserAction = (
    <Dialog.Root>
      <Dialog.Trigger render={(props) => <Button {...props} variant="primary">Buat pengguna</Button>} />
      <Dialog className="radmon-dialog mobile-sheet-dialog">
        <div className="mobile-sheet-content">
          <div className="mobile-sheet-handle" aria-hidden />
          <Dialog.Title>Buat pengguna</Dialog.Title>
          <Dialog.Description>
            Buat identitas RadMon terautentikasi. Viewer hanya dapat membaca; izin Operator dan Administrator tetap ditegakkan oleh backend.
          </Dialog.Description>
          <div className="dialog-form">
            <CreateUserForm onCreated={() => void load()} />
            <div className="form-actions dialog-close-row">
              <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary">Tutup</Button>} />
            </div>
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );

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
        </>
      )}
    </div>
  );
}
