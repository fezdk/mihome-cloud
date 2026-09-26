import json
from pathlib import Path


def test_xiaomi_x20_pro_profile_polls_sleep_notice_fields() -> None:
    profile_path = Path(__file__).parent.parent / "src" / "mihome_cloud" / "profiles" / "xiaomi.vacuum.d102gl.json"
    profile = json.loads(profile_path.read_text())
    properties = profile["properties"]

    assert properties["sleep_status"] == {"siid": 2, "piid": 25}
    assert properties["fault_ids"] == {"siid": 2, "piid": 66}
    assert properties["plugin_info_remind"] == {"siid": 2, "piid": 70}
    assert properties["notice"] == {"siid": 2, "piid": 72}
