import type { Role } from "./api";

export type AppRoute = "overview" | "stations" | "history" | "archives" | "alarms" | "users" | "system";
export type NavItem = { id: AppRoute; label: string; minimum: Role };

export const ROLE_RANK: Record<Role, number> = {
  Viewer: 1,
  Operator: 2,
  Administrator: 3,
};

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "overview", label: "Ringkasan", minimum: "Viewer" },
  { id: "stations", label: "Stasiun", minimum: "Viewer" },
  { id: "history", label: "Riwayat", minimum: "Viewer" },
  { id: "archives", label: "Arsip", minimum: "Viewer" },
  { id: "alarms", label: "Alarm", minimum: "Operator" },
  { id: "users", label: "Pengguna", minimum: "Administrator" },
  { id: "system", label: "Sistem", minimum: "Administrator" },
] as const;

export function roleAllows(role: Role, minimum: Role): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export function allowedRoutes(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => roleAllows(role, item.minimum));
}

export function routeFromLocation(): AppRoute {
  const part = window.location.pathname.replace(/^\/app\/?/, "").split("/")[0];
  const route = (part && part !== "login" ? part : "overview") as AppRoute;
  return NAV_ITEMS.some((item) => item.id === route) ? route : "overview";
}

export function routeLabel(route: AppRoute): string {
  return NAV_ITEMS.find((item) => item.id === route)?.label ?? "Ringkasan";
}

export function navigate(route: AppRoute, query?: Record<string, string | number | undefined>): void {
  const pathname = route === "overview" ? "/app" : `/app/${route}`;
  const params = new URLSearchParams();
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined) params.set(key, String(value));
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  window.history.pushState({}, "", `${pathname}${suffix}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function mobilePrimaryRoutes(role: Role): Array<AppRoute | "more"> {
  return role === "Viewer"
    ? ["overview", "stations", "history", "more"]
    : ["overview", "stations", "alarms", "more"];
}
