import {
  Archive,
  Bell,
  Broadcast,
  ClockCounterClockwise,
  GearSix,
  SquaresFour,
  UsersThree,
} from "@phosphor-icons/react";
import type { AppRoute } from "../navigation";

export function NavigationIcon({
  route,
  size = 18,
  className = "nav-icon",
}: {
  route: AppRoute;
  size?: number;
  className?: string;
}) {
  const common = { size, weight: "regular" as const, className, "aria-hidden": true };
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
