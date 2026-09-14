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
  if (!users.length) return <LayerCard className="empty-card">No users.</LayerCard>;
  return (
    <div className="mobile-card-list">
      {users.map((user) => (
        <LayerCard className="user-card" key={user.username}>
          <div className="user-card-header">
            <div>
              <h3>{user.display_name}</h3>
              <div className="cell-subtle">@{user.username}</div>
            </div>
            <Badge variant={user.enabled ? "success" : "secondary"}>{user.enabled ? "Enabled" : "Disabled"}</Badge>
          </div>
          <div className="card-meta">
            <span>Role: {user.role}</span>
            <span>Updated: {formatTimestamp(user.updated_at ?? user.created_at)}</span>
          </div>
        </LayerCard>
      ))}
    </div>
  );
}

function UserTable({ users }: { users: UserRecord[] }) {
  if (!users.length) return <LayerCard className="empty-card">No users.</LayerCard>;
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>User</Table.Head>
            <Table.Head>Display name</Table.Head>
            <Table.Head>Role</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Updated</Table.Head>
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
                  {user.enabled ? "Enabled" : "Disabled"}
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
    .catch((e) => setError(e instanceof Error ? e.message : "Unable to load users"));

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
      <Dialog.Trigger render={(props) => <Button {...props} variant="primary">Create user</Button>} />
      <Dialog>
        <Dialog.Title>Create user</Dialog.Title>
        <Dialog.Description>
          Create an authenticated RadMon identity. Viewer is read-only; Operator and Administrator permissions remain enforced by the backend.
        </Dialog.Description>
        <div className="dialog-form">
          <CreateUserForm onCreated={() => void load()} />
          <div className="form-actions dialog-close-row">
            <Dialog.Close render={(props) => <Button {...props} type="button" variant="secondary">Close</Button>} />
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );

  return (
    <div className="page-stack">
      <PageHeading
        title="Users"
        description="Authenticated RadMon identities, roles, and account state. Secrets remain write-only."
        action={createUserAction}
      />
      {error ? <ErrorCard message={error} /> : null}
      {!items ? <LoadingCard /> : (
        <>
          <div className="metric-grid user-summary">
            <MetricCard label="Users" value={summary.total} badge={<span className="cell-subtle">Authenticated identities</span>} />
            <MetricCard label="Enabled" value={summary.enabled} badge={<span className="cell-subtle">Can sign in</span>} />
            <MetricCard label="Operators" value={summary.operators} badge={<span className="cell-subtle">Operational control</span>} />
            <MetricCard label="Administrators" value={summary.administrators} badge={<span className="cell-subtle">Administrative access</span>} />
          </div>

          <PageSection title="Identity directory" description="Role and enabled state are shown without password or PIN material.">
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
