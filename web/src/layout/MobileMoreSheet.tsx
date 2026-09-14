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
  const primary = new Set(
    mobilePrimaryRoutes(user.role).filter((item): item is AppRoute => item !== "more"),
  );
  const secondary = allowedRoutes(user.role).filter((item) => !primary.has(item.id));

  return (
    <Dialog.Root>
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
      <Dialog>
        <Dialog.Title>More</Dialog.Title>
        <Dialog.Description>
          Additional RadMon views and account actions for {user.display_name}.
        </Dialog.Description>
        <div className="mobile-more-sheet">
          <div className="mobile-more-account">
            <strong>{user.display_name}</strong>
            <span>{user.role}</span>
          </div>
          {secondary.length ? (
            <div className="mobile-more-routes">
              {secondary.map((item) => (
                <Dialog.Close
                  key={item.id}
                  render={(props) => (
                    <Button
                      {...props}
                      variant={route === item.id ? "primary" : "secondary"}
                      onClick={() => navigate(item.id)}
                    >
                      {item.label}
                    </Button>
                  )}
                />
              ))}
            </div>
          ) : null}
          <div className="mobile-more-actions">
            <Dialog.Close
              render={(props) => (
                <Button
                  {...props}
                  variant="secondary"
                  onClick={() => window.open("/", "_blank", "noopener,noreferrer")}
                >
                  Full monitoring
                </Button>
              )}
            />
            <Dialog.Close
              render={(props) => (
                <Button {...props} variant="secondary" onClick={() => void onSignOut()}>
                  Sign out
                </Button>
              )}
            />
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );
}
