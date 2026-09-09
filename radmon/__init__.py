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
