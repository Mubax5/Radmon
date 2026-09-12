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
    parent = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == parent_name)
    node = next(n for n in ast.walk(parent) if isinstance(n, ast.FunctionDef) and n.name == nested_name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def class_method(path: Path, class_name: str, method_name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def patch_class(path: Path, class_name: str, methods: dict[str, str]) -> None:
    source = read(path)
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    existing = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines()
    edits = []
    missing = []
    for name, method in methods.items():
        rendered = textwrap.indent(textwrap.dedent(method).strip(), "    ").splitlines()
        node = existing.get(name)
        if node is None:
            missing.extend([""] + rendered)
        else:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
            edits.append((start, node.end_lineno, rendered))
    if missing:
        edits.append((cls.end_lineno, cls.end_lineno, missing))
    for start, end, replacement in sorted(edits, key=lambda x: x[0], reverse=True):
        lines[start:end] = replacement
    write(path, "\n".join(lines))


prod = ROOT / "radmon/production_integration_revision.py"
compat = ROOT / "radmon/production_integration_compat_revision.py"
security = ROOT / "radmon/security.py"
lan = ROOT / "radmon/lan.py"
device = ROOT / "radmon/device_admin.py"
remote = ROOT / "radmon/remote_alarm.py"
dialog = ROOT / "radmon/admin/station_admin_dialog.py"

# SecurityStore: keep original implementations as private bases, expose final direct wrappers.
sec_text = read(security)
if "import threading\n" not in sec_text:
    sec_text = sec_text.replace("import sqlite3\n", "import sqlite3\nimport threading\n", 1)
write(security, sec_text)

base_init = class_method(security, "SecurityStore", "__init__", rename="_init_base")
base_enabled = class_method(security, "SecurityStore", "set_user_enabled", rename="_set_user_enabled_base")
base_pin = class_method(security, "SecurityStore", "reset_pin", rename="_reset_pin_base")
base_revoke = class_method(security, "SecurityStore", "revoke_session", rename="_revoke_session_base")

sensitive_active = nested_function(prod, "_patch_security", "sensitive_lease_active")
clear_lease = nested_function(prod, "_patch_security", "clear_sensitive_lease")
station_source = nested_function(prod, "_patch_security", "station_source")
station_map = nested_function(prod, "_patch_security", "station_source_map")
require_sensitive = nested_function(compat, "_patch_sensitive_pin_semantics", "require_sensitive")
require_sensitive = require_sensitive.replace("module.SecurityError", "SecurityError")

init_wrapper = '''
def __init__(self, path: Path | str, *, now: Callable[[], datetime] | None = None) -> None:
    self._init_base(path, now=now)
    self._sensitive_leases: dict[str, datetime] = {}
    self._sensitive_lease_lock = threading.Lock()
'''
enabled_wrapper = '''
def set_user_enabled(self, username: str, enabled: bool) -> None:
    self._set_user_enabled_base(username, enabled)
    if not enabled:
        self.clear_sensitive_lease(username)
'''
pin_wrapper = '''
def reset_pin(self, username: str, pin: str) -> None:
    self._reset_pin_base(username, pin)
    self.clear_sensitive_lease(username)
'''
revoke_wrapper = '''
def revoke_session(self, token: str | None) -> None:
    identity = self.session_user(token) if token else None
    self._revoke_session_base(token)
    if identity is not None:
        self.clear_sensitive_lease(identity.username)
'''
patch_class(security, "SecurityStore", {
    "_init_base": base_init,
    "__init__": init_wrapper,
    "_set_user_enabled_base": base_enabled,
    "set_user_enabled": enabled_wrapper,
    "_reset_pin_base": base_pin,
    "reset_pin": pin_wrapper,
    "_revoke_session_base": base_revoke,
    "revoke_session": revoke_wrapper,
    "sensitive_lease_active": sensitive_active,
    "clear_sensitive_lease": clear_lease,
    "require_sensitive": require_sensitive,
    "station_source": station_source,
    "station_source_map": station_map,
})

# Remote source final production methods.
for method_name in ("get_device", "update_device", "respond_alarm", "alarm_states"):
    method = nested_function(prod, "_patch_remote_source", method_name)
    method = method.replace("editable", "LAN_EDITABLE_DEVICE_FIELDS")
    method = method.replace("get_device(self, serid)", "self.get_device(serid)")
    patch_class(lan, "RemoteMariaDBSource", {method_name: method})
lan_text = read(lan)
if "LAN_EDITABLE_DEVICE_FIELDS =" not in lan_text:
    marker = "LIVE_KEYS = ("
    idx = lan_text.index(marker)
    block = '''LAN_EDITABLE_DEVICE_FIELDS = {
    "name", "location", "description", "warnlevel", "alarmlevel",
    "maxidlemin", "unit", "audiopath",
}\n\n'''
    lan_text = lan_text[:idx] + block + lan_text[idx:]
# Old synthetic adapters do not have alarm_states; absence is not a production error.
lan_text = lan_text.replace(
    "state_rows = remote.alarm_states(2000)",
    "state_reader = getattr(remote, \"alarm_states\", None)\n            state_rows = state_reader(2000) if callable(state_reader) else []",
    1,
)
write(lan, lan_text)

# DeviceAdmin final constructor/write-through update.
base_dev_init = class_method(device, "DeviceAdminService", "__init__", rename="_init_base")
base_dev_update = class_method(device, "DeviceAdminService", "update_station", rename="_update_station_base")
final_dev_init = '''
def __init__(
    self,
    security,
    repository,
    audit,
    *,
    station_source=None,
    remote_factory=None,
    write_through: bool = False,
) -> None:
    self._init_base(security, repository, audit)
    self.station_source = station_source
    self.remote_factory = remote_factory
    self.write_through = bool(write_through)
    self.source_definitions: dict[str, Any] = {}
'''
final_dev_update = nested_function(prod, "_patch_device_admin", "update_station")
final_dev_update = final_dev_update.replace("original_update(self, identity, pin, serid, changes)", "self._update_station_base(identity, pin, serid, changes)")
final_dev_update = final_dev_update.replace("lan_fields", "LAN_EDITABLE_FIELDS")
device_text = read(device)
if "LAN_EDITABLE_FIELDS =" not in device_text:
    insert = '''\nLAN_EDITABLE_FIELDS = {
    "name", "location", "description", "warnlevel", "alarmlevel",
    "maxidlemin", "unit", "audiopath",
}\n'''
    first_class = device_text.index("class DeviceAdminService")
    device_text = device_text[:first_class] + insert + "\n" + device_text[first_class:]
write(device, device_text)
patch_class(device, "DeviceAdminService", {
    "_init_base": base_dev_init,
    "__init__": final_dev_init,
    "_update_station_base": base_dev_update,
    "update_station": final_dev_update,
})

# Alarm response compatibility becomes canonical, while production RemoteMariaDBSource
# remains restricted to respond_alarm()/i_flag and never ack=1 fallback.
ack = nested_function(compat, "_patch_alarm_control_adapter_compatibility", "ack")
ack = ack.replace(
    "self.security.require_sensitive(identity, 'ack_alarm', pin)",
    "from .lan import RemoteMariaDBSource\n    self.security.require_sensitive(identity, 'ack_alarm', pin)",
    1,
)
patch_class(remote, "AlarmControlService", {"ack": ack})

# LAN identity fields are authoritative and read-only in the base dialog.
dialog_text = read(dialog)
needle = '        self.unit = QLineEdit(str(station.get("unit") or "µSv/h"))\n'
if needle not in dialog_text:
    raise RuntimeError("station dialog hardware insertion point missing")
replacement = needle + '''        if source == "lan":
            self.hw_type.setEnabled(False)
            self.hw_address.setEnabled(False)
            self.hw_type.setToolTip("Identity hardware dikelola oleh source LAN.")
            self.hw_address.setToolTip("Identity hardware dikelola oleh source LAN.")
'''
dialog_text = dialog_text.replace(needle, replacement, 1)
write(dialog, dialog_text)

# Disable the consolidated production wrappers; UI/Grafana remain for Tasks 10/11.
prod_text = read(prod)
for call in ("    _patch_security()\n", "    _patch_remote_source()\n", "    _patch_device_admin()\n"):
    if call not in prod_text:
        raise RuntimeError(f"missing patch call: {call.strip()}")
    prod_text = prod_text.replace(call, "", 1)
write(prod, prod_text)

# Compatibility module is now fully unnecessary.
init = ROOT / "radmon/__init__.py"
init_text = read(init)
pattern = r"\nfrom \.production_integration_compat_revision import apply as _apply_production_integration_compat_revision\n_apply_production_integration_compat_revision\(\)\ndel _apply_production_integration_compat_revision\n"
init_text, count = re.subn(pattern, "\n", init_text)
if count != 1:
    raise RuntimeError("compat apply block missing")
write(init, init_text)
compat.unlink()

# Remove one-shot artifacts.
Path(__file__).unlink()
wf = ROOT / ".github/workflows/refactor-task8.yml"
if wf.exists():
    wf.unlink()
