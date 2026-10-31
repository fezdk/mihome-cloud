"""Synthetic fixtures only. Never add real rooms, device IDs or map blobs here."""
import base64
import hashlib
import json
import random
import struct
import zlib
from unittest.mock import Mock

import pytest
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from mihome_cloud.maps import (MODEL, MapError, X20MapReader, _inflate, _rings,
                               decode_map, geometry, grid_data, render_png)


def fixture(cells=b"\x03\x03\xff\x03\x00\x04", width=3, height=2):
    return {"width": width, "height": height, "resolution": 50,
            "origin_x": -100, "origin_y": 200, "map_id": 8,
            "map_data": base64.b64encode(zlib.compress(cells)).decode(),
            "map_room_info": [{"grid_id": 3, "room_id": 17}, {"grid_id": 4, "room_id": 23}],
            "room_attrs": [{"id": 17, "room_name": "Synthetic room"}],
            "have_pile": True, "pile_x": -50, "pile_y": 250, "pile_yaw": 0,
            "position": {"x": -50, "y": 250, "yaw": 90}}


def encode(data, did="1234567890"):
    seed, iv = MODEL[-16:].encode(), b"ABCDEF1234123412"
    key = hashlib.md5(AES.new(seed, AES.MODE_CBC, iv).encrypt(pad(seed + did.encode(), 16))).digest()
    cipher = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(zlib.compress(json.dumps(data).encode()), 16))
    return json.dumps({"version": 2, "data": base64.b64encode(cipher).decode()}).encode()


def area(ring):
    return sum(a[0] * b[1] - a[1] * b[0] for a, b in zip(ring, ring[1:])) / 2


def test_v2_roundtrip_and_wrong_device_rejected():
    raw = encode(fixture())
    assert decode_map(raw, "1234567890") == fixture()
    with pytest.raises(MapError):
        decode_map(raw, "9999999999")


@pytest.mark.parametrize("raw", [b"{}", b'{"version":3}', b'{"version":2,"data":"invalid"}', b"secret payload"])
def test_bad_envelopes_do_not_leak_payload(raw):
    with pytest.raises(MapError) as exc:
        decode_map(raw, "1234567890")
    assert raw.decode() not in str(exc.value)


def test_inflate_limits_and_truncation():
    raw = zlib.compress(b"a" * 100)
    assert _inflate(raw, 100) == b"a" * 100
    for invalid, limit in [(raw, 99), (raw[:-2], 100), (raw + b"extra", 100)]:
        with pytest.raises(MapError):
            _inflate(invalid, limit)


def test_grid_validation():
    assert grid_data(fixture())[2] == b"\x03\x03\xff\x03\x00\x04"
    for data in [fixture(width=4), fixture(width=-1), fixture(width=10**9), fixture(cells=b"1234567")]:
        with pytest.raises(MapError):
            grid_data(data)


def test_coordinates_id_join_occupancy_and_stale_property_names():
    info = {"map_uid": 0, "rooms": [{"id": 17, "name": "Stale name"}, {"id": 23, "name": ""}]}
    g = geometry(fixture(), info)
    assert g["rooms"][0]["room_id"] == 17
    assert g["rooms"][0]["name"] == "Synthetic room"
    assert g["rooms"][0]["rings_mm"][0][0] == [-100, 200]
    assert sum(area(r) for r in g["rooms"][0]["rings_mm"]) == 3 * 50**2
    assert g["occupied_cells_grid"] == [[2, 0]]
    assert g["room_info_comparison"]["room_ids_match"] is True
    assert g["room_info_comparison"]["map_uid_matches_map_id"] is False
    info["map_uid"] = 8
    assert geometry(fixture(), info)["rooms"][0]["name"] == "Stale name"


def test_ambiguous_room_ids_are_never_inferred_from_grid_labels():
    data = fixture()
    data["map_room_info"] = [{"grid_id": 3, "room_id": 0}, {"grid_id": 4, "room_id": 0}]
    assert all(r["room_id"] is None for r in geometry(data)["rooms"])
    data["map_room_info"] = []
    assert all(r["room_id"] is None for r in geometry(data)["rooms"])


