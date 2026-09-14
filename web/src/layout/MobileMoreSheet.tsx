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
  open,
  onOpenChange,
  onSignOut,
}: {
  user: SessionUser;
  route: AppRoute;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSignOut: () => Promise<void>;
}) {
  const primary = new Set(
    mobilePrimaryRoutes(user.role).filter((item): item is AppRoute => item !== "more"),
  );
  const secondary = allowedRoutes(user.role).filter((item) => !primary.has(item.id));

  async function signOut() {
    onOpenChange(false);
    await onSignOut();
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
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
                <Button
                  key={item.id}
                  variant={route === item.id ? "primary" : "secondary"}
                  onClick={() => {
                    navigate(item.id);
                    onOpenChange(false);
                  }}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          ) : null}
          <div className="mobile-more-actions">
            <Button
              variant="secondary"
              onClick={() => window.open("/", "_blank", "noopener,noreferrer")}
            >
              Full monitoring
            </Button>
            <Button variant="secondary" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </Dialog>
    </Dialog.Root>
  );
}
