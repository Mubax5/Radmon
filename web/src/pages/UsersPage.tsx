import { useEffect, useState } from "react";
import { Badge, LayerCard, Table } from "@cloudflare/kumo";
import { api, type Role } from "../api";
import { CreateUserPanel } from "../Actions";
import { ErrorCard, LoadingCard, PageHeading } from "../ui";

type UserRecord = {
  username: string;
  display_name: string;
  role: Role;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
};

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

  return (
    <>
      <PageHeading title="Users" description="Authenticated RadMon identities and assigned roles." />
      <CreateUserPanel onCreated={() => void load()} />
      {error ? <ErrorCard message={error} /> : null}
      {!items ? <LoadingCard /> : items.length === 0 ? (
        <LayerCard className="empty-card">No users.</LayerCard>
      ) : (
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
              {items.map((user) => (
                <Table.Row key={user.username}>
                  <Table.Cell><strong>{user.username}</strong></Table.Cell>
                  <Table.Cell>{user.display_name}</Table.Cell>
                  <Table.Cell>{user.role}</Table.Cell>
                  <Table.Cell>
                    <Badge variant={user.enabled ? "success" : "secondary"}>
                      {user.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </Table.Cell>
                  <Table.Cell>{user.updated_at ? new Date(user.updated_at).toLocaleString() : "—"}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        </LayerCard>
      )}
    </>
  );
}
