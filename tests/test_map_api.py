import base64
import copy
import json
import stat
import zlib
from unittest.mock import Mock

import pytest

from mihome_cloud import (MapError, MiHomeVacuum, VacuumMapClient,
                          build_map_snapshot)
from mihome_cloud.map_api import route_geometry
from mihome_cloud.map_view import write_map_view


def sample():
    return {"map_id": 7, "width": 4, "height": 3, "resolution": 50,
            "origin_x": -100, "origin_y": -50,
            "map_data": base64.b64encode(zlib.compress(bytes([3, 3, 4, 4] * 3))).decode(),
            "map_room_info": [{"grid_id": 3, "room_id": 11}, {"grid_id": 4, "room_id": 12}],
            "room_attrs": [{"id": 11, "room_name": "Test room", "name_pos_x": -75, "name_pos_y": 25},
                           {"id": 12, "room_name": "", "name_pos_x": 99999, "name_pos_y": 99999}],
            "have_pile": True, "pile_x": 0, "pile_y": 0, "pile_yaw": 123,
            "position": {"x": 25, "y": 25, "yaw": 42}, "task_id": 8,
            "paths": {"pose_id": 9, "points": [
                {"x": 0, "y": 0, "type": 0}, {"x": 10, "y": 10, "type": 0},
                {"x": 20, "y": 20, "type": 1}, {"x": 25, "y": 25, "type": 1}]}}


def metadata():
    return {"values": {"status": 2, "map_object": "private/active",
                       "room_info": {"map_uid": 0, "rooms": [{"id": 11, "name": "Stale"}]},
                       "current_map_id": 0,
                       "map_management": {"map_array": [
                           {"map_id": 7, "map_name": "Test floor", "obj_name": "private/saved", "is_current": True}]}}}


