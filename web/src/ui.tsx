import { useEffect, useId, useRef, type MouseEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { LayerCard } from "@cloudflare/kumo";

export { ResponsiveStationView, StationCards, StationDetail, StationTable } from "./components/StationViews";

/**
 * Native modal used for informational popups and the small amount of UI that
 * is not covered by Kumo's compound Dialog.  The default is intentionally a
 * normal, dismissible dialog.  Critical flows should use Kumo's
 * `role="alertdialog"` instead, so a backdrop click cannot discard a form.
 */
export function Modal({
  open,
  onOpenChange,
  title,
  ariaLabel,
  children,
  className = "",
  dialogRef,
  dismissOnBackdrop = true,
  dismissOnEscape = true,
  testId,
  "data-testid": dataTestId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  ariaLabel?: string;
  children: ReactNode;
  className?: string;
  dialogRef?: RefObject<HTMLDialogElement | null>;
  dismissOnBackdrop?: boolean;
  dismissOnEscape?: boolean;
  testId?: string;
  "data-testid"?: string;
}) {
  const internalRef = useRef<HTMLDialogElement>(null);
  const ref = dialogRef ?? internalRef;
  const titleId = useId();
  const openerRef = useRef<HTMLElement | null>(null);
  const backdropPressRef = useRef<{ pointerId: number; x: number; y: number } | null>(null);
  const suppressBackdropClickRef = useRef(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open) {
      if (openerRef.current === null) {
        openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      }
      if (!dialog.open) dialog.showModal();
      return;
    }
    if (dialog.open) dialog.close();
    const opener = openerRef.current;
    openerRef.current = null;
    if (opener && document.contains(opener)) requestAnimationFrame(() => opener.focus());
  }, [open, ref]);

  function close() {
    if (!open) return;
    onOpenChange(false);
  }

  function handleBackdropClick(event: MouseEvent<HTMLDialogElement>) {
    if (event.target !== event.currentTarget) {
      suppressBackdropClickRef.current = false;
      return;
    }
    if (suppressBackdropClickRef.current) {
      suppressBackdropClickRef.current = false;
      return;
    }
    // Native dialog clicks can bubble from the content panel.  Only the
    // dialog backdrop itself is dismissible; text selection/dragging inside
    // the panel must never close a modal.
    if (dismissOnBackdrop) close();
  }

  function handleBackdropPointerDown(event: ReactPointerEvent<HTMLDialogElement>) {
    if (event.target === event.currentTarget) {
      suppressBackdropClickRef.current = false;
      backdropPressRef.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
    } else {
      // A drag that starts in the panel and ends on the backdrop is still an
      // inside interaction and must not dismiss the dialog.
      backdropPressRef.current = null;
      suppressBackdropClickRef.current = true;
    }
  }

  function handleBackdropPointerMove(event: ReactPointerEvent<HTMLDialogElement>) {
    const press = backdropPressRef.current;
    if (!press || press.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) > 5) {
      backdropPressRef.current = null;
      suppressBackdropClickRef.current = true;
    }
  }

  function handleBackdropPointerUp(event: ReactPointerEvent<HTMLDialogElement>) {
    const press = backdropPressRef.current;
    backdropPressRef.current = null;
    if (!press || press.pointerId !== event.pointerId) return;
    if (Math.hypot(event.clientX - press.x, event.clientY - press.y) <= 5 && event.target === event.currentTarget) {
      // Click is allowed to perform the actual state change; this handler
      // only validates that the press was a short backdrop press.
      suppressBackdropClickRef.current = false;
    }
  }

  return (
    <dialog
      ref={ref}
      className={`native-user-dialog radmon-modal ${className}`.trim()}
      aria-label={ariaLabel}
      aria-labelledby={title ? titleId : undefined}
      aria-modal="true"
      data-testid={dataTestId ?? testId}
      onPointerDown={handleBackdropPointerDown}
      onPointerMove={handleBackdropPointerMove}
      onPointerUp={handleBackdropPointerUp}
      onClick={handleBackdropClick}
      onCancel={(event) => {
        event.preventDefault();
        if (dismissOnEscape) close();
      }}
    >
      <div className="native-user-dialog-content radmon-modal-content">
        {title ? <h2 id={titleId}>{title}</h2> : null}
        {children}
      </div>
    </dialog>
  );
}

export function PageHeading({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}

export function PageSection({
  title,
  description,
  action,
  children,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`page-section ${className}`.trim()}>
      <div className="page-section-header">
        <div className="page-section-title">
          <h2>{title}</h2>
          {description ? <p>{description}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  badge,
  className = "",
}: {
  label: string;
  value: ReactNode;
  badge?: ReactNode;
  className?: string;
}) {
  return (
    <LayerCard className={`metric-card ${className}`.trim()}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {badge}
    </LayerCard>
  );
}

export function formatTimestamp(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString("id-ID");
}

export function freshnessLabel(value?: string | null): string {
  if (!value) return "Belum ada measurement live";
  const parsed = new Date(value);
  const delta = Date.now() - parsed.getTime();
  if (!Number.isFinite(delta)) return "Umur data tidak diketahui";
  const minutes = Math.max(0, Math.floor(delta / 60000));
  if (minutes < 1) return "Baru saja";
  if (minutes < 60) return `${minutes} mnt lalu`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} jam lalu`;
  return `${Math.floor(hours / 24)} hari lalu`;
}

export function LoadingCard({ label = "Memuat…" }: { label?: string } = {}) {
  return (
    <LayerCard className="empty-card loading-skeleton-card" role="status" aria-busy="true" aria-label={label}>
      <span className="skeleton-text">{label}</span>
      <div className="skeleton-block" aria-hidden="true">
        <div className="skeleton-line" />
        <div className="skeleton-line short" />
        <div className="skeleton-line" />
      </div>
    </LayerCard>
  );
}

export function ErrorCard({ message }: { message: string }) {
  return <LayerCard className="error-card" role="alert">{message}</LayerCard>;
}
