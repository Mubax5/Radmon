import type { ReactNode } from "react";
import { Button, Sidebar } from "@cloudflare/kumo";
import {
  Archive,
  Bell,
  Broadcast,
  ClockCounterClockwise,
  GearSix,
  MonitorPlay,
  SquaresFour,
  UsersThree,
} from "@phosphor-icons/react";
import type { SessionUser } from "../api";
import brinLogo from "../assets/brin-logo.png";
import { allowedRoutes, navigate, type AppRoute } from "../navigation";

function NavigationIcon({ route }: { route: AppRoute }) {
  const common = { size: 18, weight: "regular" as const, className: "nav-icon", "aria-hidden": true };
  switch (route) {
    case "overview": return <SquaresFour {...common} />;
    case "stations": return <Broadcast {...common} />;
    case "history": return <ClockCounterClockwise {...common} />;
    case "archives": return <Archive {...common} />;
    case "alarms": return <Bell {...common} />;
    case "users": return <UsersThree {...common} />;
    case "system": return <GearSix {...common} />;
  }
}

export function DesktopShell({
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
  const allowed = allowedRoutes(user.role);

  return (
    <Sidebar.Provider defaultOpen>
      <div className="app-shell desktop-shell">
        <Sidebar>
          <Sidebar.Header>
            <div className="sidebar-brand">
              <img className="sidebar-logo" src={brinLogo} alt="BRIN" />
              <strong>RadMon</strong>
            </div>
          </Sidebar.Header>
          <Sidebar.Content>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Panel kontrol</Sidebar.GroupLabel>
              <Sidebar.Menu>
                {allowed.map((item) => (
                  <Sidebar.MenuButton
                    key={item.id}
                    active={route === item.id}
                    onClick={() => navigate(item.id)}
                  >
                    <NavigationIcon route={item.id} />
                    <span>{item.label}</span>
                  </Sidebar.MenuButton>
                ))}
              </Sidebar.Menu>
            </Sidebar.Group>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Monitoring</Sidebar.GroupLabel>
              <Sidebar.Menu>
                <Sidebar.MenuButton onClick={() => window.open("/", "_blank", "noopener,noreferrer") }>
                  <MonitorPlay size={18} weight="regular" className="nav-icon" aria-hidden />
                  <span>Monitoring penuh</span>
                </Sidebar.MenuButton>
              </Sidebar.Menu>
            </Sidebar.Group>
          </Sidebar.Content>
          <Sidebar.Footer>
            <div className="account-card">
              <div>
                <strong>{user.display_name}</strong>
                <span>{user.role}</span>
              </div>
              <Button variant="secondary" aria-label="Keluar" onClick={() => void onSignOut()}>
                Keluar
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
