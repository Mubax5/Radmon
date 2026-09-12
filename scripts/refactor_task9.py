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


def class_method(path: Path, class_name: str, method_name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    node = copy.deepcopy(node)
    if rename:
        node.name = rename
    return ast.unparse(node).strip() + "\n"


def nested_function(path: Path, parent_name: str, nested_name: str, *, rename: str | None = None) -> str:
    tree = ast.parse(read(path))
    parent = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == parent_name)
    node = next(n for n in ast.walk(parent) if isinstance(n, ast.FunctionDef) and n.name == nested_name)
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
    edits: list[tuple[int, int, list[str]]] = []
    missing: list[str] = []
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


def add_top_level_block(path: Path, block: str, *, before_class: str) -> None:
    source = read(path)
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == before_class)
    lines = source.splitlines()
    lines[cls.lineno - 1:cls.lineno - 1] = textwrap.dedent(block).strip().splitlines() + [""]
    write(path, "\n".join(lines))


policy = ROOT / "radmon/alarm_policy.py"
store = ROOT / "radmon/alarm_policy_store.py"
security = ROOT / "radmon/security.py"
remote = ROOT / "radmon/remote_alarm.py"
lan = ROOT / "radmon/lan.py"
runtime = ROOT / "radmon/lan_runtime.py"
policy_rev = ROOT / "radmon/alarm_policy_revision.py"
store_rev = ROOT / "radmon/alarm_policy_store_revision.py"
runtime_rev = ROOT / "radmon/alarm_policy_runtime_revision.py"

# Transaction-safe suppression creation: read inserted row on the same SQLite
# transaction when the caller supplied a connection.
start_suppression = nested_function(store_rev, "apply", "start_suppression")
start_suppression = start_suppression.replace("module._iso", "_iso")
patch_class(store, "AlarmPolicyStore", {"start_suppression": start_suppression})

# Suppression permission belongs in the canonical role map.
sec = read(security)
sec = sec.replace(
    '"view", "ack_alarm", "manage_users", "edit_station", "manage_sources",',
    '"view", "ack_alarm", "suppress_alarm", "manage_users", "edit_station", "manage_sources",',
    1,
)
sec = sec.replace(
    'Role.OPERATOR: frozenset({"view", "ack_alarm"}),',
    'Role.OPERATOR: frozenset({"view", "ack_alarm", "suppress_alarm"}),',
    1,
)
write(security, sec)

# AlarmPolicy runtime behavior becomes direct class behavior. Keep the already
# tested core algorithms as private bases so the integration changes remain small.
base_snapshot = class_method(policy, "AlarmPolicyService", "_snapshot", rename="_snapshot_base")
base_get = class_method(policy, "AlarmPolicyService", "get_policy", rename="_get_policy_base")
base_list = class_method(policy, "AlarmPolicyService", "list_events", rename="_list_events_base")
base_cycle = class_method(policy, "AlarmPolicyService", "process_cycle", rename="_process_cycle_base")
base_observe = class_method(policy, "AlarmPolicyService", "observe_source_alarm", rename="_observe_source_alarm_base")

