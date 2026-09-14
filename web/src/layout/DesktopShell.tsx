import type { ReactNode } from "react";
import { Button, Sidebar } from "@cloudflare/kumo";
import type { SessionUser } from "../api";
import brinLogo from "../assets/brin-logo.png";
import { allowedRoutes, navigate, type AppRoute } from "../navigation";

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
              <Sidebar.GroupLabel>Control plane</Sidebar.GroupLabel>
              <Sidebar.Menu>
                {allowed.map((item) => (
                  <Sidebar.MenuButton
                    key={item.id}
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
                <Sidebar.MenuButton onClick={() => window.open("/", "_blank", "noopener,noreferrer") }>
                  Full monitoring
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
              <Button variant="secondary" aria-label="Sign out" onClick={() => void onSignOut()}>
                Sign out
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
