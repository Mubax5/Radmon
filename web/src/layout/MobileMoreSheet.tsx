import { useState } from "react";
import { Button, Dialog } from "@cloudflare/kumo";
import type { SessionUser } from "../api";
import {
  allowedRoutes,
  mobilePrimaryRoutes,
  navigate,
  type AppRoute,
} from "../navigation";

export function MobileMoreSheet({
  user,
  route,
  active,
  onSignOut,
}: {
  user: SessionUser;
  route: AppRoute;
  active: boolean;
  onSignOut: () => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const primary = new Set(
    mobilePrimaryRoutes(user.role).filter((item): item is AppRoute => item !== "more"),
  );
  const secondary = allowedRoutes(user.role).filter((item) => !primary.has(item.id));

  function go(routeId: AppRoute) {
    setOpen(false);
    navigate(routeId);
  }

  function openMonitoring() {
    setOpen(false);
    window.open("/", "_blank", "noopener,noreferrer");
  }

  async function signOut() {
    setOpen(false);
    await onSignOut();
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        render={(props) => (
          <button
            {...props}
            type="button"
            className={`mobile-nav-button${active ? " is-active" : ""}`}
            aria-current={active ? "page" : undefined}
          >
            More
          </button>
        )}
      />
      <Dialog className="radmon-dialog" style={{ zIndex: 90 }}>
        <Dialog.Title>More</Dialog.Title>
        <Dialog.Description>
          Additional RadMon views and account actions for {user.display_name}.
        </Dialog.Description>
        <div
          className="mobile-more-sheet"
          data-secondary-routes={secondary.map((item) => item.id).join(",")}
        >
          <div className="mobile-more-account">
            <strong>{user.display_name}</strong>
            <span>{user.role}</span>
          </div>
          {secondary.length ? (
            <div className="mobile-more-routes">
              {secondary.map((item) => (
                <Button
                  key={item.id}
                  variant={route === item.id ? "primary" : "secondary"}
                  onClick={() => go(item.id)}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          ) : null}
          <div className="mobile-more-actions">
            <Button variant="secondary" onClick={openMonitoring}>Full monitoring</Button>
            <Button variant="secondary" onClick={() => void signOut()}>Sign out</Button>
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );
}