snapshot = '''
def _snapshot(self, tx, *, underlying, measured_value=None, threshold=None, active_event_id=None):
    snapshot = self._snapshot_base(
        tx,
        underlying=underlying,
        measured_value=measured_value,
        threshold=threshold,
        active_event_id=active_event_id,
    )
    cache = getattr(self, "_current_policy_snapshots", None)
    if cache is None:
        cache = {}
        self._current_policy_snapshots = cache
    copy = dict(snapshot)
    copy["updated_at"] = tx.state.updated_at or self.now()
    cache[int(snapshot["serid"])] = copy
    return snapshot
'''
get_policy = '''
def get_policy(self, serid):
    persistent = self._get_policy_base(serid)
    cache = getattr(self, "_current_policy_snapshots", {})
    live = dict(cache.get(int(serid), {}))
    result = dict(live)
    result.update(persistent)

    suppression = persistent.get("suppression") or {}
    underlying = live.get("underlying_dose_status")
    if not underlying:
        if persistent.get("active_event_id") or persistent.get("retrigger_locked"):
            underlying = "ALARM"
        else:
            underlying = "UNKNOWN"

    if persistent.get("suppressed"):
        policy_state = "SUPPRESSED"
    elif persistent.get("retrigger_locked") and underlying == "ALARM":
        policy_state = "RETRIGGER_LOCKED"
    elif persistent.get("active_event_id"):
        policy_state = "ALARM"
    elif underlying in {"NORMAL", "ALERT", "ALARM"}:
        policy_state = underlying
    else:
        policy_state = "NORMAL"

    result.update({
        "policy_state": policy_state,
        "underlying_dose_status": underlying,
        "measured_value": live.get("measured_value"),
        "threshold": live.get("threshold"),
        "suppression_id": suppression.get("suppression_id"),
        "suppression_expires_at": suppression.get("expires_at"),
        "suppression_pic": suppression.get("pic"),
        "suppression_reason": suppression.get("reason"),
        "updated_at": live.get("updated_at") or persistent.get("last_trigger_at") or persistent.get("last_normal_at"),
    })
    return result
'''
list_events = '''
def list_events(self, *, serid=None, active_only=False, notify_pending_only=False, limit=500):
    if notify_pending_only and not bool(getattr(self, "notifications_enabled", True)):
        return []
    return self._list_events_base(
        serid=serid,
        active_only=active_only,
        notify_pending_only=notify_pending_only,
        limit=limit,
    )
'''
process_cycle = '''
def process_cycle(self, source_id, live_rows, alarm_rows):
    events = self._process_cycle_base(source_id, live_rows, alarm_rows)
    self.notifications_enabled = True
    return events
'''
observe = '''
def observe_source_alarm(self, source_id: str, row: dict[str, Any]):
    result = self._observe_source_alarm_base(source_id, row)
    if bool(row.get("_historical_seed")):
        return result
    decision = str(result.get("decision") or "")
    if decision not in {"SUPPRESSED", "RETRIGGER_LOCKED", "COALESCED_DUPLICATE"}:
        return result
    event_time = self._measurement_time(row)
    suppression = self.store.active_suppression(int(row["serid"]))
    policy_event_id = result.get("policy_event_id")
    if policy_event_id is None and suppression is not None:
        for item in self.store.list_policy_events(serid=int(row["serid"]), limit=50):
            if item.kind == "SUPPRESSED" and item.suppression_id == suppression.suppression_id:
                policy_event_id = item.event_id
                break
    self.store.annotate_raw_alarm(
        source_id,
        int(row["serid"]),
        event_time,
        policy_decision=decision,
        suppression_id=suppression.suppression_id if suppression else None,
        operator_visible=False,
        policy_event_id=policy_event_id,
        source_silence_state="PENDING",
        source_silence_retry_at=self.now(),
    )
    result["policy_event_id"] = policy_event_id
    return result
'''
patch_class(policy, "AlarmPolicyService", {
    "_snapshot_base": base_snapshot,
    "_snapshot": snapshot,
    "_get_policy_base": base_get,
    "get_policy": get_policy,
    "_list_events_base": base_list,
    "list_events": list_events,
    "_process_cycle_base": base_cycle,
    "process_cycle": process_cycle,
    "_observe_source_alarm_base": base_observe,
    "observe_source_alarm": observe,
})

# Alarm mirror/control policy helpers become normal methods.
remote_text = read(remote)
remote_text = remote_text.replace("from dataclasses import", "from dataclasses import", 1) if "from dataclasses import" in remote_text else remote_text
if "from dataclasses import asdict\n" not in remote_text:
    remote_text = remote_text.replace("from __future__ import annotations\n\n", "from __future__ import annotations\n\nfrom dataclasses import asdict\n", 1)
if "from datetime import datetime, timedelta\n" not in remote_text:
    remote_text = remote_text.replace("from datetime import datetime\n", "from datetime import datetime, timedelta\n", 1)
