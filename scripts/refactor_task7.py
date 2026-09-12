from __future__ import annotations

import ast
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def function_source(path: Path, parent_name: str, nested_name: str) -> str:
    source = read(path)
    tree = ast.parse(source)
    parent = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parent_name
    )
    nested = next(
        node for node in ast.walk(parent)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == nested_name
    )
    lines = source.splitlines()
    start = nested.lineno - 1
    if nested.decorator_list:
        start = min(item.lineno for item in nested.decorator_list) - 1
    return textwrap.dedent("\n".join(lines[start:nested.end_lineno])) + "\n"


def replace_def_name(source: str, old: str, new: str) -> str:
    return re.sub(rf"(?m)^(\s*(?:async\s+)?def\s+){re.escape(old)}(?=\s*\()", rf"\1{new}", source, count=1)


def replace_class_method(path: Path, class_name: str, method_name: str, method_source: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(
        (
            node for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
        ),
        None,
    )
    replacement = textwrap.dedent(method_source).strip("\n").splitlines()
    replacement = [("    " + line) if line else "" for line in replacement]
    lines = source.splitlines()
    if method is None:
        insert_at = cls.end_lineno
        lines[insert_at:insert_at] = [""] + replacement
    else:
        start = method.lineno - 1
        if method.decorator_list:
            start = min(item.lineno for item in method.decorator_list) - 1
        lines[start:method.end_lineno] = replacement
    write(path, "\n".join(lines))


def replace_top_function(path: Path, name: str, function_text: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    lines = source.splitlines()
    start = node.lineno - 1
    if node.decorator_list:
        start = min(item.lineno for item in node.decorator_list) - 1
    lines[start:node.end_lineno] = textwrap.dedent(function_text).strip("\n").splitlines()
    write(path, "\n".join(lines))


def insert_before_function(path: Path, before_name: str, block: str) -> None:
    source = read(path)
    if block.strip() in source:
        return
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == before_name)
    lines = source.splitlines()
    lines[node.lineno - 1:node.lineno - 1] = textwrap.dedent(block).strip("\n").splitlines() + [""]
    write(path, "\n".join(lines))


lan = ROOT / "radmon/lan.py"
lan_revision = ROOT / "radmon/lan_revision.py"
safety_revision = ROOT / "radmon/production_safety_revision.py"
production_revision = ROOT / "radmon/production_integration_revision.py"
remote_alarm = ROOT / "radmon/remote_alarm.py"
secure_services = ROOT / "radmon/secure_services.py"
secure_context = ROOT / "radmon/secure_context.py"

insert_before_function(
    lan,
    "parse_lan_sources",
    '''
LIVE_KEYS = (
    "serid", "name", "location", "warnlevel", "alarmlevel", "unit", "audiopath",
    "description", "maxidlemin", "dtom", "doserate", "dose", "lastrate",
    "minrate", "maxrate", "avgrate", "lastdose", "mindose", "maxdose",
    "avgdose", "lastmea", "lastmeasec", "meacount", "firstmea",
)


@dataclass(slots=True)
class LivePullResult:
    source_id: str
    live_stations: int = 0
    inserted_measurements: int = 0
    mirrored_alarms: int = 0
    error: str | None = None


@dataclass(slots=True)
class BackfillPullResult:
    source_id: str
    backfill_serid: int | None = None
    inserted_measurements: int = 0
    checkpoint: datetime | None = None
    error: str | None = None
''',
)

# Direct LAN methods from the proven production revision.
for name in ("live_rows", "alarms_after"):
    replace_class_method(lan, "RemoteMariaDBSource", name, function_source(lan_revision, "apply", name))
replace_class_method(
    lan,
    "RemoteMariaDBSource",
    "active_alarm_keys",
    function_source(safety_revision, "_add_alarm_active_set_reconciliation", "active_alarm_keys"),
)
for name in ("_ensure_alarm_checkpoint_table", "load_alarm", "save_alarm"):
    replace_class_method(lan, "LanCheckpointStore", name, function_source(lan_revision, "apply", name))

# Preserve lan_revision upsert behavior as a direct helper, then layer the live
# measurement insert that production_integration_revision previously wrapped around it.
upsert_core = replace_def_name(function_source(lan_revision, "apply", "upsert_live_rows"), "upsert_live_rows", "_upsert_live_rows_base")
replace_class_method(lan, "MariaCentralStore", "_upsert_live_rows_base", upsert_core)
replace_class_method(
    lan,
    "MariaCentralStore",
    "upsert_live_rows",
    '''
def upsert_live_rows(self, source_id: str, rows: Iterable[dict[str, Any]]) -> int:
    values = list(rows)
    changed = self._upsert_live_rows_base(source_id, values)
    if not values:
        return changed
    connection = self._connection()
    try:
        with connection.cursor() as cursor:
            for row in values:
                measured_at = row.get("dtom")
                rate = row.get("doserate")
                if not isinstance(measured_at, datetime) or rate is None:
                    continue
                try:
                    interval = int(row.get("lastmeasec") or 2)
                except (TypeError, ValueError):
                    interval = 2
                if interval < 1 or interval > 3600:
                    interval = 2
                cursor.execute(
                    """
INSERT IGNORE INTO measurement
  (serid, dtom, doserate, dose, previnterval, stat)
VALUES (?, ?, ?, ?, ?, 0)
""",
                    (
                        int(row["serid"]), measured_at, float(rate),
                        float(row.get("dose") or 0.0), interval,
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return changed
''',
)
for name in ("import_measurements", "mirror_alarm_events"):
    replace_class_method(lan, "MariaCentralStore", name, function_source(lan_revision, "apply", name))
replace_class_method(
    lan,
    "MariaCentralStore",
    "mark_alarm_handled",
    function_source(safety_revision, "_add_alarm_active_set_reconciliation", "mark_alarm_handled"),
)

# Preserve the core LAN poll, then layer alarm-state reconciliation and active-set
# reconciliation in the exact order of the old wrappers.
run_live_core = replace_def_name(function_source(lan_revision, "apply", "run_live_once"), "run_live_once", "_run_live_core_once")
replace_class_method(lan, "LanAggregator", "_run_live_core_once", run_live_core)
replace_class_method(
    lan,
    "LanAggregator",
    "run_live_once",
    '''
def run_live_once(self, source):
    historical_seed = self.checkpoints.load_alarm(source.source_id) is None
    result = self._run_live_core_once(source)
    if result.error:
        return result
    try:
        remote = self.remote_factory(source)
        state_rows = remote.alarm_states(2000)
        mapped: list[dict[str, Any]] = []
        for row in state_rows:
            item = dict(row)
            remote_serid = int(item["serid"])
            item["_remote_serid"] = remote_serid
            item["serid"] = self.checkpoints.store.resolve_station(
                source.source_id, remote_serid
            )
            if historical_seed:
                item["_historical_seed"] = True
            mapped.append(item)
        if mapped and self.alarm_mirror is not None:
            self.alarm_mirror.mirror(source.source_id, mapped)
        if mapped and hasattr(self.central, "mirror_alarm_events"):
            self.central.mirror_alarm_events(source.source_id, mapped)

        if self.alarm_mirror is not None:
            key_reader = getattr(remote, "active_alarm_keys", None)
            if callable(key_reader):
                active_keys: set[tuple[int, datetime]] = set()
                for remote_serid, event_time in key_reader():
                    central_serid = self.checkpoints.store.resolve_station(
                        source.source_id, int(remote_serid)
                    )
                    active_keys.add((int(central_serid), event_time))
                handled = self.alarm_mirror.reconcile_source_active_keys(
                    source.source_id, active_keys
                )
                if handled and hasattr(self.central, "mark_alarm_handled"):
                    self.central.mark_alarm_handled(handled)
    except Exception as exc:
        result.error = str(exc)
    return result
''',
)
for name in ("run_backfill_once", "run_source_once"):
    replace_class_method(lan, "LanAggregator", name, function_source(lan_revision, "apply", name))

# Direct the newest RemoteAlarmMirror implementation from the production integration
# revision, not the older compatibility revision.
remote_text = read(remote_alarm)
if "import threading" not in remote_text:
    remote_text = remote_text.replace("from datetime import datetime\n", "from datetime import datetime\nimport threading\n", 1)
if "_REMOTE_ALARM_SCHEMA_LOCK" not in remote_text:
    marker = "from .security import SecurityStore, UserIdentity\n"
    remote_text = remote_text.replace(marker, marker + "\n\n_REMOTE_ALARM_SCHEMA_LOCK = threading.Lock()\n", 1)
write(remote_alarm, remote_text)

for old_name, final_name in (
    ("ensure_active_schema", "_ensure_active_schema"),
    ("mirror", "mirror"),
    ("row_to_dict", "_row"),
    ("list_alarms", "list_alarms"),
    ("get", "get"),
    ("mark_acknowledged", "mark_acknowledged"),
):
    method = function_source(production_revision, "_patch_alarm_mirror_and_control", old_name)
    method = replace_def_name(method, old_name, final_name)
    method = method.replace("ensure_active_schema(self)", "self._ensure_active_schema()")
    method = method.replace("row_to_dict(row)", "self._row(row)")
    method = method.replace("with schema_lock:", "with _REMOTE_ALARM_SCHEMA_LOCK:")
    replace_class_method(remote_alarm, "RemoteAlarmMirror", final_name, method)

replace_class_method(
    remote_alarm,
    "RemoteAlarmMirror",
    "reconcile_source_active_keys",
    function_source(safety_revision, "_add_alarm_active_set_reconciliation", "reconcile_source_active_keys")
        .replace("self._ensure_active_schema()", "self._ensure_active_schema()"),
)
# Move response ACK direct now because disabling the old mirror/control patch must not
# discard the current source write-through semantics.
replace_class_method(
    remote_alarm,
    "AlarmControlService",
    "ack",
    function_source(production_revision, "_patch_alarm_mirror_and_control", "ack"),
)

# Make source write-through an explicit Settings.lan_enabled boundary.
services_text = read(secure_services)
needle = "    user_admin = UserAdminService(security, audit)\n"
if needle not in services_text:
    raise RuntimeError("secure_services insertion point not found")
block = '''    user_admin = UserAdminService(security, audit)

    device_admin.source_definitions = dict(sources)
    if bool(getattr(settings, "lan_enabled", False)) and sources:
        device_admin.write_through = True
        device_admin.station_source = security.station_source

        def remote_device_factory(source_id: str):
            source = sources.get(str(source_id))
            if source is None:
                raise KeyError(f"LAN source tidak ditemukan: {source_id}")
            return RemoteMariaDBSource(source)

        device_admin.remote_factory = remote_device_factory
    else:
        device_admin.write_through = False
        device_admin.station_source = None
        device_admin.remote_factory = None
'''
services_text = services_text.replace(needle, block, 1)
write(secure_services, services_text)

replace_top_function(
    secure_context,
    "set_context",
    '''
def set_context(value: SecurityContext | None) -> None:
    global _context
    current = _context
    if current is not None and (
        value is None
        or getattr(value, "identity", None) != getattr(current, "identity", None)
    ):
        try:
            current.security.clear_sensitive_lease(current.identity.username)
        except Exception:
            pass
    _context = value
''',
)

# These canonical implementations supersede the overlapping production integration
# wrappers. Security/device/UI/Grafana patches remain for later tasks.
prod_text = read(production_revision)
for call in (
    "    _patch_secure_services()\n",
    "    _patch_alarm_mirror_and_control()\n",
    "    _patch_live_collector()\n",
):
    if call not in prod_text:
        raise RuntimeError(f"production integration call not found: {call.strip()}")
    prod_text = prod_text.replace(call, "", 1)
write(production_revision, prod_text)

# Remove the three now-consolidated package-level dispatches.
init_path = ROOT / "radmon/__init__.py"
init_text = read(init_path)
for revision in ("lan_revision", "remote_alarm_revision", "production_safety_revision"):
    pattern = rf"\nfrom \.{revision} import apply as _apply_{revision}\n_apply_{revision}\(\)\ndel _apply_{revision}\n"
    init_text, count = re.subn(pattern, "\n", init_text)
    if count != 1:
        raise RuntimeError(f"apply block not found: {revision}")
write(init_path, init_text)

for name in ("lan_revision.py", "remote_alarm_revision.py", "production_safety_revision.py"):
    (ROOT / "radmon" / name).unlink()

Path(__file__).unlink()
(ROOT / ".github/workflows/refactor-task7.yml").unlink()
