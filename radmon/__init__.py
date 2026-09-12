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

from .production_integration_compat_revision import apply as _apply_production_integration_compat_revision
_apply_production_integration_compat_revision()
del _apply_production_integration_compat_revision


from .alarm_policy_revision import apply as _apply_alarm_policy_revision
_apply_alarm_policy_revision()
del _apply_alarm_policy_revision

# The policy store is central SQLite state. Read back newly inserted suppression
# rows on the same detector transaction so uncommitted state never depends on a
# second SQLite connection.
from .alarm_policy_store_revision import apply as _apply_alarm_policy_store_revision
_apply_alarm_policy_store_revision()
del _apply_alarm_policy_store_revision

from .alarm_policy_security_revision import apply as _apply_alarm_policy_security_revision
_apply_alarm_policy_security_revision()
del _apply_alarm_policy_security_revision

from .alarm_policy_runtime_revision import apply as _apply_alarm_policy_runtime_revision
_apply_alarm_policy_runtime_revision()
del _apply_alarm_policy_runtime_revision

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
