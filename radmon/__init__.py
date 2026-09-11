"""Python-first radiation monitoring components for DPFK."""

__version__ = "0.1.0"

# Runtime compatibility patches are intentionally isolated from the older
# implementation modules. Importing any radmon submodule activates the
# production ipradmon contract before application services are constructed.
from .repository_revision import apply as _apply_repository_revision
_apply_repository_revision()
del _apply_repository_revision

from .lan_revision import apply as _apply_lan_revision
_apply_lan_revision()
del _apply_lan_revision

from .remote_alarm_revision import apply as _apply_remote_alarm_revision
_apply_remote_alarm_revision()
del _apply_remote_alarm_revision

from .archive_store_revision import apply as _apply_archive_store_revision
_apply_archive_store_revision()
del _apply_archive_store_revision

from .archive_reports_revision import apply as _apply_archive_reports_revision
_apply_archive_reports_revision()
del _apply_archive_reports_revision

# Keep the Grafana compatibility patches small and isolated from the
# legacy-compatible dashboard builder.
from .grafana_revision import apply as _apply_grafana_revision
_apply_grafana_revision()
del _apply_grafana_revision

from .grafana_bootstrap_revision import apply as _apply_grafana_bootstrap_revision
_apply_grafana_bootstrap_revision()
del _apply_grafana_bootstrap_revision

# End-to-end production integration (source write-through, alarm i_flag,
# PIN lease, live chart samples, grouped source UI, browser manuals).
from .production_integration_revision import apply as _apply_production_integration_revision
_apply_production_integration_revision()
del _apply_production_integration_revision

# Narrow compatibility guards ensure legacy/synthetic adapters do not weaken
# the deployed RemoteMariaDBSource production path.
from .production_integration_compat_revision import apply as _apply_production_integration_compat_revision
_apply_production_integration_compat_revision()
del _apply_production_integration_compat_revision

# Explicit LAN enablement gates source writes, desktop logout revokes sensitive
# elevation, and active alarm state is reconciled against each source.
from .production_safety_revision import apply as _apply_production_safety_revision
_apply_production_safety_revision()
del _apply_production_safety_revision

# Production DATETIME values are WIB wall-clock values. Keep its query
# semantics intact before applying the final UI icon compatibility pass.
from .grafana_wib_revision import apply as _apply_grafana_wib_revision
_apply_grafana_wib_revision()
del _apply_grafana_wib_revision

# Legacy production patches can replace tree/dialog methods. Apply semantic
# Tabler icons after every older compatibility layer so final visible icons
# remain distinct without changing LAN grouping behavior.
from .icon_system_revision import apply as _apply_icon_system_revision
_apply_icon_system_revision()
del _apply_icon_system_revision
