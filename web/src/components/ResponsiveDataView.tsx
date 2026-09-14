import type { ReactNode } from "react";
import { useMobileLayout } from "../responsive";

export function ResponsiveDataView({
  desktop,
  mobile,
}: {
  desktop: ReactNode;
  mobile: ReactNode;
}) {
  const isMobile = useMobileLayout();
  return isMobile ? <>{mobile}</> : <>{desktop}</>;
}
