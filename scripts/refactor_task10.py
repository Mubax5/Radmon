from __future__ import annotations

import ast
import copy
from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def function_source(path: Path, name: str, *, parent: str | None = None, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    scope = tree.body
    if parent is not None:
        owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == parent)
        scope = list(ast.walk(owner))
    node = next(node for node in scope if isinstance(node, ast.FunctionDef) and node.name == name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def class_method_source(path: Path, class_name: str, name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node = next(node for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def nested_source(path: Path, outer: str, name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    owner = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == outer)
    node = next(node for node in ast.walk(owner) if isinstance(node, ast.FunctionDef) and node.name == name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def patch_top_function(path: Path, name: str, replacement: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    node = next(node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    lines = source.splitlines()
    start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
    lines[start:node.end_lineno] = textwrap.dedent(replacement).strip().splitlines()
    write(path, "\n".join(lines))


def rename_top_and_add(path: Path, name: str, private_name: str, wrapper: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name)
    lines = source.splitlines()
    original = lines[node.lineno - 1:node.end_lineno]
    original[0] = original[0].replace(f"def {name}(", f"def {private_name}(", 1)
    rendered = original + [""] + textwrap.dedent(wrapper).strip().splitlines()
    lines[node.lineno - 1:node.end_lineno] = rendered
    write(path, "\n".join(lines))


def patch_class(path: Path, class_name: str, replacements: dict[str, str], additions: list[str] | None = None) -> None:
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
    for name, replacement in replacements.items():
        node = existing[name]
        start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
        rendered = textwrap.indent(textwrap.dedent(replacement).strip(), "    ").splitlines()
        edits.append((start, node.end_lineno, rendered))
    if additions:
        rendered: list[str] = []
        for addition in additions:
            rendered += [""] + textwrap.indent(textwrap.dedent(addition).strip(), "    ").splitlines()
        edits.append((cls.end_lineno, cls.end_lineno, rendered))
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        lines[start:end] = replacement
    write(path, "\n".join(lines))


def rename_class_methods_and_add(path: Path, class_name: str, renames: dict[str, str], additions: list[str]) -> None:
    source = read(path)
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    lines = source.splitlines()
    edits: list[tuple[int, int, list[str]]] = []
    for old, new in renames.items():
        node = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == old)
        start = min([node.lineno] + [item.lineno for item in node.decorator_list]) - 1
        block = lines[start:node.end_lineno]
        def_index = next(i for i, line in enumerate(block) if line.lstrip().startswith(f"def {old}(") or line.lstrip().startswith(f"async def {old}(") )
        block[def_index] = block[def_index].replace(f"def {old}(", f"def {new}(", 1)
        edits.append((start, node.end_lineno, block))
    rendered: list[str] = []
    for addition in additions:
        rendered += [""] + textwrap.indent(textwrap.dedent(addition).strip(), "    ").splitlines()
    edits.append((cls.end_lineno, cls.end_lineno, rendered))
    for start, end, replacement in sorted(edits, key=lambda item: item[0], reverse=True):
        lines[start:end] = replacement
    write(path, "\n".join(lines))


# ---------------------------------------------------------------------------
# Grafana bootstrap: keep the old ensure implementation as a private fallback,
# and make the reprovision-on-ready behavior the canonical public method.
# ---------------------------------------------------------------------------
bootstrap = ROOT / "radmon/grafana_bootstrap.py"
bootstrap_revision = ROOT / "radmon/grafana_bootstrap_revision.py"
base_ensure = class_method_source(bootstrap, "GrafanaBootstrap", "ensure", rename="_ensure_base")
final_ensure = nested_source(bootstrap_revision, "apply", "ensure")
final_ensure = final_ensure.replace("return original_ensure(self)", "return self._ensure_base()")
patch_class(
    bootstrap,
    "GrafanaBootstrap",
    {"ensure": base_ensure},
    additions=[final_ensure],
)


# ---------------------------------------------------------------------------
# Grafana TV: materialize the final function set in exactly the same order that
# the runtime revisions previously applied it.
# ---------------------------------------------------------------------------
tv = ROOT / "radmon/grafana_tv.py"
grafana_revision = ROOT / "radmon/grafana_revision.py"
wib_revision = ROOT / "radmon/grafana_wib_revision.py"
policy_revision = ROOT / "radmon/grafana_policy_revision.py"
production_revision = ROOT / "radmon/production_integration_revision.py"

for function_name, revision_path, outer_name, nested_name in (
    ("_header_panels", grafana_revision, "apply", "header_panels"),
    ("_latest_relation", grafana_revision, "apply", "latest_relation"),
    ("_dose_sparkline", wib_revision, "apply", "dose_sparkline"),
    ("_time_stat", wib_revision, "apply", "time_stat"),
    ("_building_trend", wib_revision, "apply", "building_trend"),
    ("_status_relation", policy_revision, "apply", "status_relation"),
    ("_operation_table", policy_revision, "apply", "operation_table"),
):
    source = nested_source(revision_path, outer_name, nested_name, rename=function_name).replace("tv.", "")
    patch_top_function(tv, function_name, source)

dose_stat = nested_source(production_revision, "_patch_grafana", "dose_stat", rename="_dose_stat").replace("tv.", "")
patch_top_function(tv, "_dose_stat", dose_stat)

helpers = """
def _utc_epoch_sql(column: str) -> str:
    return (
        "TIMESTAMPDIFF(SECOND, '1970-01-01 00:00:00', "
        f"CONVERT_TZ({column}, '+07:00', '+00:00'))"
    )


def _utc_epoch_ms_sql(column: str) -> str:
    return (
        "TIMESTAMPDIFF(MICROSECOND, '1970-01-01 00:00:00', "
        f"CONVERT_TZ({column}, '+07:00', '+00:00')) / 1000"
    )
"""
tv_text = read(tv)
if "def _utc_epoch_sql(" not in tv_text:
    marker = "\ndef _dose_sparkline("
    tv_text = tv_text.replace(marker, "\n" + textwrap.dedent(helpers).strip() + "\n\n\ndef _dose_sparkline(", 1)
    write(tv, tv_text)

final_page_three = '''
def build_page_three(page_number: int = 1) -> dict[str, Any]:
    dashboard = _build_page_three_base(page_number)
    status_panel = next(
        panel for panel in dashboard["panels"]
        if panel.get("title") == "Status Detector"
    )
    operations_panel = next(
        panel for panel in dashboard["panels"]
        if panel.get("description") == "operational-condition"
    )
    status_panel["gridPos"]["w"] = 12
    operations_panel["gridPos"]["x"] = 12
    operations_panel["gridPos"]["w"] = 12
    status_panel["options"]["displayLabels"] = ["name", "value"]
    status_panel["options"]["legend"].update(
        {"displayMode": "table", "placement": "bottom", "showLegend": True, "values": ["value"]}
    )

    alarms = next(
        panel for panel in dashboard["panels"]
        if panel.get("title") == "Alarm Terbaru · 24 Jam"
    )
    wib_now = "CONVERT_TZ(UTC_TIMESTAMP(), '+00:00', '+07:00')"
    alarms["targets"] = [_target(f"""
SELECT
  DATE_FORMAT(a.dtoa, '%Y-%m-%d %H:%i:%s') AS `Waktu`,
  a.serid AS `ID`,
  d.name AS `Ruangan`,
  d.location AS `Lokasi`,
  CASE WHEN a.lvl >= 2 THEN 'ALARM' ELSE 'ALERT' END AS `Status`,
  ROUND(a.mvalue, 3) AS `Dose Rate`,
  ROUND(a.thvalue, 3) AS `Threshold`,
  a.nhit AS `Hit Count`,
  DATE_FORMAT(a.i_op, '%Y-%m-%d %H:%i:%s') AS `Action Time`,
  COALESCE(a.pic, '') AS `PIC`,
  COALESCE(a.note, '') AS `Note`
FROM alarm a
LEFT JOIN device d ON d.serid = a.serid
WHERE a.serid IN ({_station_ids()})
  AND a.dtoa >= DATE_SUB({wib_now}, INTERVAL 24 HOUR)
ORDER BY a.dtoa DESC, a.serid
LIMIT 12
""")]
    return dashboard
'''
rename_top_and_add(tv, "build_page_three", "_build_page_three_base", final_page_three)


# ---------------------------------------------------------------------------
# PIN lease behavior belongs directly to PinDialog.
# ---------------------------------------------------------------------------
auth = ROOT / "radmon/admin/auth_dialogs.py"
auth_text = read(auth)
if "from ..secure_context import get_context" not in auth_text:
    auth_text = auth_text.replace(
        "from ..security import Role, SecurityStore, UserIdentity\n",
        "from ..secure_context import get_context\nfrom ..security import Role, SecurityStore, UserIdentity\n",
        1,
    )
    write(auth, auth_text)
base_get_pin = class_method_source(auth, "PinDialog", "get_pin", rename="_get_pin_base")
final_get_pin = '''
@classmethod
def get_pin(cls, parent=None, *, title: str = "PIN", message: str = "Masukkan PIN untuk melanjutkan") -> tuple[str, bool]:
    context = get_context()
    security = getattr(getattr(context, "device_admin", None), "security", None)
    identity = getattr(context, "identity", None)
    if security is not None and identity is not None:
        try:
            if security.sensitive_lease_active(identity):
                return "", True
        except Exception:
            pass
    return cls._get_pin_base(parent, title=title, message=message)
'''
patch_class(auth, "PinDialog", {"get_pin": base_get_pin}, additions=[final_get_pin])


# ---------------------------------------------------------------------------
# Admin main window: make source grouping, health refresh, manual paths, alarm
# beep and semantic icons normal class behavior instead of runtime wrappers.
# ---------------------------------------------------------------------------
main_window = ROOT / "radmon/admin/main_window.py"
main_text = read(main_window)
main_text = main_text.replace("import threading\n", "import threading\nimport time\n", 1)
main_text = main_text.replace(
    "    QFileDialog,\n",
    "    QApplication,\n    QFileDialog,\n",
    1,
)
if "from ..paths import ApplicationPaths" not in main_text:
    main_text = main_text.replace(
        "from ..grafana_bootstrap import GrafanaBootstrap\n",
        "from ..grafana_bootstrap import GrafanaBootstrap\nfrom ..paths import ApplicationPaths\n",
        1,
    )
constants = '''
INSTALLATION_MANUAL_PATH = "docs/manual/installation.html"
USER_MANUAL_PATH = "docs/manual/user-manual.html"


def group_stations_by_source(stations, station_source_by_serid, sources, health_by_source):
    groups = []
    for source_id, source in sources.items():
        members = [
            station for station in stations
            if station_source_by_serid.get(int(station.serid)) == source_id
        ]
        groups.append({
            "source_id": source_id,
            "host": str(getattr(source, "host", "")),
            "state": str(health_by_source.get(source_id, "UNKNOWN")),
            "stations": members,
        })
    return groups


def _source_label(source_id: str) -> str:
    text = str(source_id)
    lower = text.lower()
    if lower.startswith("gd") and lower[2:].isdigit():
        return f"Gd.{lower[2:]}"
    return text


def _source_health_map() -> dict[str, str]:
    context = get_context()
    if context is None:
        return {}
    try:
        return {
            str(row["source_id"]): str(row.get("state") or "UNKNOWN")
            for row in context.source_health.list_states()
        }
    except Exception:
        return {}
'''
if "INSTALLATION_MANUAL_PATH =" not in main_text:
    marker = "\ndef open_external_url("
    main_text = main_text.replace(marker, "\n" + textwrap.dedent(constants).strip() + "\n\n\ndef open_external_url(", 1)
write(main_window, main_text)

reload_station_sidebar = '''
def reload_station_sidebar(self, *, select_serid: int | None = None) -> None:
    context = get_context()
    source_definitions = dict(
        getattr(getattr(context, "device_admin", None), "source_definitions", {})
        if context is not None else {}
    )
    if self.source != "lan" or not source_definitions:
        return self._reload_station_sidebar_base(select_serid=select_serid)

    expanded: dict[str, bool] = {}
    old_root = self.station_tree.topLevelItem(0)
    if old_root is not None:
        for index in range(old_root.childCount()):
            item = old_root.child(index)
            sid = item.data(0, Qt.UserRole + 1)
            if sid:
                expanded[str(sid)] = item.isExpanded()

    self.station_tree.blockSignals(True)
    self.station_tree.clear()
    root = QTreeWidgetItem(self.station_tree, ["Station"])
    root.setIcon(0, app_icon("station_group"))
    root.setExpanded(True)
    selected_item = None
    try:
        stations = list(self.repository.station_configs())
        mapping = context.device_admin.security.station_source_map()
        groups = group_stations_by_source(
            stations, mapping, source_definitions, _source_health_map()
        )
    except Exception as exc:
        self.statusBar().showMessage(f"Station list error: {exc}")
        groups = []

    for group in groups:
        sid = str(group["source_id"])
        state = str(group["state"])
        host = str(group["host"])
        parent = QTreeWidgetItem(root, [f"Server {_source_label(sid)} · {host} [{state}]"])
        parent.setIcon(0, app_icon("station_group"))
        parent.setData(0, Qt.UserRole + 1, sid)
        parent.setToolTip(0, f"source={sid} · host={host} · state={state}")
        parent.setExpanded(expanded.get(sid, True))
        for station in group["stations"]:
            child = QTreeWidgetItem(parent, [f"[{station.serid}] {station.room}"])
            child.setIcon(0, app_icon("detector"))
            child.setData(0, Qt.UserRole, station.serid)
            child.setToolTip(
                0,
                f"[{station.serid}] {station.room} ({station.location}) · "
                f"Alert {station.warnlevel:g} {station.unit}, "
                f"Alarm {station.alarmlevel:g} {station.unit}",
            )
            if select_serid is not None and int(station.serid) == int(select_serid):
                selected_item = child

    if selected_item is None:
        for index in range(root.childCount()):
            parent = root.child(index)
            if parent.childCount():
                selected_item = parent.child(0)
                break
    self.station_tree.blockSignals(False)
    if selected_item is not None:
        self.station_tree.setCurrentItem(selected_item)
        self._station_changed(selected_item)
'''

select_station = '''
def _select_station_from_recent(self, serid: int) -> None:
    if self.source != "lan":
        return self._select_station_from_recent_base(serid)
    root = self.station_tree.topLevelItem(0)
    if root is None:
        return
    for group_index in range(root.childCount()):
        parent = root.child(group_index)
        for index in range(parent.childCount()):
            item = parent.child(index)
            if int(item.data(0, Qt.UserRole) or 0) == int(serid):
                parent.setExpanded(True)
                self.station_tree.setCurrentItem(item)
                return
'''

refresh_parent = '''
def _refresh_source_parent_states(self) -> None:
    if self.source != "lan":
        return
    states = _source_health_map()
    context = get_context()
    sources = dict(
        getattr(getattr(context, "device_admin", None), "source_definitions", {})
        if context is not None else {}
    )
    root = self.station_tree.topLevelItem(0)
    if root is None:
        return
    for index in range(root.childCount()):
        parent = root.child(index)
        sid = parent.data(0, Qt.UserRole + 1)
        if not sid:
            continue
        source = sources.get(str(sid))
        host = str(getattr(source, "host", ""))
        state = states.get(str(sid), "UNKNOWN")
        parent.setText(0, f"Server {_source_label(str(sid))} · {host} [{state}]")
'''

refresh_all = '''
def refresh_all(self) -> None:
    current_serid = getattr(self.settings, "serid", None)
    self.reload_station_sidebar(select_serid=current_serid)
    self._refresh_source_parent_states()
    self.refresh_current_page()
    context = get_context()
    if context is not None and hasattr(self.recent_page, "set_message_rows"):
        try:
            messages = []
            for item in context.source_health.list_states():
                state = str(item.get("state") or "UNKNOWN")
                message = f"[SERVER {state}] {item.get('source_id')} / {item.get('host')}"
                if item.get("last_error") and state in {"DEGRADED", "OFFLINE"}:
                    message += f" - {item.get('last_error')}"
                messages.append((item.get("updated_at") or "", message))
            self.recent_page.set_message_rows(messages)
        except Exception:
            pass
'''

build_actions = '''
def _build_actions(self) -> None:
    self._build_actions_base()
    try:
        self.refresh_action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    self.refresh_action.triggered.connect(self.refresh_all)
    try:
        self.install_manual_action.triggered.disconnect()
        self.user_manual_action.triggered.disconnect()
    except (RuntimeError, TypeError):
        pass
    self.install_manual_action.triggered.connect(
        lambda: self._open_manual(INSTALLATION_MANUAL_PATH)
    )
    self.user_manual_action.triggered.connect(
        lambda: self._open_manual(USER_MANUAL_PATH)
    )
'''

open_manual = '''
def _open_manual(self, relative_path: str) -> None:
    path = (ApplicationPaths.discover().app_dir / relative_path).resolve()
    if not path.is_file():
        QMessageBox.information(self, "Manual", f"Manual belum tersedia: {relative_path}")
        return
    url = QUrl.fromLocalFile(str(path)).toString()
    if not open_external_url(url):
        QMessageBox.warning(self, "Manual", f"Gagal membuka manual di browser: {path}")
'''

refresh_current = '''
def refresh_current_page(self) -> None:
    self._refresh_current_page_base()
    self._refresh_source_parent_states()
    context = get_context()
    if context is None:
        return
    try:
        active = context.alarm_mirror.list_alarms(active_only=True, limit=1)
    except Exception:
        active = []
    if active:
        now = time.monotonic()
        last = float(getattr(self, "_last_alarm_beep", 0.0))
        if now - last >= 1.5:
            QApplication.beep()
            self._last_alarm_beep = now
'''

rename_class_methods_and_add(
    main_window,
    "MainWindow",
    {
        "reload_station_sidebar": "_reload_station_sidebar_base",
        "_select_station_from_recent": "_select_station_from_recent_base",
        "_build_actions": "_build_actions_base",
        "refresh_current_page": "_refresh_current_page_base",
    },
    [
        reload_station_sidebar,
        select_station,
        refresh_parent,
        refresh_all,
        build_actions,
        refresh_current,
    ],
)
patch_class(main_window, "MainWindow", {"_open_manual": open_manual})


# Alarm UI wording/focus is now direct behavior.
alarm_page = ROOT / "radmon/admin/alarm_page.py"
alarm_text = read(alarm_page)
alarm_text = alarm_text.replace(
    'self.ack_button = QPushButton(app_icon("alarm"), "ACK / Response")',
    'self.ack_button = QPushButton(app_icon("alarm"), "Response / Silence")\n        self.ack_button.setToolTip("Isi Action/PIC/Note lalu submit untuk set i_flag=1 pada source.")',
    1,
)
write(alarm_page, alarm_text)

response_dialog = ROOT / "radmon/admin/alarm_response_dialog.py"
response_text = read(response_dialog)
response_text = response_text.replace('self.setWindowTitle("Response to Alarm")', 'self.setWindowTitle("Alarm Response / Silence")', 1)
response_text = response_text.replace(
    'self.pic = QLineEdit()\n',
    'self.pic = QLineEdit()\n        self.pic.returnPressed.connect(self.accept)\n',
    1,
)
response_text = response_text.replace(
    'buttons.accepted.connect(self.accept)\n        buttons.rejected.connect(self.reject)\n',
    'button = buttons.button(QDialogButtonBox.Ok)\n        if button is not None:\n            button.setText("Submit / Silence")\n            button.setDefault(True)\n        buttons.accepted.connect(self.accept)\n        buttons.rejected.connect(self.reject)\n',
    1,
)
write(response_dialog, response_text)


# Package initialization must be side-effect free.
write(ROOT / "radmon/__init__.py", '"""Python-first radiation monitoring components for DPFK."""\n\n__version__ = "0.1.0"\n')


# Remove every now-consolidated runtime revision.
for relative in (
    "radmon/grafana_bootstrap_revision.py",
    "radmon/grafana_policy_revision.py",
    "radmon/grafana_revision.py",
    "radmon/grafana_wib_revision.py",
    "radmon/icon_system_revision.py",
    "radmon/production_integration_revision.py",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()

# One-shot tooling removes itself from the final branch.
for relative in (
    "scripts/refactor_task10.py",
    ".github/workflows/refactor-task10.yml",
):
    path = ROOT / relative
    if path.exists():
        path.unlink()
