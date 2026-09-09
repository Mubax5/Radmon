"""Runtime compatibility patch for existing Grafana instances.

A previously provisioned Grafana can be healthy and have all expected dashboard
UIDs while still containing an older dashboard payload. The legacy bootstrap
returned immediately in that case, so fixes in the generated dashboards were
never written to an already-running Grafana. This patch repairs healthy ready
instances before returning their playlist URL.
"""
from __future__ import annotations


def apply() -> None:
    from .grafana_bootstrap import GrafanaBootstrap
    from .grafana_tv import playlist_url

    if getattr(GrafanaBootstrap.ensure, "_radmon_reprovision_patch", False):
        return

    original_ensure = GrafanaBootstrap.ensure

    def ensure(self) -> str:
        candidates = self._candidate_base_urls()
        healthy_ready_found = False
        errors: list[str] = []

        # A UID/playlist probe proves that Grafana has the expected resources,
        # but not that the stored JSON is the newest RadMon payload. When the
        # Grafana health endpoint is also reachable, overwrite datasource,
        # dashboards and playlist before reuse so source updates take effect.
        for base in candidates:
            if not self._ready(base):
                continue

            # Preserve the old fast-reuse behavior for synthetic/custom probes
            # that deliberately do not expose a health endpoint. Real RadMon
            # Grafana instances answer /api/health and follow the repair path.
            if not self.grafana_health_probe(base):
                return playlist_url(base)

            healthy_ready_found = True
            try:
                if self.api_provisioner(base) and self._ready(base):
                    return playlist_url(base)
            except Exception as exc:
                errors.append(f"{base}: {exc}")

        if healthy_ready_found:
            detail = "; ".join(errors[-4:]) if errors else "dashboard repair tidak terverifikasi"
            raise RuntimeError(
                "Grafana ditemukan tetapi payload RadMon terbaru gagal diterapkan. "
                f"{detail}"
            )

        return original_ensure(self)

    ensure._radmon_reprovision_patch = True  # type: ignore[attr-defined]
    GrafanaBootstrap.ensure = ensure
