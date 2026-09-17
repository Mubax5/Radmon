"""Contract test bug 17 Sep 2026: modal "Respons alarm" 1 event tidak auto-select.

Regresi yang dikunci:
- Header "Event aktif (1)" benar tetapi kontrol harus native dan terikat ke
  satu-satunya event aktif, bukan bergantung pada binding Kumo Select.
- Action harus native dropdown preset (backend menerima string 1-128 char,
  jadi preset selalu valid).
- Modal harus backdrop semi-transparan + background tetap mounted/visible,
  dialog center z 90, Select portal z 100 (tidak ke-clip), Escape/backdrop
  tetap menutup kecuali sedang menyimpan.
- Respons tetap real POST /api/v1/control/alarm-events/{id}/response + PIN,
  cancel suppression real.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def read(path: str) -> str:
    return (WEB / path).read_text(encoding="utf-8")


def test_single_active_event_is_auto_selected():
    actions = read("Actions.tsx")
    # Pilihan basi dibersihkan saat live refresh menyelesaikan event terpilih.
    assert "active.some" in actions
    assert 'setEventId("")' in actions
    # Auto-select satu-satunya event aktif: efek + saat dialog dibuka.
    assert "active.length === 1" in actions
    assert "setEventId(active[0].event_id)" in actions
    assert "respondOpen" in actions
    # changeRespondOpen mengikat value saat open, mereset saat close.
    assert "function changeRespondOpen" in actions
    assert "resetResponse()" in actions


def test_event_select_trigger_shows_serid_label_not_placeholder_only():
    actions = read("Actions.tsx")
    # items mapping id -> label SERID.
    assert "eventItems" in actions
    assert "SERID ${item.serid}" in actions
    # Native select terikat value ke pilihan efektif dan punya selector stabil.
    assert 'label={`Event aktif (${active.length})`}' in actions
    assert 'testId="alarm-event-select"' in actions
    assert 'name="event_id"' in actions
    assert "value={selectedEventId}" in actions
    assert '<option value="">Pilih event...' in actions
    # Tombol kirim terkunci sampai event terikat.
    assert "!selectedEventId || !pic || !reason || !pin" in actions


def test_action_is_preset_select_not_free_text_input():
    actions = read("Actions.tsx")
    assert "RESPONSE_ACTION_ITEMS" in actions
    assert "Konfirmasi" in actions
    assert "Eskalasi" in actions
    assert "Selesai" in actions
    # Action dirender sebagai native preset terikat value.
    assert 'label="Action"' in actions
    assert 'testId="alarm-action-select"' in actions
    assert 'name="action"' in actions
    assert "value={action}" in actions
    # Tidak ada lagi Input teks bebas untuk Action respons.
    assert '<Input label="Action"' not in actions


def test_response_and_cancel_still_hit_real_endpoints_with_pin():
    actions = read("Actions.tsx")
    assert "/api/v1/control/alarm-events/${encodeURIComponent(selectedEventId)}/response" in actions
    assert "{ pin, action, pic, reason }" in actions
    assert "/api/v1/control/suppressions/${encodeURIComponent(item.suppression_id)}/cancel" in actions
    assert "{ pin: cancelPin, reason: cancelReason }" in actions
    assert "onChanged()" in actions


def test_modal_stacking_keeps_background_mounted_and_select_on_top():
    css = read("radmon.css") + "\n" + read("radmon-overlays.css")
    actions = read("Actions.tsx")
    # Kontrak lapisan: backdrop 80 < dialog 90 < select portal 100 < toast 110.
    assert "--radmon-layer-backdrop" in css
    assert "--radmon-layer-dialog: 90" in css
    assert "--radmon-layer-select: 100" in css
    assert "--radmon-layer-toast: 110" in css
    assert '[role="presentation"]' in css
    assert '[role="dialog"]' in css
    assert "[data-kumo-select-positioner]" in css
    assert "z-index: var(--radmon-layer-select) !important" in css
    # Backdrop hanya memudarkan (opacity-80), background tetap mounted/visible.
    assert "opacity-80" in css or "bg-kumo-recessed" in css
    assert "background: rgba(17, 24, 39, .42)" in css
    assert "opacity: 1 !important" in css
    assert 'body:has([role="dialog"])' in css
    assert ".page-stack" in css
    assert "visibility: visible" in css
    assert "overflow-y: auto" in css
    # Dialog memakai portal Kumo (center, Escape/backdrop menutup via
    # onOpenChange) dan Select tetap portal body agar tidak ke-clip.
    assert "Dialog.Root open={respondOpen} onOpenChange={changeRespondOpen}" in actions
    assert 'className="radmon-dialog mobile-sheet-dialog"' in actions
    # Saat menyimpan, Escape/backdrop diblokir agar POST tidak ganda/batal diam-diam.
    assert 'if (!open && pending === "respond") return;' in actions
