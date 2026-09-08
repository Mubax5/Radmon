"""Python-first radiation monitoring components for DPFK."""

__version__ = "0.1.0"

# Keep the Grafana generator patch small and isolated from the legacy-compatible
# dashboard builder. Importing any ``radmon`` submodule activates the revised
# header/timestamp helpers before payloads are generated.
from .grafana_revision import apply as _apply_grafana_revision

_apply_grafana_revision()
del _apply_grafana_revision
