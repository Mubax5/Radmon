import { useEffect, useState } from "react";
import { Button, LayerCard } from "@cloudflare/kumo";
import { api } from "./api";
import { AlarmOperations, CreateUserPanel } from "./Actions";
import { AuthProvider, LoginPage, useSession } from "./auth";
import { AppLayout, useAppRoute } from "./layout";
import { ArchivesPage } from "./pages/ArchivesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { StationsPage } from "./pages/StationsPage";
import { ErrorCard, JsonTable, LoadingCard, PageHeading } from "./ui";

type PolicyEvent = Record<string, unknown> & {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
};

function AlarmsPage() {
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<PolicyEvent[]>("/api/v1/control/alarm-events")
    .then((rows) => { setItems(rows); setError(""); })
    .catch((e) => setError(e.message));

  useEffect(() => { void load(); }, []);

  return (
    <>
      <PageHeading
        title="Alarms"
        description="Central alarm-policy events. Response and suppression are protected by operator role and PIN policy."
        action={<Button variant="secondary" onClick={() => void load()}>Refresh</Button>}
      />
      {error ? <ErrorCard message={error} /> : null}
      {items ? (
        <>
          <AlarmOperations events={items} onChanged={() => void load()} />
          <JsonTable rows={items} empty="No alarm events." />
        </>
      ) : <LoadingCard />}
    </>
  );
}

function UsersPage() {
  const [items, setItems] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Array<Record<string, unknown>>>("/api/v1/control/users")
    .then((rows) => { setItems(rows); setError(""); })
    .catch((e) => setError(e.message));

  useEffect(() => { void load(); }, []);

  return (
    <>
      <PageHeading title="Users" description="Authenticated RadMon identities and assigned roles." />
      <CreateUserPanel onCreated={() => void load()} />
      {error ? <ErrorCard message={error} /> : null}
      {items ? <JsonTable rows={items} empty="No users." /> : <LoadingCard />}
    </>
  );
}

function SystemPage() {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<Record<string, unknown>>("/api/v1/web/system")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeading
        title="System"
        description="Central runtime diagnostics and monitoring administration."
        action={
          <Button
            variant="secondary"
            onClick={() => window.open("http://localhost:3300", "_blank", "noopener,noreferrer")}
          >
            Open Grafana admin
          </Button>
        }
      />
      {error ? <ErrorCard message={error} /> : data ? (
        <LayerCard className="system-card"><pre>{JSON.stringify(data, null, 2)}</pre></LayerCard>
      ) : <LoadingCard />}
    </>
  );
}

function RadMonApplication() {
  const { user, loading, signOut } = useSession();
  const route = useAppRoute(user);

  if (loading) {
    return <main className="login-shell"><LayerCard className="login-card">Loading RadMon…</LayerCard></main>;
  }
  if (!user) return <LoginPage />;

  return (
    <AppLayout user={user} route={route} onSignOut={signOut}>
      {route === "overview" && <OverviewPage />}
      {route === "stations" && <StationsPage />}
      {route === "history" && <HistoryPage />}
      {route === "archives" && <ArchivesPage />}
      {route === "alarms" && <AlarmsPage />}
      {route === "users" && <UsersPage />}
      {route === "system" && <SystemPage />}
    </AppLayout>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <RadMonApplication />
    </AuthProvider>
  );
}
