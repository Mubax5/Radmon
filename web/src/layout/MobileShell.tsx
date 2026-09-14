import type { ReactNode } from "react";
import {
  Bell,
  Broadcast,
  ClockCounterClockwise,
  SquaresFour,
} from "@phosphor-icons/react";
import type { SessionUser } from "../api";
import brinLogo from "../assets/brin-logo.png";
import {
  mobilePrimaryRoutes,
  navigate,
  routeLabel,
  type AppRoute,
} from "../navigation";
import { MobileMoreSheet } from "./MobileMoreSheet";

function MobileNavigationIcon({ route }: { route: AppRoute }) {
  const common = { size: 22, weight: "regular" as const, className: "mobile-nav-icon", "aria-hidden": true };
  switch (route) {
    case "overview": return <SquaresFour {...common} />;
    case "stations": return <Broadcast {...common} />;
    case "history": return <ClockCounterClockwise {...common} />;
    case "alarms": return <Bell {...common} />;
    default: return <SquaresFour {...common} />;
  }
}

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
  const primary = mobilePrimaryRoutes(user.role);
  const pinnedRoutes = primary.filter((item): item is AppRoute => item !== "more");
  const moreActive = !pinnedRoutes.includes(route);

  return (
    <div className="app-shell mobile-shell">
      <header className="mobile-topbar">
        <div className="mobile-topbar-brand">
          <img src={brinLogo} alt="BRIN" />
        </div>
      </header>

      <main className="mobile-content">{children}</main>

      <nav className="mobile-bottom-nav" aria-label="Navigasi utama">
        <div className="mobile-bottom-nav-inner">
          {primary.map((item) => {
            if (item === "more") {
              return (
                <MobileMoreSheet
                  key="more"
                  user={user}
                  route={route}
                  active={moreActive}
                  onSignOut={onSignOut}
                />
              );
            }
            const active = route === item;
            return (
              <button
                type="button"
                key={item}
                className={`mobile-nav-button${active ? " is-active" : ""}`}
                aria-current={active ? "page" : undefined}
                aria-label={routeLabel(item)}
                onClick={() => navigate(item)}
              >
                <MobileNavigationIcon route={item} />
                <span className="mobile-nav-label">{routeLabel(item)}</span>
              </button>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
