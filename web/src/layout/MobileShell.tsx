import { useState, type ReactNode } from "react";
import type { SessionUser } from "../api";
import brinLogo from "../assets/brin-logo.png";
import {
  mobilePrimaryRoutes,
  navigate,
  routeLabel,
  type AppRoute,
} from "../navigation";
import { MobileMoreSheet } from "./MobileMoreSheet";

export function MobileShell({
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
  const [moreOpen, setMoreOpen] = useState(false);
  const primary = mobilePrimaryRoutes(user.role);
  const pinnedRoutes = primary.filter((item): item is AppRoute => item !== "more");
  const moreActive = !pinnedRoutes.includes(route);

  return (
    <div className="app-shell mobile-shell">
      <header className="mobile-topbar">
        <div className="mobile-topbar-brand">
          <img src={brinLogo} alt="BRIN" />
        </div>
        <strong>{routeLabel(route)}</strong>
      </header>

      <main className="mobile-content">{children}</main>

      <nav className="mobile-bottom-nav" aria-label="Primary navigation">
        <div className="mobile-bottom-nav-inner">
          {primary.map((item) => {
            if (item === "more") {
              return (
                <button
                  type="button"
                  key="more"
                  className={`mobile-nav-button${moreActive ? " is-active" : ""}`}
                  aria-current={moreActive ? "page" : undefined}
                  onClick={() => setMoreOpen(true)}
                >
                  More
                </button>
              );
            }
            const active = route === item;
            return (
              <button
                type="button"
                key={item}
                className={`mobile-nav-button${active ? " is-active" : ""}`}
                aria-current={active ? "page" : undefined}
                onClick={() => navigate(item)}
              >
                {routeLabel(item)}
              </button>
            );
          })}
        </div>
      </nav>

      <MobileMoreSheet
        user={user}
        route={route}
        open={moreOpen}
        onOpenChange={setMoreOpen}
        onSignOut={onSignOut}
      />
    </div>
  );
}