@pytest.fixture
def client(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("mihome_cloud.map_api.time.monotonic", lambda: clock[0])
    c = VacuumMapClient(Mock(), "1234567890")
    c._reader = Mock()
    c._reader.metadata.side_effect = lambda: copy.deepcopy(metadata())
    c._reader.fetch.side_effect = lambda obj: (b"private raw", copy.deepcopy(sample()))
    return c, clock


def test_snapshot_labels_coordinates_and_positions():
    s = build_map_snapshot(sample(), room_info=metadata()["values"]["room_info"])
    p = s.to_dict()
    assert p["map"]["id"] == 7
    assert p["rooms"][0]["name"] == "Test room"
    assert p["rooms"][0]["label"] == {"x": -75, "y": 25, "source": "map_room_attrs"}
    assert p["rooms"][1]["name"] == ""
    assert p["rooms"][1]["display_name"] == "Room 12"
    assert p["rooms"][1]["label"]["source"] == "interior_cell"
    assert 0 <= p["rooms"][1]["label"]["x"] <= 100
    assert p["robot"]["position"] == {"x": 25, "y": 25}
    assert p["robot"]["footprint"]["diameter_mm"] == 350
    assert p["dock"]["position"] == {"x": 0, "y": 0}
    assert p["dock"]["anchor_verified"] is False
    assert p["freshness"]["source_updated_at"] is None
    assert p["freshness"]["live_updates_verified"] is False
    assert "Test room" not in repr(s)
    json.dumps(p, allow_nan=False)


def test_explicit_names_and_absent_positions():
    d = sample()
    d.pop("position")
    d["have_pile"] = False
    p = build_map_snapshot(d, room_names={12: "Explicit name"}).to_dict()
    assert p["rooms"][1]["name"] == "Explicit name"
    assert p["robot"]["position"] is None
    assert p["dock"]["position"] is None
    with pytest.raises(MapError):
        build_map_snapshot(d, room_names={12: 123})


def test_route_groups_type_zero_runs_instead_of_splitting_every_point():
    r = route_geometry(sample())
    assert len(r["points"]) == 4
    assert r["segments"] == [
        {"type": 0, "kind": "transport", "points": [[0, 0], [10, 10]]},
        {"type": 1, "kind": "cleaning", "points": [[20, 20], [25, 25]]}]
    assert r["pose_id"] == 9


def test_bad_route_point_breaks_run_and_unknown_types_survive():
    d = sample()
    d["paths"]["points"] = [{"x": 1, "y": 2, "type": 1},
                             {"x": float('nan'), "y": 3, "type": 1},
                             {"x": 4, "y": 5, "type": 1},
                             {"x": 6, "y": 7, "type": 99}]
    r = route_geometry(d)
    assert r["discarded_points"] == 1
    assert len(r["segments"]) == 3
    assert r["segments"][-1]["kind"] == "unknown"
    d["paths"]["points"] = json.dumps(r["points"])
    assert route_geometry(d)["available"]
    assert route_geometry({})["available"] is False
    assert route_geometry({"paths": {"points": []}})["available"] is True
    with pytest.raises(MapError):
        route_geometry({"paths": {"points": 'bad'}})


def test_revisions_distinguish_raster_labels_and_dynamic_overlay():
    d = sample()
    original = build_map_snapshot(d).to_dict()
    d["position"]["x"] += 10
    d["paths"]["points"].append({"x": 35, "y": 25, "type": 1})
    moved = build_map_snapshot(d).to_dict()
    assert moved["map"]["revision"] == original["map"]["revision"]
    assert moved["overlay_revision"] != original["overlay_revision"]
    renamed = build_map_snapshot(d, room_names={11: "Changed"}).to_dict()
    assert renamed["map"]["revision"] != moved["map"]["revision"]
    assert renamed["map"]["raster_revision"] == moved["map"]["raster_revision"]


def test_shared_cache_no_network_on_construction_or_repeated_getters(client):
    c, clock = client
    c._reader.metadata.assert_not_called()
    first = c.get_snapshot()
    assert c.get_positions()["map_id"] == 7
    assert c.get_route()["task_id"] == 8
    c._reader.metadata.assert_called_once()
    c._reader.fetch.assert_called_once_with("private/active")
    assert not first.to_dict()["freshness"]["cache_hit"]
    clock[0] += 4
    next_data = c.get_snapshot().to_dict()
    assert next_data["freshness"]["age_seconds"] == 4
    assert next_data["freshness"]["fetched_at"] == first.to_dict()["freshness"]["fetched_at"]
    next_data["rooms"][0]["name"] = "Caller mutation"
    assert c.get_snapshot().to_dict()["rooms"][0]["name"] == "Test room"


def test_constant_object_name_does_not_hide_updated_position(client):
    c, clock = client
    first = c.get_snapshot()
    clock[0] += 5
    changed = sample()
    changed["position"]["x"] = 70
    c._reader.fetch.side_effect = lambda obj: (b"new raw", changed)
    new = c.get_snapshot()
    assert new.to_dict()["robot"]["position"]["x"] == 70
    assert c._reader.fetch.call_count == 2
    assert first.to_dict()["map"]["raster_revision"] == new.to_dict()["map"]["raster_revision"]


def test_list_maps_no_object_or_device_identifiers_and_ttl(client):
    c, clock = client
    result = c.list_maps()
    assert result[0].to_dict() == {"map_id": 7, "name": "Test floor", "is_current": True}
    assert "private" not in json.dumps(result[0].to_dict())
    clock[0] += 20
    c.list_maps()
    c._reader.metadata.assert_called_once()
    c._reader.fetch.assert_not_called()


def test_saved_map_identity_mismatch_is_rejected_and_never_switches(client):
    c, clock = client
    c._reader.fetch.side_effect = lambda obj: (b"wrong", {**sample(), "map_id": 99})
    with pytest.raises(MapError):
        c.get_snapshot(7)
    c._reader.fetch.assert_called_once_with("private/saved")
    assert not any(call[0] in ('action', 'set_property', 'login') for call in c._reader.mock_calls)


def test_stale_failure_retains_old_fetch_time_and_backs_off(client):
    c, clock = client
    first = c.get_snapshot()
    c._reader.fetch.side_effect = RuntimeError("signed URL with secret")
    clock[0] += 5
    stale = c.get_snapshot().to_dict()
    assert stale["freshness"]["stale"]
    assert stale["freshness"]["fetched_at"] == first.to_dict()["freshness"]["fetched_at"]
    assert stale["freshness"]["error"] == "map_refresh_failed"
    assert "secret" not in json.dumps(stale)
    calls = c._reader.fetch.call_count
    clock[0] += 1
    c.get_snapshot()
    assert c._reader.fetch.call_count == calls
    with pytest.raises(MapError):
        c.get_snapshot(allow_stale=False)
    clock[0] += 4
    c.get_snapshot()
    clock[0] += 5
    c.get_snapshot()
    assert c._reader.fetch.call_count == calls + 1  # second failure backed off 10 seconds


def test_unchanged_content_preserves_change_time_but_updates_fetch_time(client, monkeypatch):
    c, clock = client
    monkeypatch.setattr("mihome_cloud.map_api._utc", lambda: "2026-01-01T00:00:00+00:00")
    first = c.get_snapshot().to_dict()
    clock[0] += 5
    monkeypatch.setattr("mihome_cloud.map_api._utc", lambda: "2026-01-01T00:00:05+00:00")
    second = c.get_snapshot().to_dict()
    assert first["revision"] == second["revision"]
    assert first["freshness"]["content_changed_at"] == second["freshness"]["content_changed_at"]
    assert first["freshness"]["fetched_at"] != second["freshness"]["fetched_at"]


def test_opt_in_vacuum_property_does_not_poll_and_reuses_instance():
    cloud = Mock()
    vacuum = MiHomeVacuum(cloud, "1234567890", "xiaomi.vacuum.d102gl", {})
    assert vacuum.maps is vacuum.maps
    cloud._rpc.assert_not_called()
    with pytest.raises(MapError):
        MiHomeVacuum(cloud, "1234567890", "unsupported.model", {}).maps


@pytest.mark.parametrize("interval", [0, 1, 4.9, float('nan'), float('inf'), True])
def test_refresh_guard_rejects_unsafe_values(interval):
    with pytest.raises(ValueError):
        VacuumMapClient(Mock(), "1234567890", min_refresh_interval=interval)


def test_private_view_atomic_publication_and_no_image_rewrite(tmp_path):
    root = tmp_path / "viewer"
    first = build_map_snapshot(sample())
    write_map_view(first, root)
    p = json.loads((root / "snapshot.json").read_text())
    image = root / p["map"]["image"]
    image_stat = image.stat()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(f.stat().st_mode) == 0o600 for f in root.iterdir())
    changed = sample()
    changed["position"]["x"] = 55
    write_map_view(build_map_snapshot(changed), root)
    assert image.stat().st_mtime_ns == image_stat.st_mtime_ns
    assert json.loads((root / "snapshot.json").read_text())["robot"]["position"]["x"] == 55
    assert not list(root.glob('.map-*'))
    assert (root / "index.html").is_file()
    assert "private/" not in (root / "snapshot.json").read_text()


def test_view_refuses_unmanaged_directory_and_symlink(tmp_path):
    snapshot = build_map_snapshot(sample())
    with pytest.raises(ValueError):
        write_map_view(snapshot, tmp_path)
    linked = tmp_path / "link"
    linked.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        write_map_view(snapshot, linked)
