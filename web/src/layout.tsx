import { useEffect, useMemo, useState, type ReactNode } from "react";
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
import { Button, Sidebar } from "@cloudflare/kumo";
import type { Role, SessionUser } from "./api";

export type AppRoute = "overview" | "stations" | "history" | "archives" | "alarms" | "users" | "system";

const ROLE_RANK: Record<Role, number> = { Viewer: 1, Operator: 2, Administrator: 3 };

const NAV = [
  { id: "overview", label: "Overview", minimum: "Viewer", icon: HouseIcon },
  { id: "stations", label: "Stations", minimum: "Viewer", icon: MapPinIcon },
  { id: "history", label: "History", minimum: "Viewer", icon: ChartLineUpIcon },
  { id: "archives", label: "Archives", minimum: "Viewer", icon: ArchiveIcon },
  { id: "alarms", label: "Alarms", minimum: "Operator", icon: BellIcon },
  { id: "users", label: "Users", minimum: "Administrator", icon: UsersIcon },
  { id: "system", label: "System", minimum: "Administrator", icon: GearIcon },
] as const;

function routeFromLocation(): AppRoute {
  const part = window.location.pathname.replace(/^\/app\/?/, "").split("/")[0];
  const route = (part && part !== "login" ? part : "overview") as AppRoute;
  return NAV.some((item) => item.id === route) ? route : "overview";
}

function navigate(route: AppRoute) {
  const path = route === "overview" ? "/app" : `/app/${route}`;
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useAppRoute(user: SessionUser | null): AppRoute {
  const [route, setRoute] = useState<AppRoute>(routeFromLocation());
  useEffect(() => {
    const handler = () => setRoute(routeFromLocation());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  if (!user) return "overview";
  const allowed = NAV.some(
    (item) => item.id === route && ROLE_RANK[user.role] >= ROLE_RANK[item.minimum],
  );
  return allowed ? route : "overview";
}

export function AppLayout({
  user,
  route,
  onSignOut,
  children,
}: {
  user: SessionUser;
  route: AppRoute;
  onSignOut: () => Promise<void>;
  children: ReactNode;
}) {
  const allowed = useMemo(
    () => NAV.filter((item) => ROLE_RANK[user.role] >= ROLE_RANK[item.minimum]),
    [user.role],
  );

  return (
    <Sidebar.Provider defaultOpen>
      <div className="app-shell">
        <Sidebar>
          <Sidebar.Header>
            <div className="sidebar-brand">
              <span className="brand-mark small">R</span>
              <div><strong>RadMon</strong><span>BRIN</span></div>
            </div>
          </Sidebar.Header>
          <Sidebar.Content>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Control plane</Sidebar.GroupLabel>
              <Sidebar.Menu>
                {allowed.map((item) => (
                  <Sidebar.MenuButton
                    key={item.id}
                    icon={item.icon}
                    active={route === item.id}
                    onClick={() => navigate(item.id)}
                  >
                    {item.label}
                  </Sidebar.MenuButton>
                ))}
              </Sidebar.Menu>
            </Sidebar.Group>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Monitoring</Sidebar.GroupLabel>
              <Sidebar.Menu>
                <Sidebar.MenuButton
                  icon={GaugeIcon}
                  onClick={() => window.open("/", "_blank", "noopener,noreferrer")}
                >
                  Full monitoring
                </Sidebar.MenuButton>
              </Sidebar.Menu>
            </Sidebar.Group>
          </Sidebar.Content>
          <Sidebar.Footer>
            <div className="account-card">
              <div><strong>{user.display_name}</strong><span>{user.role}</span></div>
              <Button
                variant="secondary"
                shape="square"
                aria-label="Sign out"
                onClick={() => void onSignOut()}
              >
                <SignOutIcon />
              </Button>
            </div>
            <Sidebar.Trigger />
          </Sidebar.Footer>
        </Sidebar>
        <main className="content-shell">{children}</main>
      </div>
    </Sidebar.Provider>
  );
}
