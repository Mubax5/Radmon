import { useState } from "react";
import { Dialog } from "@cloudflare/kumo";
import { DotsThree, MonitorPlay, SignOut, X } from "@phosphor-icons/react";
import type { SessionUser } from "../api";
import {
  allowedRoutes,
  mobilePrimaryRoutes,
  navigate,
  type AppRoute,
} from "../navigation";
import { NavigationIcon } from "./NavigationIcon";

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
            aria-label="Lainnya"
          >
            <DotsThree size={22} weight="bold" className="mobile-nav-icon nav-icon" aria-hidden />
            <span className="mobile-nav-label">Lainnya</span>
          </button>
        )}
      />
      <Dialog className="radmon-dialog mobile-sheet-dialog mobile-sheet-panel">
        <div className="mobile-sheet-content">
          <div className="mobile-sheet-handle" aria-hidden />
          <div className="mobile-sheet-heading">
            <div>
              <Dialog.Title>Lainnya</Dialog.Title>
              <Dialog.Description>Halaman tambahan dan pengaturan akun.</Dialog.Description>
            </div>
            <Dialog.Close
              render={(props) => (
                <button {...props} type="button" className="mobile-sheet-close" aria-label="Tutup menu lainnya">
                  <X size={20} weight="regular" aria-hidden />
                </button>
              )}
            />
          </div>

          <div
            className="mobile-more-sheet"
            data-secondary-routes={secondary.map((item) => item.id).join(",")}
          >
            <div className="mobile-more-account">
              <strong>{user.display_name}</strong>
              <span>{user.role}</span>
            </div>

            {secondary.length ? (
              <div className="mobile-more-routes" aria-label="Halaman tambahan">
                {secondary.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={`mobile-more-route${route === item.id ? " is-active" : ""}`}
                    aria-current={route === item.id ? "page" : undefined}
                    onClick={() => go(item.id)}
                  >
                    <NavigationIcon route={item.id} size={20} className="mobile-more-route-icon nav-icon" />
                    <span>{item.label}</span>
                  </button>
                ))}
              </div>
            ) : null}

            <div className="mobile-more-actions" aria-label="Tindakan akun">
              <button type="button" className="mobile-more-route" onClick={openMonitoring}>
                <MonitorPlay size={20} weight="regular" className="mobile-more-route-icon" aria-hidden />
                <span>Monitoring penuh</span>
              </button>
              <button type="button" className="mobile-more-route mobile-more-signout" onClick={() => void signOut()}>
                <SignOut size={20} weight="regular" className="mobile-more-route-icon" aria-hidden />
                <span>Keluar</span>
              </button>
            </div>
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );
}
