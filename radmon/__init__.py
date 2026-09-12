"""Python-first radiation monitoring components for DPFK."""

__version__ = "0.1.0"






from .grafana_revision import apply as _apply_grafana_revision
_apply_grafana_revision()
del _apply_grafana_revision

from .grafana_bootstrap_revision import apply as _apply_grafana_bootstrap_revision
_apply_grafana_bootstrap_revision()
del _apply_grafana_bootstrap_revision

from .production_integration_revision import apply as _apply_production_integration_revision
_apply_production_integration_revision()
del _apply_production_integration_revision







# Preserve the production WIB wall-clock conversion first, then layer the
# central policy JOIN over those already-final query builders.
from .grafana_wib_revision import apply as _apply_grafana_wib_revision
_apply_grafana_wib_revision()
del _apply_grafana_wib_revision

from .grafana_policy_revision import apply as _apply_grafana_policy_revision
_apply_grafana_policy_revision()
del _apply_grafana_policy_revision

# Semantic icons stay last among UI compatibility patches.
from .icon_system_revision import apply as _apply_icon_system_revision
_apply_icon_system_revision()
del _apply_icon_system_revision
