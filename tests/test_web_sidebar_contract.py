"""Contract test untuk sidebar desktop + RBAC/error alarms UI.

Mengunci perbaikan Luna:
- Tombol collapse sidebar ada di atas (header), bukan footer.
- Rel collapse tidak me-reflow teks di tengah animasi (anti-flicker).
- RBAC operator/admin + error 401/403/409 tampil jelas (detail backend).
- Respons alarm & cancel suppression real ke API (bukan dummy).
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_sidebar_collapse_trigger_lives_in_header_not_footer():
    desktop = read("layout/DesktopShell.tsx")
    header = desktop.split("<Sidebar.Header", 1)[1].split("</Sidebar.Header>", 1)[0]
    footer = desktop.split("<Sidebar.Footer>", 1)[1].split("</Sidebar.Footer>", 1)[0]
    assert "<Sidebar.Trigger" in header, "tombol collapse wajib di atas (header)"
    assert "<Sidebar.Trigger" not in footer, "tombol collapse tidak boleh di footer"
    assert "sidebar-collapse-button" in header


def test_sidebar_collapsed_rail_hides_wide_content_without_removing_trigger():
    desktop = read("layout/DesktopShell.tsx")
    css = read("radmon.css") + "\n" + read("radmon-overlays.css") + "\n" + read("ui-polish.css")
    # Trigger tetap mounted di kedua state agar rail 57px bisa dibuka lagi.
    assert desktop.count("<Sidebar.Trigger") == 1
    # State collapse Kumo: data-state="collapsed" pada .group/sidebar.
    assert '.group\\/sidebar[data-state="collapsed"]' in css
    assert ".sidebar-logo" in css
    # Logo + teks akun disembunyikan seketika saat collapse agar transisi
    # width tidak me-reflow teks (anti-flicker).
    collapsed_rules = [
        block for block in css.split("}") if '[data-state="collapsed"]' in block
    ]
    joined = "}".join(collapsed_rules)
    assert ".sidebar-logo" in joined
    assert ".account-card" in joined
    assert "display: none" in joined
    # Footer memakai state sidebar: teks akun hanya saat expanded,
    # tombol ikon saat collapsed.
    assert "useSidebar" in desktop
    assert "account-card-collapsed" in desktop
    assert 'aria-label="Keluar"' in desktop


def test_alarm_routes_require_operator_and_admin_routes_require_administrator():
    navigation = read("navigation.ts")
    assert '{ id: "alarms", label: "Alarm", minimum: "Operator" }' in navigation
    assert '{ id: "users", label: "Pengguna", minimum: "Administrator" }' in navigation
    assert '{ id: "system", label: "Sistem", minimum: "Administrator" }' in navigation
    # Route di luar role jatuh kembali ke overview, bukan blank.
    layout = read("layout.tsx")
    assert 'return allowed ? route : "overview"' in layout


def test_api_errors_surface_backend_detail_for_401_403_409():
    api = read("api.ts")
    # Detail backend (mis. "operator permission required", 409 konflik)
    # diteruskan ke ErrorCard/Feedback, bukan status generik.
    assert "payload.detail" in api
    assert "radmon:session-expired" in api
    alarms = read("pages/AlarmsPage.tsx")
    assert "<ErrorCard message={error} />" in alarms
    assert "<ErrorCard message={`Data alarm mungkin usang: ${error}`} />" in alarms
    actions = read("Actions.tsx")
    assert "error instanceof Error ? error.message" in actions


def test_alarm_response_posts_pin_to_real_event_endpoint():
    actions = read("Actions.tsx")
    assert "/api/v1/control/alarm-events/${encodeURIComponent(selectedEventId)}/response" in actions
    assert '"pin, action, pic, reason"' in actions or "{ pin, action, pic, reason }" in actions
    # Tombol kirim terkunci sampai event + PIC + alasan + PIN terisi.
    assert "!selectedEventId || !pic || !reason || !pin" in actions


def test_suppression_cancel_is_real_api_call_with_pin_and_reason():
    actions = read("Actions.tsx")
    assert "/api/v1/control/suppressions/${encodeURIComponent(item.suppression_id)}/cancel" in actions
    assert "{ pin: cancelPin, reason: cancelReason }" in actions
    # Bukan dummy: state dibersihkan, list dimuat ulang, sukses dilaporkan.
    assert 'setCancelOpen("")' in actions
    assert "onChanged()" in actions
    assert "Suppression stasiun" in actions and "diakhiri" in actions
