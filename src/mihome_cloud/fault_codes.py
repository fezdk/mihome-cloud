"""Fault code maps for MIoT vacuum devices.

Different device families use different fault code ranges:
- Dreame-native (dreame.vacuum.*): codes 0-125
- Xiaomi-branded Dreame (xiaomi.vacuum.*): 6-digit codes (1xxxxx, 3xxxxx)

Use `lookup_fault(model, code)` to get a human-readable description.
Unknown codes return a generic description based on the code range.
"""

from __future__ import annotations

# Dreame-native fault codes (dreame.vacuum.* models)
# Source: Tasshack/dreame-vacuum DreameVacuumErrorCode enum
DREAME_FAULTS: dict[int, str] = {
    0: "no_error",
    1: "drop_sensor",
    2: "cliff_sensor",
    3: "bumper_stuck",
    4: "gesture_sensor",
    5: "bumper_repeat",
    6: "drop_repeat",
    7: "optical_flow",
    8: "dustbin_missing",
    9: "water_tank_missing",
    10: "water_tank_empty",
    11: "dustbin_full",
    12: "main_brush_stuck",
    13: "side_brush_stuck",
    14: "fan_error",
    15: "left_wheel_motor",
    16: "right_wheel_motor",
    17: "turn_stuck",
    18: "forward_stuck",
    19: "charger_error",
    20: "battery_low",
    21: "charge_fault",
    22: "battery_percentage",
    23: "heart_error",
    24: "camera_blocked",
    25: "moved_while_charging",
    26: "flow_shielding",
    27: "infrared_shielding",
    28: "charge_no_power",
    29: "battery_fault",
    30: "fan_speed_error",
    31: "left_wheel_speed",
    32: "right_wheel_speed",
    33: "accelerometer_error",
    34: "gyroscope_error",
    35: "compass_error",
    36: "left_magnet_error",
    37: "right_magnet_error",
    38: "optical_flow_error",
    39: "infrared_fault",
    40: "camera_fault",
    41: "strong_magnet",
    42: "water_pump_error",
    43: "rtc_error",
    44: "auto_key_triggered",
    45: "power_rail_error",
    46: "camera_idle",
    47: "blocked",
    48: "lidar_error",
    49: "lidar_bumper",
    50: "water_pump_2",
    51: "filter_blocked",
    54: "edge_sensor",
    55: "carpet_error",
    56: "laser_error",
    57: "edge_sensor_2",
    58: "ultrasonic_error",
    59: "no_go_zone",
    61: "route_error",
    62: "route_error_2",
    63: "blocked_2",
    64: "blocked_3",
    65: "restricted_area",
    66: "restricted_area_2",
    67: "restricted_area_3",
    68: "remove_mop_first",
    69: "mop_removed",
    70: "mop_removed_2",
    71: "mop_pad_stopped",
    72: "mop_pad_stopped_2",
    74: "mop_install_failed",
    75: "low_battery_shutdown",
    76: "dirty_tank_not_installed",
    78: "robot_in_hidden_room",
    79: "lidar_failed_to_lift",
    80: "robot_stuck",
    81: "robot_stuck_repeat",
    82: "slippery_floor",
    84: "unknown_error",
    85: "check_mop_install",
    86: "dirty_water_tank_full",
    88: "retractable_leg_stuck",
    89: "internal_error",
    90: "robot_stuck_2",
    91: "stuck_on_table",
    92: "stuck_on_passage",
    93: "stuck_on_threshold",
    94: "stuck_on_low_area",
    95: "stuck_on_ramp",
    96: "stuck_on_obstacle",
    97: "stuck_on_pet",
    98: "stuck_on_slippery_surface",
    99: "stuck_on_carpet",
    101: "dustbin_full",
    102: "dustbin_open",
    103: "dustbin_open_2",
    104: "dustbin_full_2",
    105: "water_tank_error",
    106: "dirty_water_tank_error",
    107: "water_tank_dry",
    108: "dirty_water_tank_2",
    109: "dirty_water_tank_blocked",
    110: "dirty_water_tank_pump",
    111: "mop_pad_error",
    112: "wet_mop_pad",
    114: "clean_mop_pad",
    116: "clean_tank_level_low",
    117: "station_disconnected",
    118: "dirty_tank_level_high",
    119: "washboard_error",
    120: "no_mop_in_station",
    121: "dust_bag_full",
    122: "unknown_warning",
    123: "self_test_failed",
    124: "washboard_not_working",
    125: "drainage_failed",
}

# Xiaomi-branded vacuum fault codes (xiaomi.vacuum.* models)
# These use 6-digit codes. Empirically mapped — add as discovered.
# Format appears to be: {category}{specific_code}
#   1xxxxx = general/sensor
#   3xxxxx = motor/wheel
XIAOMI_FAULTS: dict[int, str] = {
    0: "no_error",
    100008: "sensor_warning",           # Often reported at idle, may be informational
    320004: "drive_wheel_error",        # Wheel stuck or blocked
}

def lookup_fault(model: str, code: int) -> str:
    """Look up a fault code description for a device model.

    Args:
        model: Device model string (e.g. "xiaomi.vacuum.d102gl", "dreame.vacuum.r2205")
        code: Fault code integer

    Returns:
        Human-readable fault description, or "unknown_{code}" if not mapped.
    """
    if code == 0:
        return "no_error"

    if model.startswith("xiaomi.vacuum."):
        return XIAOMI_FAULTS.get(code, f"unknown_{code}")

    if model.startswith("dreame.vacuum."):
        return DREAME_FAULTS.get(code, f"unknown_{code}")

    # Unknown model family — try both maps
    return XIAOMI_FAULTS.get(code) or DREAME_FAULTS.get(code) or f"unknown_{code}"
