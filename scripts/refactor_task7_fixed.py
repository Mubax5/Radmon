from __future__ import annotations

import ast
import copy
from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def nested_function(path: Path, parent_name: str, nested_name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    parent = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == parent_name
    )
    node = next(
        node for node in ast.walk(parent)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == nested_name
    )
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def patch_class(path: Path, class_name: str, methods: dict[str, str]) -> None:
    """Replace/append class methods using one immutable source-coordinate pass."""
    source = read(path)
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    existing = {
        node.name: node
        for node in cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    lines = source.splitlines()
    edits: list[tuple[int, int, list[str]]] = []
    missing: list[str] = []
    for name, method in methods.items():
        rendered = textwrap.indent(textwrap.dedent(method).strip(), "    ").splitlines()
        node = existing.get(name)
        if node is None:
            missing.extend([""] + rendered)
            continue
        start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
        end = node.end_lineno
        edits.append((start, end, rendered))
    if missing:
        # cls.end_lineno is 1-based and points at the final line in the class;
        # using it as a 0-based insertion index places new indented methods
        # immediately after that line and before the next top-level definition.
        edits.append((cls.end_lineno, cls.end_lineno, missing))
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        lines[start:end] = replacement
    write(path, "\n".join(lines))


def insert_before_top_level(path: Path, before_name: str, block: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    target = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == before_name
    )
    lines = source.splitlines()
    lines[target.lineno - 1:target.lineno - 1] = textwrap.dedent(block).strip().splitlines() + [""]
    write(path, "\n".join(lines))


def replace_top_function(path: Path, name: str, replacement: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
    lines = source.splitlines()
    start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
    lines[start:node.end_lineno] = textwrap.dedent(replacement).strip().splitlines()
    write(path, "\n".join(lines))


lan = ROOT / "radmon/lan.py"
lan_revision = ROOT / "radmon/lan_revision.py"
safety_revision = ROOT / "radmon/production_safety_revision.py"
production_revision = ROOT / "radmon/production_integration_revision.py"
remote_alarm = ROOT / "radmon/remote_alarm.py"
secure_services = ROOT / "radmon/secure_services.py"
secure_context = ROOT / "radmon/secure_context.py"

# Stable top-level result types from lan_revision.
insert_before_top_level(
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

live_rows = nested_function(lan_revision, "apply", "live_rows")
alarms_after = nested_function(lan_revision, "apply", "alarms_after")
active_alarm_keys = nested_function(safety_revision, "_add_alarm_active_set_reconciliation", "active_alarm_keys")
patch_class(
    lan,
    "RemoteMariaDBSource",
    {
        "live_rows": live_rows,
        "alarms_after": alarms_after,
        "active_alarm_keys": active_alarm_keys,
    },
)

patch_class(
    lan,
    "LanCheckpointStore",
    {
        "_ensure_alarm_checkpoint_table": nested_function(lan_revision, "apply", "_ensure_alarm_checkpoint_table"),
        "load_alarm": nested_function(lan_revision, "apply", "load_alarm"),
        "save_alarm": nested_function(lan_revision, "apply", "save_alarm"),
    },
)

base_upsert = nested_function(lan_revision, "apply", "upsert_live_rows", rename="_upsert_live_rows_base")
final_upsert = '''
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
'''
patch_class(
    lan,
    "MariaCentralStore",
    {
        "_upsert_live_rows_base": base_upsert,
        "upsert_live_rows": final_upsert,
        "import_measurements": nested_function(lan_revision, "apply", "import_measurements"),
        "mirror_alarm_events": nested_function(lan_revision, "apply", "mirror_alarm_events"),
        "mark_alarm_handled": nested_function(safety_revision, "_add_alarm_active_set_reconciliation", "mark_alarm_handled"),
    },
)

core_live = nested_function(lan_revision, "apply", "run_live_once", rename="_run_live_core_once").replace("lan.", "")
run_backfill = nested_function(lan_revision, "apply", "run_backfill_once").replace("lan.", "")
run_source = nested_function(lan_revision, "apply", "run_source_once").replace("lan.", "")
final_live = '''
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
'''
patch_class(
    lan,
    "LanAggregator",
    {
        "_run_live_core_once": core_live,
        "run_live_once": final_live,
        "run_backfill_once": run_backfill,
        "run_source_once": run_source,
    },
)

# Final RemoteAlarmMirror implementation from production integration plus safety reconciliation.
remote_text = read(remote_alarm)
if "import threading" not in remote_text:
    remote_text = remote_text.replace("from datetime import datetime\n", "from datetime import datetime\nimport threading\n", 1)
if "_REMOTE_ALARM_SCHEMA_LOCK" not in remote_text:
    marker = "from .security import SecurityStore, UserIdentity\n"
    remote_text = remote_text.replace(marker, marker + "\n\n_REMOTE_ALARM_SCHEMA_LOCK = threading.Lock()\n", 1)
write(remote_alarm, remote_text)

ensure = nested_function(production_revision, "_patch_alarm_mirror_and_control", "ensure_active_schema", rename="_ensure_active_schema")
ensure = ensure.replace("schema_lock", "_REMOTE_ALARM_SCHEMA_LOCK")
mirror = nested_function(production_revision, "_patch_alarm_mirror_and_control", "mirror").replace("ensure_active_schema(self)", "self._ensure_active_schema()")
row = nested_function(production_revision, "_patch_alarm_mirror_and_control", "row_to_dict", rename="_row")
list_alarms = nested_function(production_revision, "_patch_alarm_mirror_and_control", "list_alarms")
list_alarms = list_alarms.replace("ensure_active_schema(self)", "self._ensure_active_schema()").replace("row_to_dict(row)", "self._row(row)")
get = nested_function(production_revision, "_patch_alarm_mirror_and_control", "get")
get = get.replace("ensure_active_schema(self)", "self._ensure_active_schema()").replace("row_to_dict(row)", "self._row(row)")
mark_ack = nested_function(production_revision, "_patch_alarm_mirror_and_control", "mark_acknowledged")
mark_ack = mark_ack.replace("ensure_active_schema(self)", "self._ensure_active_schema()").replace("get(self,", "self.get(")
reconcile = nested_function(safety_revision, "_add_alarm_active_set_reconciliation", "reconcile_source_active_keys")
patch_class(
    remote_alarm,
    "RemoteAlarmMirror",
    {
        "_ensure_active_schema": ensure,
        "mirror": mirror,
        "_row": row,
        "list_alarms": list_alarms,
        "get": get,
        "mark_acknowledged": mark_ack,
        "reconcile_source_active_keys": reconcile,
    },
)
patch_class(
    remote_alarm,
    "AlarmControlService",
    {"ack": nested_function(production_revision, "_patch_alarm_mirror_and_control", "ack")},
)

# Explicit runtime authorization boundary: configured endpoints alone do not enable writes.
services_text = read(secure_services)
needle = "    user_admin = UserAdminService(security, audit)\n"
if needle not in services_text:
    raise RuntimeError("secure_services insertion point not found")
services_text = services_text.replace(
    needle,
    '''    user_admin = UserAdminService(security, audit)\n\n    device_admin.source_definitions = dict(sources)\n    if bool(getattr(settings, "lan_enabled", False)) and sources:\n        device_admin.write_through = True\n        device_admin.station_source = security.station_source\n\n        def remote_device_factory(source_id: str):\n            source = sources.get(str(source_id))\n            if source is None:\n                raise KeyError(f"LAN source tidak ditemukan: {source_id}")\n            return RemoteMariaDBSource(source)\n\n        device_admin.remote_factory = remote_device_factory\n    else:\n        device_admin.write_through = False\n        device_admin.station_source = None\n        device_admin.remote_factory = None\n''',
    1,
)
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

# Disable now-consolidated wrappers; Task 8/10/11 retain their still-needed patch calls.
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

# Remove all one-shot artifacts restored by the revert plus this fixed script/workflow.
for relative in (
    "scripts/refactor_task7.py",
    "scripts/refactor_task7_fixed.py",
    ".github/workflows/refactor-task7.yml",
    ".github/workflows/refactor-task7-retry.yml",
    ".github/workflows/refactor-task7-repair.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
