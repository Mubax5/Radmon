import { LayerCard } from "@cloudflare/kumo";
import { AuthProvider, LoginPage, useSession } from "./auth";
import { AppLayout, useAppRoute } from "./layout";
import { AlarmsPage } from "./pages/AlarmsPage";
import { ArchivesPage } from "./pages/ArchivesPage";
import { HistoryPage } from "./pages/HistoryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { StationsPage } from "./pages/StationsPage";
import { SystemPage } from "./pages/SystemPage";
import { UsersPage } from "./pages/UsersPage";

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
