"""Python-first radiation monitoring components for DPFK."""

__version__ = "0.1.0"

# Keep the Grafana compatibility patches small and isolated from the
# legacy-compatible dashboard builder. Importing any ``radmon`` submodule
# activates the revised header/timestamp helpers and makes an already-running
# Grafana refresh its stored dashboards before the playlist is reused.
from .grafana_revision import apply as _apply_grafana_revision

_apply_grafana_revision()
del _apply_grafana_revision

from .grafana_bootstrap_revision import apply as _apply_grafana_bootstrap_revision

_apply_grafana_bootstrap_revision()
del _apply_grafana_bootstrap_revision
