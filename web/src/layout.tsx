import { useEffect, useState, type ReactNode } from "react";
import type { SessionUser } from "./api";
import { DesktopShell } from "./layout/DesktopShell";
import { MobileShell } from "./layout/MobileShell";
import {
  NAV_ITEMS,
  roleAllows,
  routeFromLocation,
  type AppRoute,
} from "./navigation";
import { useMobileLayout } from "./responsive";

export type { AppRoute } from "./navigation";
export { navigate } from "./navigation";

export function useAppRoute(user: SessionUser | null): AppRoute {
  const [route, setRoute] = useState<AppRoute>(routeFromLocation());

  useEffect(() => {
    const handler = () => setRoute(routeFromLocation());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);

  if (!user) return "overview";
  const allowed = NAV_ITEMS.some(
    (item) => item.id === route && roleAllows(user.role, item.minimum),
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
  const mobile = useMobileLayout();
  const props = { user, route, onSignOut, children };
  return mobile ? <MobileShell {...props} /> : <DesktopShell {...props} />;
}
