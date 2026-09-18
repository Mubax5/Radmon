import { lazy, Suspense } from "react";
import { LayerCard } from "@cloudflare/kumo";
import { AuthProvider, LoginPage, useSession } from "./auth";
import { AppLayout, useAppRoute } from "./layout";

const AlarmsPage = lazy(() => import("./pages/AlarmsPage").then(({ AlarmsPage }) => ({ default: AlarmsPage })));
const ArchivesPage = lazy(() => import("./pages/ArchivesPage").then(({ ArchivesPage }) => ({ default: ArchivesPage })));
const HistoryPage = lazy(() => import("./pages/HistoryPage").then(({ HistoryPage }) => ({ default: HistoryPage })));
const OverviewPage = lazy(() => import("./pages/OverviewPage").then(({ OverviewPage }) => ({ default: OverviewPage })));
const StationsPage = lazy(() => import("./pages/StationsPage").then(({ StationsPage }) => ({ default: StationsPage })));
const StationDetailPage = lazy(() => import("./pages/StationDetailPage").then(({ StationDetailPage }) => ({ default: StationDetailPage })));
const ReportsPage = lazy(() => import("./pages/ReportsPage").then(({ ReportsPage }) => ({ default: ReportsPage })));
const SystemPage = lazy(() => import("./pages/SystemPage").then(({ SystemPage }) => ({ default: SystemPage })));
const UsersPage = lazy(() => import("./pages/UsersPage").then(({ UsersPage }) => ({ default: UsersPage })));

function RadMonApplication() {
  const { user, loading, signOut } = useSession();
  const route = useAppRoute(user);

  if (loading) {
    return <main className="login-shell"><LayerCard className="login-card">Memuat RadMon…</LayerCard></main>;
  }
  if (!user) return <LoginPage />;

  return (
    <AppLayout user={user} route={route} onSignOut={signOut}>
      <Suspense fallback={<LayerCard className="login-card">Memuat halaman...</LayerCard>}>
        {route === "overview" && <OverviewPage />}
        {route === "stations" && <StationsPage />}
        {route === "station" && <StationDetailPage />}
        {route === "history" && <HistoryPage />}
        {route === "archives" && <ArchivesPage />}
        {route === "reports" && <ReportsPage />}
        {route === "alarms" && <AlarmsPage />}
        {route === "users" && <UsersPage />}
        {route === "system" && <SystemPage />}
      </Suspense>
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
