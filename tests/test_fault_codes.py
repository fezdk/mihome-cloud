from mihome_cloud.fault_codes import lookup_fault, lookup_fault_message


def test_xiaomi_x20_pro_brush_error_fault_code() -> None:
    assert lookup_fault("xiaomi.vacuum.d102gl", 320002) == "brush_error"


def test_xiaomi_x20_pro_mop_pad_holder_stuck_fault_code() -> None:
    assert lookup_fault("xiaomi.vacuum.d102gl", 320013) == "mop_pad_holder_stuck"
    assert lookup_fault("xiaomi.vacuum.d102gl", 340001) == "mop_pad_holder_stuck"
    assert lookup_fault_message("xiaomi.vacuum.d102gl", 320013) == "Please check and clean the mop pad holder."


def test_unknown_xiaomi_fault_code_remains_visible() -> None:
    assert lookup_fault("xiaomi.vacuum.d102gl", 399999) == "unknown_399999"
