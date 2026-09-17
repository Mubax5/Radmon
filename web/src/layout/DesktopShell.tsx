import type { ReactNode } from "react";
import { Button, Sidebar, useSidebar } from "@cloudflare/kumo";
import { MonitorPlay, SignOut } from "@phosphor-icons/react";
import type { SessionUser } from "../api";
import brinLogo from "../assets/brin-logo.png";
import { allowedRoutes, navigate, type AppRoute } from "../navigation";
import { NavigationIcon } from "./NavigationIcon";

function AccountFooter({
  user,
  onSignOut,
}: {
  user: SessionUser;
  onSignOut: () => Promise<void>;
}) {
  const { open } = useSidebar();
  if (!open) {
    return (
      <div className="account-card account-card-collapsed">
        <Button
          variant="secondary"
          aria-label="Keluar"
          title={`Keluar (${user.display_name})`}
          onClick={() => void onSignOut()}
        >
          <SignOut size={18} weight="regular" aria-hidden />
        </Button>
      </div>
    );
  }
  return (
    <div className="account-card">
      <div>
        <strong>{user.display_name}</strong>
        <span>{user.role}</span>
      </div>
      <Button variant="secondary" aria-label="Keluar" onClick={() => void onSignOut()}>
        Keluar
      </Button>
    </div>
  );
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
    <Sidebar.Provider defaultOpen mobileBreakpoint={768}>
      <div className="app-shell desktop-shell">
        <Sidebar>
          <Sidebar.Header className="sidebar-header">
            <div className="sidebar-brand">
              <img className="sidebar-logo" src={brinLogo} alt="BRIN" />
              <Sidebar.Trigger className="sidebar-collapse-button" data-testid="sidebar-collapse-trigger" />
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
                    <span className="sidebar-icon-wrapper" aria-hidden="true">
                      <NavigationIcon route={item.id} />
                    </span>
                    <span>{item.label}</span>
                  </Sidebar.MenuButton>
                ))}
              </Sidebar.Menu>
            </Sidebar.Group>
            <Sidebar.Group>
              <Sidebar.GroupLabel>Monitoring</Sidebar.GroupLabel>
              <Sidebar.Menu>
                <Sidebar.MenuButton onClick={() => window.open("/", "_blank", "noopener,noreferrer") }>
                  <span className="sidebar-icon-wrapper" aria-hidden="true">
                    <MonitorPlay size={18} weight="regular" className="nav-icon" aria-hidden />
                  </span>
                  <span>Monitoring penuh</span>
                </Sidebar.MenuButton>
              </Sidebar.Menu>
            </Sidebar.Group>
          </Sidebar.Content>
          <Sidebar.Footer>
            <AccountFooter user={user} onSignOut={onSignOut} />
          </Sidebar.Footer>
        </Sidebar>
        <main className="content-shell">{children}</main>
      </div>
    </Sidebar.Provider>
  );
}
