import { useEffect, useMemo, useState } from "react";
import {
  ArchiveIcon,
  BellIcon,
  ChartLineUpIcon,
  GaugeIcon,
  GearIcon,
  HouseIcon,
  MapPinIcon,
  SignOutIcon,
  UsersIcon,
} from "@phosphor-icons/react";
import { Badge, Button, Input, LayerCard, Sidebar, Table } from "@cloudflare/kumo";
import { api, currentUser, login, logout, type Role, type SessionUser, type Station } from "./api";
import { AlarmOperations, CreateUserPanel } from "./Actions";

const ROLE_RANK: Record<Role, number> = { Viewer: 1, Operator: 2, Administrator: 3 };

type PolicyEvent = Record<string, unknown> & {
  event_id: string;
  serid: number;
  status: string;
  kind: string;
  measured_value?: number | null;
  threshold?: number | null;
  surfaced_at?: string;
};

type NavItem = {
  id: string;
  label: string;
  minimum: Role;
  icon: typeof HouseIcon;
};

const NAV: NavItem[] = [
  { id: "overview", label: "Overview", minimum: "Viewer", icon: HouseIcon },
  { id: "stations", label: "Stations", minimum: "Viewer", icon: MapPinIcon },
  { id: "history", label: "History", minimum: "Viewer", icon: ChartLineUpIcon },
  { id: "archives", label: "Archives", minimum: "Viewer", icon: ArchiveIcon },
  { id: "alarms", label: "Alarms", minimum: "Operator", icon: BellIcon },
  { id: "users", label: "Users", minimum: "Administrator", icon: UsersIcon },
  { id: "system", label: "System", minimum: "Administrator", icon: GearIcon },
];

function routeFromLocation() {
  const part = window.location.pathname.replace(/^\/app\/?/, "").split("/")[0];
  return part && part !== "login" ? part : "overview";
}