write(remote, remote_text)
mirror_helpers = {
    "_policy_store": '''
def _policy_store(self):
    from .alarm_policy_store import AlarmPolicyStore
    store = getattr(self, "policy_store", None)
    if store is None:
        store = AlarmPolicyStore(self.store)
        self.policy_store = store
    return store
''',
    "annotate_policy": '''
def annotate_policy(self, source_id, serid, event_time, **kwargs):
    return self._policy_store().annotate_raw_alarm(source_id, serid, event_time, **kwargs)
''',
    "pending_source_silences": '''
def pending_source_silences(self, source_id=None, *, at=None, limit=25):
    return self._policy_store().pending_source_silences(source_id, at=at, limit=limit)
''',
    "mark_source_silence_result": '''
def mark_source_silence_result(self, source_id, serid, event_time, *, state, retry_at=None):
    return self._policy_store().mark_source_silence_result(
        source_id, serid, event_time, state=state, retry_at=retry_at
    )
''',
}
patch_class(remote, "RemoteAlarmMirror", mirror_helpers)
control_helpers = {
    "_policy_store": '''
def _policy_store(self):
    from .alarm_policy_store import AlarmPolicyStore
    store = getattr(self, "policy_store", None)
    if store is None:
        store = AlarmPolicyStore(self.security)
        self.policy_store = store
    return store
''',
    "silence_source_row": '''
def silence_source_row(self, source_id: str, serid: int, event_time: datetime, *, action: str, pic: str, reason: str) -> bool:
    remote = self.remote_factory(str(source_id))
    responder = getattr(remote, "respond_alarm", None)
    if not callable(responder):
        raise RuntimeError("source tidak mendukung alarm response")
    at = self.now()
    return bool(responder(int(serid), event_time, action=action, pic=pic, note=reason, at=at))
''',
    "respond_policy_event": '''
def respond_policy_event(self, identity, pin: str, event_id: str, *, action: str, pic: str, reason: str):
    self.security.require_sensitive(identity, "ack_alarm", pin)
    action_text = str(action or "").strip()
    pic_text = str(pic or "").strip()
    reason_text = str(reason or "").strip()
    if not action_text or not pic_text:
        raise ValueError("Action dan PIC wajib diisi")
    store = self._policy_store()
    event = store.get_event(str(event_id))
    if event is None:
        raise RuntimeError("policy event tidak ditemukan")
    if event.status != "ACTIVE":
        raise RuntimeError("policy event sudah ditangani")
    at = self.now()
    with self.security._connection() as db:
        rows = db.execute(
            """SELECT source_id, serid, remote_serid, event_time
               FROM remote_alarm_state
               WHERE policy_event_id=? ORDER BY event_time""",
            (str(event_id),),
        ).fetchall()
    for row in rows:
        source_id = str(row[0])
        central_serid = int(row[1])
        remote_serid = int(row[2]) if row[2] is not None else central_serid
        event_time = datetime.fromisoformat(str(row[3]))
        try:
            if not self.silence_source_row(
                source_id, remote_serid, event_time,
                action=action_text, pic=pic_text, reason=reason_text,
            ):
                raise RuntimeError("source menolak alarm response")
            store.mark_source_silence_result(source_id, central_serid, event_time, state="CONFIRMED")
        except Exception as exc:
            store.mark_source_silence_result(
                source_id, central_serid, event_time, state="FAILED",
                retry_at=at + timedelta(seconds=5),
            )
            self.audit.record(
                "ALARM_POLICY_SOURCE_RESPONSE", identity, "alarm", str(event_id),
                success=False, reason=str(exc), source=source_id,
            )
    policy = getattr(self, "policy", None)
    if policy is not None:
        responded = policy.mark_event_responded(str(event_id), at, pic_text, action_text, reason_text)
    else:
        responded = store.respond_event(str(event_id), at, pic_text, action_text, reason_text)
    self.audit.record(
        "ALARM_POLICY_RESPONSE", identity, "alarm", str(event_id),
        before=asdict(event), after=asdict(responded), source=event.source_id,
    )
    return asdict(responded)
''',
}
patch_class(remote, "AlarmControlService", control_helpers)