def test_boundaries_preserve_holes_disjoint_and_diagonal_cells():
    cells = {(x, y) for x in range(3) for y in range(3)} - {(1, 1)}
    rings = _rings(cells)
    assert sorted(area(r) for r in rings) == [-1, 9]
    assert len(_rings({(0, 0), (1, 1)})) == 2
    rng = random.Random(12)
    for _ in range(80):
        mask = {(x, y) for x in range(6) for y in range(6) if rng.random() < .6}
        rings = _rings(mask)
        assert sum(area(r) for r in rings) == len(mask)
        assert all(r[0] == r[-1] for r in rings)


def test_png_dimensions_crcs_and_y_flip():
    png = render_png(fixture(), scale=1)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, payload = 8, b""
    while pos < len(png):
        size = struct.unpack(">I", png[pos:pos + 4])[0]
        kind, data = png[pos + 4:pos + 8], png[pos + 8:pos + 8 + size]
        assert zlib.crc32(kind + data) & 0xffffffff == struct.unpack(">I", png[pos + 8 + size:pos + 12 + size])[0]
        if kind == b"IHDR":
            assert struct.unpack(">II", data[:8]) == (3, 2)
        if kind == b"IDAT":
            payload += data
        pos += 12 + size
    pixels = zlib.decompress(payload)
    assert pixels[:10] == b"\0" + bytes((129, 181, 201, 248, 247, 244, 236, 188, 123))


def cloud():
    c = Mock()
    c._base_url = "https://de.api.io.mi.com/app"
    return c


def test_metadata_only_reads_preserves_raw_and_property_errors():
    c = cloud()
    response = {"code": 0, "result": [
        {"siid": 2, "piid": 16, "code": 0, "value": '{"rooms":[],"map_uid":0}'},
        {"siid": 10, "piid": 6, "code": -1, "value": 999},
    ]}
    c._rpc.return_value = response
    result = X20MapReader(c, "1234567890").metadata()
    assert result["raw_response"] == response
    assert result["values"]["room_info"]["map_uid"] == 0
    assert result["values"]["current_map_id"] is None
    args, kwargs = c._rpc.call_args
    assert args[0].endswith("/v2/home/rpc/1234567890")
    assert args[1]["method"] == "get_properties"
    assert kwargs == {"allow_reauth": False}
    c.login.assert_not_called()
    c.action.assert_not_called()
    c.set_property.assert_not_called()


def test_failed_session_is_not_retried_or_logged():
    c = cloud()
    c._rpc.side_effect = RuntimeError("secret session")
    with pytest.raises(MapError, match="Cloud read failed") as exc:
        X20MapReader(c, "1234567890").metadata()
    assert "secret" not in str(exc.value)
    assert c._rpc.call_count == 1
    c.login.assert_not_called()


def test_null_url_response_and_http_rejected():
    c = cloud()
    for result in [None, {"url": "http://storage.example/map?secret=value"}]:
        c._rpc.return_value = {"code": 0, "result": result}
        with pytest.raises(MapError):
            X20MapReader(c, "1234567890").download("synthetic/object")


def test_download_uses_pro_and_separate_cookie_free_session(monkeypatch):
    c = cloud()
    c._rpc.return_value = {"code": 0, "result": {"url": "https://storage.example/map?private=1"}}
    session, response = Mock(), Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.status_code = 200
    response.iter_content.return_value = [b"map"]
    session.get.return_value = response
    monkeypatch.setattr("mihome_cloud.maps.requests.Session", lambda: session)
    assert X20MapReader(c, "1234567890").download("synthetic/object") == b"map"
    args, kwargs = c._rpc.call_args
    assert args[0].endswith("/v2/home/get_interim_file_url_pro")
    assert args[1] == {"obj_name": "synthetic/object"}
    assert kwargs == {"allow_reauth": False}
    assert session.get.call_args.kwargs == {"timeout": (10, 30), "stream": True, "allow_redirects": False}
    c._session.get.assert_not_called()