function navigate(route: string) {
  const path = route === "overview" ? "/app" : `/app/${route}`;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function PageHeading({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

function Login({ onLogin }: { onLogin: (user: SessionUser) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const user = await login(username, password);
      onLogin(user);
      window.history.replaceState({}, "", "/app");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-shell">
      <LayerCard className="login-card">
        <div className="brand-mark">R</div>
        <h1>Sign in to RadMon</h1>
        <p>Radiation monitoring control plane for authorized BRIN users.</p>
        <form onSubmit={submit} className="login-form">
          <Input label="Username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
          <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          {error ? <div className="form-error">{error}</div> : null}
          <Button type="submit" variant="primary" disabled={busy || !username || !password}>
            {busy ? "Signing in…" : "Sign in"}
          </Button>
        </form>
      </LayerCard>
    </main>
  );
}

function OverviewPage() {
  const [data, setData] = useState<{ counts: Record<string, number>; stations: Station[] } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api<{ counts: Record<string, number>; stations: Station[] }>("/api/v1/web/overview").then(setData).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorCard message={error} />;
  if (!data) return <LoadingCard />;
  const cards = [
    ["Normal", data.counts.normal || 0, "success"],
    ["Warning", data.counts.warning || 0, "warning"],
    ["Alarm", data.counts.alarm || 0, "error"],
    ["Offline", data.counts.offline || 0, "secondary"],
  ] as const;
  return (
    <>
      <PageHeading title="Radiation monitoring" description="Current health and dose state across all connected stations." />
      <div className="metric-grid">
        {cards.map(([label, value, variant]) => (
          <LayerCard className="metric-card" key={label}>
            <div className="metric-label">{label}</div>
            <div className="metric-value">{value}</div>
            <Badge variant={variant}>{label}</Badge>
          </LayerCard>
        ))}
      </div>
      <StationTable stations={data.stations} />
    </>
  );
}

function statusVariant(status?: string): "success" | "warning" | "error" | "secondary" {
  if (status === "normal") return "success";
  if (status === "warning") return "warning";
  if (status === "alarm") return "error";
  return "secondary";
}

function StationTable({ stations }: { stations: Station[] }) {
  return (
    <LayerCard className="table-card">
      <Table>
        <Table.Header>
          <Table.Row>
            <Table.Head>Station</Table.Head>
            <Table.Head>Location</Table.Head>
            <Table.Head>Status</Table.Head>
            <Table.Head>Dose rate</Table.Head>
            <Table.Head>Updated</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {stations.map((station) => (
            <Table.Row key={station.serid}>
              <Table.Cell><strong>{station.name}</strong><div className="cell-subtle">SERID {station.serid}</div></Table.Cell>
              <Table.Cell>{station.location}</Table.Cell>
              <Table.Cell><Badge variant={statusVariant(station.status)}>{station.status || "configured"}</Badge></Table.Cell>
              <Table.Cell>{station.doserate == null ? "—" : `${station.doserate.toFixed(3)} ${station.unit}`}</Table.Cell>
              <Table.Cell>{station.dtom ? new Date(station.dtom).toLocaleString() : "—"}</Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </LayerCard>
  );
}

function StationsPage() {
  const [stations, setStations] = useState<Station[] | null>(null);
  useEffect(() => { api<Station[]>("/api/v1/web/stations").then(setStations); }, []);
  return <><PageHeading title="Stations" description="Configured radiation monitoring stations." />{stations ? <StationTable stations={stations} /> : <LoadingCard />}</>;
}

function HistoryPage() {
  const [stations, setStations] = useState<Station[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [rows, setRows] = useState<Array<Record<string, unknown>>>([]);
  useEffect(() => { api<Station[]>("/api/v1/web/stations").then((items) => { setStations(items); setSelected(items[0]?.serid ?? null); }); }, []);
  useEffect(() => { if (selected) api<Array<Record<string, unknown>>>(`/api/v1/web/stations/${selected}/history?limit=240`).then(setRows); }, [selected]);
  return (
    <>
      <PageHeading title="History" description="Recent measurements retained by the central database." />
      <LayerCard className="filter-card">
        <label>Station</label>
        <select value={selected ?? ""} onChange={(e) => setSelected(Number(e.target.value))}>
          {stations.map((s) => <option key={s.serid} value={s.serid}>{s.name} — {s.location}</option>)}
        </select>
      </LayerCard>
      <LayerCard className="table-card"><Table><Table.Header><Table.Row><Table.Head>Time</Table.Head><Table.Head>Dose rate</Table.Head><Table.Head>Dose</Table.Head><Table.Head>Status</Table.Head></Table.Row></Table.Header><Table.Body>{rows.map((row, index) => <Table.Row key={`${row.dtom}-${index}`}><Table.Cell>{String(row.dtom ?? "")}</Table.Cell><Table.Cell>{String(row.doserate ?? "")}</Table.Cell><Table.Cell>{String(row.dose ?? "")}</Table.Cell><Table.Cell>{String(row.stat ?? "")}</Table.Cell></Table.Row>)}</Table.Body></Table></LayerCard>
    </>
  );
}

function ArchivesPage() {
  const [items, setItems] = useState<Array<Record<string, unknown>> | null>(null);
  useEffect(() => { api<Array<Record<string, unknown>>>("/api/v1/control/archives").then(setItems); }, []);
  return <><PageHeading title="Archives" description="Verified quarterly archive bundles and retention state." />{items ? <JsonTable rows={items} empty="No archive bundles yet." /> : <LoadingCard />}</>;
}

function AlarmsPage() {
  const [items, setItems] = useState<PolicyEvent[] | null>(null);
  const [error, setError] = useState("");
  const load = () => api<PolicyEvent[]>("/api/v1/control/alarm-events").then((rows) => { setItems(rows); setError(""); }).catch((e) => setError(e.message));
  useEffect(() => { void load(); }, []);
  return (
    <>
      <PageHeading title="Alarms" description="Central alarm-policy events. Response and suppression are protected by operator role and PIN policy." action={<Button variant="secondary" onClick={() => void load()}>Refresh</Button>} />
      {error ? <ErrorCard message={error} /> : null}
      {items ? <><AlarmOperations events={items} onChanged={() => void load()} /><JsonTable rows={items} empty="No alarm events." /></> : <LoadingCard />}
    </>
  );
}

function UsersPage() {
  const [items, setItems] = useState<Array<Record<string, unknown>> | null>(null);
  const [error, setError] = useState("");
  const load = () => api<Array<Record<string, unknown>>>("/api/v1/control/users").then((rows) => { setItems(rows); setError(""); }).catch((e) => setError(e.message));
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
  useEffect(() => { api<Record<string, unknown>>("/api/v1/web/system").then(setData); }, []);
  return (
    <>
      <PageHeading title="System" description="Central runtime diagnostics and monitoring administration." action={<Button variant="secondary" onClick={() => window.open("http://localhost:3300", "_blank", "noopener,noreferrer")}>Open Grafana admin</Button>} />
      {data ? <LayerCard className="system-card"><pre>{JSON.stringify(data, null, 2)}</pre></LayerCard> : <LoadingCard />}
    </>
  );
}

function JsonTable({ rows, empty }: { rows: Array<Record<string, unknown>>; empty: string }) {
  if (!rows.length) return <LayerCard className="empty-card">{empty}</LayerCard>;
  const keys = Object.keys(rows[0]).slice(0, 6);
  return <LayerCard className="table-card"><Table><Table.Header><Table.Row>{keys.map((key) => <Table.Head key={key}>{key.replaceAll("_", " ")}</Table.Head>)}</Table.Row></Table.Header><Table.Body>{rows.map((row, index) => <Table.Row key={index}>{keys.map((key) => <Table.Cell key={key}>{typeof row[key] === "object" ? JSON.stringify(row[key]) : String(row[key] ?? "—")}</Table.Cell>)}</Table.Row>)}</Table.Body></Table></LayerCard>;
}

function LoadingCard() { return <LayerCard className="empty-card">Loading…</LayerCard>; }
function ErrorCard({ message }: { message: string }) { return <LayerCard className="error-card">{message}</LayerCard>; }

function Shell({ user, onLogout }: { user: SessionUser; onLogout: () => void }) {
  const [route, setRoute] = useState(routeFromLocation());
  useEffect(() => {
    const handler = () => setRoute(routeFromLocation());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  const allowed = useMemo(() => NAV.filter((item) => ROLE_RANK[user.role] >= ROLE_RANK[item.minimum]), [user.role]);
  const validRoute = allowed.some((item) => item.id === route) ? route : "overview";
  return (
    <Sidebar.Provider defaultOpen>
      <div className="app-shell">
        <Sidebar>
          <Sidebar.Header><div className="sidebar-brand"><span className="brand-mark small">R</span><div><strong>RadMon</strong><span>BRIN</span></div></div></Sidebar.Header>
          <Sidebar.Content>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Control plane</Sidebar.GroupLabel>
              <Sidebar.Menu>
                {allowed.map((item) => <Sidebar.MenuButton key={item.id} icon={item.icon} active={validRoute === item.id} onClick={() => navigate(item.id)}>{item.label}</Sidebar.MenuButton>)}
              </Sidebar.Menu>
            </Sidebar.Group>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Monitoring</Sidebar.GroupLabel>
              <Sidebar.Menu><Sidebar.MenuButton icon={GaugeIcon} onClick={() => window.open("/", "_blank", "noopener,noreferrer")}>Full monitoring</Sidebar.MenuButton></Sidebar.Menu>
            </Sidebar.Group>
          </Sidebar.Content>
          <Sidebar.Footer><div className="account-card"><div><strong>{user.display_name}</strong><span>{user.role}</span></div><Button variant="secondary" shape="square" aria-label="Sign out" onClick={onLogout}><SignOutIcon /></Button></div><Sidebar.Trigger /></Sidebar.Footer>
        </Sidebar>
        <main className="content-shell">
          {validRoute === "overview" && <OverviewPage />}
          {validRoute === "stations" && <StationsPage />}
          {validRoute === "history" && <HistoryPage />}
          {validRoute === "archives" && <ArchivesPage />}
          {validRoute === "alarms" && <AlarmsPage />}
          {validRoute === "users" && <UsersPage />}
          {validRoute === "system" && <SystemPage />}
        </main>
      </div>
    </Sidebar.Provider>
  );
}

export default function App() {
  const [user, setUser] = useState<SessionUser | null | undefined>(undefined);
  useEffect(() => { currentUser().then((identity) => { setUser(identity); if (!identity && window.location.pathname !== "/app/login") window.history.replaceState({}, "", "/app/login"); }); }, []);
  if (user === undefined) return <main className="login-shell"><LayerCard className="login-card">Loading RadMon…</LayerCard></main>;
  if (!user) return <Login onLogin={setUser} />;
  return <Shell user={user} onLogout={() => { void logout().finally(() => { setUser(null); window.history.replaceState({}, "", "/app/login"); }); }} />;
}