# Integrate bounded source-silence retry and policy evaluation directly in LAN.
lan_text = read(lan)
lan_text = lan_text.replace("from datetime import datetime\n", "from datetime import datetime, timedelta, timezone\n", 1)
write(lan, lan_text)
helper_tree = ast.parse(read(policy_rev))
helper_names = {"_SILENCE_DECISIONS", "_BACKOFF_SECONDS", "_utcnow", "_ensure_retry_column", "_pending_alarm_rows", "_mapped_live_rows", "_retry_source_silences"}
helper_nodes = []
for node in helper_tree.body:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        names = {t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)}
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        if names & helper_names:
            helper_nodes.append(node)
    elif isinstance(node, ast.FunctionDef) and node.name in helper_names:
        helper_nodes.append(node)
helper_block = "\n\n".join(ast.unparse(copy.deepcopy(node)) for node in helper_nodes)
add_top_level_block(lan, helper_block, before_class="LanSource")

base_live = class_method(lan, "LanAggregator", "run_live_once", rename="_run_live_policy_base_once")
final_live = '''
def run_live_once(self, source):
    result = self._run_live_policy_base_once(source)
    alarm_policy = getattr(self, "alarm_policy", None)
    if result.error or alarm_policy is None:
        return result
    try:
        mapped_live = _mapped_live_rows(self, source)
        mapped_alarms = _pending_alarm_rows(
            getattr(self, "alarm_mirror", None), source.source_id, limit=500
        )
        alarm_policy.process_cycle(source.source_id, mapped_live, mapped_alarms)
        _retry_source_silences(self, source, alarm_policy)
    except Exception as exc:
        result.error = str(exc)
    return result
'''
patch_class(lan, "LanAggregator", {
    "_run_live_policy_base_once": base_live,
    "run_live_once": final_live,
})

# Runtime aggregator owns the policy reference directly.
runtime_text = read(runtime)
old_runtime = '''    def _aggregator(self, batch_size: int | None = None) -> LanAggregator:
        return LanAggregator(
            self.central,
            self.checkpoints,
            remote_factory=lambda item: RemoteMariaDBSource(item),
            alarm_mirror=self.services.alarm_mirror,
            batch_size=self.batch_size if batch_size is None else max(1, int(batch_size)),
        )
'''
new_runtime = '''    def _aggregator(self, batch_size: int | None = None) -> LanAggregator:
        aggregator = LanAggregator(
            self.central,
            self.checkpoints,
            remote_factory=lambda item: RemoteMariaDBSource(item),
            alarm_mirror=self.services.alarm_mirror,
            batch_size=self.batch_size if batch_size is None else max(1, int(batch_size)),
        )
        aggregator.alarm_policy = getattr(self.services, "alarm_policy", None)
        return aggregator
'''
if old_runtime not in runtime_text:
    raise RuntimeError("LanRuntime._aggregator canonical block not found")
write(runtime, runtime_text.replace(old_runtime, new_runtime, 1))

# Remove package monkey-patch dispatch and revision files.
init = ROOT / "radmon/__init__.py"
init_text = read(init)
for revision in (
    "alarm_policy_revision",
    "alarm_policy_store_revision",
    "alarm_policy_security_revision",
    "alarm_policy_runtime_revision",
):
    pattern = rf"\n(?:#.*\n)*from \.{revision} import apply as _apply_{revision}\n_apply_{revision}\(\)\ndel _apply_{revision}\n"
    init_text, count = re.subn(pattern, "\n", init_text)
    if count != 1:
        # Comments between blocks can make the broad form too greedy; use exact fallback.
        exact = f"from .{revision} import apply as _apply_{revision}\n_apply_{revision}()\ndel _apply_{revision}\n"
        if exact not in init_text:
            raise RuntimeError(f"apply block missing: {revision}")
        init_text = init_text.replace(exact, "", 1)
write(init, init_text)
for name in (
    "alarm_policy_revision.py",
    "alarm_policy_store_revision.py",
    "alarm_policy_security_revision.py",
    "alarm_policy_runtime_revision.py",
):
    (ROOT / "radmon" / name).unlink()

# Remove one-shot artifacts.
Path(__file__).unlink()
wf = ROOT / ".github/workflows/refactor-task9.yml"
if wf.exists():
    wf.unlink()
