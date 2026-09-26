import json
from pathlib import Path

import pytest

from mihome_cloud.devices.vacuum import MiHomeVacuum


def vacuum(raw):
    profile = json.loads((Path(__file__).parents[1] / "src/mihome_cloud/profiles/xiaomi.vacuum.d102gl.json").read_text())
    device = MiHomeVacuum(None, "synthetic", "xiaomi.vacuum.d102gl", profile)
    device.get_properties = lambda names: {k: v for k, v in raw.items() if k in names}
    device.get_property = lambda name: raw.get(name)
    return device


@pytest.mark.parametrize("code,label", [(4,"sweeping"),(7,"going_to_wash"),(12,"station_working"),
                                       (14,"station_working"),(16,"sweeping_mopping"),(17,"mopping"),
                                       (20,"wash_break"),(15,"error"),(2,"charging")])
def test_activity_is_not_overwritten_by_selected_program(code, label):
    device = vacuum({"status":code, "sweep_mop_type":4})
    assert device.status() == label
    assert device.full_state()["status"] == label
    assert device.full_state()["sweep_mop_type"] == "sweeping_then_mopping"


def test_station_is_still_busy_and_raw_station_data_is_preserved():
    raw = {"status":14,"fault":100008,"charging":1,
           "base_station_working_status":'{"mode":1,"runtime":0,"total_time":0}'}
    device = vacuum(raw)
    snapshot = device.full_state()
    assert device.is_busy()
    assert snapshot["charging"] is True
    assert snapshot["fault_code_raw"] == 100008
    assert snapshot["fault_active"] is False
    assert "fault_code" not in snapshot
    assert snapshot["base_station_working_status"] == raw["base_station_working_status"]
    assert "drying" not in snapshot


def test_faults_zero_missing_and_active_are_distinct():
    active = vacuum({"status":15,"fault":100008}).full_state()
    assert active["fault_active"] is True and active["fault_code"] == 100008
    zero = vacuum({"status":14,"fault":0}).full_state()
    assert zero["fault_code"] == 0 and zero["fault"] == "none"
    assert "fault_active" not in vacuum({"status":14}).full_state()
    assert vacuum({"fault":100008}).full_state()["fault_active"] is None
